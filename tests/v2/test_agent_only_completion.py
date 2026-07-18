import tempfile
import unittest
from pathlib import Path

from skills.vivarium.vivarium_v2.errors import IntegrityError
from skills.vivarium.vivarium_v2.execution import complete_agent_only
from skills.vivarium.vivarium_v2.project import ProjectStore
from tests.v2.support import (
    FrozenClock,
    agent_only_evidence,
    agent_only_intent,
    valid_commit_request,
)


class AgentOnlyCompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _store(self, name):
        store = ProjectStore.init(
            self.root / name, FrozenClock("2026-07-18T00:00:00Z")
        )
        store.register_run("run-1", analysis_state="MAKING")
        return store

    def test_closed_agent_only_completion_builds_one_durable_proof(self):
        store = self._store("success")
        intent = agent_only_intent()
        evidence = agent_only_evidence(store)
        first = complete_agent_only(store, intent, evidence)
        roots = []
        for _ in range(100):
            recovered = complete_agent_only(store, intent, evidence)
            roots.append(store.capture()[1][0].run_local_state_root)
            self.assertEqual(recovered.proof, first.proof)

        self.assertEqual(first.classification.outcome, "success")
        self.assertIsNotNone(first.proof)
        self.assertEqual(len(set(roots)), 1)
        self.assertEqual(store.recover().external_invocations, 0)
        types = store.business_event_types()
        self.assertEqual(types.count("COMPLETION_PROOF_RECORDED"), 1)
        self.assertFalse(
            {"LOCAL_EXECUTION_INTENT", "SUBMIT_CALL_STARTED", "EXTERNAL_CALL_STARTED"}
            & set(types)
        )

    def test_external_capability_is_durable_non_success_and_cannot_commit(self):
        for index, field in enumerate(("requested_capabilities", "observed_capabilities")):
            for capability in ("process", "network", "broker", "scheduler"):
                with self.subTest(field=field, capability=capability):
                    store = self._store(f"external-{index}-{capability}")
                    evidence = agent_only_evidence(store, **{field: (capability,)})
                    result = complete_agent_only(store, agent_only_intent(), evidence)
                    self.assertNotEqual(result.classification.outcome, "success")
                    self.assertIsNone(result.proof)
                    self.assertEqual(store.recover().external_invocations, 0)
                    self.assertNotIn(
                        "COMPLETION_PROOF_RECORDED", store.business_event_types()
                    )
                    with self.assertRaises(IntegrityError):
                        store.prepare_commit(valid_commit_request())
                    self.assertNotIn("STAGE_COMMITTED", store.business_event_types())

    def test_missing_agent_closure_is_never_success(self):
        cases = (
            {"maker_terminal_success": False},
            {"child_count": 1},
            {"capability_revocation_receipt_digest": ""},
            {"sealed_output_bundle_digest": ""},
            {"output_quiescence_manifest_digest": ""},
        )
        for index, overrides in enumerate(cases):
            with self.subTest(overrides=overrides):
                store = self._store(f"closure-{index}")
                result = complete_agent_only(
                    store, agent_only_intent(), agent_only_evidence(store, **overrides)
                )
                self.assertNotEqual(result.classification.outcome, "success")
                self.assertIsNone(result.proof)
                self.assertEqual(store.recover().external_invocations, 0)

    def test_capability_variants_and_unresolved_authority_objects_never_succeed(self):
        for index, capability in enumerate(("process_spawn", "network_access")):
            with self.subTest(capability=capability):
                store = self._store(f"capability-variant-{index}")
                result = complete_agent_only(
                    store,
                    agent_only_intent(),
                    agent_only_evidence(store, requested_capabilities=(capability,)),
                )
                self.assertNotEqual(result.classification.outcome, "success")
                self.assertIsNone(result.proof)
        store = self._store("unresolved-authority")
        result = complete_agent_only(
            store, agent_only_intent(), agent_only_evidence()
        )
        self.assertNotEqual(result.classification.outcome, "success")
        self.assertIsNone(result.proof)


if __name__ == "__main__":
    unittest.main()
