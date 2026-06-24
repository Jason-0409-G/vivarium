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

Hybrid execution (run light, scaffold heavy) · never auto-install · provenance (tool+version+command per step) · the figure serves the science (no overclaiming, n=1 is not basin-scale) · soft-delete (no `rm`).

## License

See `LICENSE` (MIT).
