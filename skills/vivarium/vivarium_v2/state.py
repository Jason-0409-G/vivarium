from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import NamedTuple

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


class Transition(NamedTuple):
    reducer: str
    from_state: str
    event: str
    guard: str
    to_state: str
    owner_ledger: str


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


@dataclass(frozen=True, order=True)
class MutationClientRecord:
    operation_key: str
    state: ExternalClientState
    head_digest: str


@dataclass(frozen=True, order=True)
class RunEventReference:
    event_id: str
    event_hash: str


@dataclass(frozen=True)
class RunLocalState:
    run_id: str
    ledger_id: str
    run_event_seq: int
    run_event_hash: str
    analysis_state: AnalysisState
    attempt_dependency_heads: tuple[DependencyHead, ...]
    attempt_dependency_heads_root: str
    preparations: tuple[Preparation, ...]
    evidence_cut_heads: tuple[EvidenceCutHead, ...]
    obligations: tuple[ObligationRecord, ...]
    mutation_clients: tuple[MutationClientRecord, ...]
    postcommit_intake_blockers: tuple[str, ...]
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
    event_id: str
    event_hash: str


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
    invalidation_closure: tuple[str, ...]
    project_validity_root: str
    project_validity_reducer_digest: str
    project_semantic_cut_root: str


@dataclass(frozen=True)
class ProjectValidity:
    active_object_heads: tuple[ProjectObjectHead, ...]
    invalidation_closure: tuple[str, ...]
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
