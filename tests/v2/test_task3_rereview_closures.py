import copy
import unittest

from skills.vivarium.vivarium_v2.errors import IntegrityError
from skills.vivarium.vivarium_v2.events import ZERO_HASH
from skills.vivarium.vivarium_v2.reducers import (
    federate,
    reduce_project_cut,
    reduce_project_validity,
    reduce_run,
    reduce_run_validity,
)
from skills.vivarium.vivarium_v2.state import (
    ALL_TRANSITIONS,
    AnalysisState,
    derive_transition,
    match_transition,
)
from tests.v2.test_task3_review_closures import (
    HASH_A,
    HASH_B,
    HASH_C,
    HASH_D,
    activation,
    append,
    evidence_and_prepare,
    prefixes,
    project_genesis,
    run_genesis,
)


def initial_run(state, *, run_id="review-run", obligations=(), clients=()):
    events = run_genesis(state, run_id=run_id)
    payload = dict(events[0].payload)
    if obligations:
        payload["obligations"] = list(obligations)
    if clients:
        payload["mutation_clients"] = list(clients)
    return append((), events[0].ledger_id, "RUN_LEDGER_GENESIS", payload)


def prepared_local(run_id):
    events, evidence, prepare = evidence_and_prepare(
        run_genesis("COMMITTING", run_id=run_id), commit_tx=f"commit-{run_id}"
    )
    return reduce_run(events), evidence, prepare


def commit_event_payload(revision, run_id, prepare, evidence, object_id, dependencies=()):
    return activation(
        revision,
        object_id,
        f"{object_id}-head-{revision}",
        dependencies,
        object_type="stage",
        run_id=run_id,
        run_event_id=prepare.event_id,
        run_event_hash=prepare.event_hash,
        commit_tx_id=f"commit-{run_id}",
        prepare_event_id=prepare.event_id,
        prepare_event_hash=prepare.event_hash,
        evidence_cut_id=evidence.payload["evidence_cut_id"],
        evidence_cut_digest=evidence.payload["head_digest"],
    )


def recheck_open_payload(revision, run_id, prepare, evidence, object_id):
    payload = commit_event_payload(
        revision, run_id, prepare, evidence, object_id
    )
    payload.pop("commit_tx_id")
    payload.update(
        {
            "recheck_tx_id": f"recheck-{revision}",
            "recheck_scope": "own_stage",
            "target_namespace": "work",
            "target_object_id": object_id,
        }
    )
    return payload


