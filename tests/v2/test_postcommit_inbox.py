import tempfile
import unittest
from pathlib import Path

from skills.vivarium.vivarium_v2.project import INBOX_LIMIT
from tests.v2.support import prepared_fixture


class PostcommitInboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _committed(self, name):
        store = prepared_fixture(self.root / name)
        event = store.complete_commit(store._test_prepared_commit)
        return store, event

    def test_inbox_is_durable_before_recheck_and_recovery_is_idempotent(self):
        store, commit = self._committed("normal")
        receipt = store.inbox_observation("run-1", commit.payload["object_id"], b"late")
        self.assertEqual(receipt.analysis_state, "BLOCKED_POSTCOMMIT_INTAKE")
        roots = [store.recover().federated_state_root for _ in range(100)]
        self.assertEqual(len(set(roots)), 1)
        self.assertEqual(store.business_event_types().count("COMPLETION_RECHECK_OPENED"), 1)
        self.assertEqual(store.business_event_types().count("POSTCOMMIT_OBSERVATION_OPENED"), 1)
        self.assertEqual(store.recover().analysis_state, "COMPLETION_RECHECK_PENDING")

    def test_oversize_is_truncated_and_stays_escalated(self):
        store, commit = self._committed("oversize")
        receipt = store.inbox_observation(
            "run-1", commit.payload["object_id"], b"x" * (INBOX_LIMIT + 1)
        )
        self.assertTrue(receipt.oversize)
        state = store.recover()
        self.assertEqual(state.analysis_state, "ESCALATED")
        self.assertFalse(state.default_retrievable)
        self.assertNotIn("COMPLETION_RECHECK_OPENED", store.business_event_types())


if __name__ == "__main__":
    unittest.main()
