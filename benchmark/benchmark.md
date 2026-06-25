# vivarium — skill benchmark (with-skill vs. no-skill baseline)

**Executor**: claude-opus-4-8 (general-purpose subagents)  
**Date**: 2026-06-24T15:45:52Z  
**Design**: 4 representative tasks (search / compare / phylo / report), 1 run each per configuration. Baseline = identical prompt and identical `bio_tools` environment, only the skill withheld.

## Summary

| Metric | With skill | No-skill baseline | Delta |
|---|---|---|---|
| **Assertion pass rate** | **100%** | 82% | **+0.18** |
| **Wall-clock (mean)** | **72s** | 97s | **-25.6s (~26% faster)** |
| Output tokens (mean) | 54381 | 53200 | +1181 (+2%) |

## Per-task breakdown

| Task | Pass (skill) | Pass (baseline) | Time (skill) | Time (base) | Where the skill wins |
|---|---|---|---|---|---|
| search · homolog search (3 query proteins) | 5/5 | 4/5 | 46s | 69s | baseline left 8 BLAST-DB binaries in the deliverables folder (skill builds DB in a temp dir) |
| compare · ANI matrix + same-species call (4 genomes) | 4/4 | 4/4 | 50s | 79s | tie on correctness; skill ~37% faster and returns a clean square matrix (no raw logs) |
| phylo · ML tree from 8 groEL proteins | 4/4 | 4/4 | 117s | 136s | tie; both correct and both honestly flagged the tree as unresolved (near-identical seqs) |
| report · publication ANI heatmap | 4/4 | 2/4 | 74s | 104s | baseline exported a screen-res PNG with no 600 dpi TIFF; skill emits SVG+PDF+TIFF(600dpi,LZW) |

## What the numbers say

- **Correctness parity, reproducibility edge.** On ANI and the tree an unguided model already gets the biology right, so the skill ties there — but it lands every result with a tool+version+command provenance footer (`=== vivarium-… done === / tool: … / command: …`), which a bare run records inconsistently.
- **Journal-ready output is where guidance pays off.** Asked for a "publication-quality" figure, the baseline produced a screen-resolution PNG; the skill always emits editable **SVG + PDF + TIFF at 600 dpi (LZW)** with restrained, Nature-style styling.
- **Output hygiene.** The bundled runners build scratch databases in temp dirs, so the deliverables folder holds only the answer — the baseline left BLAST-DB binaries and raw logs behind.
- **Faster.** Calling a hardened bundled script beats re-deriving flags and parsing raw `outfmt 6` from scratch — ~26% less wall-clock for ~2% more tokens (the one-time cost of reading SKILL.md).

*Single-run, single-machine: directional evidence of the skill's value, not a powered statistical claim. Reproduce with the prompts in each skill's `evals/evals.json` against `tests/data/`.*
