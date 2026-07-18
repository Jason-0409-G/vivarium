from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from ._replay_common import (
    COMPLETION_ABORT_REASONS,
    DEPENDENCY_HEADS_DOMAIN,
    RUN_LOCAL_REDUCER_DIGEST,
    _analysis_value,
    _dependency,
    _dependency_projection,
    _require_dict,
    _require_int,
    _require_string,
    _verify_event_prefix,
)
from ._run_composites import _apply_keyed_client_transition, _apply_typed_composite
from ._run_state_support import (
    _new_attempt_from_payload,
    _parse_initial_clients,
    _parse_initial_obligations,
    _run_local_projection_v2,
)
from .canonical import domain_hash
from .errors import IntegrityError
from .events import Event, ZERO_HASH
from .state import (
    AnalysisState,
    AttemptState,
    COMMIT_ABORT_REASON_TARGET,
    COMPLETION_ABORT_OUTCOME,
    CheckerReviewHead,
    CompletionClassification,
    CompletionProofHead,
    DuplicateScope,
    EvidenceBundleHead,
    EvidenceCutHead,
    Preparation,
    QuorumDecisionHead,
    RunEventReference,
    RunLocalState,
    ValidatorReportHead,
    derive_transition,
    validate_event_payload,
)

RUN_LOCAL_DOMAIN = "vivarium-run-local-state/v1"


