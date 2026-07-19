import sys
import tempfile
import unittest
from pathlib import Path

from skills.vivarium.vivarium_v2.loop import perform_one_step
from skills.vivarium.vivarium_v2.project import ProjectStore
from tests.v2.support import FrozenClock

REPO_ROOT = Path(__file__).resolve().parents[2]
GENOME = REPO_ROOT / "tests" / "data" / "genomes" / "S_vesiculosa_M7.fna"
STATS_SCRIPT = REPO_ROOT / "skills" / "vivarium" / "scripts" / "steps" / "genome_stats.py"


class LoopStepTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _store(self, name):
        store = ProjectStore.init(self.root / name, FrozenClock("2026-07-20T00:00:00Z"))
        store.register_run("run-1", analysis_state="EXECUTION_PENDING")
        return store

    @unittest.skipUnless(GENOME.is_file(), "Shewanella genome fixture not present")
    def test_perform_one_step_commits_a_real_genome_stage(self):
        # One durable loop iteration: a real genome-stats step executes as an OS
        # process, is validated + checked, and commits into the project ledger as
        # a STAGE_COMMITTED complete-cut — the durable equivalent of marking a
        # stage done in the V1 JSON manifest.
        store = self._store("commit")
        step = perform_one_step(
            store,
            run_id="run-1",
            argv=(sys.executable, str(STATS_SCRIPT), str(GENOME)),
        )

        self.assertTrue(step.committed)
        self.assertEqual(step.validation_outcome, "pass")
        self.assertIsNotNone(step.stage_committed_event)
        self.assertEqual(step.stage_committed_event.event_type, "STAGE_COMMITTED")
        self.assertEqual(step.result.classification.outcome, "success")

        # the run advanced to COMMITTED and the committed stage is the active object
        state = store.recover()
        run = next(item for item in state.federated_states if item.run_id == "run-1")
        self.assertEqual(run.analysis_state.value, "COMMITTED")

        # the real bioinformatics output is sealed and on disk
        stats = (
            store.root / "runs" / "run-1" / "attempts" / "stage-1" / "attempt-1" / "workspace" / "stats.tsv"
        )
        self.assertIn("S_vesiculosa_M7.fna", stats.read_text(encoding="ascii"))

    def test_idempotent_recommit_returns_same_stage_committed(self):
        store = self._store("idem")
        first = perform_one_step(
            store, run_id="run-1", argv=(sys.executable, str(STATS_SCRIPT), str(GENOME))
        )
        second = store.complete_commit(first.commit_tx_id)
        self.assertEqual(second.event_type, "STAGE_COMMITTED")
        self.assertEqual(
            second.payload["object_head"],
            first.stage_committed_event.payload["object_head"],
        )


if __name__ == "__main__":
    unittest.main()
