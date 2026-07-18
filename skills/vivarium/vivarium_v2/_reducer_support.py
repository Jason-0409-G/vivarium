from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from .canonical import domain_hash
from .errors import IntegrityError
from .events import Event, ZERO_HASH
from .state import (
    AnalysisState,
    AttemptState,
    COMMIT_ABORT_REASON_TARGET,
    CompletionClassification,
    DependencyHead,
    EvidenceCutHead,
    ExternalClientState,
    MutationClientRecord,
    ObligationRecord,
    ObligationState,
    Preparation,
    ProjectObjectHead,
    ProjectOverlay,
    RunEventReference,
    RunLocalState,
    STATE_MACHINE,
    derive_transition,
)

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


def _attempt_projection(item: AttemptState) -> dict[str, Any]:
    return {
        "attempt_id": item.attempt_id,
        "prior_attempt_id": item.prior_attempt_id,
        "branch_id": item.branch_id,
        "analysis_state": item.analysis_state.value,
        "direct_dependency_heads": [
            _dependency_projection(value) for value in item.direct_dependency_heads
        ],
        "dependency_closure": [
            _dependency_projection(value) for value in item.dependency_closure
        ],
        "request_key": item.request_key,
        "intent_key": item.intent_key,
        "execution_key": item.execution_key,
        "local_execution_key": item.local_execution_key,
        "submission_key": item.submission_key,
        "operation_keys": list(item.operation_keys),
    }


def _classification_projection(item: CompletionClassification) -> dict[str, str]:
    return {
        "classification_id": item.classification_id,
        "event_id": item.event_id,
        "event_hash": item.event_hash,
        "evidence_cut_id": item.evidence_cut_id,
        "evidence_cut_digest": item.evidence_cut_digest,
        "outcome": item.outcome,
        "classification_digest": item.classification_digest,
    }


def _preparation_projection(item: Preparation) -> dict[str, Any]:
    return {
        "commit_tx_id": item.commit_tx_id,
        "prepare_event_id": item.prepare_event_id,
        "prepare_event_hash": item.prepare_event_hash,
        "evidence_cut_id": item.evidence_cut_id,
        "evidence_cut_digest": item.evidence_cut_digest,
        "origin_state": item.origin_state.value,
        "active": item.active,
    }


def _evidence_projection(item: EvidenceCutHead) -> dict[str, str]:
    return {
        "evidence_cut_id": item.evidence_cut_id,
        "head_digest": item.head_digest,
        "event_id": item.event_id,
        "event_hash": item.event_hash,
    }


def _obligation_projection(item: ObligationRecord) -> dict[str, str]:
    return {
        "obligation_id": item.obligation_id,
        "obligation_kind": item.obligation_kind,
        "state": item.state.value,
        "head_digest": item.head_digest,
    }


def _client_projection(item: MutationClientRecord) -> dict[str, str]:
    return {
        "operation_key": item.operation_key,
        "state": item.state.value,
        "head_digest": item.head_digest,
    }


def _parse_initial_obligations(payload: dict[str, Any]) -> dict[str, ObligationRecord]:
    result: dict[str, ObligationRecord] = {}
    values = payload.get("obligations", [])
    if not isinstance(values, list):
        raise IntegrityError("initial obligations must be a list")
    for raw in values:
        item = _require_dict(raw, "initial obligation")
        if set(item) != {"obligation_id", "obligation_kind", "state", "head_digest"}:
            raise IntegrityError("initial obligation has an invalid field set")
        record = ObligationRecord(
            _require_string(item, "obligation_id"),
            _require_string(item, "obligation_kind"),
            _obligation_value(_require_string(item, "state"), "initial obligation state"),
            _require_string(item, "head_digest"),
        )
        if record.obligation_id in result:
            raise IntegrityError("initial obligation IDs must be unique")
        result[record.obligation_id] = record
    return result


