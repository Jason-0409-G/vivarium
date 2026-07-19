import sys
import tempfile
import unittest
from pathlib import Path

from skills.vivarium.vivarium_v2.project import ProjectStore
from skills.vivarium.vivarium_v2.steps import run_local_step
from tests.v2.support import FrozenClock

REPO_ROOT = Path(__file__).resolve().parents[2]
GENOME = REPO_ROOT / "tests" / "data" / "genomes" / "S_vesiculosa_M7.fna"
STATS_SCRIPT = REPO_ROOT / "skills" / "vivarium" / "scripts" / "steps" / "genome_stats.py"


class GenomeStatsStepTests(unittest.TestCase):
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
    def test_genome_stats_step_runs_a_real_genome_through_the_durable_engine(self):
        # A real bioinformatics step (zero-dependency genome stats on a real 4.8 MB
        # Shewanella genome) runs as an OS process through the broker + real harness
        # and produces durable, classified success evidence + a completion proof.
        store = self._store("genome")
        result = run_local_step(
            store,
            run_id="run-1",
            argv=(sys.executable, str(STATS_SCRIPT), str(GENOME)),
        )

        self.assertEqual(result.classification.outcome, "success")
        self.assertIsNotNone(result.proof)
        self.assertEqual(result.evidence_cut.exit_code, 0)

        workspace = (
            store.root / "runs" / "run-1" / "attempts" / "stage-1" / "attempt-1" / "workspace"
        )
        stats = (workspace / "stats.tsv").read_text(encoding="ascii")
        self.assertIn("S_vesiculosa_M7.fna", stats)
        # real computed statistics for this genome
        self.assertIn("4782877", stats)
        header, row = stats.strip().splitlines()
        self.assertEqual(header.split("\t")[0], "genome")
        self.assertEqual(row.split("\t")[1], "1")  # one contig


if __name__ == "__main__":
    unittest.main()