class AuthorityAndSelectorCounterexamples(unittest.TestCase):
    def test_durable_authority_chain_is_frozen_before_each_transition(self):
        events = run_genesis("COLLECTING")
        events = append(
            events, events[0].ledger_id, "EVIDENCE_CUT_FROZEN",
            {"evidence_cut_id": "cut-1", "head_digest": HASH_A},
        )
        evidence = events[-1]
        events = append(
            events, events[0].ledger_id, "EVIDENCE_BUNDLE_FROZEN",
            {
                "bundle_id": "bundle-1",
                "bundle_digest": HASH_B,
                "evidence_cut_id": "cut-1",
                "evidence_cut_event_id": evidence.event_id,
                "evidence_cut_event_hash": evidence.event_hash,
                "evidence_cut_digest": HASH_A,
            },
        )
        bundle = events[-1]
        events = append(
            events, events[0].ledger_id, "COMPLETION_CLASSIFIED",
            {
                "classification_id": "classification-1",
                "evidence_cut_id": "cut-1",
                "evidence_cut_digest": HASH_A,
                "outcome": "success",
            },
        )
        classification_event = events[-1]
        classification = reduce_run(events).completion_classifications[-1]
        events = append(
            events, events[0].ledger_id, "COMPLETION_PROOF_RECORDED",
            {
                "completion_proof_id": "proof-1",
                "completion_proof_digest": HASH_C,
                "classification_id": "classification-1",
                "classification_event_id": classification_event.event_id,
                "classification_event_hash": classification_event.event_hash,
                "classification_digest": classification.classification_digest,
                "evidence_cut_id": "cut-1",
                "evidence_cut_digest": HASH_A,
            },
        )
        proof = events[-1]
        events = append(
            events, events[0].ledger_id, "COMPLETION_SUCCESS_PROVEN",
            {
                "completion_proof_id": "proof-1",
                "completion_proof_event_id": proof.event_id,
                "completion_proof_event_hash": proof.event_hash,
                "completion_proof_digest": HASH_C,
                "bundle_id": "bundle-1",
                "bundle_event_id": bundle.event_id,
                "bundle_event_hash": bundle.event_hash,
                "bundle_digest": HASH_B,
            },
        )
        events = append(
            events, events[0].ledger_id, "VALIDATOR_REPORT_SEALED",
            {
                "validator_report_id": "validator-1",
                "validator_report_digest": HASH_D,
                "completion_proof_id": "proof-1",
                "completion_proof_event_id": proof.event_id,
                "completion_proof_event_hash": proof.event_hash,
                "completion_proof_digest": HASH_C,
                "bundle_id": "bundle-1",
                "bundle_event_id": bundle.event_id,
                "bundle_event_hash": bundle.event_hash,
                "bundle_digest": HASH_B,
                "validation_outcome": "pass",
            },
        )
        validator = events[-1]
        events = append(
            events, events[0].ledger_id, "VALIDATION_PASSED",
            {
                "validator_report_id": "validator-1",
                "validator_report_event_id": validator.event_id,
                "validator_report_event_hash": validator.event_hash,
                "validator_report_digest": HASH_D,
            },
        )
        events = append(
            events, events[0].ledger_id, "CHECKER_ALLOCATED", {"event_digest": HASH_A}
        )
        events = append(
            events, events[0].ledger_id, "CHECKER_REVIEW_SEALED",
            {
                "checker_review_id": "review-1",
                "checker_review_digest": HASH_A,
                "validator_report_id": "validator-1",
                "validator_report_event_id": validator.event_id,
                "validator_report_event_hash": validator.event_hash,
                "validator_report_digest": HASH_D,
                "review_outcome": "pass",
            },
        )
        review = events[-1]
        events = append(
            events, events[0].ledger_id, "QUORUM_DECISION_SEALED",
            {
                "quorum_decision_id": "quorum-1",
                "quorum_decision_digest": HASH_B,
                "validator_report_id": "validator-1",
                "validator_report_event_id": validator.event_id,
                "validator_report_event_hash": validator.event_hash,
                "validator_report_digest": HASH_D,
                "checker_review_id": "review-1",
                "checker_review_event_id": review.event_id,
                "checker_review_event_hash": review.event_hash,
                "checker_review_digest": HASH_A,
                "quorum_outcome": "pass",
            },
        )
        quorum = events[-1]
        events = append(
            events, events[0].ledger_id, "CHECKER_QUORUM_PASSED",
            {
                "quorum_decision_id": "quorum-1",
                "quorum_decision_event_id": quorum.event_id,
                "quorum_decision_event_hash": quorum.event_hash,
                "quorum_decision_digest": HASH_B,
            },
        )

        replayed = reduce_run(events)

        self.assertEqual(replayed.analysis_state, AnalysisState.COMMITTING)
        self.assertEqual(len(replayed.evidence_bundle_heads), 1)
        self.assertEqual(len(replayed.completion_proof_heads), 1)
        self.assertEqual(len(replayed.validator_report_heads), 1)
        self.assertEqual(len(replayed.checker_review_heads), 1)
        self.assertEqual(len(replayed.quorum_decision_heads), 1)

    def test_arbitrary_proof_and_bundle_cannot_authorize_validation(self):
        events = run_genesis("COLLECTING")
        events = append(
            events,
            events[0].ledger_id,
            "EVIDENCE_CUT_FROZEN",
            {"evidence_cut_id": "cut-1", "head_digest": HASH_B},
        )
        events = append(
            events,
            events[0].ledger_id,
            "COMPLETION_CLASSIFIED",
            {
                "classification_id": "classification-1",
                "evidence_cut_id": "cut-1",
                "evidence_cut_digest": HASH_B,
                "outcome": "success",
            },
        )
        classification = events[-1]
        forged = append(
            events,
            events[0].ledger_id,
            "COMPLETION_SUCCESS_PROVEN",
            {
                "classification_id": "classification-1",
                "classification_event_id": classification.event_id,
                "classification_event_hash": classification.event_hash,
                "evidence_cut_id": "cut-1",
                "evidence_cut_digest": HASH_B,
                "completion_proof_id": "never-recorded-proof",
                "completion_proof_digest": HASH_C,
                "bundle_digest": HASH_D,
            },
        )

        with self.assertRaises(IntegrityError):
            reduce_run(forged)

    def test_arbitrary_quorum_digest_cannot_authorize_committing(self):
        events = run_genesis("CHECKING")
        forged = append(
            events,
            events[0].ledger_id,
            "CHECKER_QUORUM_PASSED",
            {"event_digest": HASH_D},
        )

        with self.assertRaises(IntegrityError):
            reduce_run(forged)

    def test_selector_without_analysis_namespace_cannot_fall_back(self):
        obligations = (
            {
                "obligation_id": "operation:cancel-1",
                "obligation_kind": "cancellation",
                "state": "CANCELLATION_UNCERTAIN",
                "head_digest": HASH_A,
            },
        )
        events = initial_run("RUNNING_REMOTE", obligations=obligations)
        forged = append(
            events,
            events[0].ledger_id,
            "OPERATION_RECONCILED",
            {
                "operation_result": "cancel_resolved",
                "analysis_delta": {
                    "expected_state": "RUNNING_REMOTE",
                    "new_state": "COLLECTING",
                },
                "obligation_deltas": [
                    {
                        "obligation_id": "operation:cancel-1",
                        "obligation_kind": "cancellation",
                        "expected_state": "CANCELLATION_UNCERTAIN",
                        "new_state": "RESOLVED",
                        "head_digest": HASH_B,
                    }
                ],
                "client_deltas": [],
            },
        )

        with self.assertRaises(IntegrityError):
            reduce_run(forged)

    def test_success_classification_cannot_authorize_retryable_abort(self):
        events, _, preparation = evidence_and_prepare(run_genesis("COMMITTING"))
        events = append(
            events,
            events[0].ledger_id,
            "COMPLETION_CLASSIFIED",
            {
                "classification_id": "classification-success",
                "evidence_cut_id": "cut-1",
                "evidence_cut_digest": HASH_B,
                "outcome": "success",
            },
        )
        classification = reduce_run(events).completion_classifications[-1]
        forged = append(
            events,
            events[0].ledger_id,
            "STAGE_COMMIT_ABORTED",
            {
                "commit_tx_id": "commit-1",
                "prepare_event_id": preparation.event_id,
                "prepare_event_hash": preparation.event_hash,
                "abort_reason": "COMPLETION_FAILURE_RETRYABLE",
                "analysis_from": "COMMITTING",
                "analysis_target": "RETRYABLE_FAILURE",
                "sealed_failure_digest": classification.classification_digest,
                "preparation_delta": {"from": "ACTIVE", "to": "INACTIVE"},
                "completion_classification_id": classification.classification_id,
                "completion_classification_digest": classification.classification_digest,
            },
        )

        with self.assertRaises(IntegrityError):
            reduce_run(forged)


