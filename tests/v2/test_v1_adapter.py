import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from skills.vivarium.vivarium_v2.project import ProjectStore
from skills.vivarium.vivarium_v2.state import DependencyHead
from skills.vivarium.vivarium_v2.v1_adapter import (
    V1StepNeedsScaffold,
    ingest_v1_step,
    missing_tools,
    resolve_env,
    run_v1_step,
    v1_stage_workspace,
    v1_step_argv,
)
from tests.v2.support import FrozenClock

REPO_ROOT = Path(__file__).resolve().parents[2]
GENOMES = REPO_ROOT / "tests" / "data" / "genomes"

_ENV, _PYTHON = resolve_env()
_HAS_PLOT_LIBS = (
    subprocess.run(
        [_PYTHON, "-c", "import pandas, matplotlib"], capture_output=True
    ).returncode
    == 0
)


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

    def test_absolute_out_is_rejected_to_prevent_silent_evidence_loss(self):
        store = self._store("badout", "compare-run")
        with self.assertRaises(ValueError):
            run_v1_step(
                store,
                run_id="compare-run",
                subskill="compare",
                action="ani",
                flags={"--indir": str(GENOMES), "--out": "/tmp/escapes_workspace.tsv"},
            )

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

    def test_scaffolded_stage_ingests_user_supplied_outputs(self):
        # A heavy stage (e.g. Prokka) is scaffolded: the user runs the tool and
        # drops its outputs into the attempt workspace; ingest_v1_step seals them
        # as the stage's durable committed evidence.
        store = self._store("ingest", "annotate-run")
        workspace = v1_stage_workspace(store, "annotate-run")
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "genome.gff").write_text("##gff-version 3\nseq1\tProkka\tCDS\t1\t9\n")
        (workspace / "genome.faa").write_text(">gene1\nMKVL\n")
        step = ingest_v1_step(
            store,
            run_id="annotate-run",
            expected_outputs=["genome.gff", "genome.faa"],
        )
        self.assertTrue(step.committed)
        self.assertEqual(step.validation_outcome, "pass")
        # the user-supplied outputs survive as the committed stage's sealed evidence
        self.assertTrue((workspace / "genome.gff").is_file())
        self.assertTrue((workspace / "genome.faa").is_file())

    def test_ingest_fails_closed_when_an_expected_output_is_missing(self):
        store = self._store("ingest-missing", "annotate-run")
        step = ingest_v1_step(
            store, run_id="annotate-run", expected_outputs=["never_produced.gff"]
        )
        self.assertFalse(step.committed)
        # a missing scaffold output does not poison the ledger
        state = store.recover()
        run = next(item for item in state.federated_states if item.run_id == "annotate-run")
        self.assertNotEqual(run.analysis_state.value, "COMMITTED")

    @unittest.skipUnless(
        _HAS_PLOT_LIBS
        and shutil.which("fastANI")
        and (GENOMES / "S_vesiculosa_M7.fna").is_file(),
        "fastANI / plot libs / genomes not all present",
    )
    def test_v1_pipeline_ani_then_heatmap_as_a_durable_dag(self):
        # The culmination: two real V1 tools cooperate as a durable DAG. compare:ani
        # (FastANI) commits an ANI matrix; report:heatmap (matplotlib) reads that
        # committed matrix, declares a DAG edge to the compare stage, and commits a
        # figure -- real inter-stage data flow, durable and validated end to end.
        store = ProjectStore.init(self.root / "pipe", FrozenClock("2026-07-20T00:00:00Z"))

        store.register_run("compare-run", analysis_state="EXECUTION_PENDING")
        ani = run_v1_step(
            store,
            run_id="compare-run",
            subskill="compare",
            action="ani",
            flags={"--indir": str(GENOMES), "--out": "ani_matrix.tsv"},
        )
        self.assertTrue(ani.committed)
        ani_matrix = v1_stage_workspace(store, "compare-run") / "ani_matrix.tsv"
        self.assertTrue(ani_matrix.is_file())

        store.register_run("report-run", analysis_state="EXECUTION_PENDING")
        edge = DependencyHead(
            "work", "stage:compare-run", ani.stage_committed_event.payload["object_head"]
        )
        report = run_v1_step(
            store,
            run_id="report-run",
            subskill="report",
            action="heatmap",
            flags={"--input": str(ani_matrix), "--out": "heatmap"},
            dependencies=(edge,),
        )
        self.assertTrue(report.committed)
        # the figure was produced from the upstream stage's real output
        figures = [
            p
            for p in v1_stage_workspace(store, "report-run").glob("heatmap.*")
            if p.stat().st_size > 0
        ]
        self.assertTrue(figures)
        # the report commit records the DAG edge to the compare stage
        edges = report.stage_committed_event.payload["dependencies"]
        self.assertEqual(edges[0]["object_id"], "stage:compare-run")

    @unittest.skipUnless(_HAS_PLOT_LIBS, "resolved python lacks pandas/matplotlib")
    def test_report_heatmap_runs_through_the_durable_engine_with_injected_env(self):
        # report:heatmap needs pandas/matplotlib, which live in the bio env, not
        # necessarily the harness's own python. The adapter injects the resolved
        # interpreter + PATH so plot.py runs; the figure commits as durable evidence.
        store = self._store("report", "report-run")
        workspace = v1_stage_workspace(store, "report-run")
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "ani_matrix.tsv").write_text(
            "genome\tA\tB\nA\t100.00\t95.20\nB\t95.20\t100.00\n", encoding="ascii"
        )
        step = run_v1_step(
            store,
            run_id="report-run",
            subskill="report",
            action="heatmap",
            flags={"--input": "ani_matrix.tsv", "--out": "heatmap"},
        )
        self.assertTrue(step.committed)
        figures = [p for p in workspace.glob("heatmap.*") if p.stat().st_size > 0]
        self.assertTrue(figures, "a real figure file must be produced and sealed")

    @unittest.skipUnless(
        not missing_tools("phylo", "tree", path=_ENV["PATH"]),
        "mafft/trimal/iqtree not on the resolved PATH",
    )
    def test_phylo_tree_runs_real_iqtree_through_the_durable_engine(self):
        # phylo:tree runs the real MAFFT -> trimAl -> IQ-TREE pipeline through the
        # durable engine and commits the ML tree; --seed keeps it reproducible.
        store = self._store("phylo", "phylo-run")
        homologs = self.root / "homologs.faa"
        homologs.write_text(
            ">a\nMKVLIAGDTRSHKPWQEFNYCLMDGATRSVWY\n"
            ">b\nMKVLIAGDTKSHKPWQEFNYCLMDGATRSVWY\n"
            ">c\nMKVLIAGDTRSHKPYQEFNYCLNDGATRSVWY\n"
            ">d\nMKVLTAGDTRSHKPWQEFNYCLMDGATRSVWY\n",
            encoding="ascii",
        )
        step = run_v1_step(
            store,
            run_id="phylo-run",
            subskill="phylo",
            action="tree",
            flags={
                "--input": str(homologs),
                "--out": "tree",
                "--bb": 1000,
                "--threads": 1,
                "--seed": 42,
            },
        )
        self.assertTrue(step.committed)
        workspace = (
            store.root / "runs" / "phylo-run" / "attempts" / "stage-1" / "attempt-1" / "workspace"
        )
        treefile = workspace / "tree.treefile"
        self.assertTrue(treefile.is_file())
        # a Newick tree with all four taxa
        newick = treefile.read_text(encoding="ascii")
        for taxon in ("a", "b", "c", "d"):
            self.assertIn(taxon, newick)

    @unittest.skipUnless(
        not missing_tools("search", "sequence_search", path=_ENV["PATH"]),
        "blast not on the resolved PATH",
    )
    def test_search_sequence_search_runs_real_blast_through_the_durable_engine(self):
        # search:sequence_search runs a real BLASTP through the durable engine and
        # commits its hit table. vivarium_search.sh takes flags directly (no
        # positional action), which the adapter handles.
        store = self._store("search", "search-run")
        seqs = self.root / "seqs"
        seqs.mkdir()
        protein = "MKVLIAGDTRSHKPWQEFNYCLMDGATRSVWYPQEKLHNFCMTAGDRSVWYP"
        (seqs / "query.faa").write_text(f">q1\n{protein}\n", encoding="ascii")
        (seqs / "target.faa").write_text(
            f">t1\n{protein}\n>decoy\n{'G' * 40}\n", encoding="ascii"
        )
        step = run_v1_step(
            store,
            run_id="search-run",
            subskill="search",
            action="sequence_search",
            flags={
                "--query": str(seqs / "query.faa"),
                "--target": str(seqs / "target.faa"),
                "--type": "prot",
                "--out": "hits.tsv",
            },
        )
        self.assertTrue(step.committed)
        hits = (
            store.root
            / "runs" / "search-run" / "attempts" / "stage-1" / "attempt-1" / "workspace"
            / "hits.tsv"
        ).read_text(encoding="ascii")
        self.assertIn("q1", hits)
        self.assertIn("t1", hits)

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
