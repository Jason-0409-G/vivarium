#!/usr/bin/env python3
"""vivarium orchestrator — plan a comparative-genomics DAG and track it in a run manifest.

  init    --goal <goal> [--indir <dir>] [--inputs f1 f2 ...] [--workdir <dir>] [--backend python|R] [--note <s>]
  status  --manifest <run_manifest.json>

This does NOT run analyses; it plans the stage graph, creates the run workspace, and writes/reads the manifest.
The vivarium sub-skills do the actual work and update the manifest as stages complete.
"""
import argparse
import glob
import json
import os
import shutil
import sys
from datetime import datetime

WEIGHT = {
    "light":    "run now",
    "moderate": "run now (minutes)",
    "heavy":    "scaffold (hand the command to the user, then resume)",
}

# Each stage: (sub-skill, action, weight)
DAGS = {
    "compare-genomes": [
        ("vivarium-prep",    "stats",      "light"),
        ("vivarium-compare", "ani",        "light"),
        ("vivarium-compare", "aai",        "light"),
        ("vivarium-report",  "heatmap",    "light"),
    ],
    "phylogeny": [
        ("vivarium-prep",    "annotate",   "moderate"),
        ("vivarium-compare", "orthology",  "heavy"),
        ("vivarium-phylo",   "tree",       "moderate"),
        ("vivarium-report",  "tree-figure","light"),
    ],
    "selection": [
        ("vivarium-phylo",   "tree",       "moderate"),
        ("vivarium-phylo",   "dnds",       "heavy"),
    ],
    "full": [
        ("vivarium-prep",    "stats",      "light"),
        ("vivarium-prep",    "annotate",   "moderate"),
        ("vivarium-compare", "ani",        "light"),
        ("vivarium-compare", "aai",        "light"),
        ("vivarium-compare", "orthology",  "heavy"),
        ("vivarium-compare", "synteny",    "moderate"),
        ("vivarium-phylo",   "tree",       "moderate"),
        ("vivarium-report",  "heatmap",    "light"),
    ],
}


def die(msg):
    sys.stderr.write(f"ERROR: {msg}\n")
    sys.exit(1)


def _print_stages(stages):
    print(f"\n{'#':>2}  {'sub-skill':<18} {'action':<12} {'weight':<9} status")
    for i, st in enumerate(stages, 1):
        print(f"{i:>2}  {st['skill']:<18} {st['action']:<12} {st['weight']:<9} "
              f"{st['status']}  [{WEIGHT[st['weight']]}]")


def cmd_init(a):
    if a.goal not in DAGS:
        die(f"unknown --goal '{a.goal}'. Choose one of: {', '.join(DAGS)}")
    inputs = []
    if a.indir:
        if not os.path.isdir(a.indir):
            die(f"--indir not a directory: {a.indir}")
        for ext in ("*.fna", "*.fa", "*.fasta"):
            inputs += sorted(glob.glob(os.path.join(a.indir, ext)))
        if not inputs:
            die(f"no genome FASTAs (.fna/.fa/.fasta) in {a.indir}")
    inputs += a.inputs or []
    # dedup by absolute path, preserving order (so --indir + --inputs overlap isn't double-counted)
    seen = set(); deduped = []
    for p in inputs:
        ap = os.path.abspath(p)
        if ap not in seen:
            seen.add(ap); deduped.append(p)
    inputs = deduped
    if not inputs:
        die("provide --indir <dir> or --inputs <files ...>")
    if not os.path.isdir(a.workdir):
        die(f"--workdir does not exist: {a.workdir}")
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"vivarium_run_{a.goal}" + (f"_{a.note}" if a.note else "")
    rundir = os.path.join(a.workdir, name)
    os.makedirs(rundir, exist_ok=True)
    stages = [{
        "skill": s, "action": act, "weight": w, "status": "planned",
        "inputs": [], "outputs": [], "command": "", "version": "", "qc": "",
    } for (s, act, w) in DAGS[a.goal]]
    manifest = {
        "goal": a.goal, "created": ts, "workdir": rundir, "backend": a.backend,
        "inputs": [{"path": p, "name": os.path.splitext(os.path.basename(p))[0]} for p in inputs],
        "stages": stages,
    }
    mpath = os.path.join(rundir, "run_manifest.json")
    if os.path.isfile(mpath):
        # the manifest is the run's source of truth and audit trail — never silently destroy it
        if not a.force:
            die(f"a run manifest already exists: {mpath}\n"
                f"       Refusing to overwrite it (it is the run's source of truth / audit trail).\n"
                f"       Start a separate run with --note <tag>, move the old run to the project's _deleted/, or pass --force.")
        bak = f"{mpath}.{ts}.bak"
        shutil.copy2(mpath, bak)
        print(f"--force: backed up existing manifest to {bak}")
    json.dump(manifest, open(mpath, "w"), indent=2)
    print(f"goal: {a.goal}   inputs: {len(inputs)} genomes   workspace: {rundir}")
    _print_stages(stages)
    print(f"\nmanifest: {mpath}")
    print("Next: run each light/moderate stage via its sub-skill now; hand heavy stages to the user as commands, then resume from the manifest.")