def _parse_initial_clients(payload: dict[str, Any]) -> dict[str, MutationClientRecord]:
    result: dict[str, MutationClientRecord] = {}
    values = payload.get("mutation_clients", [])
    if not isinstance(values, list):
        raise IntegrityError("initial mutation clients must be a list")
    for raw in values:
        item = _require_dict(raw, "initial mutation client")
        if set(item) != {"operation_key", "state", "head_digest"}:
            raise IntegrityError("initial mutation client has an invalid field set")
        record = MutationClientRecord(
            _require_string(item, "operation_key"),
            _client_value(_require_string(item, "state"), "initial client state"),
            _require_string(item, "head_digest"),
        )
        if record.operation_key in result:
            raise IntegrityError("initial mutation client keys must be unique")
        result[record.operation_key] = record
    return result


def _apply_typed_composite(
    event: Event,
    payload: dict[str, Any],
    composite: str,
    analysis_state: AnalysisState,
    obligations: dict[str, ObligationRecord],
    clients: dict[str, MutationClientRecord],
) -> tuple[
    AnalysisState, dict[str, ObligationRecord], dict[str, MutationClientRecord]
]:
    analysis_delta = _require_dict(payload["analysis_delta"], "analysis_delta")
    if set(analysis_delta) != {"expected_state", "new_state"}:
        raise IntegrityError("typed composite analysis_delta has an invalid field set")
    expected_analysis = _analysis_value(
        _require_string(analysis_delta, "expected_state"), "analysis expected_state"
    )
    target_analysis = _analysis_value(
        _require_string(analysis_delta, "new_state"), "analysis new_state"
    )
    if expected_analysis != analysis_state:
        raise IntegrityError("typed composite analysis CAS precondition failed")
    analysis_transition = derive_transition(
        "analysis", analysis_state.value, event.event_type, payload
    )
    if analysis_transition is None or analysis_transition.to_state != target_analysis.value:
        raise IntegrityError("typed composite analysis target is not machine-derived")

    raw_obligations = payload["obligation_deltas"]
    raw_clients = payload["client_deltas"]
    if not isinstance(raw_obligations, list) or not isinstance(raw_clients, list):
        raise IntegrityError("typed composite delta collections must be lists")
    if composite in {"duplicate_detected", "submission_reconciled", "duplicate_arbitrated"}:
        if not raw_obligations:
            raise IntegrityError("typed composite requires its cross-object obligation delta")
    if composite == "operation_reconciled" and payload["operation_result"] == "cancel_terminal":
        if len(raw_obligations) != 2 or not raw_clients:
            raise IntegrityError("cancel-terminal composite requires cancel, parent, and client deltas")

    staged_obligations = dict(obligations)
    obligation_ids: list[str] = []
    obligation_kinds: list[str] = []
    for raw in raw_obligations:
        delta = _require_dict(raw, "obligation delta")
        expected_fields = {
            "obligation_id", "obligation_kind", "expected_state", "new_state", "head_digest"
        }
        if set(delta) != expected_fields:
            raise IntegrityError("typed obligation delta has an invalid field set")
        obligation_id = _require_string(delta, "obligation_id")
        obligation_kind = _require_string(delta, "obligation_kind")
        obligation_ids.append(obligation_id)
        obligation_kinds.append(obligation_kind)
        current = staged_obligations.get(obligation_id)
        if current is None or current.obligation_kind != obligation_kind:
            raise IntegrityError("typed obligation delta references an unknown object")
        expected = _obligation_value(
            _require_string(delta, "expected_state"), "obligation expected_state"
        )
        target = _obligation_value(
            _require_string(delta, "new_state"), "obligation new_state"
        )
        if current.state != expected:
            raise IntegrityError("typed obligation delta CAS precondition failed")
        transition = derive_transition(
            "obligation", current.state.value, event.event_type, payload
        )
        if transition is None or transition.to_state != target.value:
            raise IntegrityError("typed obligation target is not machine-derived")
        staged_obligations[obligation_id] = ObligationRecord(
            obligation_id,
            obligation_kind,
            target,
            _require_string(delta, "head_digest"),
        )
    if obligation_ids != sorted(obligation_ids) or len(obligation_ids) != len(set(obligation_ids)):
        raise IntegrityError("typed obligation deltas must be sorted and unique")
    if composite == "operation_reconciled" and payload["operation_result"] == "cancel_terminal":
        if sorted(obligation_kinds) != ["cancellation", "submission"]:
            raise IntegrityError("cancel-terminal composite must update cancel and parent submission")

    staged_clients = dict(clients)
    client_ids: list[str] = []
    for raw in raw_clients:
        delta = _require_dict(raw, "client delta")
        expected_fields = {"operation_key", "expected_state", "new_state", "head_digest"}
        if set(delta) != expected_fields:
            raise IntegrityError("typed client delta has an invalid field set")
        operation_key = _require_string(delta, "operation_key")
        client_ids.append(operation_key)
        current = staged_clients.get(operation_key)
        if current is None:
            raise IntegrityError("typed client delta references an unknown operation")
        expected = _client_value(
            _require_string(delta, "expected_state"), "client expected_state"
        )
        target = _client_value(_require_string(delta, "new_state"), "client new_state")
        if current.state != expected:
            raise IntegrityError("typed client delta CAS precondition failed")
        transition = derive_transition(
            "external_client", current.state.value, event.event_type, payload
        )
        if transition is None or transition.to_state != target.value:
            raise IntegrityError("typed client target is not machine-derived")
        staged_clients[operation_key] = MutationClientRecord(
            operation_key, target, _require_string(delta, "head_digest")
        )
    if client_ids != sorted(client_ids) or len(client_ids) != len(set(client_ids)):
        raise IntegrityError("typed client deltas must be sorted and unique")
    if composite == "duplicate_arbitrated":
        open_clients = {
            key
            for key, value in clients.items()
            if value.state != ExternalClientState.TERMINAL_DRAINED
        }
        if set(client_ids) != open_clients:
            raise IntegrityError("duplicate arbitration must close every client debt")
    return target_analysis, staged_obligations, staged_clients


