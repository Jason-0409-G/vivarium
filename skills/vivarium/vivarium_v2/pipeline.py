"""Device-aware pipeline planning for the V1-tools-on-V2-loop workflow.

Turns a comparative-genomics goal into an ordered, durable DAG of stages, and for
each stage decides -- from the user's actual machine (cores, RAM, installed tools,
whether a cluster scheduler is present) -- WHERE it should run:

  local_inline    tool present + fits this machine -> the loop runs it now
  cluster         too heavy / tool absent, but a scheduler (sbatch/qsub) exists
                  -> we emit a ready job script for the user to submit
  scaffold_local  too heavy / tool absent, no scheduler -> the user runs it
                  externally and ingests the outputs

The routing is a resource-aware heuristic, not a precise runtime predictor: it
keeps jobs that would not fit off the local machine and produces the exact command
(and cluster script) for the rest. Actual auto-submission + polling of a real
scheduler is Phase B; here we plan and generate.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .v1_adapter import (
    ACTIONS,
    action_outputs,
    missing_tools,
    resolve_env,
    v1_stage_workspace,
    v1_step_argv,
)

# Goal -> ordered (subskill, action) sequence (vivarium/SKILL.md goals).
GOALS: dict[str, list[tuple[str, str]]] = {
    "compare-genomes": [
        ("prep", "stats"), ("compare", "ani"), ("compare", "aai"), ("report", "heatmap"),
    ],
    "phylogeny": [
        ("prep", "annotate"), ("compare", "orthology"), ("phylo", "tree"), ("report", "heatmap"),
    ],
    "selection": [("phylo", "tree"), ("phylo", "selection")],
    "full": [
        ("prep", "stats"), ("prep", "annotate"),
        ("compare", "ani"), ("compare", "aai"), ("compare", "orthology"), ("compare", "synteny"),
        ("phylo", "tree"), ("report", "heatmap"),
    ],
}


def _total_ram_gb() -> float:
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        if pages > 0 and page_size > 0:
            return round(pages * page_size / 1e9, 1)
    except (ValueError, OSError, AttributeError):
        pass
    try:
        out = subprocess.run(
            ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, check=True
        )
        return round(int(out.stdout.strip()) / 1e9, 1)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def probe_device(*, env: Mapping[str, str] | None = None) -> dict:
    """Detect the machine's compute capacity + toolchain: cores, total RAM, which
    cluster scheduler (if any) is reachable, on the tool-resolving PATH."""
    if env is None:
        env, _ = resolve_env()
    path = env.get("PATH", os.environ.get("PATH", ""))
    scheduler = next(
        (s for s in ("sbatch", "qsub", "bsub") if shutil.which(s, path=path)), None
    )
    return {
        "cores": os.cpu_count() or 1,
        "ram_gb": _total_ram_gb(),
        "scheduler": scheduler,
        "path": path,
    }


def route_stage(subskill: str, action: str, device: Mapping) -> str:
    """Decide where a stage runs: 'local_inline' | 'cluster' | 'scaffold_local'."""
    spec = ACTIONS.get((subskill, action))
    if spec is None:
        raise KeyError(f"unknown V1 action: {subskill}:{action}")
    absent = missing_tools(subskill, action, path=device.get("path"))
    resource = spec.get("resource", {})
    fits_local = (
        device.get("ram_gb", 0) >= resource.get("ram_gb", 0)
        and device.get("cores", 1) >= 1
    )
    if spec["mode"] == "inline" and not absent and fits_local:
        return "local_inline"
    if device.get("scheduler"):
        return "cluster"
    return "scaffold_local"


def cluster_script(stage: "PlannedStage", device: Mapping, *, walltime: str = "08:00:00") -> str:
    """A ready-to-submit job script for a stage routed to a scheduler. Site-specific
    module loads / accounts are left as a clearly marked line for the user."""
    resource = ACTIONS[(stage.subskill, stage.action)].get("resource", {})
    cores = resource.get("cores", 1)
    ram_gb = resource.get("ram_gb", 4)
    scheduler = device.get("scheduler")
    if scheduler == "sbatch":
        header = (
            f"#!/bin/bash\n#SBATCH --job-name={stage.run_id}\n"
            f"#SBATCH --cpus-per-task={cores}\n#SBATCH --mem={ram_gb}G\n"
            f"#SBATCH --time={walltime}\n"
        )
    else:  # qsub / PBS-style
        header = (
            f"#!/bin/bash\n#PBS -N {stage.run_id}\n"
            f"#PBS -l select=1:ncpus={cores}:mem={ram_gb}gb\n"
            f"#PBS -l walltime={walltime}\n"
        )
    return (
        header
        + "# module load <the tool>   # configure for your cluster\n"
        + f"cd '{stage.workspace}' || exit 1\n"
        + stage.command
        + "\n"
    )


@dataclass(frozen=True)
class PlannedStage:
    run_id: str
    subskill: str
    action: str
    mode: str
    route: str
    command: str
    expected_outputs: tuple[str, ...]
    depends_on: tuple[str, ...]
    flags: dict = field(default_factory=dict)
    workspace: str = ""


def plan_pipeline(
    *,
    goal: str | None = None,
    stages: Sequence[tuple[str, str]] | None = None,
    params: Mapping[tuple[str, str], Mapping[str, object]] | None = None,
    device: Mapping | None = None,
    store=None,
) -> list[PlannedStage]:
    """Expand a goal (or an explicit stage list) into an ordered DAG. Each stage
    carries its exact command, expected output globs, DAG dependencies, and the
    routing decision for THIS device. Pass store to fill in each stage's workspace
    path (where a scaffold/cluster stage's outputs must land)."""
    params = params or {}
    env, interpreter = resolve_env()
    device = device or probe_device(env=env)
    if goal is not None:
        if goal not in GOALS:
            raise KeyError(f"unknown goal: {goal} (have {sorted(GOALS)})")
        sequence = GOALS[goal]
    elif stages is not None:
        sequence = list(stages)
    else:
        raise ValueError("plan_pipeline needs a goal or an explicit stages list")

    planned: list[PlannedStage] = []
    produced: dict[tuple[str, str], str] = {}
    prefix = goal or "pipeline"
    for index, (subskill, action) in enumerate(sequence):
        spec = ACTIONS.get((subskill, action))
        if spec is None:
            raise KeyError(f"unknown V1 action: {subskill}:{action}")
        flags = dict(params.get((subskill, action), {}))
        run_id = f"{prefix}-{index:02d}-{subskill}-{action}"
        # Wire a DAG edge to each declared upstream that this plan actually
        # produces. A declared upstream absent from the plan is not an error: the
        # same action serves several goals, and some inputs (genomes, a provided
        # alignment) come from outside the pipeline.
        upstream = spec.get("upstream", [])
        depends_on = tuple(produced[u] for u in upstream if u in produced)
        command = " ".join(v1_step_argv(subskill, action, flags, python=interpreter))
        outputs = tuple(action_outputs(subskill, action, flags))
        route = route_stage(subskill, action, device)
        workspace = ""
        if store is not None:
            workspace = str(v1_stage_workspace(store, run_id))
        planned.append(
            PlannedStage(
                run_id, subskill, action, spec["mode"], route, command, outputs,
                depends_on, flags, workspace,
            )
        )
        produced[(subskill, action)] = run_id
    return planned


__all__ = [
    "GOALS",
    "PlannedStage",
    "probe_device",
    "route_stage",
    "cluster_script",
    "plan_pipeline",
]
