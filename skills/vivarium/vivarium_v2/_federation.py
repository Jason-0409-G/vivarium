from __future__ import annotations

from ._run_state_support import (
    _attempt_projection,
    _client_projection,
    _evidence_projection,
    _obligation_projection,
    _preparation_projection,
)
from ._validity import reduce_project_validity, reduce_run_validity
from .canonical import domain_hash
from .errors import IntegrityError
from .state import (
    AnalysisState,
    ExternalClientState,
    FederatedState,
    ObligationState,
    ProjectSemanticCut,
    ProjectValidity,
    RunLocalState,
    RunValiditySlice,
)

FEDERATED_DOMAIN = "vivarium-federated-run-state/v1"
FEDERATED_REDUCER_DIGEST = domain_hash(
    "vivarium-reducer-definition/v1", {"reducer": "federated", "version": 1}
)


def federate(
    local: RunLocalState,
    cut: ProjectSemanticCut,
    validity: ProjectValidity,
    run_slice: RunValiditySlice,
) -> FederatedState:
    expected_validity = reduce_project_validity(cut)
    if validity != expected_validity:
        raise IntegrityError("federation received a mismatched project validity output")
    expected_slice = reduce_run_validity(cut, validity, local)
    if run_slice != expected_slice:
        raise IntegrityError("federation received a mismatched run validity slice")

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
        and not run_slice.completion_recheck_blockers
        and not run_slice.validity_reasons
        and not run_slice.operational_escalated
        and unresolved == 0
        and not live_clients
    )
    if default_retrievable:
        availability = "RETRIEVABLE"
    elif local.postcommit_intake_blockers:
        availability = "BLOCKED_POSTCOMMIT_INTAKE"
    elif run_slice.completion_recheck_blockers or run_slice.state in {
        AnalysisState.COMPLETION_RECHECK_PENDING,
        AnalysisState.PENDING_COMPLETION_DEPENDENCY,
    }:
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
        "attempts": [_attempt_projection(item) for item in run_slice.attempts],
        "active_attempt_id": run_slice.active_attempt_id,
        "effective_availability": availability,
        "completion_recheck_blockers": list(run_slice.completion_recheck_blockers),
        "operational_escalated": run_slice.operational_escalated,
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
        run_slice.attempts,
        run_slice.active_attempt_id,
        availability,
        run_slice.completion_recheck_blockers,
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


def build_federated_state(local: RunLocalState, cut: ProjectSemanticCut) -> FederatedState:
    validity = reduce_project_validity(cut)
    run_slice = reduce_run_validity(cut, validity, local)
    return federate(local, cut, validity, run_slice)