def _apply_keyed_client_transition(
    event: Event,
    payload: dict[str, Any],
    clients: dict[str, MutationClientRecord],
) -> dict[str, MutationClientRecord]:
    raw_deltas = payload["client_deltas"]
    if not raw_deltas:
        raise IntegrityError("keyed client event requires one or more deltas")
    staged = dict(clients)
    identities: list[str] = []
    for raw in raw_deltas:
        delta = _require_dict(raw, "client delta")
        if set(delta) != {"operation_key", "expected_state", "new_state", "head_digest"}:
            raise IntegrityError("keyed client delta has an invalid field set")
        key = _require_string(delta, "operation_key")
        identities.append(key)
        current = staged.get(key)
        current_state = current.state if current else ExternalClientState.NONE
        expected = _client_value(delta["expected_state"], "client expected_state")
        target = _client_value(delta["new_state"], "client new_state")
        if current_state != expected:
            raise IntegrityError("keyed client CAS precondition failed")
        transition = derive_transition(
            "external_client", current_state.value, event.event_type, payload
        )
        if transition is None or transition.to_state != target.value:
            raise IntegrityError("keyed client target is not machine-derived")
        staged[key] = MutationClientRecord(
            key, target, _require_string(delta, "head_digest")
        )
    if identities != sorted(identities) or len(identities) != len(set(identities)):
        raise IntegrityError("keyed client deltas must be sorted and unique")
    return staged


