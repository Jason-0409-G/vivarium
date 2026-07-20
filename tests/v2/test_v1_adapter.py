import shutil
import tempfile
import unittest
from pathlib import Path

from skills.vivarium.vivarium_v2.project import ProjectStore
from skills.vivarium.vivarium_v2.v1_adapter import (
    V1StepNeedsScaffold,
    missing_tools,
    run_v1_step,
    v1_step_argv,
)
from tests.v2.support import FrozenClock

REPO_ROOT = Path(__file__).resolve().parents[2]
GENOMES = REPO_ROOT / "tests" / "data" / "genomes"


class V1AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _store(self, name, run_id):
        store = ProjectStore.init(self.root / name, FrozenClock("2026-07-20T00:00:00Z"))
        store.register_run(run_id, analysis_state="EXECUTION_PENDING")
        return store

    def test_argv_assembly_for_a_bash_subskill(self):
        argv = v1_step_argv("compare", "ani", {"--indir": "/g", "--out": "ani_matrix.tsv"})
        self.assertEqual(argv[0], "bash")
        self.assertTrue(argv[1].endswith("vivarium-compare/scripts/compare.sh"))
        self.assertEqual(argv[2], "ani")
        self.assertIn("--indir", argv)
        self.assertIn("/g", argv)

    def test_heavy_action_defers_to_scaffold_with_the_exact_command(self):
        store = self._store("scaffold", "prep-run")
        with self.assertRaises(V1StepNeedsScaffold) as ctx:
            run_v1_step(
                store,
                run_id="prep-run",
                subskill="prep",
                action="annotate",
                flags={"--genome": "/g.fna", "--out": "annot"},
            )
        self.assertIn("prep.sh", " ".join(ctx.exception.command))
        self.assertIn("annotate", ctx.exception.command)

    @unittest.skipUnless(
        shutil.which("fastANI") and (GENOMES / "S_vesiculosa_M7.fna").is_file(),
        "fastANI or genome fixtures not present",
    )
    def test_compare_ani_runs_real_fastani_through_the_durable_engine(self):
        # A real V1 bioinformatics tool (FastANI all-vs-all over the real Shewanella
        # genomes) runs as an OS process through the durable engine and commits its
        # ANI matrix as a STAGE_COMMITTED object.
        self.assertEqual(missing_tools("compare", "ani"), [])
        store = self._store("ani", "compare-run")
        step = run_v1_step(
            store,
            run_id="compare-run",
            subskill="compare",
            action="ani",
            flags={"--indir": str(GENOMES), "--out": "ani_matrix.tsv"},
        )
        self.assertTrue(step.committed)
        self.assertEqual(step.validation_outcome, "pass")
        matrix = (
            store.root
            / "runs" / "compare-run" / "attempts" / "stage-1" / "attempt-1" / "workspace"
            / "ani_matrix.tsv"
        ).read_text(encoding="ascii")
        # a real square ANI matrix: the genomes as labels + 100.00 on the diagonal
        self.assertIn("S_vesiculosa_M7", matrix)
        self.assertIn("100.00", matrix)


if __name__ == "__main__":
    unittest.main()
