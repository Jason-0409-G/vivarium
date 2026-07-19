import dataclasses
import unittest

from skills.vivarium.vivarium_v2.errors import IntegrityError
from skills.vivarium.vivarium_v2.events import Event, ZERO_HASH
from skills.vivarium.vivarium_v2.reducers import reduce_run
from skills.vivarium.vivarium_v2.state import (
    ALL_TRANSITIONS,
    ALIAS_TOKENS,
    AnalysisState,
    COMMIT_ABORT_REASON_TARGET,
    ExternalClientState,
    ObligationState,
    match_transition,
)


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
HASH_D = "sha256:" + "d" * 64


def run_genesis_payload(analysis_state="PLANNED", **extra):
    payload = {
        "run_id": "run-state-machine",
        "analysis_state": analysis_state,
        "attempt_id": "attempt-1",
        "branch_id": "branch-1",
        "logical_scope_key": "logical-scope-1",
        "request_key": "request-1",
        "intent_key": "intent-1",
        "execution_key": "execution-1",
        "local_execution_key": "local-execution-1",
        "submission_key": "submission-1",
        "operation_keys": [],
        "merge_policy_digest": HASH_A,
    }
    payload.update(extra)
    return payload


def append_event(events, event_type, payload):
    sequence = len(events)
    event = Event.build(
        ledger_id="run:state-machine",
        event_seq=sequence,
        event_id=f"run-sm-{sequence}",
        event_type=event_type,
        tx_id=f"tx-sm-{sequence}",
        prev_event_hash=events[-1].event_hash if events else ZERO_HASH,
        recorded_at=f"2026-07-18T00:00:{sequence:02d}Z",
        effective_at=f"2026-07-18T00:00:{sequence:02d}Z",
        payload=payload,
    )
    return (*events, event)


class StateMachineCompilationTests(unittest.TestCase):
    def test_every_compiled_transition_is_concrete_and_namespaced(self):
        namespaces = {
            "analysis": {item.value for item in AnalysisState},
            "obligation": {item.value for item in ObligationState},
            "external_client": {item.value for item in ExternalClientState},
        }

        self.assertTrue(ALL_TRANSITIONS)
        self.assertEqual(len(ALL_TRANSITIONS), len(set(ALL_TRANSITIONS)))
        for transition in ALL_TRANSITIONS:
            with self.subTest(transition=transition):
                self.assertNotIn(transition.from_state, ALIAS_TOKENS)
                self.assertNotIn(transition.to_state, ALIAS_TOKENS)
                self.assertNotIn(transition.guard, ALIAS_TOKENS)
                self.assertIn(transition.from_state, namespaces[transition.reducer])
                self.assertIn(transition.to_state, namespaces[transition.reducer])
                self.assertIn(transition.owner_ledger, {"run", "project"})
                self.assertEqual(
                    match_transition(
                        transition.reducer,
                        transition.from_state,
                        transition.event,
                        transition.guard,
                    ),
                    transition,
                )

    def test_unlisted_transition_has_zero_matches(self):
        with self.assertRaises(IntegrityError):
            match_transition("analysis", "PLANNED", "STAGE_COMMITTED", "commit_tx_durable")

    def test_abort_cross_product_is_fully_expanded(self):
        self.assertEqual(len(COMMIT_ABORT_REASON_TARGET), 15)
        for source in (AnalysisState.COMMITTING, AnalysisState.RECOVERY_REQUIRED):
            for reason, target in COMMIT_ABORT_REASON_TARGET.items():
                with self.subTest(source=source, reason=reason):
                    transition = match_transition(
                        "analysis",
                        source.value,
                        "STAGE_COMMIT_ABORTED",
                        reason,
                    )
                    self.assertEqual(transition.to_state, target.value)
                    self.assertEqual(transition.owner_ledger, "run")