def _run_local_projection_v2(
    *,
    run_id: str,
    ledger_id: str,
    tail: Event,
    attempts: tuple[AttemptState, ...],
    active_attempt_id: str,
    dependency_root: str,
    preparations: tuple[Preparation, ...],
    evidence: tuple[EvidenceCutHead, ...],
    classifications: tuple[CompletionClassification, ...],
    obligations: tuple[ObligationRecord, ...],
    clients: tuple[MutationClientRecord, ...],
    blockers: tuple[str, ...],
    reachable: tuple[RunEventReference, ...],
    merge_policy_digest: str,
) -> dict[str, Any]:
    active = next(item for item in attempts if item.attempt_id == active_attempt_id)
    return {
        "run_id": run_id,
        "ledger_id": ledger_id,
        "run_event_seq": tail.event_seq,
        "run_event_hash": tail.event_hash,
        "analysis_state": active.analysis_state.value,
        "attempts": [_attempt_projection(item) for item in attempts],
        "active_attempt_id": active_attempt_id,
        "attempt_dependency_heads": [
            _dependency_projection(item) for item in active.direct_dependency_heads
        ],
        "attempt_dependency_closure": [
            _dependency_projection(item) for item in active.dependency_closure
        ],
        "attempt_dependency_heads_root": dependency_root,
        "preparations": [_preparation_projection(item) for item in preparations],
        "evidence_cut_heads": [_evidence_projection(item) for item in evidence],
        "completion_classifications": [
            _classification_projection(item) for item in classifications
        ],
        "obligations": [_obligation_projection(item) for item in obligations],
        "mutation_clients": [_client_projection(item) for item in clients],
        "postcommit_intake_blockers": list(blockers),
        "reachable_run_events": [
            {"event_id": item.event_id, "event_hash": item.event_hash} for item in reachable
        ],
        "merge_policy_digest": merge_policy_digest,
        "run_local_reducer_digest": RUN_LOCAL_REDUCER_DIGEST,
    }


def _new_attempt_from_payload(
    payload: dict[str, Any], analysis_state: AnalysisState, prior: str | None
) -> AttemptState:
    return AttemptState(
        _require_string(payload, "attempt_id"),
        prior,
        _require_string(payload, "branch_id"),
        analysis_state,
        (),
        (),
        _require_string(payload, "request_key"),
        _require_string(payload, "intent_key"),
        _require_string(payload, "execution_key"),
        _require_string(payload, "local_execution_key"),
        _require_string(payload, "submission_key"),
        tuple(payload["operation_keys"]),
    )


def _project_object(namespace: str, payload: dict[str, Any]) -> ProjectObjectHead:
    required = {"object_type", "object_id", "object_head", "dependencies"}
    if not required <= set(payload):
        raise IntegrityError("semantic activation fields are incomplete")
    raw_dependencies = payload["dependencies"]
    if not isinstance(raw_dependencies, list):
        raise IntegrityError("semantic activation dependencies must be a list")
    dependencies = tuple(sorted(_dependency(raw) for raw in raw_dependencies))
    if len(dependencies) != len({(item.namespace, item.object_id) for item in dependencies}):
        raise IntegrityError("semantic activation dependencies must be unique")
    return ProjectObjectHead(
        namespace,
        _require_string(payload, "object_type"),
        _require_string(payload, "object_id"),
        _require_string(payload, "object_head"),
        dependencies,
        payload.get("run_id") if isinstance(payload.get("run_id"), str) else None,
    )


def _object_projection(item: ProjectObjectHead) -> dict[str, Any]:
    return {
        "namespace": item.namespace,
        "object_type": item.object_type,
        "object_id": item.object_id,
        "object_head": item.object_head,
        "dependencies": [_dependency_projection(dep) for dep in item.dependencies],
        "owner_run_id": item.owner_run_id,
    }


def _compute_invalidation(
    objects: tuple[ProjectObjectHead, ...], explicit: set[str]
) -> tuple[str, ...]:
    by_identity = {(item.namespace, item.object_id): item for item in objects}
    invalid = set(explicit)
    changed = True
    while changed:
        changed = False
        for item in objects:
            identity = f"{item.namespace}:{item.object_id}"
            if identity in invalid:
                continue
            for dependency in item.dependencies:
                active = by_identity.get((dependency.namespace, dependency.object_id))
                dep_identity = f"{dependency.namespace}:{dependency.object_id}"
                if (
                    active is None
                    or active.object_head != dependency.object_head
                    or dep_identity in invalid
                ):
                    invalid.add(identity)
                    changed = True
                    break
    return tuple(sorted(invalid))


def empty_project_state_root(namespace: str) -> str:
    if namespace not in GENESIS_TYPES:
        raise IntegrityError("unknown project reducer namespace")
    return domain_hash(
        ACTIVE_ROOT_DOMAIN, {"namespace": namespace, "objects": []}
    )


