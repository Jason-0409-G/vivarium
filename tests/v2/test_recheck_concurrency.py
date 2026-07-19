import tempfile
import unittest
from pathlib import Path

from tests.v2.support import prepared_fixture


class RecheckConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _committed(self, name):
        store = prepared_fixture(self.root / name)
        commit = store.complete_commit(store._test_prepared_commit)
        return store, commit

    def test_two_owner_observations_do_not_poison_store(self):
        # Two independent late observations on the same committed object is a
        # normal concurrency case (design §7.4.2). It must not brick the store.
        store, commit = self._committed("two-obs")
        oid = commit.payload["object_id"]
        store.inbox_observation("run-1", oid, b"late-1")
        store.inbox_observation("run-1", oid, b"late-2")

        # recover() must not raise and must be byte-identical across repeats.
        roots = [store.recover().federated_state_root for _ in range(50)]
        self.assertEqual(len(set(roots)), 1)

        state = store.recover()
        self.assertEqual(state.analysis_state, "COMPLETION_RECHECK_PENDING")

        types = store.business_event_types()
        self.assertEqual(types.count("COMPLETION_RECHECK_OPENED"), 2)
        self.assertEqual(types.count("POSTCOMMIT_OBSERVATION_OPENED"), 2)

        # First recheck owns the suspension; the second is an additional blocker.
        scopes = [
            event.payload["recheck_scope"]
            for event in store._project_ledger("work").recover().events
            if event.event_type == "COMPLETION_RECHECK_OPENED"
        ]
        self.assertEqual(scopes, ["own_stage", "additional"])


if __name__ == "__main__":
    unittest.main()
