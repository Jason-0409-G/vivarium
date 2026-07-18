from __future__ import annotations

import fcntl
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .canonical import durable_replace
from .errors import IntegrityError
from .events import Event, ZERO_HASH


@dataclass(frozen=True)
class RecoveryResult:
    events: Sequence[Event]
    quarantined_tail: bytes


class Ledger:
    def __init__(self, path: Path, ledger_id: str):
        self.path = Path(path)
        self.ledger_id = ledger_id

    def append(self, event: Event) -> None:
        line = event.to_line()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existed = self.path.exists()
        with self.path.open("a+b") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                fh.seek(0)
                current = self._recover_bytes(fh.read())
                if current.quarantined_tail:
                    raise IntegrityError("ledger has an unresolved torn tail")
                expected_seq = len(current.events)
                expected_prev = (
                    ZERO_HASH
                    if expected_seq == 0
                    else current.events[-1].event_hash
                )
                if event.ledger_id != self.ledger_id:
                    raise IntegrityError("ledger_id mismatch")
                if (
                    event.event_seq != expected_seq
                    or event.prev_event_hash != expected_prev
                ):
                    raise IntegrityError("event sequence or prev hash mismatch")
                fh.seek(0, os.SEEK_END)
                written = fh.write(line)
                if written != len(line):
                    raise OSError("short ledger write")
                fh.flush()
                os.fsync(fh.fileno())
                if not existed:
                    directory_fd = os.open(self.path.parent, os.O_RDONLY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def recover(self) -> RecoveryResult:
        if not self.path.exists():
            return RecoveryResult((), b"")
        return self._recover_bytes(self.path.read_bytes())

    def quarantine_tail(self, quarantine_dir: Path) -> Path | None:
        tail = self.recover().quarantined_tail
        if not tail:
            return None
        digest = hashlib.sha256(tail).hexdigest()
        destination = Path(quarantine_dir) / f"sha256-{digest}.tail"
        durable_replace(destination, tail)
        return destination

    def _recover_bytes(self, data: bytes) -> RecoveryResult:
        events: list[Event] = []
        offset = 0
        while offset < len(data):
            newline = data.find(b"\n", offset)
            if newline < 0:
                return RecoveryResult(tuple(events), data[offset:])
            line = data[offset : newline + 1]
            offset = newline + 1
            is_last = offset == len(data)
            try:
                event = Event.from_line(line)
            except IntegrityError:
                if is_last:
                    return RecoveryResult(tuple(events), line)
                raise
            index = len(events)
            expected_prev = ZERO_HASH if index == 0 else events[-1].event_hash
            if event.ledger_id != self.ledger_id or event.event_seq != index:
                raise IntegrityError("ledger identity or sequence mismatch")
            if event.prev_event_hash != expected_prev:
                raise IntegrityError("prev hash mismatch")
            events.append(event)
        return RecoveryResult(tuple(events), b"")
