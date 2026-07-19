from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .canonical import domain_hash
from .errors import IntegrityError
from .events import Event, ZERO_HASH, _HASH_PATTERN
from .state import AnalysisState, DependencyHead, ExternalClientState, ObligationState

PROJECT_VALIDITY_DOMAIN = "vivarium-project-validity/v1"
DEPENDENCY_HEADS_DOMAIN = "vivarium-attempt-dependency-heads/v1"
ACTIVE_ROOT_DOMAIN = "vivarium-project-active-root/v1"

RUN_LOCAL_REDUCER_DIGEST = domain_hash(
    "vivarium-reducer-definition/v1", {"reducer": "run-local", "version": 1}
)
PROJECT_VALIDITY_REDUCER_DIGEST = domain_hash(
    "vivarium-reducer-definition/v1", {"reducer": "project-validity", "version": 1}
)
LEDGER_REDUCER_DIGESTS = {
    namespace: domain_hash(
        "vivarium-reducer-definition/v1",
        {"reducer": f"project-{namespace}", "version": 1},
    )
    for namespace in ("truth", "decision", "work", "memory", "run_registry")
}

GENESIS_TYPES = {
    "truth": "TRUTH_LEDGER_GENESIS",
    "decision": "DECISION_LEDGER_GENESIS",
    "work": "WORK_LEDGER_GENESIS",
    "memory": "MEMORY_LEDGER_GENESIS",
    "run_registry": "RUN_REGISTRY_LEDGER_GENESIS",
}
GENESIS_LEDGER_IDS = {
    "truth": "project-truth",
    "decision": "project-decision",
    "work": "project-work",
    "memory": "project-memory",
    "run_registry": "project-run-registry",
}
COMPLETION_ABORT_REASONS = frozenset(
    {
        "COMPLETION_FAILURE_RETRYABLE",
        "COMPLETION_FAILURE_RESOURCE",
        "COMPLETION_FAILURE_PERMANENT",
        "COMPLETION_PREEMPTED",
        "COMPLETION_CANCELLED",
        "COMPLETION_UNKNOWN_FINALITY",
    }
)


def _require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IntegrityError(f"{label} must be an object")
    return value


def _require_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise IntegrityError(f"{field} must be a non-empty string")
    return value


def _require_digest(payload: dict[str, Any], field: str) -> str:
    value = _require_string(payload, field)
    if _HASH_PATTERN.fullmatch(value) is None:
        raise IntegrityError(f"{field} must be a sha256 digest")
    return value


def _require_int(payload: dict[str, Any], field: str) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise IntegrityError(f"{field} must be an integer")
    return value


def _analysis_value(value: str, label: str) -> AnalysisState:
    try:
        return AnalysisState(value)
    except ValueError as exc:
        raise IntegrityError(f"{label} is not a closed analysis state") from exc


def _obligation_value(value: str, label: str) -> ObligationState:
    try:
        return ObligationState(value)
    except ValueError as exc:
        raise IntegrityError(f"{label} is not a closed obligation state") from exc


def _client_value(value: str, label: str) -> ExternalClientState:
    try:
        return ExternalClientState(value)
    except ValueError as exc:
        raise IntegrityError(f"{label} is not a closed external-client state") from exc


def _verify_event_prefix(
    events: Sequence[Event], *, genesis_type: str, ledger_id: str | None = None
) -> tuple[Event, ...]:
    if not isinstance(events, tuple) or not events:
        raise IntegrityError("verified prefix must be a non-empty immutable Event tuple")
    first = events[0]
    if not isinstance(first, Event) or first.event_type != genesis_type:
        raise IntegrityError("verified prefix has the wrong genesis anchor")
    if ledger_id is not None and first.ledger_id != ledger_id:
        raise IntegrityError("verified prefix has the wrong ledger anchor")
    expected_ledger = first.ledger_id
    previous_hash = ZERO_HASH
    for sequence, item in enumerate(events):
        if not isinstance(item, Event):
            raise IntegrityError("verified prefix contains a non-Event value")
        item.to_line()
        if item.ledger_id != expected_ledger:
            raise IntegrityError("verified prefix crosses ledgers")
        if item.event_seq != sequence or item.prev_event_hash != previous_hash:
            raise IntegrityError("verified prefix is not a contiguous hash chain")
        previous_hash = item.event_hash
    return events


def _dependency(payload: Any) -> DependencyHead:
    item = _require_dict(payload, "dependency head")
    if set(item) != {"namespace", "object_id", "object_head"}:
        raise IntegrityError("dependency head has an invalid field set")
    return DependencyHead(
        _require_string(item, "namespace"),
        _require_string(item, "object_id"),
        _require_string(item, "object_head"),
    )


def _dependency_projection(item: DependencyHead) -> dict[str, str]:
    return {
        "namespace": item.namespace,
        "object_id": item.object_id,
        "object_head": item.object_head,
    }
