"""Adapter: run a V1 vivarium sub-skill action as a durable V2 loop step.

The V1 comparative-genomics skill is a family of bundled scripts with one uniform
CLI shape -- `bash <script> <action> --flag value ...`, writing results to a
relative `--out` -- so a single data-driven adapter wires them all into the loop
rather than per-tool code. It only assembles the argv and hands it to
loop.perform_one_step; the durable engine (real process -> validated -> committed
stage) is untouched. A step whose external tools are not on PATH, or that is
declared heavy, is not run inline: it raises V1StepNeedsScaffold with the exact
command so the caller can hand it to the user, who runs it and returns the outputs
into the attempt workspace to be sealed (the scaffold/ingest path).
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .loop import StepCommit, perform_one_step
from .state import DependencyHead

_SKILLS = Path(__file__).resolve().parents[2]

V1_SCRIPTS = {
    "prep": _SKILLS / "vivarium-prep" / "scripts" / "prep.sh",
    "compare": _SKILLS / "vivarium-compare" / "scripts" / "compare.sh",
    "phylo": _SKILLS / "vivarium-phylo" / "scripts" / "phylo.sh",
    "search": _SKILLS / "vivarium-search" / "scripts" / "vivarium_search.sh",
}
REPORT_PY = _SKILLS / "vivarium-report" / "scripts" / "plot.py"
INGEST_SCRIPT = _SKILLS / "vivarium" / "scripts" / "steps" / "ingest_outputs.py"

# (subskill, action) -> declaration. mode 'inline' runs now if every tool is on
# PATH; 'scaffold' always defers (heavy / long-running). tools=[] means a pure
# script (no external bioinformatics binary).
ACTIONS: dict[tuple[str, str], dict] = {
    ("prep", "stats"): {"mode": "inline", "tools": ["seqkit"]},
    ("prep", "annotate"): {"mode": "scaffold", "tools": ["prokka"]},
    ("compare", "ani"): {"mode": "inline", "tools": ["fastANI"]},
    ("compare", "aai"): {"mode": "inline", "tools": ["EzAAI"]},
    ("compare", "synteny"): {"mode": "inline", "tools": ["nucmer", "show-coords"]},
    ("compare", "orthology"): {"mode": "scaffold", "tools": ["orthofinder"]},
    ("phylo", "tree_fast"): {"mode": "inline", "tools": ["mafft", "trimal", "FastTree"]},
    ("phylo", "tree"): {"mode": "inline", "tools": ["mafft", "trimal", "iqtree"]},
    ("phylo", "selection"): {"mode": "scaffold", "tools": ["pal2nal.pl", "codeml"]},
    ("search", "sequence_search"): {"mode": "inline", "tools": ["blastp", "makeblastdb"]},
    ("report", "heatmap"): {"mode": "inline", "tools": []},
    ("report", "bars"): {"mode": "inline", "tools": []},
}


@dataclass(frozen=True)
class V1StepNeedsScaffold(Exception):
    subskill: str
    action: str
    missing_tools: tuple[str, ...]
    command: tuple[str, ...]

    def __str__(self) -> str:
        why = (
            f"missing tools {list(self.missing_tools)}"
            if self.missing_tools
            else "declared heavy"
        )
        return (
            f"{self.subskill}:{self.action} must be scaffolded ({why}); "
            f"run it yourself and drop the outputs into the attempt workspace:\n  "
            + " ".join(self.command)
        )


def _flatten(flags: Mapping[str, object]) -> list[str]:
    out: list[str] = []
    for key, value in flags.items():
        out.append(key)
        if value is not None and value is not True:
            out.append(str(value))
    return out


def v1_step_argv(subskill: str, action: str, flags: Mapping[str, object]) -> list[str]:
    if subskill == "report":
        return [sys.executable, str(REPORT_PY), action, *_flatten(flags)]
    script = V1_SCRIPTS.get(subskill)
    if script is None:
        raise KeyError(f"unknown V1 sub-skill: {subskill}")
    return ["bash", str(script), action, *_flatten(flags)]


def missing_tools(subskill: str, action: str) -> list[str]:
    spec = ACTIONS.get((subskill, action))
    if spec is None:
        raise KeyError(f"unknown V1 action: {subskill}:{action}")
    return [tool for tool in spec["tools"] if shutil.which(tool) is None]


def run_v1_step(
    store,
    *,
    run_id: str,
    subskill: str,
    action: str,
    flags: Mapping[str, object],
    dependencies: Sequence[DependencyHead] = (),
    stage_id: str = "stage-1",
    attempt_id: str = "attempt-1",
) -> StepCommit:
    """Run one V1 sub-skill action as a durable committed stage. Raises
    V1StepNeedsScaffold (with the exact command) when the action is heavy or its
    tools are not installed, rather than running it inline."""
    spec = ACTIONS.get((subskill, action))
    if spec is None:
        raise KeyError(f"unknown V1 action: {subskill}:{action}")
    argv = v1_step_argv(subskill, action, flags)
    absent = missing_tools(subskill, action)
    if spec["mode"] == "scaffold" or absent:
        raise V1StepNeedsScaffold(subskill, action, tuple(absent), tuple(argv))
    return perform_one_step(
        store,
        run_id=run_id,
        argv=argv,
        dependencies=dependencies,
        stage_id=stage_id,
        attempt_id=attempt_id,
    )


def v1_stage_workspace(
    store, run_id: str, stage_id: str = "stage-1", attempt_id: str = "attempt-1"
) -> Path:
    """Where the user drops a scaffolded stage's outputs before ingesting them."""
    return (
        Path(store.root)
        / "runs" / run_id / "attempts" / stage_id / attempt_id / "workspace"
    )


def ingest_v1_step(
    store,
    *,
    run_id: str,
    expected_outputs: Sequence[str],
    dependencies: Sequence[DependencyHead] = (),
    stage_id: str = "stage-1",
    attempt_id: str = "attempt-1",
) -> StepCommit:
    """Commit a scaffolded stage. The user has already run the heavy/uninstalled
    tool and placed its outputs in v1_stage_workspace(...); this runs a
    deterministic ingest process that verifies those outputs are present and
    non-empty, then seals them as the stage's durable evidence."""
    if not expected_outputs:
        raise ValueError("ingest_v1_step requires the expected output names")
    argv = [sys.executable, str(INGEST_SCRIPT), *expected_outputs]
    return perform_one_step(
        store,
        run_id=run_id,
        argv=argv,
        dependencies=dependencies,
        stage_id=stage_id,
        attempt_id=attempt_id,
    )


__all__ = [
    "run_v1_step",
    "ingest_v1_step",
    "v1_stage_workspace",
    "v1_step_argv",
    "missing_tools",
    "V1StepNeedsScaffold",
    "ACTIONS",
]
