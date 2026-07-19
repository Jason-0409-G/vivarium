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

    def test_c1_commit_rejects_a_persisted_fabricated_bundle_json(self):
        # C-1 (increment 1, reworked): a canonical, self-hashing JSON blob that
        # is NOT a genuine validator-sealed EvidenceBundle — it neither
        # reconstructs into an EvidenceBundle nor has content-addressed evidence
        # artifacts — must be rejected by the durable-bundle gate, even though it
        # round-trips its own digest and claims sealed_by_role=validator. The
        # inline four-check version accepted exactly this forgery.
        from skills.vivarium.vivarium_v2.canonical import (
            canonical_bytes,
            domain_hash,
            durable_replace,
        )
        from skills.vivarium.vivarium_v2.evidence import require_durable_evidence_bundle

        store = self._store("fabricated-bundle-json")
        body = {"sealed_by_role": "validator", "totally": "fabricated"}
        digest = domain_hash("vivarium-evidence-bundle/v1", body)
        durable_replace(
            Path(store.root)
            / "artifacts"
            / "evidence-bundles"
            / f"{digest[7:]}.json",
            canonical_bytes(body),
        )
        with self.assertRaises(IntegrityError):
            require_durable_evidence_bundle(store, digest)

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

    def test_c1_commit_rejects_a_foreign_run_success_cut(self):
        # C-1 (increment 3a): the committed success cut must belong to the run
        # being committed. A genuine success cut minted for a *different* run
        # cannot be borrowed to certify this run's commit.
        store = self._store("foreign-cut", state="COMMITTING")
        evidence = _seal_commit_evidence(store, "commit-1")
        evidence["execution_evidence_cut_digest"] = persist_execution_evidence_cut(
            store, execution_evidence_cut(run_id="run-2")
        )
        with self.assertRaises(IntegrityError):
            store.prepare_commit(valid_commit_request(**evidence))

    def test_c1_commit_rejects_a_foreign_run_bundle(self):
        # C-1 (increment 3a): the sealed evidence bundle must belong to the run
        # being committed. A real bundle sealed for a *different* run cannot be
        # borrowed to certify this run's commit.
        store = self._store("foreign-bundle", state="COMMITTING")
        store.register_run("run-2", analysis_state="COLLECTING")
        foreign = _seal_commit_evidence(store, "commit-2", run_id="run-2")
        with self.assertRaises(IntegrityError):
            store.prepare_commit(valid_commit_request(run_id="run-1", **foreign))

    def test_c1_commit_rejects_a_non_passing_checker_review(self):
        # C-1 (increment 3b): the commit re-runs decide_gate over the sealed
        # checker reviews. A durable quorum whose checker review rejected cannot
        # be committed, no matter what checker_quorum_valid claims.
        store = self._store("reject-review", state="COMMITTING")
        evidence = _seal_commit_evidence(store, "commit-1", review_outcome="reject")
        with self.assertRaises(IntegrityError):
            store.prepare_commit(valid_commit_request(**evidence))

    def test_c1_commit_rejects_soft_isolated_checker(self):
        # C-1 (increment 3b): decide_gate rejects a checker without hard
        # capability isolation, so the commit must too.
        store = self._store("soft-isolation", state="COMMITTING")
        evidence = _seal_commit_evidence(store, "commit-1", isolation_level="soft")
        with self.assertRaises(IntegrityError):
            store.prepare_commit(valid_commit_request(**evidence))

    def test_c1_commit_rejects_a_fabricated_quorum_record(self):
        # C-1 (increment 3b): quorum_decision_digest must resolve to a real,
        # reconstructable quorum record that decide_gate passes — a canonical
        # self-hashing junk blob must not certify the quorum.
        from skills.vivarium.vivarium_v2.canonical import (
            canonical_bytes,
            domain_hash,
            durable_replace,
        )

        store = self._store("fabricated-quorum", state="COMMITTING")
        evidence = _seal_commit_evidence(store, "commit-1")
        junk = {"schema_version": "vivarium.quorum-record/v1", "totally": "fabricated"}
        digest = domain_hash("vivarium-quorum-record/v1", junk)
        durable_replace(
            store.root / "artifacts" / "quorum-records" / f"{digest[7:]}.json",
            canonical_bytes(junk),
        )
        evidence["quorum_decision_digest"] = digest
        with self.assertRaises(IntegrityError):
            store.prepare_commit(valid_commit_request(**evidence))

    def test_c1_commit_rejects_a_success_cut_decoupled_from_the_bundle(self):
        # C-1 (increment 3b follow-up): the re-classified success cut must be the
        # exact cut the evidence bundle sealed. Pairing a different — even real,
        # same-run, success — cut with the bundle is a decoupling forgery.
        store = self._store("decoupled-cut", state="COMMITTING")
        evidence = _seal_commit_evidence(store, "commit-1")
        evidence["execution_evidence_cut_digest"] = persist_execution_evidence_cut(
            store, execution_evidence_cut(run_id="run-1", stage_id="stage-other")
        )
        with self.assertRaises(IntegrityError):
            store.prepare_commit(valid_commit_request(**evidence))

    def test_c1_commit_rejects_a_quorum_record_with_extra_fields(self):
        # C-1 (increment 3b follow-up): the quorum record schema is closed like
        # the sibling evidence-bundle gate — unexpected top-level keys are
        # rejected, not silently ignored.
        import json

        from skills.vivarium.vivarium_v2.canonical import (
            canonical_bytes,
            domain_hash,
            durable_replace,
        )

        store = self._store("extra-quorum-fields", state="COMMITTING")
        evidence = _seal_commit_evidence(store, "commit-1")
        records = store.root / "artifacts" / "quorum-records"
        body = json.loads(
            (records / f"{evidence['quorum_decision_digest'][7:]}.json").read_bytes()
        )
        body["totally"] = "extra"
        digest = domain_hash("vivarium-quorum-record/v1", body)
        durable_replace(records / f"{digest[7:]}.json", canonical_bytes(body))
        evidence["quorum_decision_digest"] = digest
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
