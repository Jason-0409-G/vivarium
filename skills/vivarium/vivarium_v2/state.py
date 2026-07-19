from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, NamedTuple

from .canonical import domain_hash
from .errors import IntegrityError
from .events import Event


STATE_MACHINE_PATH = Path(__file__).parent / "schemas" / "state_machine.yaml"
ALIAS_TOKENS = frozenset({"any", "same", "prior", "*"})


def load_state_machine() -> dict[str, object]:
    try:
        body = json.loads(STATE_MACHINE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IntegrityError("state-machine source is not strict UTF-8 JSON") from exc
    if not isinstance(body, dict) or body.get("schema_version") != "vivarium.state-machine/v1":
        raise IntegrityError("unsupported state-machine schema")
    return body


STATE_MACHINE = load_state_machine()
AnalysisState = Enum(
    "AnalysisState",
    {value: value for value in STATE_MACHINE["enums"]["analysis_state"]},
    type=str,
)
ObligationState = Enum(
    "ObligationState",
    {value: value for value in STATE_MACHINE["enums"]["obligation_state"]},
    type=str,
)
ExternalClientState = Enum(
    "ExternalClientState",
    {value: value for value in STATE_MACHINE["enums"]["external_client_state"]},
    type=str,
)

COMMIT_ABORT_REASON_TARGET = {
    reason: AnalysisState(target)
    for reason, target in STATE_MACHINE["abort_reason_target"].items()
}
COMPLETION_ABORT_OUTCOME = dict(STATE_MACHINE["completion_abort_outcome"])


class Transition(NamedTuple):
    reducer: str
    from_state: str
    event: str
    guard: str
    to_state: str
    owner_ledger: str


@dataclass(frozen=True)
class EventContract:
    event_type: str
    owner_ledger: str
    namespace: str | None
    action: str
    required_fields: tuple[tuple[str, str], ...]
    optional_fields: tuple[tuple[str, str], ...]
    selector_field: str | None
    selector_guards: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]
    composite: str | None


def _compile_transitions() -> tuple[Transition, ...]:
    enums = {
        "analysis": frozenset(STATE_MACHINE["enums"]["analysis_state"]),
        "obligation": frozenset(STATE_MACHINE["enums"]["obligation_state"]),
        "external_client": frozenset(STATE_MACHINE["enums"]["external_client_state"]),
    }
    source_sets = STATE_MACHINE.get("source_sets")
    rows = STATE_MACHINE.get("transitions")
    if not isinstance(source_sets, dict) or not isinstance(rows, list):
        raise IntegrityError("state-machine source sets/transitions must be closed collections")
    compiled: list[Transition] = []
    for row in rows:
        if not isinstance(row, dict):
            raise IntegrityError("state-machine transition must be an object")
        expected = {"reducer", "event", "guard", "to", "owner_ledger"}
        source_keys = {"from", "from_set"} & set(row)
        if len(source_keys) != 1 or set(row) != expected | source_keys:
            raise IntegrityError("state-machine transition has an invalid field set")
        reducer = row["reducer"]
        if reducer not in enums:
            raise IntegrityError("state-machine transition has an unknown reducer")
        if "from" in row:
            sources = (row["from"],)
        else:
            source_name = row["from_set"]
            sources = source_sets.get(source_name)
            if not isinstance(sources, list) or not sources:
                raise IntegrityError("state-machine transition references an open source set")
        for source in sources:
            values = (
                source,
                row["event"],
                row["guard"],
                row["to"],
                row["owner_ledger"],
            )
            if not all(isinstance(value, str) and value for value in values):
                raise IntegrityError("compiled state-machine transition is not concrete")
            if any(value.lower() in ALIAS_TOKENS for value in values):
                raise IntegrityError("compiled state-machine transition contains an alias")
            if source not in enums[reducer] or row["to"] not in enums[reducer]:
                raise IntegrityError("compiled transition crosses reducer namespaces")
            if row["owner_ledger"] not in {"run", "project"}:
                raise IntegrityError("compiled transition has an invalid owner ledger")
            compiled.append(
                Transition(reducer, source, row["event"], row["guard"], row["to"], row["owner_ledger"])
            )

    for source in (AnalysisState.COMMITTING.value, AnalysisState.RECOVERY_REQUIRED.value):
        for reason, target in COMMIT_ABORT_REASON_TARGET.items():
            compiled.append(
                Transition("analysis", source, "STAGE_COMMIT_ABORTED", reason, target.value, "run")
            )
    ordered = tuple(sorted(compiled))
    if len(ordered) != len(set(ordered)):
        raise IntegrityError("state-machine contains duplicate concrete transitions")
    keys = [(item.reducer, item.from_state, item.event, item.guard) for item in ordered]
    if len(keys) != len(set(keys)):
        raise IntegrityError("state-machine transition lookup is ambiguous")
    return ordered


