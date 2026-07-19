import unittest

from skills.vivarium.vivarium_v2.errors import IntegrityError
from skills.vivarium.vivarium_v2.events import Event, ZERO_HASH
from skills.vivarium.vivarium_v2.reducers import (
    federate,
    reduce_project_cut,
    reduce_project_validity,
    reduce_run,
    reduce_run_validity,
)
from skills.vivarium.vivarium_v2.state import AnalysisState, ProjectPrefixes
from tests.v2.test_federated_recovery import (
    HASH_C,
    HASH_D,
    LEDGERS,
    as_prefixes,
    commit_payload,
    event,
    federated,
    genesis_prefixes,
    prepared_run,
)


def activate(prefix, namespace, event_type, revision, object_id, object_head, dependencies=()):
    ledger_id = LEDGERS[namespace][0]
    activation = event(
        prefix,
        ledger_id,
        event_type,
        {
            "project_revision": revision,
            "object_type": "fact" if namespace == "truth" else namespace,
            "object_id": object_id,
            "object_head": object_head,
            "dependencies": list(dependencies),
        },
    )
    return (*prefix, activation)


class RunValidityTests(unittest.TestCase):
    def setUp(self):
        dependency_a = {"namespace": "truth", "object_id": "fact-A", "object_head": "A1"}
        dependency_b = {"namespace": "truth", "object_id": "fact-B", "object_head": "B1"}
        prefixes = genesis_prefixes()
        prefixes["truth"] = activate(
            prefixes["truth"], "truth", "FACT_ACTIVATED", 1, "fact-A", "A1"
        )
        prefixes["truth"] = activate(
            prefixes["truth"], "truth", "FACT_ACTIVATED", 2, "fact-B", "B1"
        )
        dependency_baseline = reduce_project_cut(as_prefixes(prefixes))
        events_a, evidence_a, prepare_a = prepared_run(
            "depends-A",
            (dependency_a,),
            project_revision=dependency_baseline.project_revision,
            project_semantic_cut_root=dependency_baseline.project_semantic_cut_root,
        )
        events_b, evidence_b, prepare_b = prepared_run(
            "depends-B",
            (dependency_b,),
            project_revision=dependency_baseline.project_revision,
            project_semantic_cut_root=dependency_baseline.project_semantic_cut_root,
        )
        self.local_a = reduce_run(events_a)
        self.local_b = reduce_run(events_b)
        commit_a = event(
            prefixes["work"],
            "project-work",
            "STAGE_COMMITTED",
            commit_payload(3, "depends-A", prepare_a, evidence_a),
        )
        prefixes["work"] += (commit_a,)
        commit_b = event(
            prefixes["work"],
            "project-work",
            "STAGE_COMMITTED",
            commit_payload(4, "depends-B", prepare_b, evidence_b),
        )
        prefixes["work"] += (commit_b,)
        self.cut_A1 = reduce_project_cut(as_prefixes(prefixes))

        prefixes["truth"] = activate(
            prefixes["truth"], "truth", "FACT_ACTIVATED", 5, "fact-A", "A2"
        )
        self.cut_A2 = reduce_project_cut(as_prefixes(prefixes))
        self.prefixes = prefixes

    def slice_for(self, local, cut):
        validity = reduce_project_validity(cut)
        return reduce_run_validity(cut, validity, local)

    def _policy_lock(self, decision_prefix, revision, object_id, object_head, policy_digest):
        locked = event(
            decision_prefix,
            LEDGERS["decision"][0],
            "POLICY_LOCKED",
            {
                "project_revision": revision,
                "object_type": "decision",
                "object_id": object_id,
                "object_head": object_head,
                "dependencies": [],
                "locked_policy_digest": policy_digest,
            },
        )
        return (*decision_prefix, locked)

    def test_unrelated_policy_lock_does_not_stale_independent_run(self):
        # M-3: locking a new, unrelated policy must not stale a run whose frozen
        # dependency closure does not include that policy object — only runs that
        # actually depend on the changed policy stale (design 1276/2399). The
        # dependency-blind global policy watermark staled every existing run.
        prefixes = dict(self.prefixes)
        prefixes["decision"] = self._policy_lock(
            prefixes["decision"], 6, "policy-unrelated", "PQ1", HASH_C
        )
        cut = reduce_project_cut(as_prefixes(prefixes))
        self.assertEqual(
            self.slice_for(self.local_b, cut).state, AnalysisState.COMMITTED
        )

    def test_unrelated_policy_lock_keeps_slice_root_byte_identical(self):
        # M-4: an unrelated policy lock must not move an independent run's
        # validity slice — the relevant-input root must be dependency-scoped and
        # must not embed the global locked policy digest (design 2399: unrelated
        # policy scope changes keep the run slice byte-identical).
        before = self.slice_for(self.local_b, self.cut_A2)
        prefixes = dict(self.prefixes)
        prefixes["decision"] = self._policy_lock(
            prefixes["decision"], 6, "policy-unrelated", "PQ1", HASH_C
        )
        after = self.slice_for(self.local_b, reduce_project_cut(as_prefixes(prefixes)))
        self.assertEqual(
            before.relevant_project_validity_input_root,
            after.relevant_project_validity_input_root,
        )
        self.assertEqual(before.run_validity_slice_root, after.run_validity_slice_root)

    def test_policy_dependent_run_stales_when_its_policy_superseded(self):
        # M-3 guard: a run that DOES depend on a policy object still stales when
        # that policy is superseded, through the dependency-closure path — so
        # dropping the global watermark does not under-stale.
        prefixes = genesis_prefixes()
        prefixes["decision"] = self._policy_lock(
            prefixes["decision"], 1, "policy-P", "P1", HASH_C
        )
        baseline = reduce_project_cut(as_prefixes(prefixes))
        events, evidence, prepare = prepared_run(
            "depends-P",
            ({"namespace": "decision", "object_id": "policy-P", "object_head": "P1"},),
            project_revision=baseline.project_revision,
            project_semantic_cut_root=baseline.project_semantic_cut_root,
        )
        local = reduce_run(events)
        commit = event(
            prefixes["work"],
            "project-work",
            "STAGE_COMMITTED",
            commit_payload(2, "depends-P", prepare, evidence),
        )
        prefixes["work"] += (commit,)
        committed_cut = reduce_project_cut(as_prefixes(prefixes))
        self.assertEqual(
            self.slice_for(local, committed_cut).state, AnalysisState.COMMITTED
        )
        prefixes["decision"] = self._policy_lock(
            prefixes["decision"], 3, "policy-P", "P2", HASH_D
        )
        superseded_cut = reduce_project_cut(as_prefixes(prefixes))
        self.assertEqual(
            self.slice_for(local, superseded_cut).state, AnalysisState.STALE_CONTEXT
        )

    def test_fact_change_stales_only_dependent_run(self):
        self.assertEqual(
            self.slice_for(self.local_a, self.cut_A2).state,
            AnalysisState.STALE_CONTEXT,
        )
        self.assertEqual(
            self.slice_for(self.local_b, self.cut_A2).state,
            AnalysisState.COMMITTED,
        )

    def test_relevant_slice_ignores_unrelated_project_change(self):
        before_b = self.slice_for(self.local_b, self.cut_A1)
        after_b = self.slice_for(self.local_b, self.cut_A2)

        self.assertEqual(before_b.relevant_project_validity_input_root, after_b.relevant_project_validity_input_root)
        self.assertEqual(before_b.run_validity_slice_root, after_b.run_validity_slice_root)
        self.assertNotEqual(self.cut_A1.project_semantic_cut_root, self.cut_A2.project_semantic_cut_root)
        self.assertNotEqual(
            federated(self.local_b, self.cut_A1).federated_state_root,
            federated(self.local_b, self.cut_A2).federated_state_root,
        )

    def _stale_recheck_terminal(self, terminal_kind, terminal_event_type):
        # STAGE_COMMITTED -> RECHECK_OPENED(own_stage) -> FACT_ACTIVATED(depended-on)
        # -> <terminal>: the depended-on fact changing mid-recheck flips the run
        # to STALE_CONTEXT; the terminal recheck event must not raise. Returns the
        # resulting slice state.
        prefixes = genesis_prefixes()
        prefixes["truth"] = activate(
            prefixes["truth"], "truth", "FACT_ACTIVATED", 1, "fact-A", "A1"
        )
        baseline = reduce_project_cut(as_prefixes(prefixes))
        events, evidence, prepare = prepared_run(
            "recheck-run",
            ({"namespace": "truth", "object_id": "fact-A", "object_head": "A1"},),
            project_revision=baseline.project_revision,
            project_semantic_cut_root=baseline.project_semantic_cut_root,
        )
        local = reduce_run(events)

        def recheck_payload(revision, kind):
            payload = commit_payload(revision, "recheck-run", prepare, evidence)
            payload.pop("commit_tx_id")
            payload["recheck_tx_id"] = "recheck-1"
            payload["object_head"] = f"stage-recheck-run-{kind}"
            payload["target_namespace"] = "work"
            payload["target_object_id"] = "stage-recheck-run"
            if kind == "opened":
                payload["recheck_scope"] = "own_stage"
            elif kind == "refreshed":
                payload["refresh_result"] = "own_success"
            elif kind == "deferred":
                payload["escalation_reason"] = "classification_cannot_finish_safely"
            return payload

        commit = event(
            prefixes["work"],
            "project-work",
            "STAGE_COMMITTED",
            commit_payload(2, "recheck-run", prepare, evidence),
        )
        prefixes["work"] += (commit,)
        opened = event(
            prefixes["work"],
            "project-work",
            "COMPLETION_RECHECK_OPENED",
            recheck_payload(3, "opened"),
        )
        prefixes["work"] += (opened,)
        prefixes["truth"] = activate(
            prefixes["truth"], "truth", "FACT_ACTIVATED", 4, "fact-A", "A2"
        )
        terminal = event(
            prefixes["work"],
            "project-work",
            terminal_event_type,
            recheck_payload(5, terminal_kind),
        )
        prefixes["work"] += (terminal,)
        cut = reduce_project_cut(as_prefixes(prefixes))
        return self.slice_for(local, cut).state

    def test_recheck_refresh_after_dependency_stale_yields_stale_slice(self):
        # M-5: a legal COMPLETION_PROOF_REFRESHED after a mid-recheck dependency
        # change must yield a STALE slice — staleness dominates the restore —
        # rather than raising and leaving an uncomputable run certificate on a
        # fully legal ledger (design 1070/1071/1276).
        self.assertEqual(
            self._stale_recheck_terminal("refreshed", "COMPLETION_PROOF_REFRESHED"),
            AnalysisState.STALE_CONTEXT,
        )

    def test_recheck_revoke_after_dependency_stale_yields_stale_slice(self):
        # M-5 follow-up: COMPLETION_PROOF_REVOKED during dependency staleness is
        # the same class — staleness dominates, the slice stays STALE, no raise.
        self.assertEqual(
            self._stale_recheck_terminal("revoked", "COMPLETION_PROOF_REVOKED"),
            AnalysisState.STALE_CONTEXT,
        )

    def test_recheck_defer_after_dependency_stale_keeps_stale_slice(self):
        # M-5 follow-up: COMPLETION_RECHECK_DEFERRED during dependency staleness
        # likewise keeps the STALE slice instead of raising.
        self.assertEqual(
            self._stale_recheck_terminal("deferred", "COMPLETION_RECHECK_DEFERRED"),
            AnalysisState.STALE_CONTEXT,
        )

    def test_all_five_genesis_anchors_are_required(self):
        prefixes = genesis_prefixes()
        prefixes["memory"] = ()

        with self.assertRaises(IntegrityError):
            reduce_project_cut(ProjectPrefixes(**prefixes))

    def test_cross_ledger_revision_gap_is_rejected(self):
        prefixes = genesis_prefixes()
        prefixes["truth"] = activate(
            prefixes["truth"], "truth", "FACT_ACTIVATED", 2, "fact-A", "A1"
        )

        with self.assertRaises(IntegrityError):
            reduce_project_cut(as_prefixes(prefixes))

    def test_run_validity_rejects_mismatched_project_validity(self):
        old_validity = reduce_project_validity(self.cut_A1)

        with self.assertRaises(IntegrityError):
            reduce_run_validity(self.cut_A2, old_validity, self.local_a)

    def test_prefix_chain_corruption_is_rejected(self):
        prefixes = genesis_prefixes()
        invalid = Event.build(
            ledger_id="project-truth",
            event_seq=2,
            event_id="truth-gap",
            event_type="FACT_ACTIVATED",
            tx_id="truth-gap-tx",
            prev_event_hash=prefixes["truth"][-1].event_hash,
            recorded_at="2026-07-18T00:00:02Z",
            effective_at="2026-07-18T00:00:02Z",
            payload={
                "project_revision": 1,
                "object_type": "fact",
                "object_id": "fact-A",
                "object_head": "A1",
                "dependencies": [],
            },
        )
        prefixes["truth"] += (invalid,)

        with self.assertRaises(IntegrityError):
            reduce_project_cut(as_prefixes(prefixes))


if __name__ == "__main__":
    unittest.main()
