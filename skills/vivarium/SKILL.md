---
name: vivarium
description: >-
  Orchestrate a full local comparative-genomics workflow over a set of genomes: plan the analysis as a stage graph, run
  the steps in order through the vivarium sub-skills (prep, compare, phylo, search, report), track everything in a run
  manifest, and pause-and-resume at the heavy steps. Use whenever the user wants an end-to-end comparative-genomics
  analysis rather than a single step — "compare these genomes and make figures", "run the whole pipeline on this genome
  set", "characterize these strains", "build me a phylogeny and find the unique genes", "比较这些基因组并出图", "把这套
  基因组从头分析一遍", "跑完整比较基因组流程", "vivarium". For a single isolated step (just BLAST / just a heatmap / just
  ANI) defer to the specific sub-skill instead. Light steps run locally in bio_tools; heavy steps are scaffolded.
---

# vivarium — comparative-genomics workflow orchestrator

Plan and run a multi-step comparative-genomics analysis as a stage graph (DAG), keeping a single run manifest as the source of truth. Light stages run now; heavy stages (assembly, eggNOG/dbCAN, OrthoFinder, big trees, PAML) are scaffolded — you hand the user the command, they run it, you resume from the manifest.

This skill **coordinates**; the actual work lives in the sub-skills. Read the relevant sub-skill's SKILL.md before running its stage.

| Sub-skill | Does |
|---|---|
| `vivarium-prep` | assembly QC (stats, CheckM2), annotation (Prokka → eggNOG/dbCAN) |
| `vivarium-compare` | ANI/AAI, orthology (OrthoFinder), synteny (MUMmer) |
| `vivarium-phylo` | alignment → trim → tree (IQ-TREE), selection (PAML dN/dS) |
| `vivarium-search` | BLAST/DIAMOND/HMMER sequence search |
| `vivarium-report` | publication-grade figures + tables (Python/R) |

## Step 1 — read the goal, plan the DAG

Map the user's goal to a stage graph. Common goals (the bundled `orchestrate.py` knows these):

- **compare-genomes** → prep:stats → compare:ani → compare:aai → report:heatmap
- **phylogeny** → prep:annotate(per genome) → compare:orthology(single-copy core) → phylo:tree → report
- **selection** → (orthogroup of interest) → phylo:tree → phylo:dnds(scaffold)
- **full** → prep(stats+annotate) → compare(ani+aai+orthology+synteny) → phylo:tree → report

State the plan to the user before running, and note which stages are light (run now) vs heavy (scaffold).

## Step 2 — set up the run workspace + manifest

```bash
python3 <skill-dir>/scripts/orchestrate.py init --goal <goal> --indir <genomes_dir> --workdir <dir>
#   prints the planned stage table and writes <workdir>/vivarium_run_<goal>/run_manifest.json
#   (refuses to overwrite an existing run — use --note <tag> for a new run, or --force to back-up-and-replace)
python3 <skill-dir>/scripts/orchestrate.py status --manifest <run_manifest.json>   # show progress any time
```
The manifest records, per stage: the sub-skill, the action, status (`planned` → `done`/`scaffolded`/`failed`), inputs, outputs, the exact command, the tool version, and any QC gate. It is the single source of truth for the run **and** the methods section — every number traces back to it. **Write each finished stage back into it** so it stays the truth:
```bash
python3 <skill-dir>/scripts/orchestrate.py update --manifest <run_manifest.json> --stage <N> \
    --status done --command "<exact command>" --version "<tool version>" --outputs <files...>
```

## Step 3 — execute the DAG, stage by stage

For each stage in order:
1. Read the relevant sub-skill and run its bundled step (light) or generate its scaffold command (heavy).
2. Record the result into the manifest (command, version, outputs, status). For a light stage that's `done`; for a heavy stage hand the user the command and mark `scaffolded`.
3. **Pause at scaffolded stages**: stop, give the user the command, and resume from the manifest when they say it's finished (ingest the outputs, mark `done`, continue downstream).
4. Honor data flow: a stage reads its inputs from the prior stages' manifest outputs (e.g. compare:orthology consumes prep:annotate's `.faa`; report:heatmap consumes compare:ani's matrix).

Don't silently run a heavy stage because it's "next" — assembly, OrthoFinder, eggNOG, big trees and PAML can run for a long time; scaffolding keeps the user in control.

## Step 4 — close with the report + methods

Finish with `vivarium-report` for the figures and a methods paragraph built from the manifest (every tool + version + command). The story the figures tell must match what the numbers support — don't let the report overclaim past the analysis.

## House rules (shared across vivarium)

- **Never auto-install** tools or databases; surface what's missing and let the user decide.
- Don't `rm` run workspaces or intermediates; move to the project's `_deleted/` if cleanup is needed.
- Keep interpretation tied to evidence; a workflow that produces a figure has not proven a mechanism. n=1 is not a basin-scale claim.
