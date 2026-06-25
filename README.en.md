# vivarium

> **English** ｜ [中文](README.md)
>
> A Claude Code skill set for local comparative genomics.

## Overview

**vivarium** is a Claude Code skill set for conducting comparative-genomics analyses locally. Given a set of genome assemblies and an analysis goal, it plans the analysis as a stage graph, executes the lightweight steps in a `bio_tools` conda environment, and returns publication-grade figures and tables together with methods-ready provenance. The skill set adopts a **hybrid-execution** model: lightweight analyses (assembly QC, ANI/AAI, alignment-to-tree, sequence search, plotting) are run immediately, whereas computationally intensive or long-running stages (de novo assembly, eggNOG/dbCAN functional annotation, OrthoFinder orthology, large phylogenies, PAML selection tests) are emitted as ready-to-run commands for the user to execute, with their outputs ingested and interpreted on return.

vivarium is the analytical counterpart of the manuscript-preparation skill set [`scriptorium`](https://github.com/Jason-0409-G/scriptorium) (research-to-paper): scriptorium converts research into manuscripts; vivarium converts genomes into results.

## Skills

| Skill | Function | Local / scaffolded |
|---|---|---|
| **`vivarium`** | Umbrella orchestrator: goal → analysis DAG → sub-skill chaining → `run_manifest` tracking → pause/resume at heavy stages | coordinates |
| **`vivarium-prep`** | Assembly QC (contigs / N50 / GC / completeness); annotation (Prokka → eggNOG / dbCAN) | `stats` local; assembly / eggNOG / dbCAN scaffolded |
| **`vivarium-compare`** | Genome relatedness (ANI/AAI via FastANI/EzAAI); orthology (OrthoFinder); synteny (MUMmer) | ANI / AAI / synteny local; OrthoFinder scaffolded |
| **`vivarium-phylo`** | Align → trim → infer tree (MAFFT / trimAl / IQ-TREE); selection (PAML dN/dS) | `tree` local; PAML scaffolded |
| **`vivarium-search`** | Sequence-similarity search (BLAST / DIAMOND / HMMER) | local |
| **`vivarium-report`** | Publication-grade figures and tables (Python matplotlib / R ggplot2); export to SVG + PDF + TIFF at 600 dpi | local |

Each skill is independently triggerable; the umbrella `vivarium` composes them into an end-to-end pipeline.

## Benchmark (with-skill vs. no-skill baseline)

Four representative tasks (search / compare / phylogeny / report) were evaluated under an identical prompt and an identical `bio_tools` environment, with the presence of the skill as the only manipulated variable. Tasks were executed by claude-opus-4-8 (general-purpose sub-agents), once per configuration (single-machine, single-run; directional evidence rather than a powered statistical claim). Full data and per-assertion evidence are in [`benchmark/benchmark.md`](benchmark/benchmark.md).

| Metric | With skill | No-skill baseline | Δ |
|---|---|---|---|
| **Assertion pass rate** | **100%** | 82% | **+18 pt** |
| **Wall-clock (mean)** | **72 s** | 97 s | **≈26% faster** |
| Output tokens (mean) | 54.4 k | 53.2 k | +2% (one-time SKILL.md read) |

| Task | Pass (skill) | Pass (baseline) | Where the skill differs |
|---|---|---|---|
| search · homologues of 3 query proteins | 5/5 | 4/5 | baseline left 8 BLAST-DB binaries in the deliverables directory; the skill builds the database in a temporary directory |
| compare · 4-genome ANI + same-species call | 4/4 | 4/4 | parity on correctness; the skill is ≈37% faster and returns a clean matrix with no residual logs |
| phylogeny · ML tree from 8 groEL sequences | 4/4 | 4/4 | parity; both correctly reported the tree as unresolvable (near-identical sequences), avoiding overstatement |
| report · publication-grade ANI heatmap | 4/4 | **2/4** | baseline exported a screen-resolution PNG with no 600 dpi TIFF; the skill consistently exports SVG + PDF + TIFF (600 dpi, LZW) |

**Interpretation.** The skill set matches a careful baseline on biological correctness but diverges where publishability and reproducibility are at stake: (i) every run records a `tool + version + command` provenance footer, which an unguided run logs inconsistently; (ii) "publication-grade" output is consistently editable SVG + PDF + 600 dpi TIFF in a restrained, Nature-style convention, whereas the baseline produced a screen-resolution raster; (iii) the deliverables directory contains only results, scratch databases being confined to temporary directories; and (iv) invoking hardened bundled scripts rather than re-deriving command-line flags reduces wall-clock time by ≈26%.

## Triggering accuracy

On a deliberately boundary-heavy routing set of 20 queries — including "render an *existing* tree" (→ report, not phylo), "ANI already computed, plot it" (→ report, not compare), whole-pipeline versus single-step requests, and four should-trigger-nothing negatives (writing methods, polishing an abstract, weather, summarising a PDF) — all six descriptions route correctly (**20/20 = 100%**). Each skill additionally ships `evals/trigger_evals.json` (67 should-/should-not-trigger queries in total), serving both as a triggering contract and as a regression guard; with an API key configured, these feed the official `skill-creator` optimiser directly via `run_loop.py --eval-set <file>`.

## Installation

**Option 1 · Plugin marketplace (recommended)**
```
/plugin marketplace add https://github.com/Jason-0409-G/vivarium.git
/plugin install vivarium@vivarium
/reload-plugins
```
> Use the full HTTPS URL to avoid clone failures when no SSH key is configured.

**Option 2 · Script (clone, then install locally)**
```bash
git clone https://github.com/Jason-0409-G/vivarium.git
cd vivarium
bash install.sh            # copies skills/ into ~/.claude/skills/
```

## Update

This plugin uses **semantic versioning** (the `version` field in `.claude-plugin/plugin.json`). **Users only receive an update when you bump that version**; what changed in each release is in [`CHANGELOG.md`](CHANGELOG.md).

**If installed from the marketplace**
```
/plugin marketplace update vivarium     # pull the latest catalog
/plugin update vivarium@vivarium        # install the new version
/reload-plugins                         # apply in this session (or restart)
```
You can also enable **auto-update** for the `vivarium` marketplace under `/plugin` → Marketplaces.

**If installed via the script**
```bash
cd vivarium   # the folder you cloned
git pull
bash install.sh
```

## Dependencies

Analysis tools must be available in a **`bio_tools` conda environment** (the skills never auto-install; missing tools are reported, not installed):
- QC / annotation: seqkit, Prokka, (CheckM2, Flye, eggNOG-mapper, dbCAN — optional / heavy)
- Comparison: FastANI, EzAAI, OrthoFinder, MUMmer4
- Phylogenetics: MAFFT, trimAl, IQ-TREE, FastTree, PAML (codeml), PAL2NAL
- Search: BLAST+, DIAMOND, HMMER
- Plotting: Python (pandas / matplotlib) or R (ggplot2 / svglite / ragg)

## Design principles

- **Hybrid execution.** Lightweight steps run immediately; heavy steps are emitted as commands for the user to run — no unattended long jobs.
- **No automatic installation.** Missing tools or databases are surfaced for the user to decide upon.
- **Provenance (software versions recorded at every step).** Each script prints a uniform footer `=== vivarium-… done === / tool: <name>(<version>) / command: <exact command>`; the six analysis scripts and both plotting back-ends (matplotlib / ggplot2, with their versions) are unified, so output is methods-ready.
- **Figures serve the science.** No overstatement; an n = 1 observation is not extrapolated.
- **Soft deletion.** No `rm`; files requiring removal are moved to `_deleted/`.
- **Robust under weaker, non-Claude models.** Every step is "run this exact command and read its output"; analytical logic lives entirely in bundled scripts (FastANI / IQ-TREE / BLAST … plus the unified provenance footer), so the model neither assembles flags nor orchestrates multi-step tool calls. The set therefore remains stable on a non-Claude backend (e.g. `deepseek-v4-pro[1m]`, sub-agents on `deepseek-v4-flash`).

## License

See `LICENSE` (MIT).