class ScopedCompositeCounterexamples(unittest.TestCase):
    def test_cancel_operation_cannot_publish_with_another_clients_identity(self):
        obligations = (
            {
                "obligation_id": "operation:cancel-A",
                "obligation_kind": "cancellation",
                "state": "CANCELLATION_UNCERTAIN",
                "head_digest": HASH_A,
            },
            {
                "obligation_id": "submission:submission-1",
                "obligation_kind": "submission",
                "state": "JOB_LIVE",
                "head_digest": HASH_A,
            },
        )
        clients = (
            {"operation_key": "cancel-A", "state": "WIRE_IN_FLIGHT", "head_digest": HASH_A},
            {"operation_key": "cancel-B", "state": "WIRE_IN_FLIGHT", "head_digest": HASH_A},
        )
        events = initial_run("RUNNING_REMOTE", obligations=obligations, clients=clients)
        forged = append(
            events,
            events[0].ledger_id,
            "OPERATION_RECONCILED",
            {
                "operation_result": "cancel_terminal",
                "analysis_delta": {"expected_state": "RUNNING_REMOTE", "new_state": "COLLECTING"},
                "obligation_deltas": [
                    {
                        "obligation_id": "operation:cancel-A",
                        "obligation_kind": "cancellation",
                        "expected_state": "CANCELLATION_UNCERTAIN",
                        "new_state": "RESOLVED",
                        "head_digest": HASH_B,
                    },
                    {
                        "obligation_id": "submission:submission-1",
                        "obligation_kind": "submission",
                        "expected_state": "JOB_LIVE",
                        "new_state": "ACCOUNTING_PENDING",
                        "head_digest": HASH_B,
                    },
                ],
                "client_deltas": [
                    {
                        "operation_key": "cancel-B",
                        "expected_state": "WIRE_IN_FLIGHT",
                        "new_state": "TERMINAL_DRAINED",
                        "head_digest": HASH_C,
                    }
                ],
            },
        )

        with self.assertRaises(IntegrityError):
            reduce_run(forged)

    def test_scoped_composite_requires_exact_expected_head_and_scope(self):
        obligations = (
            {
                "obligation_id": "operation:cancel-A",
                "obligation_kind": "cancellation",
                "state": "CANCELLATION_UNCERTAIN",
                "head_digest": HASH_A,
                "side_effect_scope_key": "scope-1",
                "operation_key": "cancel-A",
                "parent_obligation_id": "submission:submission-1",
            },
            {
                "obligation_id": "submission:submission-1",
                "obligation_kind": "submission",
                "state": "JOB_LIVE",
                "head_digest": HASH_A,
                "side_effect_scope_key": "scope-1",
            },
        )
        clients = (
            {
                "operation_key": "cancel-A",
                "state": "WIRE_IN_FLIGHT",
                "head_digest": HASH_A,
                "side_effect_scope_key": "scope-1",
            },
        )
        events = initial_run("RUNNING_REMOTE", obligations=obligations, clients=clients)
        payload = {
            "operation_result": "cancel_terminal",
            "side_effect_scope_key": "scope-1",
            "operation_obligation_id": "operation:cancel-A",
            "parent_obligation_id": "submission:submission-1",
            "external_client_id": "cancel-A",
            "operation_key": "cancel-A",
            "analysis_delta": {"expected_state": "RUNNING_REMOTE", "new_state": "COLLECTING"},
            "obligation_deltas": [
                {
                    "obligation_id": "operation:cancel-A",
                    "obligation_kind": "cancellation",
                    "expected_state": "CANCELLATION_UNCERTAIN",
                    "new_state": "RESOLVED",
                    "expected_head_digest": HASH_A,
                    "new_head_digest": HASH_B,
                },
                {
                    "obligation_id": "submission:submission-1",
                    "obligation_kind": "submission",
                    "expected_state": "JOB_LIVE",
                    "new_state": "ACCOUNTING_PENDING",
                    "expected_head_digest": HASH_A,
                    "new_head_digest": HASH_B,
                },
            ],
            "client_deltas": [
                {
                    "operation_key": "cancel-A",
                    "expected_state": "WIRE_IN_FLIGHT",
                    "new_state": "TERMINAL_DRAINED",
                    "expected_head_digest": HASH_A,
                    "new_head_digest": HASH_C,
                }
            ],
        }

        valid = append(events, events[0].ledger_id, "OPERATION_RECONCILED", payload)
        self.assertEqual(reduce_run(valid).analysis_state, AnalysisState.COLLECTING)

        wrong_head = copy.deepcopy(payload)
        wrong_head["obligation_deltas"][0]["expected_head_digest"] = HASH_D
        with self.assertRaises(IntegrityError):
            reduce_run(append(events, events[0].ledger_id, "OPERATION_RECONCILED", wrong_head))

        wrong_scope = copy.deepcopy(payload)
        wrong_scope["side_effect_scope_key"] = "scope-2"
        with self.assertRaises(IntegrityError):
            reduce_run(append(events, events[0].ledger_id, "OPERATION_RECONCILED", wrong_scope))

    def test_duplicate_arbitration_ignores_open_client_outside_frozen_scope(self):
        obligation = {
            "obligation_id": "submission:submission-1",
            "obligation_kind": "submission",
            "state": "SUBMISSION_UNCERTAIN",
            "head_digest": HASH_A,
            "side_effect_scope_key": "scope-1",
        }
        clients = (
            {
                "operation_key": "duplicate-1",
                "state": "WIRE_IN_FLIGHT",
                "head_digest": HASH_A,
                "side_effect_scope_key": "scope-1",
            },
            {
                "operation_key": "unrelated-1",
                "state": "WIRE_IN_FLIGHT",
                "head_digest": HASH_A,
                "side_effect_scope_key": "scope-2",
            },
        )
        events = initial_run("SUBMISSION_UNCERTAIN", obligations=(obligation,), clients=clients)
        events = append(
            events,
            events[0].ledger_id,
            "DUPLICATE_EXTERNAL_SIDE_EFFECT_DETECTED",
            {
                "detection_kind": "multiple_accepted_jobs",
                "side_effect_scope_key": "scope-1",
                "submission_obligation_id": "submission:submission-1",
                "scoped_obligation_ids": ["submission:submission-1"],
                "scoped_client_ids": ["duplicate-1"],
                "analysis_delta": {
                    "expected_state": "SUBMISSION_UNCERTAIN",
                    "new_state": "ESCALATED",
                },
                "obligation_deltas": [
                    {
                        "obligation_id": "submission:submission-1",
                        "obligation_kind": "submission",
                        "expected_state": "SUBMISSION_UNCERTAIN",
                        "new_state": "DUPLICATE_EXTERNAL_SIDE_EFFECT",
                        "expected_head_digest": HASH_A,
                        "new_head_digest": HASH_B,
                    }
                ],
                "client_deltas": [],
            },
        )
        payload = {
            "arbitration_result": "live_queued",
            "side_effect_scope_key": "scope-1",
            "submission_obligation_id": "submission:submission-1",
            "scoped_obligation_ids": ["submission:submission-1"],
            "scoped_client_ids": ["duplicate-1"],
            "analysis_delta": {"expected_state": "ESCALATED", "new_state": "QUEUED"},
            "obligation_deltas": [
                {
                    "obligation_id": "submission:submission-1",
                    "obligation_kind": "submission",
                    "expected_state": "DUPLICATE_EXTERNAL_SIDE_EFFECT",
                    "new_state": "JOB_LIVE",
                    "expected_head_digest": HASH_B,
                    "new_head_digest": HASH_C,
                }
            ],
            "client_deltas": [
                {
                    "operation_key": "duplicate-1",
                    "expected_state": "WIRE_IN_FLIGHT",
                    "new_state": "TERMINAL_DRAINED",
                    "expected_head_digest": HASH_A,
                    "new_head_digest": HASH_D,
                }
            ],
        }

        replayed = reduce_run(
            append(events, events[0].ledger_id, "DUPLICATE_ARBITRATED", payload)
        )

        by_key = {item.operation_key: item for item in replayed.mutation_clients}
        self.assertEqual(by_key["duplicate-1"].state.value, "TERMINAL_DRAINED")
        self.assertEqual(by_key["unrelated-1"].state.value, "WIRE_IN_FLIGHT")