ALL_TRANSITIONS = _compile_transitions()
ANALYSIS_TRANSITIONS = tuple(item for item in ALL_TRANSITIONS if item.reducer == "analysis")
OBLIGATION_TRANSITIONS = tuple(item for item in ALL_TRANSITIONS if item.reducer == "obligation")
EXTERNAL_CLIENT_TRANSITIONS = tuple(
    item for item in ALL_TRANSITIONS if item.reducer == "external_client"
)


def _compile_event_contracts() -> tuple[EventContract, ...]:
    source = STATE_MACHINE.get("event_contracts")
    if not isinstance(source, dict):
        raise IntegrityError("state-machine event contracts are missing")
    defaults = source.get("default_transition_fields")
    project_namespaces = source.get("project_namespaces")
    selectors = source.get("selectors")
    overrides = source.get("overrides")
    if not isinstance(defaults, dict) or not isinstance(project_namespaces, dict) or not isinstance(selectors, dict) or not isinstance(overrides, dict):
        raise IntegrityError("state-machine event contract source is malformed")
    event_namespaces: dict[str, str] = {}
    for namespace_name, event_names in project_namespaces.items():
        if namespace_name not in {"truth", "decision", "work", "memory", "run_registry"} or not isinstance(event_names, list):
            raise IntegrityError("event contract project namespace map is malformed")
        for event_name in event_names:
            if event_name in event_namespaces:
                raise IntegrityError("project event belongs to multiple reducer namespaces")
            event_namespaces[event_name] = namespace_name
    transition_events = {item.event for item in ALL_TRANSITIONS}
    contracts: list[EventContract] = []
    for event_type in sorted(transition_events | set(overrides)):
        transition_owners = {
            item.owner_ledger for item in ALL_TRANSITIONS if item.event == event_type
        }
        raw = overrides.get(event_type)
        if raw is None:
            if len(transition_owners) != 1:
                raise IntegrityError("transition event owner is ambiguous")
            required = dict(defaults)
            optional: dict[str, str] = {}
            owner = next(iter(transition_owners))
            action = "transition"
            composite = None
        else:
            if not isinstance(raw, dict):
                raise IntegrityError("event contract override must be an object")
            expected = {"owner_ledger", "action", "required", "optional"}
            allowed = expected | {"composite"}
            allowed_with_namespace = allowed | {"namespace"}
            expected_with_namespace = expected | {"namespace"}
            if set(raw) not in (expected, allowed, expected_with_namespace, allowed_with_namespace):
                raise IntegrityError("event contract override has an invalid field set")
            owner = raw["owner_ledger"]
            action = raw["action"]
            required = raw["required"]
            optional = raw["optional"]
            composite = raw.get("composite")
        namespace = raw.get("namespace") if raw is not None else None
        namespace = namespace or event_namespaces.get(event_type)
        if namespace is not None and namespace not in {"truth", "decision", "work", "memory", "run_registry"}:
            raise IntegrityError("event contract project namespace is invalid")
        if owner not in {"run", "project"} or not isinstance(action, str) or not action:
            raise IntegrityError("event contract owner/action is invalid")
        if transition_owners and transition_owners != {owner}:
            raise IntegrityError("event contract owner disagrees with transitions")
        if not isinstance(required, dict) or not isinstance(optional, dict):
            raise IntegrityError("event contract fields must be objects")
        if set(required) & set(optional) or "guard" in required or "guard" in optional:
            raise IntegrityError("event contract fields overlap or trust a free guard")
        selector = selectors.get(event_type)
        selector_field = None
        selector_guards: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = ()
        if selector is not None:
            if not isinstance(selector, dict) or set(selector) != {"field", "values"}:
                raise IntegrityError("event selector contract is malformed")
            selector_field = selector["field"]
            values = selector["values"]
            if not isinstance(selector_field, str) or not isinstance(values, dict) or not values:
                raise IntegrityError("event selector is open")
            if selector_field not in required:
                required = {**required, selector_field: "string"}
            selector_guards = tuple(
                sorted(
                    (
                        value,
                        tuple(sorted(mapping.items())),
                    )
                    for value, mapping in values.items()
                )
            )
        contracts.append(
            EventContract(
                event_type,
                owner,
                namespace,
                action,
                tuple(sorted(required.items())),
                tuple(sorted(optional.items())),
                selector_field,
                selector_guards,
                composite,
            )
        )
    compiled = tuple(contracts)
    by_event = {item.event_type: item for item in compiled}
    for event_type in transition_events:
        if event_type not in by_event:
            raise IntegrityError("transition has no typed event contract")
    for reducer in ("analysis", "obligation", "external_client"):
        keys = {
            (item.from_state, item.event)
            for item in ALL_TRANSITIONS
            if item.reducer == reducer
        }
        for source_state, event_type in keys:
            candidates = [
                item
                for item in ALL_TRANSITIONS
                if item.reducer == reducer
                and item.from_state == source_state
                and item.event == event_type
            ]
            if len(candidates) > 1:
                contract = by_event[event_type]
                guards = {
                    dict(mapping).get(reducer)
                    for _, mapping in contract.selector_guards
                    if dict(mapping).get(reducer) is not None
                }
                if {item.guard for item in candidates} - guards:
                    raise IntegrityError(
                        "ambiguous transition lacks an exact typed selector: "
                        f"{reducer}/{source_state}/{event_type}"
                    )
    return compiled


