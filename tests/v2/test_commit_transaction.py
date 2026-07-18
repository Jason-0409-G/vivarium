import tempfile
import unittest
from pathlib import Path

from skills.vivarium.vivarium_v2.errors import IntegrityError
from skills.vivarium.vivarium_v2.state import COMMIT_ABORT_REASON_TARGET
from tests.v2.support import (
    COMMIT_CRASH_POINTS,
    inject_once,
    prepared_fixture,
    valid_prepared_commit,
)


class CommitCrashTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_each_crash_window_converges_once(self):
        for point in COMMIT_CRASH_POINTS:
            with self.subTest(point=point):
                store = prepared_fixture(self.root / point)
                inject_once(store, point)
                roots = [store.recover().federated_state_root for _ in range(100)]
                self.assertEqual(len(set(roots)), 1)
                types = store.business_event_types()
                self.assertLessEqual(types.count("STAGE_COMMITTED"), 1)
                self.assertLessEqual(types.count("STAGE_COMMIT_ABORTED"), 1)
                self.assertFalse(
                    {"STAGE_COMMITTED", "STAGE_COMMIT_ABORTED"}.issubset(types)
                )

    def test_every_closed_abort_reason_is_exactly_once(self):
        for index, (reason, target) in enumerate(COMMIT_ABORT_REASON_TARGET.items()):
            with self.subTest(reason=reason):
                store = prepared_fixture(self.root / f"abort-{index}")
                event = store.abort_commit(store._test_prepared_commit, reason)
                self.assertEqual(event.payload["analysis_target"], target.value)
                self.assertEqual(
                    store.abort_commit(store._test_prepared_commit, reason), event
                )
                with self.assertRaises(IntegrityError):
                    store.complete_commit(store._test_prepared_commit)

    def test_branch_and_authority_cas_are_checked(self):
        store = prepared_fixture(self.root / "cas")
        forged = valid_prepared_commit(
            store, commit_tx_id="commit-forged", expected_generation=9
        )
        with self.assertRaises(IntegrityError):
            store.complete_commit(forged)


if __name__ == "__main__":
    unittest.main()
