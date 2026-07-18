import inspect
import json
import unittest
from pathlib import Path

from skills.vivarium.vivarium_v2.canonical import domain_hash
from skills.vivarium.vivarium_v2.errors import IntegrityError
from skills.vivarium.vivarium_v2.events import Event, ZERO_HASH
from skills.vivarium.vivarium_v2 import reducers, state as state_module
from skills.vivarium.vivarium_v2.reducers import (
    federate,
    reduce_project_cut,
    reduce_project_validity,
    reduce_run,
    reduce_run_validity,
)
from skills.vivarium.vivarium_v2.state import AnalysisState, ProjectPrefixes


FIXTURE = Path(__file__).parent / "fixtures" / "state_machine_transitions_v1.json"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
HASH_D = "sha256:" + "d" * 64


def append(events, ledger_id, event_type, payload, *, event_id=None):
    seq = len(events)
    item = Event.build(
        ledger_id=ledger_id,
        event_seq=seq,
        event_id=event_id or f"{ledger_id}-{seq}",
        event_type=event_type,
        tx_id=f"tx-{ledger_id}-{seq}",
        prev_event_hash=events[-1].event_hash if events else ZERO_HASH,
        recorded_at=f"2026-07-18T02:00:{seq:02d}Z",
        effective_at=f"2026-07-18T02:00:{seq:02d}Z",
        payload=payload,
    )
    return (*events, item)


def run_genesis(state="PLANNED", run_id="review-run", attempt_id="attempt-1"):
    return append(
        (),
        f"run:{run_id}",
        "RUN_LEDGER_GENESIS",
        {
            "run_id": run_id,
            "analysis_state": state,
            "attempt_id": attempt_id,
            "branch_id": "branch-1",
            "logical_scope_key": "logical-scope-1",
            "request_key": "request-1",
            "intent_key": "intent-1",
            "execution_key": "execution-1",
            "local_execution_key": "local-1",
            "submission_key": "submission-1",
            "operation_keys": [],
            "merge_policy_digest": HASH_A,
        },
    )


PROJECT_LEDGERS = {
    "truth": ("project-truth", "TRUTH_LEDGER_GENESIS"),
    "decision": ("project-decision", "DECISION_LEDGER_GENESIS"),
    "work": ("project-work", "WORK_LEDGER_GENESIS"),
    "memory": ("project-memory", "MEMORY_LEDGER_GENESIS"),
    "run_registry": ("project-run-registry", "RUN_REGISTRY_LEDGER_GENESIS"),
}


def empty_root(namespace):
    return domain_hash(
        "vivarium-project-active-root/v1",
        {"namespace": namespace, "objects": []},
    )


def project_genesis():
    values = {}
    for namespace, (ledger_id, event_type) in PROJECT_LEDGERS.items():
        values[namespace] = append(
            (),
            ledger_id,
            event_type,
            {
                "activated_objects": [],
                "canonical_dependency_edges": [],
                "initial_state_root": empty_root(namespace),
                "locked_policy_digest": HASH_D,
            },
        )
    return values


def prefixes(values):
    return ProjectPrefixes(**values)


def activation(revision, object_id, object_head, dependencies=(), **extra):
    return {
        "project_revision": revision,
        "object_type": "fact",
        "object_id": object_id,
        "object_head": object_head,
        "dependencies": list(dependencies),
        **extra,
    }


def evidence_and_prepare(events, origin="COMMITTING", commit_tx="commit-1"):
    events = append(
        events,
        events[0].ledger_id,
        "EVIDENCE_CUT_FROZEN",
        {"evidence_cut_id": "cut-1", "head_digest": HASH_B},
    )
    evidence = events[-1]
    events = append(
        events,
        events[0].ledger_id,
        "COMMIT_PREPARED",
        {
            "commit_tx_id": commit_tx,
            "evidence_cut_id": "cut-1",
            "evidence_cut_digest": HASH_B,
            "origin_state": origin,
        },
    )
    return events, evidence, events[-1]


