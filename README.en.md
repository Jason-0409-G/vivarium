# vivarium

A Claude Code skill set for **local comparative-genomics analysis**. Give vivarium a set of genomes and a goal; it plans and runs the comparative-genomics workflow and produces publication-grade figures/tables plus methods-ready provenance. **Hybrid execution**: light analyses run locally in the `bio_tools` conda env; heavy/long steps (assembly, eggNOG/dbCAN, OrthoFinder, big trees, PAML) are scaffolded as ready-to-run commands rather than blocking the session.

Companion to the writing skill set [`scriptorium`](https://github.com/Jason-0409-G/scriptorium) (research-to-paper): scriptorium turns research into papers, vivarium turns genomes into results.

## Skills

| Skill | Does | Run / scaffold |
|---|---|---|
| **`vivarium`** | Umbrella orchestrator: goal → analysis DAG → chains the sub-skills → tracks a run manifest → pause/resume at heavy steps | coordinates |
| **`vivarium-prep`** | Assembly QC (contigs/N50/GC/completeness), annotation (Prokka → eggNOG/dbCAN) | stats runs; assembly/eggNOG/dbCAN scaffold |
| **`vivarium-compare`** | ANI/AAI (FastANI/EzAAI), orthology (OrthoFinder), synteny (MUMmer) | ANI/AAI/synteny run; OrthoFinder scaffold |
| **`vivarium-phylo`** | Align → trim → tree (MAFFT/trimAl/IQ-TREE), selection (PAML dN/dS) | tree runs; PAML scaffold |
| **`vivarium-search`** | Sequence search (BLAST/DIAMOND/HMMER) | runs |
| **`vivarium-report`** | Publication-grade figures + tables (Python matplotlib / R ggplot2), exporting SVG+PDF+TIFF 600 dpi | runs |

Each skill triggers on its own; the umbrella `vivarium` chains them end to end.

## Benchmark (with-skill vs. no-skill baseline, measured)

4 representative tasks (search / compare / phylo / report), **same prompt, same `bio_tools` env — the only variable is whether the skill is present**. Executor claude-opus-4-8 (general-purpose subagents), 1 run per cell (single-machine, directional evidence — not a powered statistical claim). Full data + per-assertion evidence in [`benchmark/benchmark.md`](benchmark/benchmark.md).

| Metric | With skill | No-skill baseline | Delta |
|---|---|---|---|
| **Assertion pass rate** | **100%** | 82% | **+18 pt** |
| **Wall-clock (mean)** | **72s** | 97s | **~26% faster** |
| Output tokens (mean) | 54.4k | 53.2k | +2% (one-time SKILL.md read) |

| Task | Pass (skill) | Pass (base) | Where the skill wins |
|---|---|---|---|
| search · homologs of 3 query proteins | 5/5 | 4/5 | baseline dumped 8 BLAST-DB binaries into the deliverables dir; skill builds the DB in a temp dir |
| compare · 4-genome ANI + same-species call | 4/4 | 4/4 | correctness tie; skill ~37% faster, clean matrix, no raw logs |
| phylo · ML tree from 8 groEL proteins | 4/4 | 4/4 | tie; both honestly flagged the tree as unresolved (near-identical seqs) |
| report · publication ANI heatmap | 4/4 | **2/4** | baseline exported a screen-res PNG, no 600 dpi TIFF; skill always emits SVG+PDF+TIFF(600dpi,LZW) |

**Strengths**: parity with a careful baseline on correctness, but a clear edge where "publishable / reproducible" matters — ① a tool+version+command provenance footer on every run, ② publication output always SVG+PDF+TIFF 600 dpi Nature-style (baseline gave a screen PNG), ③ a clean deliverables dir (scratch DBs in temp), ④ ~26% less wall-clock by calling a hardened bundled script instead of re-deriving flags.

## Triggering hit-rate

20 deliberately boundary-heavy routing queries — including "render an **existing** tree" → report (not phylo), "ANI already computed, plot it" → report (not compare), whole-pipeline vs. single-step, and 4 should-trigger-nothing negatives — route correctly across all 6 descriptions: **20/20 = 100%**. Each skill ships `evals/trigger_evals.json` (67 should-/should-not-trigger queries total) as both a triggering contract and a regression guard; with an API key configured it feeds the official `skill-creator` `run_loop.py --eval-set <file>` description optimizer directly.

## Install

**Option 1 · Plugin marketplace (recommended)**
```
/plugin marketplace add https://github.com/Jason-0409-G/vivarium.git
/plugin install vivarium@vivarium
/reload-plugins
```
> Use the full HTTPS URL to avoid clone failures when SSH keys aren't configured.

**Option 2 · Script (clone, then install locally)**
```bash
git clone https://github.com/Jason-0409-G/vivarium.git
cd vivarium
bash install.sh            # copies skills/ into ~/.claude/skills/
```

## Dependencies

Analysis tools must be in a **`bio_tools` conda env** (the skills never auto-install — they name what's missing): seqkit, Prokka, (CheckM2/Flye/eggNOG-mapper/dbCAN optional), FastANI, EzAAI, OrthoFinder, MUMmer4, MAFFT, trimAl, IQ-TREE, FastTree, PAML (codeml), PAL2NAL, BLAST+, DIAMOND, HMMER; and Python (pandas/matplotlib) or R (ggplot2/svglite/ragg) for figures.

## Design principles

Hybrid execution (run light, scaffold heavy) · never auto-install · **provenance (every run prints a `tool: <name>(<version>) / command: <exact command>` footer — all 6 analysis scripts and both plot backends, matplotlib/ggplot2 with their versions, are unified)** · the figure serves the science (no overclaiming, n=1 is not basin-scale) · soft-delete (no `rm`).

## License

See `LICENSE` (MIT).
