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
        events_a, evidence_a, prepare_a = prepared_run("depends-A", (dependency_a,))
        events_b, evidence_b, prepare_b = prepared_run("depends-B", (dependency_b,))
        self.local_a = reduce_run(events_a)
        self.local_b = reduce_run(events_b)

        prefixes = genesis_prefixes()
        prefixes["truth"] = activate(
            prefixes["truth"], "truth", "FACT_ACTIVATED", 1, "fact-A", "A1"
        )
        prefixes["truth"] = activate(
            prefixes["truth"], "truth", "FACT_ACTIVATED", 2, "fact-B", "B1"
        )
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

    def slice_for(self, local, cut):
        validity = reduce_project_validity(cut)
        return reduce_run_validity(cut, validity, local)

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