def reduce_run(events: Sequence[Event]) -> RunLocalState:
    prefix = _verify_event_prefix(events, genesis_type="RUN_LEDGER_GENESIS")
    genesis_payload = _require_dict(prefix[0].payload, "run genesis payload")
    validate_event_payload("RUN_LEDGER_GENESIS", genesis_payload, "run")
    run_id = _require_string(genesis_payload, "run_id")
    initial_state = _analysis_value(
        _require_string(genesis_payload, "analysis_state"), "run genesis analysis state"
    )
    merge_policy_digest = _require_string(genesis_payload, "merge_policy_digest")
    first_attempt = _new_attempt_from_payload(genesis_payload, initial_state, None)
    attempts: dict[str, AttemptState] = {first_attempt.attempt_id: first_attempt}
    active_attempt_id = first_attempt.attempt_id
    evidence: dict[str, EvidenceCutHead] = {}
    bundles: dict[str, EvidenceBundleHead] = {}
    preparations: dict[str, Preparation] = {}
    classifications: dict[str, CompletionClassification] = {}
    proofs: dict[str, CompletionProofHead] = {}
    validator_reports: dict[str, ValidatorReportHead] = {}
    checker_reviews: dict[str, CheckerReviewHead] = {}
    quorum_decisions: dict[str, QuorumDecisionHead] = {}
    duplicate_scopes: dict[str, DuplicateScope] = {}
    obligations = _parse_initial_obligations(genesis_payload)
    clients = _parse_initial_clients(genesis_payload)
    blockers: set[str] = set()

    def active() -> AttemptState:
        return attempts[active_attempt_id]

    def set_active_state(value: AnalysisState) -> None:
        attempts[active_attempt_id] = replace(active(), analysis_state=value)

    for item in prefix[1:]:
        payload = _require_dict(item.payload, f"{item.event_type} payload")
        contract = validate_event_payload(item.event_type, payload, "run")
        action = contract.action
        if action == "freeze_dependencies":
            if payload["attempt_id"] != active_attempt_id:
                raise IntegrityError("dependency closure targets a non-active attempt")
            if (
                active().direct_dependency_heads
                or active().dependency_closure
                or active().project_semantic_cut_root_baseline != ZERO_HASH
            ):
                raise IntegrityError("attempt dependency closure may only be frozen once")
            direct = tuple(sorted(_dependency(raw) for raw in payload["direct_dependency_heads"]))
            closure = tuple(sorted(_dependency(raw) for raw in payload["dependency_closure"]))
            if len(direct) != len({(d.namespace, d.object_id) for d in direct}):
                raise IntegrityError("direct dependency identities must be unique")
            if len(closure) != len({(d.namespace, d.object_id) for d in closure}):
                raise IntegrityError("dependency closure identities must be unique")
            closure_map = {(value.namespace, value.object_id): value for value in closure}
            if any(closure_map.get((value.namespace, value.object_id)) != value for value in direct):
                raise IntegrityError("dependency closure must include every direct head")
            project_revision = _require_int(payload, "project_revision")
            if project_revision < 0:
                raise IntegrityError("project dependency baseline revision cannot be negative")
            attempts[active_attempt_id] = replace(
                active(),
                direct_dependency_heads=direct,
                dependency_closure=closure,
                project_revision_baseline=project_revision,
                project_semantic_cut_root_baseline=_require_string(
                    payload, "project_semantic_cut_root"
                ),
            )
        elif action == "freeze_evidence":
            cut_id = _require_string(payload, "evidence_cut_id")
            if cut_id in evidence:
                raise IntegrityError("evidence cut head may only be frozen once")
            evidence[cut_id] = EvidenceCutHead(
                cut_id,
                active_attempt_id,
                _require_string(payload, "head_digest"),
                item.event_id,
                item.event_hash,
            )
        elif action == "freeze_evidence_bundle":
            bundle_id = _require_string(payload, "bundle_id")
            cut = evidence.get(_require_string(payload, "evidence_cut_id"))
            if bundle_id in bundles:
                raise IntegrityError("evidence bundle IDs must be unique")
            if (
                cut is None
                or cut.attempt_id != active_attempt_id
                or payload["evidence_cut_event_id"] != cut.event_id
                or payload["evidence_cut_event_hash"] != cut.event_hash
                or payload["evidence_cut_digest"] != cut.head_digest
            ):
                raise IntegrityError("evidence bundle does not bind a reachable evidence cut")
            bundles[bundle_id] = EvidenceBundleHead(
                bundle_id,
                active_attempt_id,
                _require_string(payload, "bundle_digest"),
                cut.evidence_cut_id,
                cut.event_id,
                cut.event_hash,
                cut.head_digest,
                item.event_id,
                item.event_hash,
            )
        elif action == "prepare_commit":
            if active().analysis_state not in {AnalysisState.COMMITTING, AnalysisState.RECOVERY_REQUIRED}:
                raise IntegrityError("commit preparation is not legal in the active attempt")
            commit_tx_id = _require_string(payload, "commit_tx_id")
            if commit_tx_id in preparations:
                raise IntegrityError("commit_tx_id may only have one durable preparation")
            cut_id = _require_string(payload, "evidence_cut_id")
            cut_digest = _require_string(payload, "evidence_cut_digest")
            if (
                cut_id not in evidence
                or evidence[cut_id].attempt_id != active_attempt_id
                or evidence[cut_id].head_digest != cut_digest
            ):
                raise IntegrityError("commit preparation references an unknown evidence cut")
            origin = _analysis_value(
                _require_string(payload, "origin_state"), "commit preparation origin state"
            )
            if origin not in {AnalysisState.CHECKING, AnalysisState.COMMITTING}:
                raise IntegrityError("commit preparation origin is not recoverable")
            preparations[commit_tx_id] = Preparation(
                commit_tx_id,
                item.event_id,
                item.event_hash,
                cut_id,
                cut_digest,
                origin,
                True,
            )
        elif action == "inbox_observation":
            if active().analysis_state not in {
                AnalysisState.COMMITTING,
                AnalysisState.RECOVERY_REQUIRED,
                AnalysisState.COMMITTED,
                AnalysisState.COMPLETION_RECHECK_PENDING,
            }:
                raise IntegrityError("postcommit intake is not legal before commit preparation")
            observation_id = _require_string(payload, "observation_id")
            if observation_id in blockers:
                raise IntegrityError("postcommit observation IDs must be unique")
            blockers.add(observation_id)
        elif action == "open_observation":
            observation_id = _require_string(payload, "observation_id")
            if observation_id not in blockers:
                raise IntegrityError("opened observation is not inboxed")
            blockers.remove(observation_id)
        elif action == "classify_completion":
            classification_id = _require_string(payload, "classification_id")
            if classification_id in classifications:
                raise IntegrityError("completion classification IDs must be unique")
            cut_id = _require_string(payload, "evidence_cut_id")
            cut_digest = _require_string(payload, "evidence_cut_digest")
            if (
                cut_id not in evidence
                or evidence[cut_id].attempt_id != active_attempt_id
                or evidence[cut_id].head_digest != cut_digest
            ):
                raise IntegrityError("completion classification references an unknown evidence cut")
            outcome = _require_string(payload, "outcome")
            classification_body = {
                "classification_id": classification_id,
                "attempt_id": active_attempt_id,
                "event_id": item.event_id,
                "event_hash": item.event_hash,
                "evidence_cut_id": cut_id,
                "evidence_cut_digest": cut_digest,
                "outcome": outcome,
            }
            classification = CompletionClassification(
                classification_id,
                active_attempt_id,
                item.event_id,
                item.event_hash,
                cut_id,
                cut_digest,
                outcome,
                domain_hash("vivarium-completion-classification/v1", classification_body),
            )
            classifications[classification_id] = classification
            if active().analysis_state == AnalysisState.COLLECTING and outcome != "success":
                transition = derive_transition(
                    "analysis", active().analysis_state.value, item.event_type, payload
                )
                if transition is None or transition.owner_ledger != "run":
                    raise IntegrityError("completion outcome is not a run-owned transition")
                set_active_state(AnalysisState(transition.to_state))
            elif active().analysis_state not in {AnalysisState.COLLECTING, AnalysisState.COMMITTING}:
                raise IntegrityError("completion classification is not legal in this attempt state")
        elif action == "record_completion_proof":
            if active().analysis_state != AnalysisState.COLLECTING:
                raise IntegrityError("completion proof must be recorded while collecting")
            proof_id = _require_string(payload, "completion_proof_id")
            classification = classifications.get(_require_string(payload, "classification_id"))
            if (
                proof_id in proofs
                or classification is None
                or classification.attempt_id != active_attempt_id
                or classification.outcome != "success"
            ):
                raise IntegrityError("completion proof has no unique durable success classification")
            if (
                payload["classification_event_id"] != classification.event_id
                or payload["classification_event_hash"] != classification.event_hash
                or payload["classification_digest"] != classification.classification_digest
                or payload["evidence_cut_id"] != classification.evidence_cut_id
                or payload["evidence_cut_digest"] != classification.evidence_cut_digest
            ):
                raise IntegrityError("completion proof binding disagrees with classification")
            proofs[proof_id] = CompletionProofHead(
                proof_id,
                active_attempt_id,
                _require_string(payload, "completion_proof_digest"),
                classification.classification_id,
                classification.event_id,
                classification.event_hash,
                classification.classification_digest,
                classification.evidence_cut_id,
                classification.evidence_cut_digest,
                item.event_id,
                item.event_hash,
            )
        elif action == "prove_completion_success":
            proof = proofs.get(_require_string(payload, "completion_proof_id"))
            bundle = bundles.get(_require_string(payload, "bundle_id"))
            if (
                proof is None
                or bundle is None
                or proof.attempt_id != active_attempt_id
                or bundle.attempt_id != active_attempt_id
                or payload["completion_proof_event_id"] != proof.event_id
                or payload["completion_proof_event_hash"] != proof.event_hash
                or payload["completion_proof_digest"] != proof.completion_proof_digest
                or payload["bundle_event_id"] != bundle.event_id
                or payload["bundle_event_hash"] != bundle.event_hash
                or payload["bundle_digest"] != bundle.bundle_digest
                or proof.evidence_cut_id != bundle.evidence_cut_id
                or proof.evidence_cut_digest != bundle.evidence_cut_digest
            ):
                raise IntegrityError("success transition lacks the exact durable proof and bundle")
            transition = derive_transition(
                "analysis", active().analysis_state.value, item.event_type, payload
            )
            if transition is None or transition.owner_ledger != "run":
                raise IntegrityError("success proof cannot select validation")
            set_active_state(AnalysisState(transition.to_state))
        elif action == "seal_validator_report":
            if active().analysis_state != AnalysisState.VALIDATING:
                raise IntegrityError("validator report must be sealed while validating")
            report_id = _require_string(payload, "validator_report_id")
            proof = proofs.get(_require_string(payload, "completion_proof_id"))
            bundle = bundles.get(_require_string(payload, "bundle_id"))
            outcome = _require_string(payload, "validation_outcome")
            if report_id in validator_reports or outcome not in {"pass", "repairable", "scientifically_invalid"}:
                raise IntegrityError("validator report identity/outcome is not closed")
            if (
                proof is None
                or bundle is None
                or proof.attempt_id != active_attempt_id
                or bundle.attempt_id != active_attempt_id
                or payload["completion_proof_event_id"] != proof.event_id
                or payload["completion_proof_event_hash"] != proof.event_hash
                or payload["completion_proof_digest"] != proof.completion_proof_digest
                or payload["bundle_event_id"] != bundle.event_id
                or payload["bundle_event_hash"] != bundle.event_hash
                or payload["bundle_digest"] != bundle.bundle_digest
                or proof.evidence_cut_id != bundle.evidence_cut_id
            ):
                raise IntegrityError("validator report authority chain is inconsistent")
            validator_reports[report_id] = ValidatorReportHead(
                report_id,
                active_attempt_id,
                _require_string(payload, "validator_report_digest"),
                proof.completion_proof_id,
                proof.event_id,
                proof.event_hash,
                proof.completion_proof_digest,
                bundle.bundle_id,
                bundle.event_id,
                bundle.event_hash,
                bundle.bundle_digest,
                outcome,
                item.event_id,
                item.event_hash,
            )
        elif action == "apply_validator_report":
            report = validator_reports.get(_require_string(payload, "validator_report_id"))
            if (
                report is None
                or report.attempt_id != active_attempt_id
                or payload["validator_report_event_id"] != report.event_id
                or payload["validator_report_event_hash"] != report.event_hash
                or payload["validator_report_digest"] != report.validator_report_digest
            ):
                raise IntegrityError("validation transition lacks its sealed report")
            expected_outcome = (
                "pass" if item.event_type == "VALIDATION_PASSED" else payload["validation_result"]
            )
            if report.validation_outcome != expected_outcome:
                raise IntegrityError("validator report outcome disagrees with transition")
            transition = derive_transition(
                "analysis", active().analysis_state.value, item.event_type, payload
            )
            if transition is None or transition.owner_ledger != "run":
                raise IntegrityError("validator report cannot select a run transition")
            set_active_state(AnalysisState(transition.to_state))
        elif action == "seal_checker_review":
            if active().analysis_state != AnalysisState.CHECKING:
                raise IntegrityError("checker review must be sealed while checking")
            review_id = _require_string(payload, "checker_review_id")
            report = validator_reports.get(_require_string(payload, "validator_report_id"))
            outcome = _require_string(payload, "review_outcome")
            if review_id in checker_reviews or outcome not in {"pass", "repairable", "unrecoverable"}:
                raise IntegrityError("checker review identity/outcome is not closed")
            if (
                report is None
                or report.attempt_id != active_attempt_id
                or payload["validator_report_event_id"] != report.event_id
                or payload["validator_report_event_hash"] != report.event_hash
                or payload["validator_report_digest"] != report.validator_report_digest
                or report.validation_outcome != "pass"
            ):
                raise IntegrityError("checker review does not bind a passed validator report")
            checker_reviews[review_id] = CheckerReviewHead(
                review_id,
                active_attempt_id,
                _require_string(payload, "checker_review_digest"),
                report.validator_report_id,
                report.event_id,
                report.event_hash,
                report.validator_report_digest,
                outcome,
                item.event_id,
                item.event_hash,
            )
        elif action == "apply_checker_review":
            review = checker_reviews.get(_require_string(payload, "checker_review_id"))
            if (
                review is None
                or review.attempt_id != active_attempt_id
                or payload["checker_review_event_id"] != review.event_id
                or payload["checker_review_event_hash"] != review.event_hash
                or payload["checker_review_digest"] != review.checker_review_digest
                or review.review_outcome != payload["review_result"]
            ):
                raise IntegrityError("checker transition lacks its matching sealed review")
            transition = derive_transition(
                "analysis", active().analysis_state.value, item.event_type, payload
            )
            if transition is None or transition.owner_ledger != "run":
                raise IntegrityError("checker review cannot select a run transition")
            set_active_state(AnalysisState(transition.to_state))
        elif action == "seal_quorum_decision":
            if active().analysis_state != AnalysisState.CHECKING:
                raise IntegrityError("quorum decision must be sealed while checking")
            decision_id = _require_string(payload, "quorum_decision_id")
            report = validator_reports.get(_require_string(payload, "validator_report_id"))
            review = checker_reviews.get(_require_string(payload, "checker_review_id"))
            if decision_id in quorum_decisions or payload["quorum_outcome"] != "pass":
                raise IntegrityError("quorum decision identity/outcome is not closed")
            if (
                report is None
                or review is None
                or report.attempt_id != active_attempt_id
                or review.attempt_id != active_attempt_id
                or payload["validator_report_event_id"] != report.event_id
                or payload["validator_report_event_hash"] != report.event_hash
                or payload["validator_report_digest"] != report.validator_report_digest
                or payload["checker_review_event_id"] != review.event_id
                or payload["checker_review_event_hash"] != review.event_hash
                or payload["checker_review_digest"] != review.checker_review_digest
                or review.validator_report_id != report.validator_report_id
                or review.review_outcome != "pass"
            ):
                raise IntegrityError("quorum decision authority chain is inconsistent")
            quorum_decisions[decision_id] = QuorumDecisionHead(
                decision_id,
                active_attempt_id,
                _require_string(payload, "quorum_decision_digest"),
                report.validator_report_id,
                report.event_id,
                report.event_hash,
                report.validator_report_digest,
                review.checker_review_id,
                review.event_id,
                review.event_hash,
                review.checker_review_digest,
                "pass",
                item.event_id,
                item.event_hash,
            )
        elif action == "apply_quorum_decision":
            decision = quorum_decisions.get(_require_string(payload, "quorum_decision_id"))
            if (
                decision is None
                or decision.attempt_id != active_attempt_id
                or payload["quorum_decision_event_id"] != decision.event_id
                or payload["quorum_decision_event_hash"] != decision.event_hash
                or payload["quorum_decision_digest"] != decision.quorum_decision_digest
                or decision.quorum_outcome != "pass"
            ):
                raise IntegrityError("quorum transition lacks its sealed passed decision")
            transition = derive_transition(
                "analysis", active().analysis_state.value, item.event_type, payload
            )
            if transition is None or transition.owner_ledger != "run":
                raise IntegrityError("quorum decision cannot select committing")
            set_active_state(AnalysisState(transition.to_state))
        elif action == "abort_commit":
            reason = _require_string(payload, "abort_reason")
            target = COMMIT_ABORT_REASON_TARGET[reason]
            if payload["analysis_from"] != active().analysis_state.value or payload["analysis_target"] != target.value:
                raise IntegrityError("commit abort state binding disagrees with reason map")
            transition = derive_transition(
                "analysis", active().analysis_state.value, item.event_type, payload
            )
            if transition is None or transition.to_state != target.value:
                raise IntegrityError("commit abort is not machine-derived")
            preparation = preparations.get(_require_string(payload, "commit_tx_id"))
            if preparation is None or not preparation.active:
                raise IntegrityError("commit abort has no matching active preparation")
            if payload["prepare_event_id"] != preparation.prepare_event_id or payload["prepare_event_hash"] != preparation.prepare_event_hash:
                raise IntegrityError("commit abort preparation binding does not match")
            if payload["preparation_delta"] != {"from": "ACTIVE", "to": "INACTIVE"}:
                raise IntegrityError("commit abort must deactivate its preparation")
            if reason in COMPLETION_ABORT_REASONS:
                latest = next(
                    (
                        value
                        for value in reversed(classifications.values())
                        if value.attempt_id == active_attempt_id
                    ),
                    None,
                )
                if (
                    latest is None
                    or payload.get("completion_classification_id") != latest.classification_id
                    or payload.get("completion_classification_digest") != latest.classification_digest
                    or latest.evidence_cut_id != preparation.evidence_cut_id
                    or latest.evidence_cut_digest != preparation.evidence_cut_digest
                    or latest.outcome != COMPLETION_ABORT_OUTCOME[reason]
                    or payload["sealed_failure_digest"] != latest.classification_digest
                ):
                    raise IntegrityError("completion abort lacks a durable latest-cut classification")
            preparations[preparation.commit_tx_id] = replace(preparation, active=False)
            set_active_state(target)
        elif action == "abort_recovery":
            preparation = preparations.get(_require_string(payload, "commit_tx_id"))
            if preparation is None or not preparation.active:
                raise IntegrityError("recovery abort has no matching active preparation")
            if active().analysis_state != AnalysisState.RECOVERY_REQUIRED:
                raise IntegrityError("recovery abort requires RECOVERY_REQUIRED")
            if payload["prepare_event_id"] != preparation.prepare_event_id or payload["prepare_event_hash"] != preparation.prepare_event_hash:
                raise IntegrityError("recovery abort preparation binding does not match")
            target = _analysis_value(payload["recovery_target_state"], "recovery target")
            if target != preparation.origin_state or target not in {AnalysisState.CHECKING, AnalysisState.COMMITTING}:
                raise IntegrityError("recovery abort target disagrees with durable origin")
            transition = derive_transition(
                "analysis", active().analysis_state.value, item.event_type, payload
            )
            if transition is None or transition.to_state != target.value:
                raise IntegrityError("recovery abort target is not machine-derived")
            preparations[preparation.commit_tx_id] = replace(preparation, active=False)
            set_active_state(target)
        elif action == "create_attempt":
            transition = derive_transition(
                "analysis", active().analysis_state.value, item.event_type, payload
            )
            if transition is None or transition.to_state != AnalysisState.PLANNED.value:
                raise IntegrityError("attempt creation is not a closed repair transition")
            if payload["prior_attempt_id"] != active_attempt_id:
                raise IntegrityError("attempt successor does not bind the active terminal attempt")
            successor = _new_attempt_from_payload(
                payload,
                AnalysisState.PLANNED,
                active_attempt_id,
                logical_scope_key=active().logical_scope_key,
                direct_dependency_heads=active().direct_dependency_heads,
                dependency_closure=active().dependency_closure,
                project_revision_baseline=active().project_revision_baseline,
                project_semantic_cut_root_baseline=(
                    active().project_semantic_cut_root_baseline
                ),
            )
            if successor.attempt_id in attempts:
                raise IntegrityError("attempt IDs must be unique")
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
                    raise IntegrityError("successor attempt must allocate new branch and execution keys")
            attempts[successor.attempt_id] = successor
            active_attempt_id = successor.attempt_id
        elif action == "composite":
            new_state, staged_obligations, staged_clients, staged_scopes = _apply_typed_composite(
                item,
                payload,
                contract.composite or "",
                active().analysis_state,
                obligations,
                clients,
                duplicate_scopes,
            )
            obligations = staged_obligations
            clients = staged_clients
            duplicate_scopes = staged_scopes
            set_active_state(new_state)
        elif action == "keyed_client_transition":
            clients = _apply_keyed_client_transition(item, payload, clients)
        elif action == "transition":
            transition = derive_transition(
                "analysis", active().analysis_state.value, item.event_type, payload
            )
            if transition is None or transition.owner_ledger != "run":
                raise IntegrityError("typed run event has no run-owned analysis transition")
            set_active_state(AnalysisState(transition.to_state))
        else:
            raise IntegrityError(f"unsupported run reducer action: {action}")

    ordered_attempts = tuple(attempts.values())
    active_attempt = attempts[active_attempt_id]
    dependency_root = domain_hash(
        DEPENDENCY_HEADS_DOMAIN,
        {
            "direct": [_dependency_projection(item) for item in active_attempt.direct_dependency_heads],
            "closure": [_dependency_projection(item) for item in active_attempt.dependency_closure],
        },
    )
    ordered_preparations = tuple(sorted(preparations.values()))
    ordered_evidence = tuple(sorted(evidence.values()))
    ordered_classifications = tuple(classifications.values())
    ordered_bundles = tuple(bundles.values())
    ordered_proofs = tuple(proofs.values())
    ordered_validator_reports = tuple(validator_reports.values())
    ordered_checker_reviews = tuple(checker_reviews.values())
    ordered_quorum_decisions = tuple(quorum_decisions.values())
    ordered_duplicate_scopes = tuple(sorted(duplicate_scopes.values()))
    ordered_obligations = tuple(sorted(obligations.values()))
    ordered_clients = tuple(sorted(clients.values()))
    ordered_blockers = tuple(sorted(blockers))
    reachable = tuple(RunEventReference(item.event_id, item.event_hash) for item in prefix)
    projection = _run_local_projection_v2(
        run_id=run_id,
        ledger_id=prefix[-1].ledger_id,
        tail=prefix[-1],
        attempts=ordered_attempts,
        active_attempt_id=active_attempt_id,
        dependency_root=dependency_root,
        preparations=ordered_preparations,
        evidence=ordered_evidence,
        classifications=ordered_classifications,
        bundles=ordered_bundles,
        proofs=ordered_proofs,
        validator_reports=ordered_validator_reports,
        checker_reviews=ordered_checker_reviews,
        quorum_decisions=ordered_quorum_decisions,
        duplicate_scopes=ordered_duplicate_scopes,
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
        active_attempt.analysis_state,
        ordered_attempts,
        active_attempt_id,
        active_attempt.direct_dependency_heads,
        active_attempt.dependency_closure,
        dependency_root,
        ordered_preparations,
        ordered_evidence,
        ordered_classifications,
        ordered_bundles,
        ordered_proofs,
        ordered_validator_reports,
        ordered_checker_reviews,
        ordered_quorum_decisions,
        ordered_duplicate_scopes,
        ordered_obligations,
        ordered_clients,
        ordered_blockers,
        reachable,
        merge_policy_digest,
        RUN_LOCAL_REDUCER_DIGEST,
        root,
    )
