from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .canonical import canonical_bytes, domain_hash
from .errors import IntegrityError


SCHEMA_VERSION = "vivarium.event/v1"
PAYLOAD_DOMAIN = "vivarium-event-payload/v1"
EVENT_DOMAIN = "vivarium-event-hash/v1"
RECORD_DOMAIN = "vivarium-event-record/v1"
ZERO_HASH = "sha256:" + "0" * 64

_HASH_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TIMESTAMP_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
_ENVELOPE_FIELDS = frozenset(
    {
        "schema_version",
        "ledger_id",
        "event_seq",
        "event_id",
        "event_type",
        "tx_id",
        "prev_event_hash",
        "recorded_at",
        "effective_at",
        "payload_hash",
        "payload",
        "event_hash",
        "record_checksum",
    }
)


def _validate_timestamp(value: Any, field: str) -> None:
    if not isinstance(value, str) or _TIMESTAMP_PATTERN.fullmatch(value) is None:
        raise IntegrityError(f"{field} must be a UTC timestamp with second precision")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise IntegrityError(f"{field} is not a valid UTC timestamp") from exc


def _reject_json_constant(value: str) -> None:
    raise IntegrityError(f"non-finite JSON number is forbidden: {value}")


@dataclass(frozen=True)
class Event:
    schema_version: str
    ledger_id: str
    event_seq: int
    event_id: str
    event_type: str
    tx_id: str
    prev_event_hash: str
    recorded_at: str
    effective_at: str
    payload_hash: str
    payload: Any
    event_hash: str
    record_checksum: str

    @classmethod
    def build(
        cls,
        *,
        ledger_id: str,
        event_seq: int,
        event_id: str,
        event_type: str,
        tx_id: str,
        prev_event_hash: str,
        recorded_at: str,
        effective_at: str,
        payload: Any,
    ) -> Event:
        payload_copy = copy.deepcopy(payload)
        payload_hash = domain_hash(PAYLOAD_DOMAIN, payload_copy)
        event_body = {
            "schema_version": SCHEMA_VERSION,
            "ledger_id": ledger_id,
            "event_seq": event_seq,
            "event_id": event_id,
            "event_type": event_type,
            "tx_id": tx_id,
            "prev_event_hash": prev_event_hash,
            "recorded_at": recorded_at,
            "effective_at": effective_at,
            "payload_hash": payload_hash,
            "payload": payload_copy,
        }
        event_hash = domain_hash(EVENT_DOMAIN, event_body)
        record_body = {**event_body, "event_hash": event_hash}
        record_checksum = domain_hash(RECORD_DOMAIN, record_body)
        event = cls(**record_body, record_checksum=record_checksum)
        event._validate_integrity()
        return event

    @classmethod
    def from_line(cls, line: bytes) -> Event:
        if not isinstance(line, bytes) or not line.endswith(b"\n"):
            raise IntegrityError("event record must end with one LF")
        body = line[:-1]
        try:
            record = json.loads(
                body.decode("utf-8"),
                parse_constant=_reject_json_constant,
            )
        except IntegrityError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IntegrityError("event record is not valid UTF-8 JSON") from exc
        if not isinstance(record, dict) or set(record) != _ENVELOPE_FIELDS:
            raise IntegrityError("event record has a non-canonical field set")
        if canonical_bytes(record) != body:
            raise IntegrityError("event record is not canonical JSON plus LF")
        event = cls(**record)
        event._validate_integrity()
        return event

    def to_line(self) -> bytes:
        self._validate_integrity()
        return canonical_bytes(self._record()) + b"\n"

    def _event_body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ledger_id": self.ledger_id,
            "event_seq": self.event_seq,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "tx_id": self.tx_id,
            "prev_event_hash": self.prev_event_hash,
            "recorded_at": self.recorded_at,
            "effective_at": self.effective_at,
            "payload_hash": self.payload_hash,
            "payload": self.payload,
        }

    def _record_body(self) -> dict[str, Any]:
        return {**self._event_body(), "event_hash": self.event_hash}

    def _record(self) -> dict[str, Any]:
        return {**self._record_body(), "record_checksum": self.record_checksum}

    def _validate_integrity(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise IntegrityError("unsupported event schema_version")
        for field in ("ledger_id", "event_id", "event_type", "tx_id"):
            if not isinstance(getattr(self, field), str):
                raise IntegrityError(f"{field} must be a string")
        if isinstance(self.event_seq, bool) or not isinstance(self.event_seq, int):
            raise IntegrityError("event_seq must be an integer")
        if self.event_seq < 0:
            raise IntegrityError("event_seq must be non-negative")
        if not isinstance(self.prev_event_hash, str) or _HASH_PATTERN.fullmatch(
            self.prev_event_hash
        ) is None:
            raise IntegrityError("prev_event_hash is malformed")
        if self.event_seq == 0 and self.prev_event_hash != ZERO_HASH:
            raise IntegrityError("genesis event must reference ZERO_HASH")
        if self.event_seq > 0 and self.prev_event_hash == ZERO_HASH:
            raise IntegrityError("non-genesis event cannot reference ZERO_HASH")
        _validate_timestamp(self.recorded_at, "recorded_at")
        _validate_timestamp(self.effective_at, "effective_at")
        for field in ("payload_hash", "event_hash", "record_checksum"):
            value = getattr(self, field)
            if not isinstance(value, str) or _HASH_PATTERN.fullmatch(value) is None:
                raise IntegrityError(f"{field} is malformed")
        if self.payload_hash != domain_hash(PAYLOAD_DOMAIN, self.payload):
            raise IntegrityError("payload_hash mismatch")
        if self.event_hash != domain_hash(EVENT_DOMAIN, self._event_body()):
            raise IntegrityError("event_hash mismatch")
        if self.record_checksum != domain_hash(RECORD_DOMAIN, self._record_body()):
            raise IntegrityError("record_checksum mismatch")
