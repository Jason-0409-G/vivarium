"""P1 regression: recover() must NOT durably abort a transaction whose committed
STAGE_COMMITTED record is the torn last line of the work ledger.

Before the fix, project.recover() ran the COMMIT_INTENT resume loop before
detecting the work-ledger torn tail; _outcome() read work.recover().events (which
silently drops the quarantined torn record), misread the committed tx as
un-committed, and durably appended STAGE_COMMIT_ABORTED. Once the torn byte was
repaired (the record had been fully fsync'd), the ledger held BOTH STAGE_COMMITTED
and STAGE_COMMIT_ABORTED for one commit_tx_id -- violating "never both".

The fix: recover() fails closed (IntegrityError, no durable write) on a torn work
tail, consistent with capture(), so an abort is never recorded for a torn commit.
"""
import sys
import tempfile
import unittest
from pathlib import Path

from skills.vivarium.vivarium_v2.errors import IntegrityError
from skills.vivarium.vivarium_v2.loop import perform_one_step
from skills.vivarium.vivarium_v2.project import ProjectStore
from tests.v2.support import FrozenClock

REPO = Path(__file__).resolve().parents[2]
GENOME = REPO / "tests" / "data" / "genomes" / "S_vesiculosa_M7.fna"
STATS = REPO / "skills" / "vivarium" / "scripts" / "steps" / "genome_stats.py"


class RecoveryTornCommittedTailTests(unittest.TestCase):
    @unittest.skipUnless(GENOME.is_file() and STATS.is_file(), "fixtures absent")
    def test_torn_committed_tail_is_not_durably_aborted(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name) / "s"
        store = ProjectStore.init(root, FrozenClock("2026-07-20T00:00:00Z"))
        store.register_run("run-1", analysis_state="EXECUTION_PENDING")
        step = perform_one_step(
            store,
            run_id="run-1",
            stage_id="stage-1",
            attempt_id="attempt-1",
            argv=(sys.executable, str(STATS), str(GENOME)),
        )
        self.assertTrue(step.committed, "precondition: the stage must commit")

        work = root / "ledgers" / "work.jsonl"
        self.assertTrue(work.is_file(), "work ledger present")
        original = work.read_bytes()
        # Tear the last byte of the committed STAGE_COMMITTED record.
        work.write_bytes(original[:-1])

        reopened = ProjectStore(root, FrozenClock("2026-07-20T00:00:01Z"))
        # Recovery must fail closed on a torn work tail, NOT silently abort.
        with self.assertRaises(IntegrityError):
            reopened.recover()

        # And it must not have durably written an abort for the torn commit.
        run_events = (root / "runs" / "run-1" / "events.jsonl").read_text(encoding="ascii")
        self.assertNotIn(
            "STAGE_COMMIT_ABORTED", run_events,
            "recover() must not durably abort a transaction whose committed record was torn",
        )


if __name__ == "__main__":
    unittest.main()
