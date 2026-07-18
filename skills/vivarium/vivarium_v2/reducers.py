from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any

from .canonical import domain_hash
from .errors import IntegrityError
from .events import Event, ZERO_HASH
from .state import (
    AnalysisState,
    COMMIT_ABORT_REASON_TARGET,
    DependencyHead,
    EvidenceCutHead,
    ExternalClientState,
    FederatedState,
    MutationClientRecord,
    ObligationRecord,
    ObligationState,
    Preparation,
    ProjectObjectHead,
    ProjectOverlay,
    ProjectPrefixes,
    ProjectSemanticCut,
    ProjectValidity,
    RelevantProjectInput,
    RunEventReference,
    RunLocalState,
    RunValiditySlice,
    STATE_MACHINE,
    match_transition,
)


PROJECT_CUT_DOMAIN = "vivarium-project-semantic-cut/v1"
RUN_LOCAL_DOMAIN = "vivarium-run-local-state/v1"
RUN_VALIDITY_DOMAIN = "vivarium-run-validity-slice/v1"
FEDERATED_DOMAIN = "vivarium-federated-run-state/v1"
PROJECT_VALIDITY_DOMAIN = "vivarium-project-validity/v1"
DEPENDENCY_HEADS_DOMAIN = "vivarium-attempt-dependency-heads/v1"
RELEVANT_PROJECT_INPUT_DOMAIN = "vivarium-relevant-project-validity-input/v1"
ACTIVE_ROOT_DOMAIN = "vivarium-project-active-root/v1"