class RunReducerTests(unittest.TestCase):
    def prepared_run(self):
        events = append_event(
            (),
            "RUN_LEDGER_GENESIS",
            run_genesis_payload(),
        )
        trace = (
            ("CONTRACT_FROZEN", {"event_digest": HASH_B}),
            ("CANDIDATE_PREPARED", {"event_digest": HASH_B}),
            ("LOCAL_EXECUTION_INTENT", {"event_digest": HASH_B}),
            (
                "LOCAL_WRAPPER_ATTACHED",
                {"event_digest": HASH_B, "attachment_kind": "new_wrapper"},
            ),
            (
                "TERMINAL_EVIDENCE_FROZEN",
                {"event_digest": HASH_B, "evidence_kind": "terminal_cut"},
            ),
        )
        for event_type, payload in trace:
            events = append_event(events, event_type, payload)
        events = append_event(
            events,
            "EVIDENCE_CUT_FROZEN",
            {"evidence_cut_id": "cut-1", "head_digest": HASH_B},
        )
        evidence = events[-1]
        events = append_event(
            events,
            "EVIDENCE_BUNDLE_FROZEN",
            {
                "bundle_id": "bundle-1",
                "bundle_digest": HASH_D,
                "evidence_cut_id": "cut-1",
                "evidence_cut_event_id": evidence.event_id,
                "evidence_cut_event_hash": evidence.event_hash,
                "evidence_cut_digest": HASH_B,
            },
        )
        bundle = events[-1]
        events = append_event(
            events,
            "COMPLETION_CLASSIFIED",
            {
                "classification_id": "classification-1",
                "evidence_cut_id": "cut-1",
                "evidence_cut_digest": HASH_B,
                "outcome": "success",
            },
        )
        classification_event = events[-1]
        classification = reduce_run(events).completion_classifications[-1]
        events = append_event(
            events,
            "COMPLETION_PROOF_RECORDED",
            {
                "completion_proof_id": "proof-1",
                "completion_proof_digest": HASH_C,
                "classification_id": "classification-1",
                "classification_event_id": classification_event.event_id,
                "classification_event_hash": classification_event.event_hash,
                "classification_digest": classification.classification_digest,
                "evidence_cut_id": "cut-1",
                "evidence_cut_digest": HASH_B,
            },
        )
        proof = events[-1]
        events = append_event(
            events,
            "COMPLETION_SUCCESS_PROVEN",
            {
                "completion_proof_id": "proof-1",
                "completion_proof_event_id": proof.event_id,
                "completion_proof_event_hash": proof.event_hash,
                "completion_proof_digest": HASH_C,
                "bundle_id": "bundle-1",
                "bundle_event_id": bundle.event_id,
                "bundle_event_hash": bundle.event_hash,
                "bundle_digest": HASH_D,
            },
        )
        events = append_event(
            events,
            "VALIDATOR_REPORT_SEALED",
            {
                "validator_report_id": "validator-1",
                "validator_report_digest": HASH_A,
                "completion_proof_id": "proof-1",
                "completion_proof_event_id": proof.event_id,
                "completion_proof_event_hash": proof.event_hash,
                "completion_proof_digest": HASH_C,
                "bundle_id": "bundle-1",
                "bundle_event_id": bundle.event_id,
                "bundle_event_hash": bundle.event_hash,
                "bundle_digest": HASH_D,
                "validation_outcome": "pass",
            },
        )
        validator = events[-1]
        events = append_event(
            events,
            "VALIDATION_PASSED",
            {
                "validator_report_id": "validator-1",
                "validator_report_event_id": validator.event_id,
                "validator_report_event_hash": validator.event_hash,
                "validator_report_digest": HASH_A,
            },
        )
        events = append_event(events, "CHECKER_ALLOCATED", {"event_digest": HASH_B})
        events = append_event(
            events,
            "CHECKER_REVIEW_SEALED",
            {
                "checker_review_id": "review-1",
                "checker_review_digest": HASH_B,
                "validator_report_id": "validator-1",
                "validator_report_event_id": validator.event_id,
                "validator_report_event_hash": validator.event_hash,
                "validator_report_digest": HASH_A,
                "review_outcome": "pass",
            },
        )
        review = events[-1]
        events = append_event(
            events,
            "QUORUM_DECISION_SEALED",
            {
                "quorum_decision_id": "quorum-1",
                "quorum_decision_digest": HASH_C,
                "validator_report_id": "validator-1",
                "validator_report_event_id": validator.event_id,
                "validator_report_event_hash": validator.event_hash,
                "validator_report_digest": HASH_A,
                "checker_review_id": "review-1",
                "checker_review_event_id": review.event_id,
                "checker_review_event_hash": review.event_hash,
                "checker_review_digest": HASH_B,
                "quorum_outcome": "pass",
            },
        )
        quorum = events[-1]
        events = append_event(
            events,
            "CHECKER_QUORUM_PASSED",
            {
                "quorum_decision_id": "quorum-1",
                "quorum_decision_event_id": quorum.event_id,
                "quorum_decision_event_hash": quorum.event_hash,
                "quorum_decision_digest": HASH_C,
            },
        )
        return append_event(
            events,
            "COMMIT_PREPARED",
            {
                "commit_tx_id": "commit-1",
                "evidence_cut_id": "cut-1",
                "evidence_cut_digest": HASH_B,
                "origin_state": "COMMITTING",
            },
        )

    def test_legal_trace_reduces_and_outputs_are_frozen(self):
        state = reduce_run(self.prepared_run())

        self.assertEqual(state.analysis_state, AnalysisState.COMMITTING)
        self.assertEqual(len(state.preparations), 1)
        self.assertTrue(dataclasses.is_dataclass(state))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            state.analysis_state = AnalysisState.BLOCKED

    def test_abort_event_applies_closed_reason_target(self):
        events = self.prepared_run()
        preparation = events[-1]
        classification_digest = reduce_run(events).completion_classifications[-1].classification_digest
        events = append_event(
            events,
            "STAGE_COMMIT_ABORTED",
            {
                "commit_tx_id": "commit-1",
                "prepare_event_id": preparation.event_id,
                "prepare_event_hash": preparation.event_hash,
                "abort_reason": "EVIDENCE_BUNDLE_INTEGRITY_FAILURE",
                "analysis_from": "COMMITTING",
                "analysis_target": "BLOCKED",
                "sealed_failure_digest": classification_digest,
                "completion_classification_id": "classification-1",
                "completion_classification_digest": classification_digest,
                "preparation_delta": {"from": "ACTIVE", "to": "INACTIVE"},
            },
        )

        state = reduce_run(events)

        self.assertEqual(state.analysis_state, AnalysisState.BLOCKED)
        self.assertFalse(state.preparations[0].active)

    def test_abort_event_rejects_wrong_target(self):
        events = self.prepared_run()
        preparation = events[-1]
        classification_digest = reduce_run(events).completion_classifications[-1].classification_digest
        events = append_event(
            events,
            "STAGE_COMMIT_ABORTED",
            {
                "commit_tx_id": "commit-1",
                "prepare_event_id": preparation.event_id,
                "prepare_event_hash": preparation.event_hash,
                "abort_reason": "EVIDENCE_BUNDLE_INTEGRITY_FAILURE",
                "analysis_from": "COMMITTING",
                "analysis_target": "VALIDATING",
                "sealed_failure_digest": classification_digest,
                "completion_classification_id": "classification-1",
                "completion_classification_digest": classification_digest,
                "preparation_delta": {"from": "ACTIVE", "to": "INACTIVE"},
            },
        )

        with self.assertRaises(IntegrityError):
            reduce_run(events)

    def test_unsupported_event_fails_without_changing_prior_root(self):
        events = self.prepared_run()
        before = reduce_run(events)
        invalid = append_event(events, "UNREVIEWED_EVENT", {"semantic": True})

        with self.assertRaises(IntegrityError):
            reduce_run(invalid)
        self.assertEqual(reduce_run(events).run_local_state_root, before.run_local_state_root)

    def test_non_hex_digest_payload_is_rejected(self):
        # PR review P2 / audit task3a-2: a typed digest field must be strict
        # lowercase hex, not merely "sha256:" + any 64 characters.
        events = append_event(
            (),
            "RUN_LEDGER_GENESIS",
            run_genesis_payload(merge_policy_digest="sha256:" + "z" * 64),
        )
        with self.assertRaises(IntegrityError):
            reduce_run(events)

    def test_open_enum_value_is_reported_as_integrity_failure(self):
        events = self.prepared_run()
        invalid = append_event(
            events,
            "COMMIT_RECOVERY_REQUIRED",
            {
                "analysis_delta": {
                    "expected_state": "COMMITTING",
                    "new_state": "NOT_A_REVIEWED_STATE",
                    "guard": "crash_uncertain_tail",
                }
            },
        )

        with self.assertRaises(IntegrityError):
            reduce_run(invalid)

    def test_composite_event_updates_analysis_and_keyed_obligation_atomically(self):
        events = append_event(
            (),
            "RUN_LEDGER_GENESIS",
            run_genesis_payload(
                "SUBMISSION_UNCERTAIN",
                obligations=[
                    {
                        "obligation_id": "submission:key-1",
                        "obligation_kind": "submission",
                        "state": "SUBMISSION_UNCERTAIN",
                        "head_digest": "sha256:" + "1" * 64,
                        "side_effect_scope_key": "scope-1",
                    }
                ],
            ),
        )
        events = append_event(
            events,
            "DUPLICATE_EXTERNAL_SIDE_EFFECT_DETECTED",
            {
                "detection_kind": "multiple_accepted_jobs",
                "side_effect_scope_key": "scope-1",
                "submission_obligation_id": "submission:key-1",
                "scoped_obligation_ids": ["submission:key-1"],
                "scoped_client_ids": [],
                "analysis_delta": {
                    "expected_state": "SUBMISSION_UNCERTAIN",
                    "new_state": "ESCALATED",
                },
                "obligation_deltas": [
                    {
                        "obligation_id": "submission:key-1",
                        "obligation_kind": "submission",
                        "expected_state": "SUBMISSION_UNCERTAIN",
                        "new_state": "DUPLICATE_EXTERNAL_SIDE_EFFECT",
                        "expected_head_digest": "sha256:" + "1" * 64,
                        "new_head_digest": "sha256:" + "2" * 64,
                    }
                ],
                "client_deltas": [],
            },
        )

        state = reduce_run(events)

        self.assertEqual(state.analysis_state, AnalysisState.ESCALATED)
        self.assertEqual(state.obligations[0].state, ObligationState.DUPLICATE_EXTERNAL_SIDE_EFFECT)

    def test_external_client_transition_is_keyed_and_root_bound(self):
        events = append_event(
            (),
            "RUN_LEDGER_GENESIS",
            run_genesis_payload(),
        )
        before = reduce_run(events)
        events = append_event(
            events,
            "EXTERNAL_CALL_STARTED",
            {
                "event_digest": HASH_B,
                "side_effect_scope_key": "scope-1",
                "client_deltas": [
                    {
                        "operation_key": "operation:key-1",
                        "expected_state": "NONE",
                        "new_state": "STARTING",
                        "expected_head_digest": ZERO_HASH,
                        "new_head_digest": "sha256:" + "3" * 64,
                    }
                ]
            },
        )

        after = reduce_run(events)

        self.assertEqual(after.mutation_clients[0].state, ExternalClientState.STARTING)
        self.assertNotEqual(before.run_local_state_root, after.run_local_state_root)


if __name__ == "__main__":
    unittest.main()