EVENT_CONTRACTS = _compile_event_contracts()
EVENT_CONTRACT_BY_TYPE = {item.event_type: item for item in EVENT_CONTRACTS}
TRANSITION_SNAPSHOT_DIGEST = domain_hash(
    "vivarium-transition-snapshot/v1", [list(item) for item in ALL_TRANSITIONS]
)


def _validate_field_type(field: str, spec: str, value: Any) -> None:
    if spec in {"string", "digest", "analysis_state", "completion_outcome", "abort_reason"}:
        if not isinstance(value, str) or not value:
            raise IntegrityError(f"{field} must be a non-empty string")
        if spec == "digest":
            if (
                not value.startswith("sha256:")
                or len(value) != 71
                or any(character not in "0123456789abcdef" for character in value[7:])
            ):
                raise IntegrityError(f"{field} must be a sha256 digest")
        elif spec == "analysis_state":
            try:
                AnalysisState(value)
            except ValueError as exc:
                raise IntegrityError(f"{field} is not a closed analysis state") from exc
        elif spec == "completion_outcome" and value not in {
            "success", "failure_retryable", "failure_resource", "failure_permanent",
            "preempted", "cancelled", "unknown_finality",
        }:
            raise IntegrityError(f"{field} is not a closed completion outcome")
        elif spec == "abort_reason" and value not in COMMIT_ABORT_REASON_TARGET:
            raise IntegrityError(f"{field} is not a closed abort reason")
        return
    if spec == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise IntegrityError(f"{field} must be an integer")
        return
    if spec == "boolean":
        if not isinstance(value, bool):
            raise IntegrityError(f"{field} must be a boolean")
        return
    if spec in {"list", "empty_list", "string_list", "dependency_list", "obligation_deltas", "client_deltas"}:
        if not isinstance(value, list):
            raise IntegrityError(f"{field} must be a list")
        if spec == "empty_list" and value:
            raise IntegrityError(f"{field} must be empty at genesis")
        if spec == "string_list" and not all(isinstance(item, str) and item for item in value):
            raise IntegrityError(f"{field} must contain strings")
        if spec == "dependency_list" and not all(isinstance(item, dict) for item in value):
            raise IntegrityError(f"{field} must contain dependency objects")
        return
    if spec in {"state_delta", "analysis_delta", "dependency_delta"}:
        if not isinstance(value, dict):
            raise IntegrityError(f"{field} must be an object")
        return
    raise IntegrityError(f"unknown event contract field type: {spec}")


def validate_event_payload(event_type: str, payload: Any, owner_ledger: str) -> EventContract:
    contract = EVENT_CONTRACT_BY_TYPE.get(event_type)
    if contract is None or contract.owner_ledger != owner_ledger:
        raise IntegrityError(f"unsupported {owner_ledger} event: {event_type}")
    if not isinstance(payload, dict):
        raise IntegrityError("typed event payload must be an object")
    required = dict(contract.required_fields)
    optional = dict(contract.optional_fields)
    if not set(required) <= set(payload) or set(payload) - set(required) - set(optional):
        raise IntegrityError("typed event payload has an invalid field set")
    for field, spec in required.items():
        _validate_field_type(field, spec, payload[field])
    for field, value in payload.items():
        if field in optional:
            _validate_field_type(field, optional[field], value)
    if contract.selector_field is not None:
        selectors = dict(contract.selector_guards)
        if payload[contract.selector_field] not in selectors:
            raise IntegrityError("typed event selector is not closed")
    return contract