def cmd_status(a):
    if not os.path.isfile(a.manifest):
        die(f"manifest not found: {a.manifest}")
    try:
        m = json.load(open(a.manifest))
    except json.JSONDecodeError as e:
        die(f"manifest is not valid JSON: {e}")
    print(f"goal: {m['goal']}   created: {m['created']}   inputs: {len(m['inputs'])}   workspace: {m['workdir']}")
    _print_stages(m["stages"])
    done = sum(1 for s in m["stages"] if s["status"] == "done")
    print(f"\nprogress: {done}/{len(m['stages'])} stages done")


def cmd_update(a):
    if not os.path.isfile(a.manifest):
        die(f"manifest not found: {a.manifest}")
    try:
        m = json.load(open(a.manifest))
    except json.JSONDecodeError as e:
        die(f"manifest is not valid JSON: {e}")
    i = a.stage - 1
    if i < 0 or i >= len(m["stages"]):
        die(f"--stage {a.stage} out of range (1..{len(m['stages'])})")
    st = m["stages"][i]
    if a.status:               st["status"]  = a.status
    if a.command is not None:  st["command"] = a.command
    if a.version is not None:  st["version"] = a.version
    if a.outputs:              st["outputs"] = a.outputs
    if a.qc is not None:       st["qc"]      = a.qc
    json.dump(m, open(a.manifest, "w"), indent=2)
    print(f"updated stage {a.stage} ({st['skill']}:{st['action']}) -> status={st['status']}")


def main():
    p = argparse.ArgumentParser(description="vivarium orchestrator (plan + track a comparative-genomics DAG).")
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init", help="plan a DAG + create the run workspace/manifest")
    i.add_argument("--goal", required=True, help=f"one of: {', '.join(DAGS)}")
    i.add_argument("--indir", default=None)
    i.add_argument("--inputs", nargs="*", default=None)
    i.add_argument("--workdir", default=".")
    i.add_argument("--backend", default="python", choices=["python", "R"])
    i.add_argument("--note", default=None)
    i.add_argument("--force", action="store_true", help="overwrite an existing manifest (backs it up to .bak first)")
    i.set_defaults(func=cmd_init)
    s = sub.add_parser("status", help="show stage progress for a manifest")
    s.add_argument("--manifest", required=True)
    s.set_defaults(func=cmd_status)
    u = sub.add_parser("update", help="record a completed stage back into the manifest (programmatic write-back)")
    u.add_argument("--manifest", required=True)
    u.add_argument("--stage", type=int, required=True, help="1-based stage number")
    u.add_argument("--status", default=None, choices=["planned", "done", "scaffolded", "failed"])
    u.add_argument("--command", default=None)
    u.add_argument("--version", default=None)
    u.add_argument("--outputs", nargs="*", default=None)
    u.add_argument("--qc", default=None)
    u.set_defaults(func=cmd_update)
    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
