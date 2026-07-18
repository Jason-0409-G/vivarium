import tempfile
import unittest
from pathlib import Path

from skills.vivarium.vivarium_v2.errors import IntegrityError
from skills.vivarium.vivarium_v2.events import ZERO_HASH
from tests.v2.support import prepared_fixture, valid_prepared_commit


class RollbackForkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_rollback_is_append_only_and_late_commit_fails_generation_cas(self):
        store = prepared_fixture(self.root / "rollback")
        first = store.complete_commit(store._test_prepared_commit)
        late = valid_prepared_commit(store, commit_tx_id="late")
        before = len(store._project_ledger("work").recover().events)
        rollback = store.rollback(
            "branch-1", ZERO_HASH, invalidated_roots=(first.payload["object_head"],)
        )
        self.assertEqual(rollback.event_type, "ROLLBACK_COMMITTED")
        self.assertGreater(len(store._project_ledger("work").recover().events), before)
        self.assertEqual(store.branch_head().generation, 2)
        self.assertEqual(store.recover().analysis_state, "STALE_BRANCH")
        self.assertFalse(store.recover().default_retrievable)
        with self.assertRaises(IntegrityError):
            store.complete_commit(late)

    def test_fork_preserves_parent_and_binds_spec_delta(self):
        store = prepared_fixture(self.root / "fork")
        store.complete_commit(store._test_prepared_commit)
        parent = store.branch_head()
        event = store.fork("branch-1", "branch-2", specification_delta={"memory": "96GB"})
        child = store.branch_head("branch-2")
        self.assertEqual(event.event_type, "BRANCH_FORKED")
        self.assertEqual(child.parent_branch_id, "branch-1")
        self.assertEqual(child.state_snapshot_id, parent.state_snapshot_id)
        self.assertEqual(store.branch_head("branch-1"), parent)
        with self.assertRaises(IntegrityError):
            store.fork("branch-1", "branch-2")


if __name__ == "__main__":
    unittest.main()