class TemporalGraphAndClosureCounterexamples(unittest.TestCase):
    def test_upstream_stage_commit_never_propagates_to_descendant_run(self):
        descendant, descendant_evidence, descendant_prepare = prepared_local("descendant")
        _, upstream_evidence, upstream_prepare = prepared_local("upstream")
        values = project_genesis()
        values["work"] = append(
            values["work"],
            "project-work",
            "STAGE_COMMITTED",
            commit_event_payload(
                1,
                "descendant",
                descendant_prepare,
                descendant_evidence,
                "stage-descendant",
                ({"namespace": "work", "object_id": "stage-upstream", "object_head": "stage-upstream-head-2"},),
            ),
        )
        values["work"] = append(
            values["work"],
            "project-work",
            "STAGE_COMMITTED",
            commit_event_payload(
                2, "upstream", upstream_prepare, upstream_evidence, "stage-upstream"
            ),
        )
        cut = reduce_project_cut(prefixes(values))
        validity = reduce_project_validity(cut)

        run_slice = reduce_run_validity(cut, validity, descendant)

        self.assertEqual(run_slice.state, AnalysisState.COMMITTED)

    def test_owner_and_descendant_open_use_distinct_frozen_guards(self):
        owner, owner_evidence, owner_prepare = prepared_local("owner")
        child, child_evidence, child_prepare = prepared_local("child")
        values = project_genesis()
        values["work"] = append(
            values["work"], "project-work", "STAGE_COMMITTED",
            commit_event_payload(1, "child", child_prepare, child_evidence, "stage-child", (
                {"namespace": "work", "object_id": "stage-owner", "object_head": "stage-owner-head-2"},
            )),
        )
        values["work"] = append(
            values["work"], "project-work", "STAGE_COMMITTED",
            commit_event_payload(2, "owner", owner_prepare, owner_evidence, "stage-owner"),
        )
        values["work"] = append(
            values["work"], "project-work", "COMPLETION_RECHECK_OPENED",
            recheck_open_payload(3, "owner", owner_prepare, owner_evidence, "stage-owner"),
        )
        cut = reduce_project_cut(prefixes(values))
        validity = reduce_project_validity(cut)

        owner_slice = reduce_run_validity(cut, validity, owner)
        child_slice = reduce_run_validity(cut, validity, child)

        self.assertEqual(owner_slice.state, AnalysisState.COMPLETION_RECHECK_PENDING)
        self.assertEqual(child_slice.state, AnalysisState.PENDING_COMPLETION_DEPENDENCY)

    def test_future_graph_edge_does_not_reinterpret_prior_recheck(self):
        owner, owner_evidence, owner_prepare = prepared_local("owner")
        child, child_evidence, child_prepare = prepared_local("child")
        values = project_genesis()
        values["work"] = append(
            values["work"], "project-work", "STAGE_COMMITTED",
            commit_event_payload(1, "owner", owner_prepare, owner_evidence, "stage-owner"),
        )
        values["work"] = append(
            values["work"], "project-work", "COMPLETION_RECHECK_OPENED",
            recheck_open_payload(2, "owner", owner_prepare, owner_evidence, "stage-owner"),
        )
        values["work"] = append(
            values["work"], "project-work", "STAGE_COMMITTED",
            commit_event_payload(3, "child", child_prepare, child_evidence, "stage-child", (
                {"namespace": "work", "object_id": "stage-owner", "object_head": "stage-owner-head-1"},
            )),
        )
        cut = reduce_project_cut(prefixes(values))
        validity = reduce_project_validity(cut)

        child_slice = reduce_run_validity(cut, validity, child)

        self.assertEqual(child_slice.state, AnalysisState.COMMITTED)

    def test_missing_two_hop_claimed_closure_fails_closed(self):
        direct = {"namespace": "truth", "object_id": "stage-A", "object_head": "S1"}
        fact_a = {"namespace": "truth", "object_id": "fact-A", "object_head": "A1"}
        fact_b = {"namespace": "truth", "object_id": "fact-B", "object_head": "B1"}
        values = project_genesis()
        values["truth"] = append(
            values["truth"], "project-truth", "FACT_ACTIVATED",
            activation(1, "fact-B", "B1"),
        )
        values["truth"] = append(
            values["truth"], "project-truth", "FACT_ACTIVATED",
            activation(2, "fact-A", "A1", (fact_b,)),
        )
        values["truth"] = append(
            values["truth"], "project-truth", "FACT_ACTIVATED",
            activation(3, "stage-A", "S1", (fact_a,)),
        )
        cut = reduce_project_cut(prefixes(values))
        events = run_genesis("COMMITTED")
        events = append(
            events,
            events[0].ledger_id,
            "ATTEMPT_DEPENDENCIES_FROZEN",
            {
                "attempt_id": "attempt-1",
                "project_revision": cut.project_revision,
                "project_semantic_cut_root": cut.project_semantic_cut_root,
                "direct_dependency_heads": [direct],
                "dependency_closure": [direct, fact_a],
            },
        )
        local = reduce_run(events)
        validity = reduce_project_validity(cut)

        with self.assertRaises(IntegrityError):
            reduce_run_validity(cut, validity, local)

    def test_retry_preserves_dependency_closure_and_logical_scope(self):
        direct = {"namespace": "truth", "object_id": "fact-A", "object_head": "A1"}
        events = run_genesis("RETRYABLE_FAILURE")
        events = append(
            events,
            events[0].ledger_id,
            "ATTEMPT_DEPENDENCIES_FROZEN",
            {
                "attempt_id": "attempt-1",
                "project_revision": 0,
                "project_semantic_cut_root": ZERO_HASH,
                "direct_dependency_heads": [direct],
                "dependency_closure": [direct],
            },
        )
        events = append(
            events,
            events[0].ledger_id,
            "ATTEMPT_RETRY_CREATED",
            {
                "repair_kind": "retry_policy_budget_allow",
                "prior_attempt_id": "attempt-1",
                "attempt_id": "attempt-2",
                "branch_id": "branch-2",
                "request_key": "request-2",
                "intent_key": "intent-2",
                "execution_key": "execution-2",
                "local_execution_key": "local-2",
                "submission_key": "submission-2",
                "operation_keys": ["operation-2"],
            },
        )

        replayed = reduce_run(events)

        self.assertEqual(
            replayed.attempts[1].direct_dependency_heads,
            replayed.attempts[0].direct_dependency_heads,
        )
        self.assertEqual(
            replayed.attempts[1].dependency_closure,
            replayed.attempts[0].dependency_closure,
        )
        self.assertEqual(
            replayed.attempts[1].logical_scope_key,
            replayed.attempts[0].logical_scope_key,
        )


