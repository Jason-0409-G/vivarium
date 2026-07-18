import tempfile
import unittest
from pathlib import Path

from skills.vivarium.vivarium_v2.errors import IntegrityError
from skills.vivarium.vivarium_v2.execution import (
    LOCAL_CRASH_POINTS,
    LocalExecutionBroker,
)
from skills.vivarium.vivarium_v2.project import ProjectStore
from tests.v2.support import FakeLocalHarness, FrozenClock, local_execution_intent


class LocalExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _fixture(self, name):
        store = ProjectStore.init(
            self.root / name, FrozenClock("2026-07-18T00:00:00Z")
        )
        store.register_run("run-1", analysis_state="EXECUTION_PENDING")
        return store, local_execution_intent(), FakeLocalHarness()

    def test_local_execution_is_at_most_once_across_100_recoveries(self):
        store, intent, harness = self._fixture("happy")
        broker = LocalExecutionBroker(store, harness)
        result = broker.run_or_recover(intent)
        roots = []
        for _ in range(100):
            recovered = broker.recover(intent.execution_intent_id)
            roots.append(store.capture()[1][0].run_local_state_root)
            self.assertEqual(recovered.proof, result.proof)

        self.assertEqual(harness.main_start_count, 1)
        self.assertEqual(len(set(roots)), 1)
        self.assertEqual(result.classification.outcome, "success")
        self.assertIsNotNone(result.proof)

    def test_every_crash_window_is_attach_only_and_never_duplicates_main(self):
        self.assertEqual(
            LOCAL_CRASH_POINTS,
            (
                "before_intent_fsync",
                "after_intent_before_wrapper_start",
                "after_receipt_before_attach",
                "after_child_spawn",
                "after_wrapper_exit_before_quiescence",
                "after_classification_before_proof",
            ),
        )
        for point in LOCAL_CRASH_POINTS:
            with self.subTest(point=point):
                store, intent, harness = self._fixture(point)
                crashing = LocalExecutionBroker(store, harness, crash_at=point)
                with self.assertRaises(RuntimeError):
                    crashing.run_or_recover(intent)
                clean = LocalExecutionBroker(store, harness)
                if point in {
                    "after_intent_before_wrapper_start",
                    "after_receipt_before_attach",
                }:
                    for _ in range(100):
                        with self.assertRaises(IntegrityError):
                            clean.recover(intent.execution_intent_id)
                else:
                    if point == "before_intent_fsync":
                        clean.run_or_recover(intent)
                    else:
                        clean.recover(intent.execution_intent_id)
                    for _ in range(100):
                        clean.recover(intent.execution_intent_id)
                self.assertLessEqual(harness.main_start_count, 1)

    def test_active_attempt_and_receipt_identity_are_fail_closed(self):
        store, intent, harness = self._fixture("identity")
        with self.assertRaises(IntegrityError):
            LocalExecutionBroker(store, harness).run_or_recover(
                local_execution_intent(attempt_id="attempt-2")
            )
        crashing = LocalExecutionBroker(store, harness, crash_at="after_child_spawn")
        with self.assertRaises(RuntimeError):
            crashing.run_or_recover(intent)
        harness.identity_valid = False
        clean = LocalExecutionBroker(store, harness)
        for _ in range(100):
            with self.assertRaises(IntegrityError):
                clean.recover(intent.execution_intent_id)
        self.assertEqual(harness.main_start_count, 1)


if __name__ == "__main__":
    unittest.main()