def derive_transition(
    reducer: str, from_state: str, event_type: str, payload: dict[str, Any]
) -> Transition | None:
    contract = EVENT_CONTRACT_BY_TYPE.get(event_type)
    if contract is None:
        raise IntegrityError("unknown event has no typed contract")
    candidates = tuple(
        item
        for item in ALL_TRANSITIONS
        if item.reducer == reducer and item.from_state == from_state and item.event == event_type
    )
    selected_guard = None
    if contract.selector_field is not None:
        mapping = dict(dict(contract.selector_guards)[payload[contract.selector_field]])
        if reducer not in mapping:
            if candidates:
                raise IntegrityError("typed selector disallows this reducer namespace")
            return None
        selected_guard = mapping.get(reducer)
    if not candidates:
        if selected_guard is not None:
            raise IntegrityError("typed selector requests an illegal transition")
        return None
    if selected_guard is not None:
        candidates = tuple(item for item in candidates if item.guard == selected_guard)
    elif len(candidates) > 1:
        raise IntegrityError("typed event does not select one concrete transition")
    if len(candidates) != 1:
        raise IntegrityError("typed event does not match exactly one closed transition")
    return candidates[0]


def match_transition(reducer: str, from_state: str, event: str, guard: str) -> Transition:
    matches = tuple(
        transition
        for transition in ALL_TRANSITIONS
        if (
            transition.reducer,
            transition.from_state,
            transition.event,
            transition.guard,
        )
        == (reducer, from_state, event, guard)
    )
    if len(matches) != 1:
        raise IntegrityError("event does not match exactly one closed transition")
    return matches[0]


@dataclass(frozen=True)
class ProjectPrefixes:
    truth: tuple[Event, ...]
    decision: tuple[Event, ...]
    work: tuple[Event, ...]
    memory: tuple[Event, ...]
    run_registry: tuple[Event, ...]


@dataclass(frozen=True, order=True)
class DependencyHead:
    namespace: str
    object_id: str
    object_head: str


@dataclass(frozen=True, order=True)
class EvidenceCutHead:
    evidence_cut_id: str
    attempt_id: str
    head_digest: str
    event_id: str
    event_hash: str


@dataclass(frozen=True, order=True)
class Preparation:
    commit_tx_id: str
    prepare_event_id: str
    prepare_event_hash: str
    evidence_cut_id: str
    evidence_cut_digest: str
    origin_state: AnalysisState
    active: bool


@dataclass(frozen=True, order=True)
class ObligationRecord:
    obligation_id: str
    obligation_kind: str
    state: ObligationState
    head_digest: str
    side_effect_scope_key: str
    operation_key: str | None
    parent_obligation_id: str | None


@dataclass(frozen=True, order=True)
class MutationClientRecord:
    operation_key: str
    state: ExternalClientState
    head_digest: str
    side_effect_scope_key: str


@dataclass(frozen=True, order=True)
class DuplicateScope:
    side_effect_scope_key: str
    submission_obligation_id: str
    obligation_ids: tuple[str, ...]
    client_ids: tuple[str, ...]
    event_id: str
    event_hash: str


@dataclass(frozen=True, order=True)
class RunEventReference:
    event_id: str
    event_hash: str


@dataclass(frozen=True, order=True)
class AttemptState:
    attempt_id: str
    prior_attempt_id: str | None
    branch_id: str
    logical_scope_key: str
    analysis_state: AnalysisState
    direct_dependency_heads: tuple[DependencyHead, ...]
    dependency_closure: tuple[DependencyHead, ...]
    project_revision_baseline: int
    project_semantic_cut_root_baseline: str
    request_key: str
    intent_key: str
    execution_key: str
    local_execution_key: str
    submission_key: str
    operation_keys: tuple[str, ...]


@dataclass(frozen=True, order=True)
class CompletionClassification:
    classification_id: str
    attempt_id: str
    event_id: str
    event_hash: str
    evidence_cut_id: str
    evidence_cut_digest: str
    outcome: str
    classification_digest: str