class ProjectTransitionExecutionHarness(unittest.TestCase):
    def _append_and_execute(
        self,
        values,
        local,
        before,
        event_type,
        payload,
        observed,
        *,
        relation="owner",
    ):
        values["work"] = append(
            values["work"], "project-work", event_type, payload
        )
        cut = reduce_project_cut(prefixes(values))
        validity = reduce_project_validity(cut)
        run_slice = reduce_run_validity(cut, validity, local)
        federated = federate(local, cut, validity, run_slice)
        self.assertEqual(federated.analysis_state, run_slice.state)

        overlay = cut.revision_actions[-1].overlay
        self.assertIsNotNone(overlay)
        guard = (
            overlay.owner_guard if relation == "owner" else overlay.descendant_guard
        )
        if relation == "unrelated":
            self.assertEqual(run_slice.state, before)
            return run_slice.state
        if guard:
            transition = match_transition(
                "analysis", before.value, event_type, guard
            )
        else:
            transition = derive_transition(
                "analysis", before.value, event_type, {}
            )
        self.assertIsNotNone(transition)
        self.assertEqual(run_slice.state.value, transition.to_state)
        observed.add(tuple(transition))
        return run_slice.state

    def _recheck_payload(
        self,
        revision,
        run_id,
        prepare,
        evidence,
        object_id,
        tx_id,
        event_type,
        selector,
    ):
        payload = commit_event_payload(
            revision, run_id, prepare, evidence, object_id
        )
        payload.pop("commit_tx_id")
        payload.update(
            {
                "recheck_tx_id": tx_id,
                "target_namespace": "work",
                "target_object_id": object_id,
            }
        )
        if event_type == "COMPLETION_RECHECK_OPENED":
            payload["recheck_scope"] = selector
        elif event_type == "COMPLETION_PROOF_REFRESHED":
            payload["refresh_result"] = selector
        elif event_type == "COMPLETION_RECHECK_DEFERRED":
            payload["escalation_reason"] = selector
        return payload

    def _owner_sequence(self, terminal_event, terminal_selector, observed):
        local, evidence, prepare = prepared_local("owner-harness")
        values = project_genesis()
        state = self._append_and_execute(
            values,
            local,
            AnalysisState.COMMITTING,
            "STAGE_COMMITTED",
            commit_event_payload(
                1, "owner-harness", prepare, evidence, "stage-owner-harness"
            ),
            observed,
        )
        state = self._append_and_execute(
            values,
            local,
            state,
            "COMPLETION_RECHECK_OPENED",
            self._recheck_payload(
                2,
                "owner-harness",
                prepare,
                evidence,
                "stage-owner-harness",
                "owner-recheck-1",
                "COMPLETION_RECHECK_OPENED",
                "own_stage",
            ),
            observed,
        )
        self._append_and_execute(
            values,
            local,
            state,
            terminal_event,
            self._recheck_payload(
                3,
                "owner-harness",
                prepare,
                evidence,
                "stage-owner-harness",
                "owner-recheck-1",
                terminal_event,
                terminal_selector,
            ),
            observed,
        )

    def _descendant_sequence(self, terminal_event, terminal_selector, observed):
        local, evidence, prepare = prepared_local("child-harness")
        _, upstream_evidence, upstream_prepare = prepared_local("upstream-harness")
        values = project_genesis()
        state = self._append_and_execute(
            values,
            local,
            AnalysisState.COMMITTING,
            "STAGE_COMMITTED",
            commit_event_payload(
                1,
                "upstream-harness",
                upstream_prepare,
                upstream_evidence,
                "stage-upstream-harness",
            ),
            observed,
            relation="unrelated",
        )
        state = self._append_and_execute(
            values,
            local,
            state,
            "STAGE_COMMITTED",
            commit_event_payload(
                2,
                "child-harness",
                prepare,
                evidence,
                "stage-child-harness",
                (
                    {
                        "namespace": "work",
                        "object_id": "stage-upstream-harness",
                        "object_head": "stage-upstream-harness-head-1",
                    },
                ),
            ),
            observed,
        )
        state = self._append_and_execute(
            values,
            local,
            state,
            "COMPLETION_RECHECK_OPENED",
            self._recheck_payload(
                3,
                "upstream-harness",
                upstream_prepare,
                upstream_evidence,
                "stage-upstream-harness",
                "descendant-recheck-1",
                "COMPLETION_RECHECK_OPENED",
                "own_stage",
            ),
            observed,
            relation="descendant",
        )
        self._append_and_execute(
            values,
            local,
            state,
            terminal_event,
            self._recheck_payload(
                4,
                "upstream-harness",
                upstream_prepare,
                upstream_evidence,
                "stage-upstream-harness",
                "descendant-recheck-1",
                terminal_event,
                terminal_selector,
            ),
            observed,
            relation="descendant",
        )

    def test_every_project_owned_transition_executes_through_federation(self):
        observed = set()

        # Both durable stage-commit source states execute through the full cut.
        recovery_events, recovery_evidence, recovery_prepare = evidence_and_prepare(
            run_genesis("RECOVERY_REQUIRED", run_id="recovery-harness"),
            commit_tx="commit-recovery-harness",
        )
        recovery = reduce_run(recovery_events)
        values = project_genesis()
        self._append_and_execute(
            values,
            recovery,
            AnalysisState.RECOVERY_REQUIRED,
            "STAGE_COMMITTED",
            commit_event_payload(
                1,
                "recovery-harness",
                recovery_prepare,
                recovery_evidence,
                "stage-recovery-harness",
            ),
            observed,
        )

        # Each stale source must publish a typed correction delta before PLANNED.
        for index, source in enumerate(
            ("STALE_BRANCH", "STALE_COMPLETION", "STALE_CONTEXT"), start=1
        ):
            local = reduce_run(run_genesis(source, run_id=f"correction-{index}"))
            tail = local.reachable_run_events[-1]
            values = project_genesis()
            correction_baseline = reduce_project_cut(prefixes(values))
            payload = activation(
                1,
                f"branch-correction-{index}",
                f"branch-correction-{index}-head",
                object_type="branch",
                run_id=f"correction-{index}",
                run_event_id=tail.event_id,
                run_event_hash=tail.event_hash,
                correction_id=f"correction-{index}",
                prior_attempt_id="attempt-1",
                attempt_id="attempt-2",
                branch_id="branch-2",
                request_key="request-2",
                intent_key="intent-2",
                execution_key="execution-2",
                local_execution_key="local-2",
                submission_key="submission-2",
                operation_keys=["operation-2"],
                dependency_delta={
                    "expected_direct_dependency_heads": [],
                    "new_direct_dependency_heads": [],
                    "expected_dependency_closure": [],
                    "new_dependency_closure": [],
                    "expected_logical_scope_key": "logical-scope-1",
                    "new_logical_scope_key": "logical-scope-1",
                    "expected_project_revision_baseline": 0,
                    "new_project_revision_baseline": 0,
                    "expected_project_semantic_cut_root_baseline": ZERO_HASH,
                    "new_project_semantic_cut_root_baseline": (
                        correction_baseline.project_semantic_cut_root
                    ),
                },
            )
            self._append_and_execute(
                values,
                local,
                AnalysisState(source),
                "CORRECTION_BRANCH_CREATED",
                payload,
                observed,
            )

        # Owner success/revoke and descendant success/revoke close single blockers.
        self._owner_sequence("COMPLETION_PROOF_REFRESHED", "own_success", observed)
        self._owner_sequence("COMPLETION_PROOF_REVOKED", "", observed)
        self._descendant_sequence(
            "COMPLETION_PROOF_REFRESHED", "own_success", observed
        )
        self._descendant_sequence("COMPLETION_PROOF_REVOKED", "", observed)

        # Multiple blocker paths cover additional OPEN, partial REFRESH, and DEFER.
        for relation in ("owner", "descendant"):
            run_id = f"{relation}-multi"
            local, evidence, prepare = prepared_local(run_id)
            values = project_genesis()
            revision = 1
            if relation == "descendant":
                _, target_evidence, target_prepare = prepared_local("upstream-multi")
                state = self._append_and_execute(
                    values,
                    local,
                    AnalysisState.COMMITTING,
                    "STAGE_COMMITTED",
                    commit_event_payload(
                        revision,
                        "upstream-multi",
                        target_prepare,
                        target_evidence,
                        "stage-upstream-multi",
                    ),
                    observed,
                    relation="unrelated",
                )
                revision += 1
                state = self._append_and_execute(
                    values,
                    local,
                    state,
                    "STAGE_COMMITTED",
                    commit_event_payload(
                        revision,
                        run_id,
                        prepare,
                        evidence,
                        f"stage-{run_id}",
                        (
                            {
                                "namespace": "work",
                                "object_id": "stage-upstream-multi",
                                "object_head": "stage-upstream-multi-head-1",
                            },
                        ),
                    ),
                    observed,
                )
                target_run = "upstream-multi"
                target_object = "stage-upstream-multi"
            else:
                state = self._append_and_execute(
                    values,
                    local,
                    AnalysisState.COMMITTING,
                    "STAGE_COMMITTED",
                    commit_event_payload(
                        revision, run_id, prepare, evidence, f"stage-{run_id}"
                    ),
                    observed,
                )
                target_run = run_id
                target_object = f"stage-{run_id}"
                target_prepare = prepare
                target_evidence = evidence
            revision += 1
            state = self._append_and_execute(
                values,
                local,
                state,
                "COMPLETION_RECHECK_OPENED",
                self._recheck_payload(
                    revision,
                    target_run,
                    target_prepare,
                    target_evidence,
                    target_object,
                    f"{relation}-tx-1",
                    "COMPLETION_RECHECK_OPENED",
                    "own_stage",
                ),
                observed,
                relation=relation,
            )
            revision += 1
            state = self._append_and_execute(
                values,
                local,
                state,
                "COMPLETION_RECHECK_OPENED",
                self._recheck_payload(
                    revision,
                    target_run,
                    target_prepare,
                    target_evidence,
                    target_object,
                    f"{relation}-tx-2",
                    "COMPLETION_RECHECK_OPENED",
                    "additional",
                ),
                observed,
                relation=relation,
            )
            revision += 1
            state = self._append_and_execute(
                values,
                local,
                state,
                "COMPLETION_PROOF_REFRESHED",
                self._recheck_payload(
                    revision,
                    target_run,
                    target_prepare,
                    target_evidence,
                    target_object,
                    f"{relation}-tx-1",
                    "COMPLETION_PROOF_REFRESHED",
                    "blockers_remain",
                ),
                observed,
                relation=relation,
            )
            revision += 1
            self._append_and_execute(
                values,
                local,
                state,
                "COMPLETION_RECHECK_DEFERRED",
                self._recheck_payload(
                    revision,
                    target_run,
                    target_prepare,
                    target_evidence,
                    target_object,
                    f"{relation}-tx-2",
                    "COMPLETION_RECHECK_DEFERRED",
                    "manual-review",
                ),
                observed,
                relation=relation,
            )

        expected = {
            tuple(item) for item in ALL_TRANSITIONS if item.owner_ledger == "project"
        }
        self.assertEqual(observed, expected)


if __name__ == "__main__":
    unittest.main()