def _project_graph(
    objects: tuple[ProjectObjectHead, ...]
) -> tuple[tuple[tuple[str, str], ...], tuple[tuple[str, tuple[str, ...]], ...]]:
    edges = tuple(
        sorted(
            (
                f"{item.namespace}:{item.object_id}",
                f"{dependency.namespace}:{dependency.object_id}",
            )
            for item in objects
            for dependency in item.dependencies
        )
    )
    identities = {f"{item.namespace}:{item.object_id}" for item in objects}
    descendants = {identity: set() for identity in identities}
    for source, dependency in edges:
        descendants.setdefault(dependency, set()).add(source)
    changed = True
    while changed:
        changed = False
        for identity in list(descendants):
            expanded = set(descendants[identity])
            for child in tuple(expanded):
                expanded.update(descendants.get(child, ()))
            if expanded != descendants[identity]:
                descendants[identity] = expanded
                changed = True
    return edges, tuple(
        sorted((identity, tuple(sorted(values))) for identity, values in descendants.items())
    )


def _project_validity_values_v2(
    objects: tuple[ProjectObjectHead, ...], invalidation: tuple[str, ...], policy: str
) -> tuple[
    str,
    str,
    tuple[tuple[str, str], ...],
    tuple[tuple[str, tuple[str, ...]], ...],
]:
    edges, descendants = _project_graph(objects)
    projection = {
        "active_object_heads": [_object_projection(item) for item in objects],
        "invalidation_closure": list(invalidation),
        "dependency_edges": [list(item) for item in edges],
        "descendant_closure": [
            [identity, list(values)] for identity, values in descendants
        ],
        "locked_policy_digest": policy,
        "project_validity_reducer_digest": PROJECT_VALIDITY_REDUCER_DIGEST,
    }
    return (
        PROJECT_VALIDITY_REDUCER_DIGEST,
        domain_hash(PROJECT_VALIDITY_DOMAIN, projection),
        edges,
        descendants,
    )


def _validate_overlay_binding(local: RunLocalState, overlay: ProjectOverlay) -> None:
    if overlay.run_id != local.run_id:
        return
    reachable = {(item.event_id, item.event_hash) for item in local.reachable_run_events}
    if (overlay.run_event_id, overlay.run_event_hash) not in reachable:
        raise IntegrityError("project transition references an unreachable run event")
    if overlay.event_type == "CORRECTION_BRANCH_CREATED":
        return
    preparation = next(
        (
            item
            for item in local.preparations
            if item.prepare_event_id == overlay.prepare_event_id
            and item.prepare_event_hash == overlay.prepare_event_hash
        ),
        None,
    )
    if preparation is None or not preparation.active:
        raise IntegrityError("project transition references no active durable preparation")
    if (
        overlay.event_type == "STAGE_COMMITTED"
        and overlay.transaction_id != preparation.commit_tx_id
    ):
        raise IntegrityError("project commit transaction does not match durable preparation")
    if (
        preparation.evidence_cut_id != overlay.evidence_cut_id
        or preparation.evidence_cut_digest != overlay.evidence_cut_digest
    ):
        raise IntegrityError("project transition evidence binding disagrees with preparation")
    evidence = next(
        (item for item in local.evidence_cut_heads if item.evidence_cut_id == overlay.evidence_cut_id),
        None,
    )
    if evidence is None or evidence.head_digest != overlay.evidence_cut_digest:
        raise IntegrityError("project transition references an unreachable evidence cut")


def _validate_successor_attempt(
    successor: AttemptState, attempts: dict[str, AttemptState], prior_attempt_id: str
) -> None:
    if successor.prior_attempt_id != prior_attempt_id or successor.attempt_id in attempts:
        raise IntegrityError("project correction successor identity is inconsistent")
    for prior in attempts.values():
        if (
            successor.branch_id == prior.branch_id
            or successor.request_key == prior.request_key
            or successor.intent_key == prior.intent_key
            or successor.execution_key == prior.execution_key
            or successor.local_execution_key == prior.local_execution_key
            or successor.submission_key == prior.submission_key
            or set(successor.operation_keys) & set(prior.operation_keys)
        ):
            raise IntegrityError("project correction must allocate new attempt keys")
