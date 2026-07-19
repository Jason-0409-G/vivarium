import tempfile
import unittest
from pathlib import Path

from skills.vivarium.vivarium_v2.errors import IntegrityError
from skills.vivarium.vivarium_v2.events import ZERO_HASH
from skills.vivarium.vivarium_v2.project import ProjectStore
from tests.v2.support import (
    FrozenClock,
    _seal_commit_evidence,
    execution_evidence_cut,
    persist_execution_evidence_cut,
    prepared_fixture,
    valid_commit_request,
    valid_prepared_commit,
)


class Task4FrozenReviewFixes(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _store(self, name, *, state="COLLECTING", run_id="run-1"):
        store = ProjectStore.init(
            self.root / name, FrozenClock("2026-07-18T00:00:00Z")
        )
        store.register_run(run_id, analysis_state=state)
        return store

    def test_c1_commit_rejects_synthesized_authority_defaults(self):
        store = self._store("authority", state="COMMITTING")
        prepared = store.prepare_commit(
            valid_commit_request(**_seal_commit_evidence(store, "commit-1"))
        )
        with self.assertRaises(IntegrityError):
            store.complete_commit(prepared)

    def test_c1_commit_rejects_a_fabricated_evidence_bundle(self):
        # C-1 (increment 1): prepare must fail closed when evidence_bundle_digest
        # points to no real sealed bundle — a fully forged commit request must
        # not be able to synthesize its own authority chain.
        store = self._store("forged-bundle")
        with self.assertRaises(IntegrityError):
            store.prepare_commit(valid_commit_request())

    def test_c1_commit_rejects_a_non_success_completion(self):
        # C-1 (increment 2): the commit outcome must be re-classified from a
        # real ExecutionEvidenceCut, never asserted. A failure cut (OOM) cannot
        # be committed as a success.
        store = self._store("failure-cut")
        evidence = _seal_commit_evidence(store, "commit-1")
        evidence["execution_evidence_cut_digest"] = persist_execution_evidence_cut(
            store, execution_evidence_cut(exit_code=137, oom=True)
        )
        with self.assertRaises(IntegrityError):
            store.prepare_commit(valid_commit_request(**evidence))

    def test_i1_recovery_resumes_matching_intent_without_prepare(self):
        store = self._store("intent")
        fired = False

        def crash(point):
            nonlocal fired
            if point == "artifact_write" and not fired:
                fired = True
                raise RuntimeError("crash")

        evidence = _seal_commit_evidence(store, "commit-1")
        store.fault_injector = crash
        with self.assertRaises(RuntimeError):
            store.prepare_commit(valid_commit_request(**evidence))
        store.fault_injector = None
        roots = [store.recover().federated_state_root for _ in range(3)]
        self.assertEqual(len(set(roots)), 1)
        self.assertEqual(store.business_event_types().count("STAGE_COMMITTED"), 1)

    def test_i2_recovery_resumes_partial_run_registration(self):
        store = ProjectStore.init(
            self.root / "registration", FrozenClock("2026-07-18T00:00:00Z")
        )
        store._append(
            store._run_ledger("run-1"),
            "RUN_LEDGER_GENESIS",
            {
                "run_id": "run-1",
                "analysis_state": "PLANNED",
                "attempt_id": "attempt-1",
                "branch_id": "branch-1",
                "logical_scope_key": "scope:run-1",
                "request_key": "request:run-1:1",
                "intent_key": "intent:run-1:1",
                "execution_key": "execution:run-1:1",
                "local_execution_key": "local:run-1:1",
                "submission_key": "submission:run-1:1",
                "operation_keys": [],
                "merge_policy_digest": store.capture()[0].locked_policy_digest,
            },
            "partial-registration",
        )
        store.recover()
        self.assertEqual(store.business_event_types().count("RUN_REGISTERED"), 1)

    def _two_commits(self, name):
        store = prepared_fixture(self.root / name)
        first = store.complete_commit(store._test_prepared_commit)
        store.register_run("run-2", analysis_state="COLLECTING")
        second = store.complete_commit(
            valid_prepared_commit(store, run_id="run-2", commit_tx_id="commit-2")
        )
        return store, first, second

    def test_i3_rollback_recomputes_complete_invalidated_lineage(self):
        store, first, second = self._two_commits("rollback")
        event = store.rollback(
            "branch-1", ZERO_HASH, invalidated_roots=(first.payload["object_head"],)
        )
        self.assertEqual(
            set(event.payload["invalidated_roots"]),
            {first.payload["object_head"], second.payload["object_head"]},
        )
        self.assertEqual(set(event.payload["affected_run_ids"]), {"run-1", "run-2"})

    def test_i4_fork_ancestry_stops_at_selected_checkpoint(self):
        store, first, second = self._two_commits("fork")
        store.fork(
            "branch-1", "branch-2", parent_checkpoint_id=first.payload["object_head"]
        )
        child = store.branch_head("branch-2")
        self.assertIn(first.payload["object_head"], child.ancestry)
        self.assertNotIn(second.payload["object_head"], child.ancestry)

    def test_i5_recheck_binds_complete_inbox_identity(self):
        store = prepared_fixture(self.root / "recheck")
        commit = store.complete_commit(store._test_prepared_commit)
        receipt = store.inbox_observation("run-1", commit.payload["object_id"], b"late")
        opened = store.open_recheck("run-1", receipt.observation_id)
        self.assertEqual(opened.payload["observation_id"], receipt.observation_id)
        self.assertEqual(
            opened.payload["observation_digest"], receipt.event.payload["observation_digest"]
        )
        self.assertEqual(opened.payload["target_commit_tx_id"], commit.payload["commit_tx_id"])

    def test_i6_duplicate_inbox_mismatch_rejects_without_append(self):
        store = prepared_fixture(self.root / "duplicate")
        commit = store.complete_commit(store._test_prepared_commit)
        store.inbox_observation(
            "run-1", commit.payload["object_id"], b"first", observation_id="obs-1"
        )
        before = len(store._run_ledger("run-1").recover().events)
        with self.assertRaises(IntegrityError):
            store.inbox_observation(
                "run-1", commit.payload["object_id"], b"different", observation_id="obs-1"
            )
        self.assertEqual(len(store._run_ledger("run-1").recover().events), before)
        store.capture()

    def test_i7_oversize_is_canonical_federated_escalation(self):
        store = prepared_fixture(self.root / "oversize")
        commit = store.complete_commit(store._test_prepared_commit)
        store.inbox_observation(
            "run-1", commit.payload["object_id"], b"x" * (store.inbox_limit + 1)
        )
        state = store.recover()
        self.assertEqual(state.federated_states[0].analysis_state.value, "ESCALATED")
        self.assertFalse(state.federated_states[0].default_retrievable)

    def test_same_observation_id_is_isolated_across_runs(self):
        store = prepared_fixture(self.root / "cross-run-observation")
        first = store.complete_commit(store._test_prepared_commit)
        store.register_run("run-2", analysis_state="COLLECTING")
        second = store.complete_commit(
            valid_prepared_commit(store, run_id="run-2", commit_tx_id="commit-2")
        )
        receipts = (
            store.inbox_observation(
                "run-1", first.payload["object_id"], b"late", observation_id="shared"
            ),
            store.inbox_observation(
                "run-2", second.payload["object_id"], b"late", observation_id="shared"
            ),
        )

        state = store.recover()
        opened = [
            event
            for event in store._project_ledger("work").recover().events
            if event.event_type == "COMPLETION_RECHECK_OPENED"
        ]
        self.assertEqual(len(opened), 2)
        self.assertEqual(len({receipt.recheck_tx_id for receipt in receipts}), 2)
        self.assertEqual(
            {event.payload["run_id"] for event in opened}, {"run-1", "run-2"}
        )
        self.assertTrue(
            all(
                item.analysis_state.value == "COMPLETION_RECHECK_PENDING"
                and not item.default_retrievable
                for item in state.federated_states
            )
        )


if __name__ == "__main__":
    unittest.main()
