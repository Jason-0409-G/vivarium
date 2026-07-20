import os
import shutil
import unittest

from skills.vivarium.vivarium_v2.pipeline import (
    cluster_script,
    plan_pipeline,
    probe_device,
    route_stage,
)
from skills.vivarium.vivarium_v2.v1_adapter import resolve_env

_ENV, _ = resolve_env()
_PATH = _ENV["PATH"]


class PipelinePlanTests(unittest.TestCase):
    def test_probe_device_reports_capacity(self):
        device = probe_device()
        self.assertGreaterEqual(device["cores"], 1)
        self.assertGreaterEqual(device["ram_gb"], 0.0)
        self.assertIn("scheduler", device)  # None or a scheduler name

    def test_compare_genomes_plan_wires_the_dag_with_commands_and_outputs(self):
        plan = plan_pipeline(
            goal="compare-genomes",
            params={
                ("prep", "stats"): {"--indir": "genomes/", "--out": "genome_stats.tsv"},
                ("compare", "ani"): {"--indir": "genomes/", "--out": "ani_matrix.tsv"},
                ("compare", "aai"): {"--indir": "genomes/", "--out": "aai_matrix.tsv"},
                ("report", "heatmap"): {"--input": "ani_matrix.tsv", "--out": "fig_ani"},
            },
        )
        self.assertEqual([s.action for s in plan], ["stats", "ani", "aai", "heatmap"])
        heatmap = plan[-1]
        ani = plan[1]
        # the report stage depends on the ani stage and knows its output globs
        self.assertEqual(heatmap.depends_on, (ani.run_id,))
        self.assertEqual(heatmap.expected_outputs, ("fig_ani.svg", "fig_ani.pdf"))
        self.assertIn("ani_matrix.tsv", ani.command)
        # every stage carries a routing decision
        for stage in plan:
            self.assertIn(stage.route, ("local_inline", "cluster", "scaffold_local"))

    def test_phylogeny_plan_does_not_hard_fail_on_out_of_plan_inputs(self):
        plan = plan_pipeline(
            goal="phylogeny",
            params={
                ("prep", "annotate"): {"--genome": "g.fna", "--out": "annot", "--prefix": "gA"},
                ("phylo", "tree"): {"--input": "sc.faa", "--out": "tree"},
                ("report", "heatmap"): {"--input": "m.tsv", "--out": "fig"},
            },
        )
        actions = [s.action for s in plan]
        self.assertEqual(actions, ["annotate", "orthology", "tree", "heatmap"])
        # orthology depends on annotate; tree on orthology (declared upstream, present)
        ortho = plan[1]
        self.assertEqual(ortho.depends_on, (plan[0].run_id,))
        self.assertEqual(plan[2].depends_on, (ortho.run_id,))

    def test_scaffold_action_routes_to_cluster_when_a_scheduler_exists(self):
        no_sched = {"cores": 64, "ram_gb": 512, "scheduler": None, "path": _PATH}
        with_sched = dict(no_sched, scheduler="sbatch")
        # a heavy scaffold action always defers; where depends on the device
        self.assertEqual(route_stage("compare", "orthology", no_sched), "scaffold_local")
        self.assertEqual(route_stage("compare", "orthology", with_sched), "cluster")

    def test_inline_action_too_big_for_the_device_leaves_local(self):
        tiny = {"cores": 1, "ram_gb": 1.0, "scheduler": "sbatch", "path": _PATH}
        big = {"cores": 64, "ram_gb": 512.0, "scheduler": None, "path": _PATH}
        # phylo:tree wants 8 GB; a 1 GB machine cannot run it locally
        self.assertEqual(route_stage("phylo", "tree", tiny), "cluster")
        if not shutil.which("mafft", path=_PATH):
            self.skipTest("phylo toolchain absent")
        # a big machine with the tools runs it locally
        self.assertEqual(route_stage("phylo", "tree", big), "local_inline")

    def test_cluster_script_is_submittable(self):
        device = {"scheduler": "sbatch", "cores": 8, "ram_gb": 16, "path": _PATH}
        plan = plan_pipeline(
            goal="phylogeny",
            params={("compare", "orthology"): {}},
            device=device,
        )
        ortho = next(s for s in plan if s.action == "orthology")
        script = cluster_script(ortho, device)
        self.assertIn("#SBATCH", script)
        self.assertIn("--mem=16G", script)
        self.assertIn(ortho.command, script)


if __name__ == "__main__":
    unittest.main()
