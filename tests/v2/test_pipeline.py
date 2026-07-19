import sys
import tempfile
import unittest
from pathlib import Path

from skills.vivarium.vivarium_v2.errors import IntegrityError
from skills.vivarium.vivarium_v2.loop import perform_one_step, run_pipeline
from skills.vivarium.vivarium_v2.project import ProjectStore
from skills.vivarium.vivarium_v2.state import DependencyHead
from tests.v2.support import FrozenClock

REPO_ROOT = Path(__file__).resolve().parents[2]
GENOMES = REPO_ROOT / "tests" / "data" / "genomes"
GENOME_A = GENOMES / "S_vesiculosa_M7.fna"
GENOME_B = GENOMES / "S_frigidimarina.fna"
STATS_SCRIPT = REPO_ROOT / "skills" / "vivarium" / "scripts" / "steps" / "genome_stats.py"


@unittest.skipUnless(GENOME_A.is_file() and GENOME_B.is_file(), "genome fixtures not present")
class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _store(self, name):
        return ProjectStore.init(self.root / name, FrozenClock("2026-07-20T00:00:00Z"))

    def _stats(self, genome):
        return (sys.executable, str(STATS_SCRIPT), str(genome))

    def test_two_stage_dag_commits_with_a_real_dependency_edge(self):
        # A prep -> compare pipeline: each stage runs a real step and commits; the
        # compare stage declares a DAG edge to the prep stage's committed object,
        # and the edge is recorded on the compare commit.
        store = self._store("dag")
        results = run_pipeline(
            store,
            [
                {"run_id": "prep-run", "argv": self._stats(GENOME_A)},
                {
                    "run_id": "compare-run",
                    "argv": self._stats(GENOME_B),
                    "depends_on": ["prep-run"],
                },
            ],
        )
        self.assertTrue(all(step.committed for step in results))
        prep, compare = results
        # the compare commit records the DAG edge to prep's committed stage object
        edges = compare.stage_committed_event.payload["dependencies"]
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["object_id"], "stage:prep-run")
        self.assertEqual(
            edges[0]["object_head"], prep.stage_committed_event.payload["object_head"]
        )
        # both stages reached COMMITTED
        state = store.recover()
        states = {item.run_id: item.analysis_state.value for item in state.federated_states}
        self.assertEqual(states["prep-run"], "COMMITTED")
        self.assertEqual(states["compare-run"], "COMMITTED")

    def test_stale_dependency_fails_closed(self):
        # A stage that depends on a non-active/stale committed object cannot commit.
        store = self._store("stale")
        store.register_run("prep-run", analysis_state="EXECUTION_PENDING")
        prep = perform_one_step(store, run_id="prep-run", argv=self._stats(GENOME_A))
        self.assertTrue(prep.committed)
        store.register_run("compare-run", analysis_state="EXECUTION_PENDING")
        with self.assertRaises(IntegrityError):
            perform_one_step(
                store,
                run_id="compare-run",
                argv=self._stats(GENOME_B),
                dependencies=(
                    DependencyHead("work", "stage:prep-run", "sha256:" + "0" * 64),
                ),
            )


if __name__ == "__main__":
    unittest.main()
