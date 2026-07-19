import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from skills.vivarium.vivarium_v2.cli import main

REPO_ROOT = Path(__file__).resolve().parents[2]
GENOME = REPO_ROOT / "tests" / "data" / "genomes" / "S_vesiculosa_M7.fna"


class CliRunStepTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    @unittest.skipUnless(GENOME.is_file(), "Shewanella genome fixture not present")
    def test_run_step_command_executes_a_real_genome_and_succeeds(self):
        with contextlib.redirect_stdout(io.StringIO()):
            code = main(
                [
                    "run-step",
                    "--root",
                    str(self.root / "store"),
                    "--run-id",
                    "run-1",
                    "--genome",
                    str(GENOME),
                ]
            )
        self.assertEqual(code, 0)
        stats = (
            self.root
            / "store"
            / "runs"
            / "run-1"
            / "attempts"
            / "stage-1"
            / "attempt-1"
            / "workspace"
            / "stats.tsv"
        )
        self.assertTrue(stats.is_file())
        self.assertIn("S_vesiculosa_M7.fna", stats.read_text(encoding="ascii"))
        # the durable execution evidence really landed on disk
        logs = self.root / "store" / "runs" / "run-1" / "attempts" / "stage-1" / "attempt-1" / "execution_logs"
        proofs = list(logs.glob("*.completion-proof.json"))
        self.assertEqual(len(proofs), 1)

    def test_unknown_command_fails_closed(self):
        self.assertNotEqual(main([]), 0)


if __name__ == "__main__":
    unittest.main()
