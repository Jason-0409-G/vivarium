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
            {
                "run_id": "run-state-machine",
                "analysis_state": "PLANNED",
                "merge_policy_digest": "sha256:" + "a" * 64,
            },
        )
        trace = (
            ("CONTRACT_FROZEN", "contract_frozen"),
            ("CANDIDATE_PREPARED", "requires_brokered_execution"),
            ("LOCAL_EXECUTION_INTENT", "backend_local_intent_durable"),
            ("LOCAL_WRAPPER_ATTACHED", "wrapper_receipt_identity_verified"),
            ("TERMINAL_EVIDENCE_FROZEN", "terminal_evidence_cut_frozen"),
            ("COMPLETION_SUCCESS_PROVEN", "success_classification_proof_bundle_durable"),
            ("VALIDATION_PASSED", "all_hard_gates_pass"),
            ("CHECKER_ALLOCATED", "isolated_checker_allocated"),
            ("CHECKER_QUORUM_PASSED", "quorum_pass_no_major_critical"),
        )
        for event_type, guard in trace:
            events = append_event(events, event_type, {"guard": guard})
        events = append_event(
            events,
            "EVIDENCE_CUT_FROZEN",
            {"evidence_cut_id": "cut-1", "head_digest": "sha256:" + "b" * 64},
        )
        return append_event(
            events,
            "COMMIT_PREPARED",
            {
                "commit_tx_id": "commit-1",
                "evidence_cut_id": "cut-1",
                "evidence_cut_digest": "sha256:" + "b" * 64,
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
                "sealed_failure_digest": "sha256:" + "c" * 64,
                "preparation_delta": {"from": "ACTIVE", "to": "INACTIVE"},
            },
        )

        state = reduce_run(events)

        self.assertEqual(state.analysis_state, AnalysisState.BLOCKED)
        self.assertFalse(state.preparations[0].active)

    def test_abort_event_rejects_wrong_target(self):
        events = self.prepared_run()
        preparation = events[-1]
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
                "sealed_failure_digest": "sha256:" + "c" * 64,
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
            {
                "run_id": "run-state-machine",
                "analysis_state": "SUBMISSION_UNCERTAIN",
                "merge_policy_digest": "sha256:" + "a" * 64,
                "obligations": [
                    {
                        "obligation_id": "submission:key-1",
                        "obligation_kind": "submission",
                        "state": "SUBMISSION_UNCERTAIN",
                        "head_digest": "sha256:" + "1" * 64,
                    }
                ],
            },
        )
        events = append_event(
            events,
            "DUPLICATE_EXTERNAL_SIDE_EFFECT_DETECTED",
            {
                "analysis_delta": {
                    "expected_state": "SUBMISSION_UNCERTAIN",
                    "new_state": "ESCALATED",
                    "guard": "multiple_accepted_jobs",
                },
                "obligation_deltas": [
                    {
                        "obligation_id": "submission:key-1",
                        "obligation_kind": "submission",
                        "expected_state": "SUBMISSION_UNCERTAIN",
                        "new_state": "DUPLICATE_EXTERNAL_SIDE_EFFECT",
                        "head_digest": "sha256:" + "2" * 64,
                        "guard": "multiple_accepted_targets",
                    }
                ],
            },
        )

        state = reduce_run(events)

        self.assertEqual(state.analysis_state, AnalysisState.ESCALATED)
        self.assertEqual(state.obligations[0].state, ObligationState.DUPLICATE_EXTERNAL_SIDE_EFFECT)

    def test_external_client_transition_is_keyed_and_root_bound(self):
        events = append_event(
            (),
            "RUN_LEDGER_GENESIS",
            {
                "run_id": "run-state-machine",
                "analysis_state": "PLANNED",
                "merge_policy_digest": "sha256:" + "a" * 64,
            },
        )
        before = reduce_run(events)
        events = append_event(
            events,
            "EXTERNAL_CALL_STARTED",
            {
                "client_deltas": [
                    {
                        "operation_key": "operation:key-1",
                        "expected_state": "NONE",
                        "new_state": "STARTING",
                        "head_digest": "sha256:" + "3" * 64,
                        "guard": "call_started_before_spawn",
                    }
                ]
            },
        )

        after = reduce_run(events)

        self.assertEqual(after.mutation_clients[0].state, ExternalClientState.STARTING)
        self.assertNotEqual(before.run_local_state_root, after.run_local_state_root)


if __name__ == "__main__":
    unittest.main()