class CriticalContractClosureTests(unittest.TestCase):
    def test_machine_compiles_typed_contracts_and_free_guard_is_rejected(self):
        self.assertTrue(getattr(state_module, "EVENT_CONTRACTS", ()))
        events = run_genesis()
        forged = append(
            events,
            events[0].ledger_id,
            "CONTRACT_FROZEN",
            {"guard": "contract_frozen", "contract_digest": HASH_B},
        )

        with self.assertRaises(IntegrityError):
            reduce_run(forged)

    def test_success_classification_is_durable_before_success_proof(self):
        events = run_genesis("COLLECTING")
        events = append(
            events,
            events[0].ledger_id,
            "EVIDENCE_CUT_FROZEN",
            {"evidence_cut_id": "cut-1", "head_digest": HASH_B},
        )
        evidence = events[-1]
        events = append(
            events,
            events[0].ledger_id,
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
        classified = reduce_run(events)
        classification_event = events[-1]
        events = append(
            events,
            events[0].ledger_id,
            "COMPLETION_PROOF_RECORDED",
            {
                "completion_proof_id": "proof-1",
                "completion_proof_digest": HASH_C,
                "classification_id": "classification-1",
                "classification_event_id": classification_event.event_id,
                "classification_event_hash": classification_event.event_hash,
                "classification_digest": classified.completion_classifications[0].classification_digest,
                "evidence_cut_id": "cut-1",
                "evidence_cut_digest": HASH_B,
            },
        )
        proof = events[-1]
        events = append(
            events,
            events[0].ledger_id,
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

        proven = reduce_run(events)

        self.assertEqual(classified.analysis_state, AnalysisState.COLLECTING)
        self.assertEqual(classified.completion_classifications[0].outcome, "success")
        self.assertEqual(proven.analysis_state, AnalysisState.VALIDATING)

    def test_conflicting_guard_and_outcome_cannot_select_failure(self):
        events = run_genesis("COLLECTING")
        events = append(
            events,
            events[0].ledger_id,
            "COMPLETION_CLASSIFIED",
            {"guard": "failure_retryable", "outcome": "success"},
        )

        with self.assertRaises(IntegrityError):
            reduce_run(events)

    def test_composite_is_machine_derived_and_atomic(self):
        events = run_genesis("SUBMISSION_UNCERTAIN")
        genesis = dict(events[0].payload)
        genesis["obligations"] = [
            {
                "obligation_id": "submission:submission-1",
                "obligation_kind": "submission",
                "state": "SUBMISSION_UNCERTAIN",
                "head_digest": HASH_A,
                "side_effect_scope_key": "scope-1",
            }
        ]
        events = append((), events[0].ledger_id, "RUN_LEDGER_GENESIS", genesis)
        prior = reduce_run(events)
        complete = append(
            events,
            events[0].ledger_id,
            "DUPLICATE_EXTERNAL_SIDE_EFFECT_DETECTED",
            {
                "detection_kind": "multiple_accepted_jobs",
                "side_effect_scope_key": "scope-1",
                "submission_obligation_id": "submission:submission-1",
                "scoped_obligation_ids": ["submission:submission-1"],
                "scoped_client_ids": [],
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
        applied = reduce_run(complete)
        missing = append(
            events,
            events[0].ledger_id,
            "DUPLICATE_EXTERNAL_SIDE_EFFECT_DETECTED",
            {
                "detection_kind": "multiple_accepted_jobs",
                "side_effect_scope_key": "scope-1",
                "submission_obligation_id": "submission:submission-1",
                "scoped_obligation_ids": ["submission:submission-1"],
                "scoped_client_ids": [],
                "analysis_delta": {
                    "expected_state": "SUBMISSION_UNCERTAIN",
                    "new_state": "ESCALATED",
                },
                "obligation_deltas": [],
                "client_deltas": [],
            },
        )

        self.assertEqual(applied.analysis_state, AnalysisState.ESCALATED)
        with self.assertRaises(IntegrityError):
            reduce_run(missing)
        self.assertEqual(reduce_run(events).run_local_state_root, prior.run_local_state_root)

    def test_unknown_event_with_empty_delta_arrays_is_still_unknown(self):
        events = run_genesis()
        prior = reduce_run(events)
        invalid = append(
            events,
            events[0].ledger_id,
            "UNKNOWN_COMPOSITE",
            {"obligation_deltas": [], "client_deltas": []},
        )

        with self.assertRaises(IntegrityError):
            reduce_run(invalid)
        self.assertEqual(reduce_run(events).run_local_state_root, prior.run_local_state_root)

    def test_retry_preserves_terminal_attempt_and_allocates_new_keys(self):
        events = run_genesis("RETRYABLE_FAILURE")
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

        self.assertEqual(replayed.active_attempt_id, "attempt-2")
        self.assertEqual([item.attempt_id for item in replayed.attempts], ["attempt-1", "attempt-2"])
        self.assertEqual(replayed.attempts[0].analysis_state, AnalysisState.RETRYABLE_FAILURE)
        self.assertEqual(replayed.attempts[1].analysis_state, AnalysisState.PLANNED)

    def test_project_revision_order_stales_old_attempt_then_creates_successor(self):
        local_events = run_genesis("COMMITTING")
        local_events = append(
            local_events,
            local_events[0].ledger_id,
            "ATTEMPT_DEPENDENCIES_FROZEN",
            {
                "attempt_id": "attempt-1",
                "project_revision": 0,
                "project_semantic_cut_root": ZERO_HASH,
                "direct_dependency_heads": [
                    {"namespace": "truth", "object_id": "fact-A", "object_head": "A1"}
                ],
                "dependency_closure": [
                    {"namespace": "truth", "object_id": "fact-A", "object_head": "A1"}
                ],
            },
        )
        local_events, evidence, prepare = evidence_and_prepare(local_events)
        local = reduce_run(local_events)
        values = project_genesis()
        values["truth"] = append(
            values["truth"], "project-truth", "FACT_ACTIVATED",
            activation(1, "fact-A", "A1"),
        )
        commit_payload = activation(
            2,
            "stage-review-run",
            "stage-v1",
            ({"namespace": "truth", "object_id": "fact-A", "object_head": "A1"},),
            object_type="stage",
            run_id="review-run",
            run_event_id=prepare.event_id,
            run_event_hash=prepare.event_hash,
            commit_tx_id="commit-1",
            prepare_event_id=prepare.event_id,
            prepare_event_hash=prepare.event_hash,
            evidence_cut_id="cut-1",
            evidence_cut_digest=HASH_B,
        )
        values["work"] = append(values["work"], "project-work", "STAGE_COMMITTED", commit_payload)
        values["truth"] = append(
            values["truth"], "project-truth", "FACT_ACTIVATED",
            activation(3, "fact-A", "A2"),
        )
        correction_baseline = reduce_project_cut(prefixes(values))
        correction = activation(
            4,
            "branch-review-run-2",
            "branch-v2",
            object_type="branch",
            run_id="review-run",
            run_event_id=prepare.event_id,
            run_event_hash=prepare.event_hash,
            correction_id="correction-1",
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
                "expected_direct_dependency_heads": [
                    {"namespace": "truth", "object_id": "fact-A", "object_head": "A1"}
                ],
                "new_direct_dependency_heads": [
                    {"namespace": "truth", "object_id": "fact-A", "object_head": "A2"}
                ],
                "expected_dependency_closure": [
                    {"namespace": "truth", "object_id": "fact-A", "object_head": "A1"}
                ],
                "new_dependency_closure": [
                    {"namespace": "truth", "object_id": "fact-A", "object_head": "A2"}
                ],
                "expected_logical_scope_key": "logical-scope-1",
                "new_logical_scope_key": "logical-scope-1",
                "expected_project_revision_baseline": 0,
                "new_project_revision_baseline": 3,
                "expected_project_semantic_cut_root_baseline": ZERO_HASH,
                "new_project_semantic_cut_root_baseline": (
                    correction_baseline.project_semantic_cut_root
                ),
            },
        )
        values["work"] = append(
            values["work"], "project-work", "CORRECTION_BRANCH_CREATED", correction
        )
        cut = reduce_project_cut(prefixes(values))
        validity = reduce_project_validity(cut)
        run_slice = reduce_run_validity(cut, validity, local)

        self.assertEqual(run_slice.active_attempt_id, "attempt-2")
        self.assertEqual(run_slice.attempts[0].analysis_state, AnalysisState.STALE_CONTEXT)
        self.assertEqual(run_slice.attempts[1].analysis_state, AnalysisState.PLANNED)

    def composite_local(self, analysis_state, obligations, clients=()):
        events = run_genesis(analysis_state)
        payload = dict(events[0].payload)
        payload["obligations"] = list(obligations)
        payload["mutation_clients"] = list(clients)
        events = append((), events[0].ledger_id, "RUN_LEDGER_GENESIS", payload)
        return events, reduce_run(events)

    def test_unique_held_and_terminal_reconciliation_are_fixed_composites(self):
        obligation = {
            "obligation_id": "submission:submission-1",
            "obligation_kind": "submission",
            "state": "SUBMISSION_UNCERTAIN",
            "head_digest": HASH_A,
            "side_effect_scope_key": "scope-1",
        }
        cases = (
            ("held", "SCHEDULER_BLOCKED", "JOB_LIVE"),
            ("terminal_resolved", "COLLECTING", "RESOLVED"),
        )
        for result, analysis_target, obligation_target in cases:
            with self.subTest(result=result):
                events, _ = self.composite_local("SUBMISSION_UNCERTAIN", (obligation,))
                events = append(
                    events,
                    events[0].ledger_id,
                    "SUBMISSION_RECONCILED",
                    {
                        "reconciliation_result": result,
                        "side_effect_scope_key": "scope-1",
                        "submission_obligation_id": "submission:submission-1",
                        "analysis_delta": {
                            "expected_state": "SUBMISSION_UNCERTAIN",
                            "new_state": analysis_target,
                        },
                        "obligation_deltas": [
                            {
                                "obligation_id": "submission:submission-1",
                                "obligation_kind": "submission",
                                "expected_state": "SUBMISSION_UNCERTAIN",
                                "new_state": obligation_target,
                                "expected_head_digest": HASH_A,
                                "new_head_digest": HASH_B,
                            }
                        ],
                        "client_deltas": [],
                    },
                )
                replayed = reduce_run(events)
                self.assertEqual(replayed.analysis_state.value, analysis_target)
                self.assertEqual(replayed.obligations[0].state.value, obligation_target)

    def test_duplicate_arbitration_and_cancel_terminal_are_fixed_composites(self):
        duplicate = {
            "obligation_id": "submission:submission-1",
            "obligation_kind": "submission",
            "state": "SUBMISSION_UNCERTAIN",
            "head_digest": HASH_A,
            "side_effect_scope_key": "scope-1",
        }
        events, _ = self.composite_local("SUBMISSION_UNCERTAIN", (duplicate,))
        events = append(
            events,
            events[0].ledger_id,
            "DUPLICATE_EXTERNAL_SIDE_EFFECT_DETECTED",
            {
                "detection_kind": "multiple_accepted_jobs",
                "side_effect_scope_key": "scope-1",
                "submission_obligation_id": "submission:submission-1",
                "scoped_obligation_ids": ["submission:submission-1"],
                "scoped_client_ids": [],
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
        events = append(
            events,
            events[0].ledger_id,
            "DUPLICATE_ARBITRATED",
            {
                "arbitration_result": "live_queued",
                "side_effect_scope_key": "scope-1",
                "submission_obligation_id": "submission:submission-1",
                "scoped_obligation_ids": ["submission:submission-1"],
                "scoped_client_ids": [],
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
                "client_deltas": [],
            },
        )
        arbitrated = reduce_run(events)
        self.assertEqual(arbitrated.analysis_state, AnalysisState.QUEUED)

        obligations = (
            {
                "obligation_id": "operation:cancel-1",
                "obligation_kind": "cancellation",
                "state": "CANCELLATION_UNCERTAIN",
                "head_digest": HASH_A,
                "side_effect_scope_key": "scope-1",
                "operation_key": "cancel-1",
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
                "operation_key": "cancel-1",
                "state": "WIRE_IN_FLIGHT",
                "head_digest": HASH_A,
                "side_effect_scope_key": "scope-1",
            },
        )
        events, _ = self.composite_local("RUNNING_REMOTE", obligations, clients)
        events = append(
            events,
            events[0].ledger_id,
            "OPERATION_RECONCILED",
            {
                "operation_result": "cancel_terminal",
                "side_effect_scope_key": "scope-1",
                "operation_obligation_id": "operation:cancel-1",
                "parent_obligation_id": "submission:submission-1",
                "external_client_id": "cancel-1",
                "operation_key": "cancel-1",
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
                        "operation_key": "cancel-1",
                        "expected_state": "WIRE_IN_FLIGHT",
                        "new_state": "TERMINAL_DRAINED",
                        "expected_head_digest": HASH_A,
                        "new_head_digest": HASH_C,
                    }
                ],
            },
        )
        cancelled = reduce_run(events)
        self.assertEqual(cancelled.analysis_state, AnalysisState.COLLECTING)
        self.assertEqual(
            [item.state.value for item in cancelled.obligations],
            ["RESOLVED", "ACCOUNTING_PENDING"],
        )
        self.assertEqual(cancelled.mutation_clients[0].state.value, "TERMINAL_DRAINED")


class ImportantClosureTests(unittest.TestCase):
    def test_recovery_aborted_uses_matching_preparation_origin_and_deactivates(self):
        events, _, preparation = evidence_and_prepare(run_genesis("COMMITTING"))
        events = append(
            events,
            events[0].ledger_id,
            "COMMIT_RECOVERY_REQUIRED",
            {"recovery_reason": "crash_uncertain_tail"},
        )
        events = append(
            events,
            events[0].ledger_id,
            "RECOVERY_ABORTED",
            {
                "commit_tx_id": "commit-1",
                "prepare_event_id": preparation.event_id,
                "prepare_event_hash": preparation.event_hash,
                "recovery_target_state": "COMMITTING",
                "quarantine_digest": HASH_C,
            },
        )

        replayed = reduce_run(events)

        self.assertEqual(replayed.analysis_state, AnalysisState.COMMITTING)
        self.assertFalse(replayed.preparations[0].active)

    def test_completion_abort_rejects_classification_not_already_durable(self):
        events, _, preparation = evidence_and_prepare(run_genesis("COMMITTING"))
        invalid = append(
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
                "sealed_failure_digest": HASH_C,
                "preparation_delta": {"from": "ACTIVE", "to": "INACTIVE"},
                "completion_classification_id": "not-durable",
                "completion_classification_digest": HASH_D,
            },
        )

        with self.assertRaises(IntegrityError):
            reduce_run(invalid)

    def test_recheck_deferred_and_multiple_blockers_preserve_baseline(self):
        self.assertIsNotNone(
            state_module.match_transition(
                "analysis",
                "COMPLETION_RECHECK_PENDING",
                "COMPLETION_RECHECK_OPENED",
                "additional_complete_cut_durable",
            )
        )
        self.assertIsNotNone(
            state_module.match_transition(
                "analysis",
                "COMPLETION_RECHECK_PENDING",
                "COMPLETION_RECHECK_DEFERRED",
                "classification_cannot_finish_safely",
            )
        )

    def test_missing_closed_composite_tuples_are_present(self):
        required = (
            ("obligation", "SUBMISSION_UNCERTAIN", "SUBMISSION_RECONCILED", "unique_terminal_debts_closed", "RESOLVED"),
            ("obligation", "JOB_LIVE", "OPERATION_RECONCILED", "cancel_caused_terminal", "ACCOUNTING_PENDING"),
            ("external_client", "WIRE_IN_FLIGHT", "OPERATION_RECONCILED", "cancel_response_drained", "TERMINAL_DRAINED"),
        )
        for reducer, source, event_type, guard, target in required:
            with self.subTest(reducer=reducer, guard=guard):
                self.assertEqual(
                    state_module.match_transition(reducer, source, event_type, guard).to_state,
                    target,
                )

    def test_transition_snapshot_matches_independent_golden(self):
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(state_module.TRANSITION_SNAPSHOT_DIGEST, fixture["sha256"])
        self.assertEqual(len(state_module.ALL_TRANSITIONS), fixture["transition_count"])
        for row in fixture["required_tuples"]:
            self.assertIn(tuple(row), [tuple(item) for item in state_module.ALL_TRANSITIONS])

    def test_checksum_valid_but_semantically_invalid_genesis_fails(self):
        values = project_genesis()
        invalid_payload = dict(values["truth"][0].payload)
        invalid_payload["initial_state_root"] = HASH_A
        values["truth"] = append(
            (), "project-truth", "TRUTH_LEDGER_GENESIS", invalid_payload
        )

        with self.assertRaises(IntegrityError):
            reduce_project_cut(prefixes(values))

    def test_full_transitive_attempt_dependency_closure_is_bound(self):
        direct = {"namespace": "work", "object_id": "stage-A", "object_head": "S1"}
        fact_a = {"namespace": "truth", "object_id": "fact-A", "object_head": "A1"}
        fact_b = {"namespace": "truth", "object_id": "fact-B", "object_head": "B1"}
        events = run_genesis("COMMITTED")
        events = append(
            events,
            events[0].ledger_id,
            "ATTEMPT_DEPENDENCIES_FROZEN",
            {
                "attempt_id": "attempt-1",
                "project_revision": 0,
                "project_semantic_cut_root": ZERO_HASH,
                "direct_dependency_heads": [direct],
                "dependency_closure": [direct, fact_a, fact_b],
            },
        )

        local = reduce_run(events)

        self.assertEqual(len(local.attempt_dependency_closure), 3)
        self.assertEqual(local.attempts[0].dependency_closure, local.attempt_dependency_closure)

    def test_federate_public_contract_requires_four_arguments(self):
        signature = inspect.signature(federate)
        parameters = list(signature.parameters.values())

        self.assertEqual(len(parameters), 4)
        self.assertTrue(all(item.default is inspect.Parameter.empty for item in parameters))

    def test_machine_contracts_own_dispatch_metadata(self):
        self.assertTrue(state_module.EVENT_CONTRACTS)
        self.assertNotIn("PROJECT_SEMANTIC_EVENTS", reducers.__dict__)

    def test_exhaustive_event_cross_product_has_no_ambiguous_or_cross_namespace_key(self):
        enums = {
            "analysis": [item.value for item in state_module.AnalysisState],
            "obligation": [item.value for item in state_module.ObligationState],
            "external_client": [item.value for item in state_module.ExternalClientState],
        }
        for reducer, states in enums.items():
            events = sorted({item.event for item in state_module.ALL_TRANSITIONS if item.reducer == reducer})
            guards = sorted({item.guard for item in state_module.ALL_TRANSITIONS if item.reducer == reducer})
            legal = {
                (item.from_state, item.event, item.guard)
                for item in state_module.ALL_TRANSITIONS
                if item.reducer == reducer
            }
            for source in states:
                for event_type in events:
                    for guard in guards:
                        if (source, event_type, guard) in legal:
                            self.assertEqual(
                                state_module.match_transition(reducer, source, event_type, guard).reducer,
                                reducer,
                            )
                        else:
                            with self.assertRaises(IntegrityError):
                                state_module.match_transition(reducer, source, event_type, guard)

    def test_wrong_project_namespace_fails_before_a_new_cut(self):
        values = project_genesis()
        values["decision"] = append(
            values["decision"],
            "project-decision",
            "FACT_ACTIVATED",
            activation(1, "fact-A", "A1"),
        )

        with self.assertRaises(IntegrityError):
            reduce_project_cut(prefixes(values))

    def test_two_hop_dependency_changes_each_change_relevant_slice(self):
        stage = {"namespace": "truth", "object_id": "fact-A", "object_head": "A1"}
        fact_b = {"namespace": "truth", "object_id": "fact-B", "object_head": "B1"}
        events = run_genesis("COMMITTED")
        events = append(
            events,
            events[0].ledger_id,
            "ATTEMPT_DEPENDENCIES_FROZEN",
            {
                "attempt_id": "attempt-1",
                "project_revision": 0,
                "project_semantic_cut_root": ZERO_HASH,
                "direct_dependency_heads": [stage],
                "dependency_closure": [stage, fact_b],
            },
        )
        local = reduce_run(events)
        values = project_genesis()
        values["truth"] = append(
            values["truth"], "project-truth", "FACT_ACTIVATED",
            activation(1, "fact-B", "B1"),
        )
        values["truth"] = append(
            values["truth"], "project-truth", "FACT_ACTIVATED",
            activation(2, "fact-A", "A1", (fact_b,)),
        )
        cut1 = reduce_project_cut(prefixes(values))
        values["truth"] = append(
            values["truth"], "project-truth", "FACT_ACTIVATED",
            activation(3, "fact-B", "B2"),
        )
        cut2 = reduce_project_cut(prefixes(values))
        values["truth"] = append(
            values["truth"], "project-truth", "FACT_ACTIVATED",
            activation(
                4,
                "fact-A",
                "A2",
                ({"namespace": "truth", "object_id": "fact-B", "object_head": "B2"},),
            ),
        )
        cut3 = reduce_project_cut(prefixes(values))
        slices = []
        for cut in (cut1, cut2, cut3):
            validity = reduce_project_validity(cut)
            slices.append(reduce_run_validity(cut, validity, local))

        self.assertEqual(len(slices[0].relevant_project_inputs), 2)
        self.assertNotEqual(slices[0].run_validity_slice_root, slices[1].run_validity_slice_root)
        self.assertNotEqual(slices[1].run_validity_slice_root, slices[2].run_validity_slice_root)

    def test_multiple_recheck_blockers_deferred_and_restore_baseline(self):
        local_events, evidence, prepare = evidence_and_prepare(run_genesis("COMMITTING"))
        local = reduce_run(local_events)
        values = project_genesis()

        def overlay_payload(revision, event_type, tx_id, selector_field=None, selector=None):
            payload = {
                "project_revision": revision,
                "object_type": "stage",
                "object_id": "stage-review-run",
                "object_head": f"stage-{revision}",
                "dependencies": [],
                "run_id": "review-run",
                "run_event_id": prepare.event_id,
                "run_event_hash": prepare.event_hash,
                "prepare_event_id": prepare.event_id,
                "prepare_event_hash": prepare.event_hash,
                "evidence_cut_id": "cut-1",
                "evidence_cut_digest": HASH_B,
            }
            if event_type == "STAGE_COMMITTED":
                payload["commit_tx_id"] = tx_id
            else:
                payload.update(
                    {
                        "recheck_tx_id": tx_id,
                        "target_namespace": "work",
                        "target_object_id": "stage-review-run",
                    }
                )
            if selector_field:
                payload[selector_field] = selector
            if event_type == "COMPLETION_RECHECK_DEFERRED":
                payload["escalation_reason"] = "classifier unavailable"
            return payload

        sequence = (
            ("STAGE_COMMITTED", "commit-1", None, None),
            ("COMPLETION_RECHECK_OPENED", "recheck-1", "recheck_scope", "own_stage"),
            ("COMPLETION_RECHECK_OPENED", "recheck-2", "recheck_scope", "additional"),
            ("COMPLETION_RECHECK_DEFERRED", "recheck-2", None, None),
            ("COMPLETION_PROOF_REFRESHED", "recheck-1", "refresh_result", "blockers_remain"),
        )
        for revision, (event_type, tx_id, selector_field, selector) in enumerate(sequence, 1):
            values["work"] = append(
                values["work"],
                "project-work",
                event_type,
                overlay_payload(revision, event_type, tx_id, selector_field, selector),
            )
        pending_cut = reduce_project_cut(prefixes(values))
        pending_validity = reduce_project_validity(pending_cut)
        pending = reduce_run_validity(pending_cut, pending_validity, local)
        values["work"] = append(
            values["work"],
            "project-work",
            "COMPLETION_PROOF_REFRESHED",
            overlay_payload(6, "COMPLETION_PROOF_REFRESHED", "recheck-2", "refresh_result", "own_success"),
        )
        restored_cut = reduce_project_cut(prefixes(values))
        restored_validity = reduce_project_validity(restored_cut)
        restored = reduce_run_validity(restored_cut, restored_validity, local)

        self.assertEqual(pending.completion_recheck_blockers, ("recheck-2",))
        self.assertTrue(pending.operational_escalated)
        self.assertEqual(pending.state, AnalysisState.COMPLETION_RECHECK_PENDING)
        self.assertEqual(restored.completion_recheck_blockers, ())
        self.assertFalse(restored.operational_escalated)
        self.assertEqual(restored.state, AnalysisState.COMMITTED)


if __name__ == "__main__":
    unittest.main()
