from __future__ import annotations

from typing import Any

from .errors import IntegrityError
from .events import Event
from .state import (
    AnalysisState,
    AttemptState,
    CheckerReviewHead,
    CompletionClassification,
    CompletionProofHead,
    DependencyHead,
    DuplicateScope,
    EvidenceBundleHead,
    EvidenceCutHead,
    MutationClientRecord,
    ObligationRecord,
    Preparation,
    QuorumDecisionHead,
    RunEventReference,
    ValidatorReportHead,
)
from ._replay_common import (
    RUN_LOCAL_REDUCER_DIGEST,
    _client_value,
    _dependency_projection,
    _obligation_value,
    _require_dict,
    _require_string,
)

def _attempt_projection(item: AttemptState) -> dict[str, Any]:
    return {
        "attempt_id": item.attempt_id,
        "prior_attempt_id": item.prior_attempt_id,
        "branch_id": item.branch_id,
        "logical_scope_key": item.logical_scope_key,
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


def _evidence_bundle_projection(item: EvidenceBundleHead) -> dict[str, str]:
    return {
        "bundle_id": item.bundle_id,
        "bundle_digest": item.bundle_digest,
        "evidence_cut_id": item.evidence_cut_id,
        "evidence_cut_event_id": item.evidence_cut_event_id,
        "evidence_cut_event_hash": item.evidence_cut_event_hash,
        "evidence_cut_digest": item.evidence_cut_digest,
        "event_id": item.event_id,
        "event_hash": item.event_hash,
    }


def _completion_proof_projection(item: CompletionProofHead) -> dict[str, str]:
    return {
        "completion_proof_id": item.completion_proof_id,
        "completion_proof_digest": item.completion_proof_digest,
        "classification_id": item.classification_id,
        "classification_event_id": item.classification_event_id,
        "classification_event_hash": item.classification_event_hash,
        "classification_digest": item.classification_digest,
        "evidence_cut_id": item.evidence_cut_id,
        "evidence_cut_digest": item.evidence_cut_digest,
        "event_id": item.event_id,
        "event_hash": item.event_hash,
    }


def _validator_report_projection(item: ValidatorReportHead) -> dict[str, str]:
    return {
        "validator_report_id": item.validator_report_id,
        "validator_report_digest": item.validator_report_digest,
        "completion_proof_id": item.completion_proof_id,
        "completion_proof_event_id": item.completion_proof_event_id,
        "completion_proof_event_hash": item.completion_proof_event_hash,
        "completion_proof_digest": item.completion_proof_digest,
        "bundle_id": item.bundle_id,
        "bundle_event_id": item.bundle_event_id,
        "bundle_event_hash": item.bundle_event_hash,
        "bundle_digest": item.bundle_digest,
        "validation_outcome": item.validation_outcome,
        "event_id": item.event_id,
        "event_hash": item.event_hash,
    }


def _checker_review_projection(item: CheckerReviewHead) -> dict[str, str]:
    return {
        "checker_review_id": item.checker_review_id,
        "checker_review_digest": item.checker_review_digest,
        "validator_report_id": item.validator_report_id,
        "validator_report_event_id": item.validator_report_event_id,
        "validator_report_event_hash": item.validator_report_event_hash,
        "validator_report_digest": item.validator_report_digest,
        "review_outcome": item.review_outcome,
        "event_id": item.event_id,
        "event_hash": item.event_hash,
    }


def _quorum_decision_projection(item: QuorumDecisionHead) -> dict[str, str]:
    return {
        "quorum_decision_id": item.quorum_decision_id,
        "quorum_decision_digest": item.quorum_decision_digest,
        "validator_report_id": item.validator_report_id,
        "validator_report_event_id": item.validator_report_event_id,
        "validator_report_event_hash": item.validator_report_event_hash,
        "validator_report_digest": item.validator_report_digest,
        "checker_review_id": item.checker_review_id,
        "checker_review_event_id": item.checker_review_event_id,
        "checker_review_event_hash": item.checker_review_event_hash,
        "checker_review_digest": item.checker_review_digest,
        "quorum_outcome": item.quorum_outcome,
        "event_id": item.event_id,
        "event_hash": item.event_hash,
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
    projection = {
        "obligation_id": item.obligation_id,
        "obligation_kind": item.obligation_kind,
        "state": item.state.value,
        "head_digest": item.head_digest,
        "side_effect_scope_key": item.side_effect_scope_key,
    }
    if item.operation_key is not None:
        projection["operation_key"] = item.operation_key
    if item.parent_obligation_id is not None:
        projection["parent_obligation_id"] = item.parent_obligation_id
    return projection


def _client_projection(item: MutationClientRecord) -> dict[str, str]:
    return {
        "operation_key": item.operation_key,
        "state": item.state.value,
        "head_digest": item.head_digest,
        "side_effect_scope_key": item.side_effect_scope_key,
    }


def _duplicate_scope_projection(item: DuplicateScope) -> dict[str, Any]:
    return {
        "side_effect_scope_key": item.side_effect_scope_key,
        "submission_obligation_id": item.submission_obligation_id,
        "obligation_ids": list(item.obligation_ids),
        "client_ids": list(item.client_ids),
        "event_id": item.event_id,
        "event_hash": item.event_hash,
    }


def _parse_initial_obligations(payload: dict[str, Any]) -> dict[str, ObligationRecord]:
    result: dict[str, ObligationRecord] = {}
    values = payload.get("obligations", [])
    if not isinstance(values, list):
        raise IntegrityError("initial obligations must be a list")
    for raw in values:
        item = _require_dict(raw, "initial obligation")
        kind = _require_string(item, "obligation_kind")
        base_fields = {
            "obligation_id", "obligation_kind", "state", "head_digest",
            "side_effect_scope_key",
        }
        operation_fields = {"operation_key", "parent_obligation_id"}
        expected_fields = (
            base_fields | operation_fields
            if kind in {"cancellation", "mutation"}
            else base_fields
        )
        if set(item) != expected_fields:
            raise IntegrityError("initial obligation has an invalid field set")
        record = ObligationRecord(
            _require_string(item, "obligation_id"),
            kind,
            _obligation_value(_require_string(item, "state"), "initial obligation state"),
            _require_string(item, "head_digest"),
            _require_string(item, "side_effect_scope_key"),
            _require_string(item, "operation_key") if "operation_key" in item else None,
            (
                _require_string(item, "parent_obligation_id")
                if "parent_obligation_id" in item
                else None
            ),
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
        if set(item) != {
            "operation_key", "state", "head_digest", "side_effect_scope_key"
        }:
            raise IntegrityError("initial mutation client has an invalid field set")
        record = MutationClientRecord(
            _require_string(item, "operation_key"),
            _client_value(_require_string(item, "state"), "initial client state"),
            _require_string(item, "head_digest"),
            _require_string(item, "side_effect_scope_key"),
        )
        if record.operation_key in result:
            raise IntegrityError("initial mutation client keys must be unique")
        result[record.operation_key] = record
    return result



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
    bundles: tuple[EvidenceBundleHead, ...],
    proofs: tuple[CompletionProofHead, ...],
    validator_reports: tuple[ValidatorReportHead, ...],
    checker_reviews: tuple[CheckerReviewHead, ...],
    quorum_decisions: tuple[QuorumDecisionHead, ...],
    duplicate_scopes: tuple[DuplicateScope, ...],
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
        "evidence_bundle_heads": [_evidence_bundle_projection(item) for item in bundles],
        "completion_proof_heads": [_completion_proof_projection(item) for item in proofs],
        "validator_report_heads": [
            _validator_report_projection(item) for item in validator_reports
        ],
        "checker_review_heads": [
            _checker_review_projection(item) for item in checker_reviews
        ],
        "quorum_decision_heads": [
            _quorum_decision_projection(item) for item in quorum_decisions
        ],
        "duplicate_scopes": [
            _duplicate_scope_projection(item) for item in duplicate_scopes
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
    payload: dict[str, Any],
    analysis_state: AnalysisState,
    prior: str | None,
    *,
    logical_scope_key: str | None = None,
    direct_dependency_heads: tuple[DependencyHead, ...] = (),
    dependency_closure: tuple[DependencyHead, ...] = (),
) -> AttemptState:
    return AttemptState(
        _require_string(payload, "attempt_id"),
        prior,
        _require_string(payload, "branch_id"),
        logical_scope_key or _require_string(payload, "logical_scope_key"),
        analysis_state,
        direct_dependency_heads,
        dependency_closure,
        _require_string(payload, "request_key"),
        _require_string(payload, "intent_key"),
        _require_string(payload, "execution_key"),
        _require_string(payload, "local_execution_key"),
        _require_string(payload, "submission_key"),
        tuple(payload["operation_keys"]),
    )