@dataclass(frozen=True, order=True)
class EvidenceBundleHead:
    bundle_id: str
    attempt_id: str
    bundle_digest: str
    evidence_cut_id: str
    evidence_cut_event_id: str
    evidence_cut_event_hash: str
    evidence_cut_digest: str
    event_id: str
    event_hash: str


@dataclass(frozen=True, order=True)
class CompletionProofHead:
    completion_proof_id: str
    attempt_id: str
    completion_proof_digest: str
    classification_id: str
    classification_event_id: str
    classification_event_hash: str
    classification_digest: str
    evidence_cut_id: str
    evidence_cut_digest: str
    event_id: str
    event_hash: str


@dataclass(frozen=True, order=True)
class ValidatorReportHead:
    validator_report_id: str
    attempt_id: str
    validator_report_digest: str
    completion_proof_id: str
    completion_proof_event_id: str
    completion_proof_event_hash: str
    completion_proof_digest: str
    bundle_id: str
    bundle_event_id: str
    bundle_event_hash: str
    bundle_digest: str
    validation_outcome: str
    event_id: str
    event_hash: str


@dataclass(frozen=True, order=True)
class CheckerReviewHead:
    checker_review_id: str
    attempt_id: str
    checker_review_digest: str
    validator_report_id: str
    validator_report_event_id: str
    validator_report_event_hash: str
    validator_report_digest: str
    review_outcome: str
    event_id: str
    event_hash: str


@dataclass(frozen=True, order=True)
class QuorumDecisionHead:
    quorum_decision_id: str
    attempt_id: str
    quorum_decision_digest: str
    validator_report_id: str
    validator_report_event_id: str
    validator_report_event_hash: str
    validator_report_digest: str
    checker_review_id: str
    checker_review_event_id: str
    checker_review_event_hash: str
    checker_review_digest: str
    quorum_outcome: str
    event_id: str
    event_hash: str


@dataclass(frozen=True)
class RunLocalState:
    run_id: str
    ledger_id: str
    run_event_seq: int
    run_event_hash: str
    analysis_state: AnalysisState
    attempts: tuple[AttemptState, ...]
    active_attempt_id: str
    attempt_dependency_heads: tuple[DependencyHead, ...]
    attempt_dependency_closure: tuple[DependencyHead, ...]
    attempt_dependency_heads_root: str
    preparations: tuple[Preparation, ...]
    evidence_cut_heads: tuple[EvidenceCutHead, ...]
    completion_classifications: tuple[CompletionClassification, ...]
    evidence_bundle_heads: tuple[EvidenceBundleHead, ...]
    completion_proof_heads: tuple[CompletionProofHead, ...]
    validator_report_heads: tuple[ValidatorReportHead, ...]
    checker_review_heads: tuple[CheckerReviewHead, ...]
    quorum_decision_heads: tuple[QuorumDecisionHead, ...]
    duplicate_scopes: tuple[DuplicateScope, ...]
    obligations: tuple[ObligationRecord, ...]
    mutation_clients: tuple[MutationClientRecord, ...]
    postcommit_intake_blockers: tuple[str, ...]
    postcommit_escalations: tuple[str, ...]
    reachable_run_events: tuple[RunEventReference, ...]
    merge_policy_digest: str
    run_local_reducer_digest: str
    run_local_state_root: str


@dataclass(frozen=True, order=True)
class ProjectObjectHead:
    namespace: str
    object_type: str
    object_id: str
    object_head: str
    dependencies: tuple[DependencyHead, ...]
    owner_run_id: str | None


@dataclass(frozen=True, order=True)
class AttemptDependencyDelta:
    expected_direct_dependency_heads: tuple[DependencyHead, ...]
    expected_dependency_closure: tuple[DependencyHead, ...]
    new_direct_dependency_heads: tuple[DependencyHead, ...]
    new_dependency_closure: tuple[DependencyHead, ...]
    expected_logical_scope_key: str
    new_logical_scope_key: str
    expected_project_revision_baseline: int
    new_project_revision_baseline: int
    expected_project_semantic_cut_root_baseline: str
    new_project_semantic_cut_root_baseline: str


