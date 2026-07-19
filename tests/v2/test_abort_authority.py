import tempfile
import unittest
from pathlib import Path

from skills.vivarium.vivarium_v2.reducers import reduce_run
from skills.vivarium.vivarium_v2.state import AnalysisState
from tests.v2.support import prepared_fixture


class AbortAuthorityInvalidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _local(self, store):
        return reduce_run(tuple(store._run_ledger("run-1").recover().events))

    def test_checker_abort_invalidates_stale_review_and_quorum_heads(self):
        # Aborting a prepared commit back to CHECK_PENDING must invalidate the
        # stale checker review + quorum heads so they cannot be replayed back to
        # COMMITTING without a fresh review (design 6.1: old report/review/quorum
        # are invalidated).
        store = prepared_fixture(self.root / "checker-abort")
        prepared = store._test_prepared_commit
        before = self._local(store)
        self.assertTrue(before.checker_review_heads)
        self.assertTrue(before.quorum_decision_heads)

        store.abort_commit(prepared, "CHECKER_REVIEW_OR_QUORUM_INVALID")

        after = self._local(store)
        self.assertEqual(after.analysis_state, AnalysisState.CHECK_PENDING)
        self.assertEqual(after.checker_review_heads, ())
        self.assertEqual(after.quorum_decision_heads, ())

    def test_validator_abort_invalidates_report_review_and_quorum_heads(self):
        store = prepared_fixture(self.root / "validator-abort")
        prepared = store._test_prepared_commit
        before = self._local(store)
        self.assertTrue(before.validator_report_heads)

        store.abort_commit(prepared, "VALIDATOR_REPORT_INVALID")

        after = self._local(store)
        self.assertEqual(after.analysis_state, AnalysisState.VALIDATING)
        self.assertEqual(after.validator_report_heads, ())
        self.assertEqual(after.checker_review_heads, ())
        self.assertEqual(after.quorum_decision_heads, ())


if __name__ == "__main__":
    unittest.main()