RUN_LOCAL_REDUCER_DIGEST = domain_hash(
    "vivarium-reducer-definition/v1", {"reducer": "run-local", "version": 1}
)
PROJECT_VALIDITY_REDUCER_DIGEST = domain_hash(
    "vivarium-reducer-definition/v1", {"reducer": "project-validity", "version": 1}
)
RUN_VALIDITY_REDUCER_DIGEST = domain_hash(
    "vivarium-reducer-definition/v1", {"reducer": "run-validity", "version": 1}
)
FEDERATED_REDUCER_DIGEST = domain_hash(
    "vivarium-reducer-definition/v1", {"reducer": "federated", "version": 1}
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
PROJECT_SEMANTIC_EVENTS = {
    "truth": frozenset({"FACT_ACTIVATED", "FACT_INVALIDATED"}),
    "decision": frozenset({"DECISION_ACTIVATED", "POLICY_LOCKED"}),
    "work": frozenset(
        {
            "STAGE_COMMITTED",
            "COMPLETION_RECHECK_OPENED",
            "COMPLETION_PROOF_REFRESHED",
            "COMPLETION_PROOF_REVOKED",
            "STAGE_ROLLED_BACK",
            "CORRECTION_BRANCH_CREATED",
        }
    ),
    "memory": frozenset({"MEMORY_ACTIVATED", "MEMORY_INVALIDATED"}),
    "run_registry": frozenset({"RUN_REGISTERED", "RUN_REGISTRY_ACTIVATED"}),
}
PROJECT_OVERLAY_EVENTS = frozenset(
    {
        "STAGE_COMMITTED",
        "COMPLETION_RECHECK_OPENED",
        "COMPLETION_PROOF_REFRESHED",
        "COMPLETION_PROOF_REVOKED",
        "CORRECTION_BRANCH_CREATED",
    }
)
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

ReduceRun = Callable[[Sequence[Event]], RunLocalState]
ReduceProjectCut = Callable[[ProjectPrefixes], ProjectSemanticCut]
ReduceProjectValidity = Callable[[ProjectSemanticCut], ProjectValidity]
ReduceRunValidity = Callable[
    [ProjectSemanticCut, ProjectValidity, RunLocalState], RunValiditySlice
]
Federate = Callable[
    [RunLocalState, ProjectSemanticCut, ProjectValidity, RunValiditySlice], FederatedState
]


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


def _apply_obligation_deltas(
    event: Event, payload: dict[str, Any], obligations: dict[str, ObligationRecord]
) -> bool:
    raw_deltas = payload.get("obligation_deltas")
    if raw_deltas is None:
        return False
    if not isinstance(raw_deltas, list):
        raise IntegrityError("obligation_deltas must be a list")
    identities: list[str] = []
    staged = dict(obligations)
    for raw in raw_deltas:
        item = _require_dict(raw, "obligation delta")
        expected_fields = {
            "obligation_id", "obligation_kind", "expected_state", "new_state",
            "head_digest", "guard",
        }
        if set(item) != expected_fields:
            raise IntegrityError("obligation delta has an invalid field set")
        obligation_id = _require_string(item, "obligation_id")
        identities.append(obligation_id)
        current = staged.get(obligation_id)
        current_state = current.state if current else ObligationState.NONE
        expected = _obligation_value(
            _require_string(item, "expected_state"), "obligation expected_state"
        )
        target = _obligation_value(
            _require_string(item, "new_state"), "obligation new_state"
        )
        if current_state != expected:
            raise IntegrityError("obligation delta CAS precondition failed")
        transition = match_transition(
            "obligation", current_state.value, event.event_type, _require_string(item, "guard")
        )
        if transition.to_state != target.value:
            raise IntegrityError("obligation delta target is not closed")
        staged[obligation_id] = ObligationRecord(
            obligation_id,
            _require_string(item, "obligation_kind"),
            target,
            _require_string(item, "head_digest"),
        )
    if identities != sorted(identities) or len(identities) != len(set(identities)):
        raise IntegrityError("obligation deltas must be sorted with unique IDs")
    obligations.clear()
    obligations.update(staged)
    return True


def _apply_client_deltas(
    event: Event, payload: dict[str, Any], clients: dict[str, MutationClientRecord]
) -> bool:
    raw_deltas = payload.get("client_deltas")
    if raw_deltas is None:
        return False
    if not isinstance(raw_deltas, list):
        raise IntegrityError("client_deltas must be a list")
    identities: list[str] = []
    staged = dict(clients)
    for raw in raw_deltas:
        item = _require_dict(raw, "client delta")
        expected_fields = {
            "operation_key", "expected_state", "new_state", "head_digest", "guard"
        }
        if set(item) != expected_fields:
            raise IntegrityError("client delta has an invalid field set")
        operation_key = _require_string(item, "operation_key")
        identities.append(operation_key)
        current = staged.get(operation_key)
        current_state = current.state if current else ExternalClientState.NONE
        expected = _client_value(
            _require_string(item, "expected_state"), "client expected_state"
        )
        target = _client_value(_require_string(item, "new_state"), "client new_state")
        if current_state != expected:
            raise IntegrityError("client delta CAS precondition failed")
        transition = match_transition(
            "external_client",
            current_state.value,
            event.event_type,
            _require_string(item, "guard"),
        )
        if transition.to_state != target.value:
            raise IntegrityError("client delta target is not closed")
        staged[operation_key] = MutationClientRecord(
            operation_key, target, _require_string(item, "head_digest")
        )
    if identities != sorted(identities) or len(identities) != len(set(identities)):
        raise IntegrityError("client deltas must be sorted with unique keys")
    clients.clear()
    clients.update(staged)
    return True


def _run_local_projection(
    *,
    run_id: str,
    ledger_id: str,
    tail: Event,
    analysis_state: AnalysisState,
    dependencies: tuple[DependencyHead, ...],
    dependency_root: str,
    preparations: tuple[Preparation, ...],
    evidence: tuple[EvidenceCutHead, ...],
    obligations: tuple[ObligationRecord, ...],
    clients: tuple[MutationClientRecord, ...],
    blockers: tuple[str, ...],
    reachable: tuple[RunEventReference, ...],
    merge_policy_digest: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "ledger_id": ledger_id,
        "run_event_seq": tail.event_seq,
        "run_event_hash": tail.event_hash,
        "analysis_state": analysis_state.value,
        "attempt_dependency_heads": [_dependency_projection(item) for item in dependencies],
        "attempt_dependency_heads_root": dependency_root,
        "preparations": [_preparation_projection(item) for item in preparations],
        "evidence_cut_heads": [_evidence_projection(item) for item in evidence],
        "obligations": [_obligation_projection(item) for item in obligations],
        "mutation_clients": [_client_projection(item) for item in clients],
        "postcommit_intake_blockers": list(blockers),
        "reachable_run_events": [
            {"event_id": item.event_id, "event_hash": item.event_hash} for item in reachable
        ],
        "merge_policy_digest": merge_policy_digest,
        "run_local_reducer_digest": RUN_LOCAL_REDUCER_DIGEST,
    }


def reduce_run(events: Sequence[Event]) -> RunLocalState:
    prefix = _verify_event_prefix(events, genesis_type="RUN_LEDGER_GENESIS")
    genesis_payload = _require_dict(prefix[0].payload, "run genesis payload")
    run_id = _require_string(genesis_payload, "run_id")
    analysis_state = _analysis_value(
        _require_string(genesis_payload, "analysis_state"), "run genesis analysis state"
    )
    merge_policy_digest = _require_string(genesis_payload, "merge_policy_digest")
    dependencies: tuple[DependencyHead, ...] = ()
    evidence: dict[str, EvidenceCutHead] = {}
    preparations: dict[str, Preparation] = {}
    obligations = _parse_initial_obligations(genesis_payload)
    clients = _parse_initial_clients(genesis_payload)
    blockers: set[str] = set()

    for item in prefix[1:]:
        payload = _require_dict(item.payload, f"{item.event_type} payload")
        handled = False
        if item.event_type == "ATTEMPT_DEPENDENCIES_FROZEN":
            if dependencies:
                raise IntegrityError("attempt dependency heads may only be frozen once")
            raw_dependencies = payload.get("dependency_heads")
            if not isinstance(raw_dependencies, list):
                raise IntegrityError("dependency_heads must be a list")
            dependencies = tuple(sorted(_dependency(raw) for raw in raw_dependencies))
            if len(dependencies) != len({(d.namespace, d.object_id) for d in dependencies}):
                raise IntegrityError("attempt dependency heads must have unique object identities")
            handled = True
        elif item.event_type == "EVIDENCE_CUT_FROZEN":
            cut_id = _require_string(payload, "evidence_cut_id")
            if cut_id in evidence:
                raise IntegrityError("evidence cut head may only be frozen once")
            evidence[cut_id] = EvidenceCutHead(
                cut_id,
                _require_string(payload, "head_digest"),
                item.event_id,
                item.event_hash,
            )
            handled = True
        elif item.event_type == "COMMIT_PREPARED":
            if analysis_state not in {AnalysisState.COMMITTING, AnalysisState.RECOVERY_REQUIRED}:
                raise IntegrityError("commit preparation is not legal in the current analysis state")
            commit_tx_id = _require_string(payload, "commit_tx_id")
            if commit_tx_id in preparations:
                raise IntegrityError("commit_tx_id may only have one durable preparation")
            evidence_cut_id = _require_string(payload, "evidence_cut_id")
            evidence_cut_digest = _require_string(payload, "evidence_cut_digest")
            if evidence_cut_id not in evidence or evidence[evidence_cut_id].head_digest != evidence_cut_digest:
                raise IntegrityError("commit preparation references an unknown evidence cut")
            origin = _analysis_value(
                _require_string(payload, "origin_state"), "commit preparation origin state"
            )
            if origin != analysis_state:
                raise IntegrityError("commit preparation origin state does not match")
            preparations[commit_tx_id] = Preparation(
                commit_tx_id,
                item.event_id,
                item.event_hash,
                evidence_cut_id,
                evidence_cut_digest,
                origin,
                True,
            )
            handled = True
        elif item.event_type == "POSTCOMMIT_OBSERVATION_INBOXED":
            if analysis_state not in {
                AnalysisState.COMMITTING,
                AnalysisState.RECOVERY_REQUIRED,
                AnalysisState.COMMITTED,
                AnalysisState.COMPLETION_RECHECK_PENDING,
            }:
                raise IntegrityError("postcommit intake is not legal before commit preparation")
            observation_id = _require_string(payload, "observation_id")
            _require_string(payload, "observed_object_id")
            _require_string(payload, "observation_digest")
            if observation_id in blockers:
                raise IntegrityError("postcommit observation IDs must be unique")
            blockers.add(observation_id)
            handled = True
        elif item.event_type == "POSTCOMMIT_OBSERVATION_OPENED":
            observation_id = _require_string(payload, "observation_id")
            if observation_id not in blockers:
                raise IntegrityError("opened observation is not inboxed")
            blockers.remove(observation_id)
            handled = True
        elif item.event_type == "STAGE_COMMIT_ABORTED":
            reason = _require_string(payload, "abort_reason")
            target = COMMIT_ABORT_REASON_TARGET.get(reason)
            if target is None:
                raise IntegrityError("commit abort reason is not closed")
            if _require_string(payload, "analysis_from") != analysis_state.value:
                raise IntegrityError("commit abort analysis_from does not match")
            if _require_string(payload, "analysis_target") != target.value:
                raise IntegrityError("commit abort analysis_target does not match reason map")
            transition = match_transition("analysis", analysis_state.value, item.event_type, reason)
            if transition.to_state != target.value:
                raise IntegrityError("commit abort transition disagrees with reason map")
            commit_tx_id = _require_string(payload, "commit_tx_id")
            preparation = preparations.get(commit_tx_id)
            if preparation is None or not preparation.active:
                raise IntegrityError("commit abort does not reference one active preparation")
            if (
                _require_string(payload, "prepare_event_id") != preparation.prepare_event_id
                or _require_string(payload, "prepare_event_hash") != preparation.prepare_event_hash
            ):
                raise IntegrityError("commit abort preparation binding does not match")
            _require_string(payload, "sealed_failure_digest")
            delta = _require_dict(payload.get("preparation_delta"), "preparation_delta")
            if delta != {"from": "ACTIVE", "to": "INACTIVE"}:
                raise IntegrityError("commit abort must atomically deactivate its preparation")
            if reason in COMPLETION_ABORT_REASONS:
                _require_string(payload, "completion_classification_id")
                _require_string(payload, "completion_classification_digest")
            preparations[commit_tx_id] = replace(preparation, active=False)
            analysis_state = target
            handled = True

        obligation_handled = _apply_obligation_deltas(item, payload, obligations)
        client_handled = _apply_client_deltas(item, payload, clients)

        if item.event_type != "STAGE_COMMIT_ABORTED":
            analysis_delta = payload.get("analysis_delta")
            if analysis_delta is not None:
                delta = _require_dict(analysis_delta, "analysis_delta")
                if set(delta) != {"expected_state", "new_state", "guard"}:
                    raise IntegrityError("analysis_delta has an invalid field set")
                expected = _analysis_value(
                    _require_string(delta, "expected_state"), "analysis expected_state"
                )
                target = _analysis_value(
                    _require_string(delta, "new_state"), "analysis new_state"
                )
                if expected != analysis_state:
                    raise IntegrityError("analysis delta CAS precondition failed")
                transition = match_transition(
                    "analysis", analysis_state.value, item.event_type, _require_string(delta, "guard")
                )
                if transition.owner_ledger != "run" or transition.to_state != target.value:
                    raise IntegrityError("analysis delta is not a run-owned closed transition")
                analysis_state = target
                handled = True
            elif "guard" in payload:
                guard = _require_string(payload, "guard")
                transition = match_transition(
                    "analysis", analysis_state.value, item.event_type, guard
                )
                if transition.owner_ledger != "run":
                    raise IntegrityError("project-owned transition cannot be appended to run ledger")
                analysis_state = AnalysisState(transition.to_state)
                handled = True
            elif item.event_type == "COMPLETION_CLASSIFIED":
                outcome = _require_string(payload, "outcome")
                transition = match_transition(
                    "analysis", analysis_state.value, item.event_type, outcome
                )
                if transition.owner_ledger != "run":
                    raise IntegrityError("classification transition has the wrong owner")
                analysis_state = AnalysisState(transition.to_state)
                handled = True

        if not (handled or obligation_handled or client_handled):
            raise IntegrityError(f"unsupported run event: {item.event_type}")

    ordered_dependencies = tuple(sorted(dependencies))
    dependency_root = domain_hash(
        DEPENDENCY_HEADS_DOMAIN,
        [_dependency_projection(item) for item in ordered_dependencies],
    )
    ordered_preparations = tuple(sorted(preparations.values()))
    ordered_evidence = tuple(sorted(evidence.values()))
    ordered_obligations = tuple(sorted(obligations.values()))
    ordered_clients = tuple(sorted(clients.values()))
    ordered_blockers = tuple(sorted(blockers))
    reachable = tuple(RunEventReference(item.event_id, item.event_hash) for item in prefix)
    projection = _run_local_projection(
        run_id=run_id,
        ledger_id=prefix[-1].ledger_id,
        tail=prefix[-1],
        analysis_state=analysis_state,
        dependencies=ordered_dependencies,
        dependency_root=dependency_root,
        preparations=ordered_preparations,
        evidence=ordered_evidence,
        obligations=ordered_obligations,
        clients=ordered_clients,
        blockers=ordered_blockers,
        reachable=reachable,
        merge_policy_digest=merge_policy_digest,
    )
    root = domain_hash(RUN_LOCAL_DOMAIN, projection)
    return RunLocalState(
        run_id,
        prefix[-1].ledger_id,
        prefix[-1].event_seq,
        prefix[-1].event_hash,
        analysis_state,
        ordered_dependencies,
        dependency_root,
        ordered_preparations,
        ordered_evidence,
        ordered_obligations,
        ordered_clients,
        ordered_blockers,
        reachable,
        merge_policy_digest,
        RUN_LOCAL_REDUCER_DIGEST,
        root,
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
    )


def _object_projection(item: ProjectObjectHead) -> dict[str, Any]:
    return {
        "namespace": item.namespace,
        "object_type": item.object_type,
        "object_id": item.object_id,
        "object_head": item.object_head,
        "dependencies": [_dependency_projection(dep) for dep in item.dependencies],
    }


def _overlay_projection(item: ProjectOverlay) -> dict[str, Any]:
    return {
        "project_revision": item.project_revision,
        "event_type": item.event_type,
        "run_id": item.run_id,
        "run_event_id": item.run_event_id,
        "run_event_hash": item.run_event_hash,
        "transaction_id": item.transaction_id,
        "prepare_event_id": item.prepare_event_id,
        "prepare_event_hash": item.prepare_event_hash,
        "evidence_cut_id": item.evidence_cut_id,
        "evidence_cut_digest": item.evidence_cut_digest,
        "event_id": item.event_id,
        "event_hash": item.event_hash,
    }


def _parse_genesis_objects(namespace: str, payload: dict[str, Any]) -> list[ProjectObjectHead]:
    values = payload.get("activated_objects")
    if not isinstance(values, list):
        raise IntegrityError("genesis activated_objects must be a list")
    result = []
    for raw in values:
        item = _require_dict(raw, "genesis activated object")
        result.append(_project_object(namespace, item))
    edges = payload.get("canonical_dependency_edges")
    if not isinstance(edges, list):
        raise IntegrityError("genesis canonical_dependency_edges must be a list")
    _require_string(payload, "initial_state_root")
    return result


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


def _project_validity_values(
    objects: tuple[ProjectObjectHead, ...], invalidation: tuple[str, ...], policy: str
) -> tuple[str, str]:
    projection = {
        "active_object_heads": [_object_projection(item) for item in objects],
        "invalidation_closure": list(invalidation),
        "locked_policy_digest": policy,
        "project_validity_reducer_digest": PROJECT_VALIDITY_REDUCER_DIGEST,
    }
    return PROJECT_VALIDITY_REDUCER_DIGEST, domain_hash(PROJECT_VALIDITY_DOMAIN, projection)


def reduce_project_cut(prefixes: ProjectPrefixes) -> ProjectSemanticCut:
    if not isinstance(prefixes, ProjectPrefixes):
        raise IntegrityError("project prefixes must use the frozen ProjectPrefixes model")
    verified: dict[str, tuple[Event, ...]] = {}
    locked_policies: set[str] = set()
    objects: dict[tuple[str, str], ProjectObjectHead] = {}
    explicit_invalid: set[str] = set()
    semantic: list[tuple[int, str, Event, dict[str, Any]]] = []
    semantic_tails: dict[str, Event] = {}

    for namespace in GENESIS_TYPES:
        events = _verify_event_prefix(
            getattr(prefixes, namespace),
            genesis_type=GENESIS_TYPES[namespace],
            ledger_id=GENESIS_LEDGER_IDS[namespace],
        )
        verified[namespace] = events
        genesis_payload = _require_dict(events[0].payload, f"{namespace} genesis payload")
        locked_policies.add(_require_string(genesis_payload, "locked_policy_digest"))
        for active in _parse_genesis_objects(namespace, genesis_payload):
            identity = (active.namespace, active.object_id)
            if identity in objects:
                raise IntegrityError("genesis active object identities must be unique")
            objects[identity] = active
        semantic_tails[namespace] = events[0]
        for item in events[1:]:
            if namespace == "work" and item.event_type == "HANDOFF_PUBLISHED":
                _require_string(_require_dict(item.payload, "handoff payload"), "artifact_digest")
                continue
            if item.event_type not in PROJECT_SEMANTIC_EVENTS[namespace]:
                raise IntegrityError(f"unsupported {namespace} project event: {item.event_type}")
            payload = _require_dict(item.payload, f"{item.event_type} payload")
            revision = _require_int(payload, "project_revision")
            if revision <= 0:
                raise IntegrityError("semantic project revisions must be positive")
            semantic.append((revision, namespace, item, payload))
            semantic_tails[namespace] = item

    if len(locked_policies) != 1:
        raise IntegrityError("project genesis anchors disagree on locked policy")
    locked_policy = next(iter(locked_policies))
    semantic.sort(key=lambda entry: entry[0])
    revisions = [entry[0] for entry in semantic]
    if revisions != list(range(1, len(semantic) + 1)):
        raise IntegrityError("project semantic revisions must form one cross-ledger sequence")

    overlays: list[ProjectOverlay] = []
    for revision, namespace, item, payload in semantic:
        active = _project_object(namespace, payload)
        identity = (namespace, active.object_id)
        objects[identity] = active
        identity_string = f"{namespace}:{active.object_id}"
        if item.event_type.endswith("_INVALIDATED") or payload.get("invalidated") is True:
            explicit_invalid.add(identity_string)
        else:
            explicit_invalid.discard(identity_string)
        if item.event_type == "POLICY_LOCKED":
            locked_policy = _require_string(payload, "locked_policy_digest")
        if item.event_type in PROJECT_OVERLAY_EVENTS:
            binding_fields = {"run_id", "run_event_id", "run_event_hash"}
            if item.event_type != "CORRECTION_BRANCH_CREATED":
                binding_fields |= {
                    "prepare_event_id", "prepare_event_hash", "evidence_cut_id",
                    "evidence_cut_digest",
                }
            if not binding_fields <= set(payload):
                raise IntegrityError("project-owned run transition is missing run/prepare/evidence binding")
            if item.event_type == "STAGE_COMMITTED":
                transaction_field = "commit_tx_id"
            elif item.event_type == "CORRECTION_BRANCH_CREATED":
                transaction_field = "correction_id"
            else:
                transaction_field = "recheck_tx_id"
            overlays.append(
                ProjectOverlay(
                    revision,
                    item.event_type,
                    _require_string(payload, "run_id"),
                    _require_string(payload, "run_event_id"),
                    _require_string(payload, "run_event_hash"),
                    _require_string(payload, transaction_field),
                    _require_string(payload, "prepare_event_id")
                    if item.event_type != "CORRECTION_BRANCH_CREATED" else "",
                    _require_string(payload, "prepare_event_hash")
                    if item.event_type != "CORRECTION_BRANCH_CREATED" else "",
                    _require_string(payload, "evidence_cut_id")
                    if item.event_type != "CORRECTION_BRANCH_CREATED" else "",
                    _require_string(payload, "evidence_cut_digest")
                    if item.event_type != "CORRECTION_BRANCH_CREATED" else "",
                    item.event_id,
                    item.event_hash,
                )
            )

    active_objects = tuple(sorted(objects.values()))
    invalidation = _compute_invalidation(active_objects, explicit_invalid)
    validity_digest, validity_root = _project_validity_values(
        active_objects, invalidation, locked_policy
    )

    active_roots = {}
    for namespace in GENESIS_TYPES:
        namespace_objects = [
            _object_projection(item) for item in active_objects if item.namespace == namespace
        ]
        active_roots[namespace] = domain_hash(
            ACTIVE_ROOT_DOMAIN, {"namespace": namespace, "objects": namespace_objects}
        )
    active_fact_vector_digest = domain_hash(
        "vivarium-active-fact-vector/v1",
        [
            _object_projection(item)
            for item in active_objects
            if item.namespace == "truth" and item.object_type == "fact"
        ],
    )
    tails = semantic_tails
    projection = {
        "project_revision": len(semantic),
        "truth_event_seq": tails["truth"].event_seq,
        "truth_event_hash": tails["truth"].event_hash,
        "active_truth_root": active_roots["truth"],
        "active_fact_vector_digest": active_fact_vector_digest,
        "truth_reducer_digest": LEDGER_REDUCER_DIGESTS["truth"],
        "decision_event_seq": tails["decision"].event_seq,
        "decision_event_hash": tails["decision"].event_hash,
        "active_decision_root": active_roots["decision"],
        "decision_reducer_digest": LEDGER_REDUCER_DIGESTS["decision"],
        "work_state_event_seq": tails["work"].event_seq,
        "work_state_event_hash": tails["work"].event_hash,
        "active_work_root": active_roots["work"],
        "project_work_reducer_digest": LEDGER_REDUCER_DIGESTS["work"],
        "memory_event_seq": tails["memory"].event_seq,
        "memory_event_hash": tails["memory"].event_hash,
        "active_memory_root": active_roots["memory"],
        "memory_reducer_digest": LEDGER_REDUCER_DIGESTS["memory"],
        "run_registry_event_seq": tails["run_registry"].event_seq,
        "run_registry_event_hash": tails["run_registry"].event_hash,
        "active_run_registry_root": active_roots["run_registry"],
        "run_registry_reducer_digest": LEDGER_REDUCER_DIGESTS["run_registry"],
        "locked_policy_digest": locked_policy,
        "project_validity_root": validity_root,
        "project_validity_reducer_digest": validity_digest,
    }
    cut_root = domain_hash(PROJECT_CUT_DOMAIN, projection)
    return ProjectSemanticCut(
        len(semantic),
        tails["truth"].event_seq,
        tails["truth"].event_hash,
        active_roots["truth"],
        active_fact_vector_digest,
        LEDGER_REDUCER_DIGESTS["truth"],
        tails["decision"].event_seq,
        tails["decision"].event_hash,
        active_roots["decision"],
        LEDGER_REDUCER_DIGESTS["decision"],
        tails["work"].event_seq,
        tails["work"].event_hash,
        active_roots["work"],
        LEDGER_REDUCER_DIGESTS["work"],
        tails["memory"].event_seq,
        tails["memory"].event_hash,
        active_roots["memory"],
        LEDGER_REDUCER_DIGESTS["memory"],
        tails["run_registry"].event_seq,
        tails["run_registry"].event_hash,
        active_roots["run_registry"],
        LEDGER_REDUCER_DIGESTS["run_registry"],
        locked_policy,
        active_objects,
        tuple(sorted(overlays)),
        invalidation,
        validity_root,
        validity_digest,
        cut_root,
    )


def reduce_project_validity(cut: ProjectSemanticCut) -> ProjectValidity:
    if not isinstance(cut, ProjectSemanticCut):
        raise IntegrityError("project validity requires a frozen semantic cut")
    invalidation = _compute_invalidation(cut.active_object_heads, set(cut.invalidation_closure))
    digest, root = _project_validity_values(
        cut.active_object_heads, invalidation, cut.locked_policy_digest
    )
    if (
        digest != cut.project_validity_reducer_digest
        or root != cut.project_validity_root
        or invalidation != cut.invalidation_closure
    ):
        raise IntegrityError("project semantic cut carries inconsistent validity fields")
    return ProjectValidity(
        cut.active_object_heads,
        invalidation,
        cut.locked_policy_digest,
        digest,
        root,
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


def _overlay_state(local: RunLocalState, cut: ProjectSemanticCut) -> AnalysisState:
    state = local.analysis_state
    for overlay in sorted(cut.overlays):
        if overlay.run_id != local.run_id:
            continue
        _validate_overlay_binding(local, overlay)
        if overlay.event_type == "STAGE_COMMITTED":
            guard = "commit_tx_durable" if state == AnalysisState.COMMITTING else "durable_valid_tx_found"
        elif overlay.event_type == "CORRECTION_BRANCH_CREATED":
            guard = "new_branch_created"
        elif overlay.event_type == "COMPLETION_RECHECK_OPENED":
            guard = "complete_cut_durable"
        elif overlay.event_type == "COMPLETION_PROOF_REFRESHED":
            guard = "success_allowed_grade_complete_cut"
        else:
            guard = "failure_unknown_disallowed_grade"
        transition = match_transition("analysis", state.value, overlay.event_type, guard)
        if transition.owner_ledger != "project":
            raise IntegrityError("project overlay transition has the wrong owner")
        state = AnalysisState(transition.to_state)
    return state


def reduce_run_validity(
    cut: ProjectSemanticCut, validity: ProjectValidity, local: RunLocalState
) -> RunValiditySlice:
    expected_validity = reduce_project_validity(cut)
    if validity != expected_validity:
        raise IntegrityError("run validity received a mismatched project validity output")
    if not isinstance(local, RunLocalState):
        raise IntegrityError("run validity requires a frozen run-local output")
    active = {
        (item.namespace, item.object_id): item for item in validity.active_object_heads
    }
    invalid = set(validity.invalidation_closure)
    relevant: list[RelevantProjectInput] = []
    reasons: list[str] = []
    for dependency in local.attempt_dependency_heads:
        current = active.get((dependency.namespace, dependency.object_id))
        is_invalid = f"{dependency.namespace}:{dependency.object_id}" in invalid
        active_head = current.object_head if current else None
        relevant.append(
            RelevantProjectInput(
                dependency.namespace,
                dependency.object_id,
                dependency.object_head,
                active_head,
                is_invalid,
            )
        )
        if current is None:
            reasons.append(f"missing:{dependency.namespace}:{dependency.object_id}")
        elif current.object_head != dependency.object_head:
            reasons.append(f"head_changed:{dependency.namespace}:{dependency.object_id}")
        elif is_invalid:
            reasons.append(f"invalidated:{dependency.namespace}:{dependency.object_id}")
    ordered_relevant = tuple(sorted(relevant))
    ordered_reasons = tuple(sorted(reasons))
    relevant_projection = {
        "locked_policy_digest": validity.locked_policy_digest,
        "relevant_project_inputs": [
            {
                "namespace": item.namespace,
                "object_id": item.object_id,
                "expected_head": item.expected_head,
                "active_head": item.active_head,
                "invalidated": item.invalidated,
            }
            for item in ordered_relevant
        ],
    }
    relevant_root = domain_hash(RELEVANT_PROJECT_INPUT_DOMAIN, relevant_projection)
    baseline = _overlay_state(local, cut)
    state = AnalysisState.STALE_CONTEXT if ordered_reasons else baseline
    output = {"state": state.value, "validity_reasons": list(ordered_reasons)}
    projection = {
        "run_id": local.run_id,
        "ledger_id": local.ledger_id,
        "run_event_seq": local.run_event_seq,
        "run_event_hash": local.run_event_hash,
        "run_local_state_root": local.run_local_state_root,
        "attempt_dependency_heads_root": local.attempt_dependency_heads_root,
        "relevant_project_validity_input_root": relevant_root,
        "run_validity_reducer_digest": RUN_VALIDITY_REDUCER_DIGEST,
        "run_validity_output": output,
    }
    root = domain_hash(RUN_VALIDITY_DOMAIN, projection)
    return RunValiditySlice(
        local.run_id,
        local.ledger_id,
        local.run_event_seq,
        local.run_event_hash,
        local.run_local_state_root,
        local.attempt_dependency_heads_root,
        ordered_relevant,
        relevant_root,
        RUN_VALIDITY_REDUCER_DIGEST,
        state,
        ordered_reasons,
        root,
    )


def federate(
    local: RunLocalState,
    cut: ProjectSemanticCut,
    validity: ProjectValidity | None = None,
    run_slice: RunValiditySlice | None = None,
) -> FederatedState:
    expected_validity = reduce_project_validity(cut)
    if validity is None:
        validity = expected_validity
    elif validity != expected_validity:
        raise IntegrityError("federation received a mismatched project validity output")
    expected_slice = reduce_run_validity(cut, validity, local)
    if run_slice is None:
        run_slice = expected_slice
    elif run_slice != expected_slice:
        raise IntegrityError("federation received a mismatched run validity slice")

    recheck_blockers: set[str] = set()
    for overlay in sorted(cut.overlays):
        if overlay.run_id != local.run_id:
            continue
        _validate_overlay_binding(local, overlay)
        if overlay.event_type == "COMPLETION_RECHECK_OPENED":
            recheck_blockers.add(overlay.transaction_id)
        elif overlay.event_type in {"COMPLETION_PROOF_REFRESHED", "COMPLETION_PROOF_REVOKED"}:
            if overlay.transaction_id not in recheck_blockers:
                raise IntegrityError("completion close event has no matching open blocker")
            recheck_blockers.remove(overlay.transaction_id)

    unresolved = sum(
        item.state
        not in {ObligationState.RESOLVED, ObligationState.SUBMISSION_NOT_ACCEPTED_CONFIRMED}
        for item in local.obligations
    )
    live_clients = any(
        item.state != ExternalClientState.TERMINAL_DRAINED for item in local.mutation_clients
    )
    default_retrievable = (
        run_slice.state == AnalysisState.COMMITTED
        and not local.postcommit_intake_blockers
        and not recheck_blockers
        and not run_slice.validity_reasons
        and unresolved == 0
        and not live_clients
    )
    if default_retrievable:
        availability = "RETRIEVABLE"
    elif local.postcommit_intake_blockers:
        availability = "BLOCKED_POSTCOMMIT_INTAKE"
    elif recheck_blockers or run_slice.state == AnalysisState.COMPLETION_RECHECK_PENDING:
        availability = "PENDING_COMPLETION_RECHECK"
    elif run_slice.state in {
        AnalysisState.STALE_CONTEXT,
        AnalysisState.STALE_BRANCH,
        AnalysisState.STALE_COMPLETION,
    }:
        availability = "STALE"
    else:
        availability = "UNAVAILABLE"

    output = {
        "analysis_state": run_slice.state.value,
        "effective_availability": availability,
        "completion_recheck_blockers": sorted(recheck_blockers),
        "postcommit_intake_blockers": list(local.postcommit_intake_blockers),
        "validity_reasons": list(run_slice.validity_reasons),
        "obligations": [_obligation_projection(item) for item in local.obligations],
        "mutation_clients": [_client_projection(item) for item in local.mutation_clients],
        "preparations": [_preparation_projection(item) for item in local.preparations],
        "evidence_cut_heads": [_evidence_projection(item) for item in local.evidence_cut_heads],
        "unresolved_obligation_count": unresolved,
        "default_retrievable": default_retrievable,
    }
    projection = {
        "run_id": local.run_id,
        "ledger_id": local.ledger_id,
        "run_event_seq": local.run_event_seq,
        "run_event_hash": local.run_event_hash,
        "run_local_state_root": local.run_local_state_root,
        "project_semantic_cut_root": cut.project_semantic_cut_root,
        "run_validity_slice_root": run_slice.run_validity_slice_root,
        "run_local_reducer_digest": local.run_local_reducer_digest,
        "project_validity_reducer_digest": validity.project_validity_reducer_digest,
        "run_validity_reducer_digest": run_slice.run_validity_reducer_digest,
        "federated_reducer_digest": FEDERATED_REDUCER_DIGEST,
        "merge_policy_digest": local.merge_policy_digest,
        "federated_reducer_output": output,
    }
    root = domain_hash(FEDERATED_DOMAIN, projection)
    return FederatedState(
        local.run_id,
        local.ledger_id,
        local.run_event_seq,
        local.run_event_hash,
        local.run_local_state_root,
        cut.project_semantic_cut_root,
        run_slice.run_validity_slice_root,
        run_slice.state,
        availability,
        tuple(sorted(recheck_blockers)),
        local.postcommit_intake_blockers,
        run_slice.validity_reasons,
        local.obligations,
        local.mutation_clients,
        local.preparations,
        local.evidence_cut_heads,
        unresolved,
        default_retrievable,
        local.run_local_reducer_digest,
        validity.project_validity_reducer_digest,
        run_slice.run_validity_reducer_digest,
        FEDERATED_REDUCER_DIGEST,
        local.merge_policy_digest,
        root,
    )