@dataclass(frozen=True, order=True)
class ProjectOverlay:
    project_revision: int
    event_type: str
    run_id: str
    run_event_id: str
    run_event_hash: str
    transaction_id: str
    prepare_event_id: str
    prepare_event_hash: str
    evidence_cut_id: str
    evidence_cut_digest: str
    owner_guard: str
    descendant_guard: str
    target_namespace: str
    target_object_id: str
    affected_object_ids: tuple[str, ...]
    affected_run_ids: tuple[str, ...]
    successor_attempt: AttemptState | None
    dependency_delta: AttemptDependencyDelta | None
    event_id: str
    event_hash: str


@dataclass(frozen=True, order=True)
class ProjectRevisionAction:
    project_revision: int
    namespace: str
    event_type: str
    object_id: str
    object_head: str
    dependencies: tuple[DependencyHead, ...]
    policy_digest: str | None
    overlay: ProjectOverlay | None


@dataclass(frozen=True)
class ProjectRevisionSnapshot:
    project_revision: int
    project_semantic_cut_root: str
    active_object_heads: tuple[ProjectObjectHead, ...]
    invalidation_closure: tuple[str, ...]
    locked_policy_digest: str
    project_validity_root: str
    project_validity_reducer_digest: str


@dataclass(frozen=True)
class ProjectSemanticCut:
    project_revision: int
    truth_event_seq: int
    truth_event_hash: str
    active_truth_root: str
    active_fact_vector_digest: str
    truth_reducer_digest: str
    decision_event_seq: int
    decision_event_hash: str
    active_decision_root: str
    decision_reducer_digest: str
    work_state_event_seq: int
    work_state_event_hash: str
    active_work_root: str
    project_work_reducer_digest: str
    memory_event_seq: int
    memory_event_hash: str
    active_memory_root: str
    memory_reducer_digest: str
    run_registry_event_seq: int
    run_registry_event_hash: str
    active_run_registry_root: str
    run_registry_reducer_digest: str
    locked_policy_digest: str
    active_object_heads: tuple[ProjectObjectHead, ...]
    overlays: tuple[ProjectOverlay, ...]
    revision_actions: tuple[ProjectRevisionAction, ...]
    revision_snapshots: tuple[ProjectRevisionSnapshot, ...]
    invalidation_closure: tuple[str, ...]
    project_validity_root: str
    project_validity_reducer_digest: str
    project_semantic_cut_root: str


@dataclass(frozen=True)
class ProjectValidity:
    active_object_heads: tuple[ProjectObjectHead, ...]
    invalidation_closure: tuple[str, ...]
    dependency_edges: tuple[tuple[str, str], ...]
    descendant_closure: tuple[tuple[str, tuple[str, ...]], ...]
    locked_policy_digest: str
    project_validity_reducer_digest: str
    project_validity_root: str


@dataclass(frozen=True, order=True)
class RelevantProjectInput:
    namespace: str
    object_id: str
    expected_head: str
    active_head: str | None
    invalidated: bool


@dataclass(frozen=True)
class RunValiditySlice:
    run_id: str
    ledger_id: str
    run_event_seq: int
    run_event_hash: str
    run_local_state_root: str
    attempt_dependency_heads_root: str
    relevant_project_inputs: tuple[RelevantProjectInput, ...]
    relevant_project_validity_input_root: str
    run_validity_reducer_digest: str
    state: AnalysisState
    attempts: tuple[AttemptState, ...]
    active_attempt_id: str
    completion_recheck_blockers: tuple[str, ...]
    operational_escalated: bool
    validity_reasons: tuple[str, ...]
    run_validity_slice_root: str


@dataclass(frozen=True)
class FederatedState:
    run_id: str
    ledger_id: str
    run_event_seq: int
    run_event_hash: str
    run_local_state_root: str
    project_semantic_cut_root: str
    run_validity_slice_root: str
    analysis_state: AnalysisState
    attempts: tuple[AttemptState, ...]
    active_attempt_id: str
    effective_availability: str
    completion_recheck_blockers: tuple[str, ...]
    postcommit_intake_blockers: tuple[str, ...]
    validity_reasons: tuple[str, ...]
    obligations: tuple[ObligationRecord, ...]
    mutation_clients: tuple[MutationClientRecord, ...]
    preparations: tuple[Preparation, ...]
    evidence_cut_heads: tuple[EvidenceCutHead, ...]
    unresolved_obligation_count: int
    default_retrievable: bool
    run_local_reducer_digest: str
    project_validity_reducer_digest: str
    run_validity_reducer_digest: str
    federated_reducer_digest: str
    merge_policy_digest: str
    federated_state_root: str
