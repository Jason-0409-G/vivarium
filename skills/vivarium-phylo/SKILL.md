---
name: vivarium-phylo
description: >-
  Build a phylogeny from sequences and test genes for selection. Use whenever the user wants to align sequences, build a
  gene or species tree, infer phylogeny, bootstrap a tree, or test for positive/purifying selection (dN/dS, ω) with
  PAML. Triggers on phrases like "build a tree", "phylogeny / phylogenetic tree of", "align these sequences", "MAFFT /
  trimAl / IQ-TREE", "bootstrap support", "is this gene under selection", "dN/dS / omega", "run PAML / codeml", "建树/系统发育树",
  "比对这些序列", "建一棵树", "自展支持", "这个基因受不受选择", "算 dN/dS", "跑 PAML". Alignment→trim→tree runs locally in
  the bio_tools conda env; large trees and PAML selection tests are scaffolded as ready-to-run commands. Part of the
  vivarium comparative-genomics skill set.
---

# vivarium-phylo — alignment, trees, and selection

Turn a set of homologous sequences into a defensible tree, and test genes for selection. The align→trim→tree path runs now in `bio_tools`; big trees (many taxa, partitioned models) and codon-based dN/dS tests (PAML) are handed back as exact commands.

## Step 1 — pick the analysis

| Goal | Path | Tool |
|---|---|---|
| Gene/species tree from homologous proteins or genes | align → trim → ML tree | MAFFT → trimAl → IQ-TREE (bundled) |
| Quick tree for a big alignment | align → trim → fast tree | MAFFT → trimAl → FastTree (`--fast`) |
| Is a gene under selection? (ω = dN/dS) | codon alignment → codeml | pal2nal + PAML (scaffold) |

## Step 2 — alignment → trim → tree (bundled, runnable)

```bash
bash <skill-dir>/scripts/phylo.sh tree --input <homologs.faa> --out <prefix> [--fast] [--bb 1000]
```
Pipeline: **MAFFT** (`--auto`) → **trimAl** (`-automated1`, removes poorly aligned columns) → **IQ-TREE** (ModelFinder `-m MFP`, `-B <bb>` ultrafast bootstrap) — or **FastTree** with `--fast` for a quick look. Outputs `<prefix>.aln`, `<prefix>.trim.aln`, `<prefix>.treefile`, and the IQ-TREE log/model. Input is a multi-FASTA of **homologous** sequences (one per taxon for a species tree; orthogroup members for a gene tree) — get them from a vivarium-compare orthogroup or a vivarium-search hit set, not a random mix.

For **many taxa / a concatenated supermatrix** (slow), scaffold IQ-TREE rather than blocking:
```bash
iqtree -s <supermatrix.aln> -p <partitions.nex> -m MFP -B 1000 -T AUTO --prefix big_tree
```

## Step 3 — selection (dN/dS, PAML) — scaffold

dN/dS needs a **codon** alignment (align proteins, then map back to CDS with PAL2NAL) and a PAML control file; codeml is slow and fiddly, so scaffold it:
```bash
# 1. protein alignment of the orthogroup -> codon alignment from the matching CDS
pal2nal.pl <prot.aln> <cds.fna> -output paml -nogap -codontable 11 > <codon.aln>   # -codontable 11 = bacterial code
# 2. codeml with a control file (.ctl). Minimal site-model keys (set these so codeml never prompts):
#      seqfile=<codon.aln>  treefile=<tree>  outfile=out.txt  seqtype=1  CodonFreq=2
#      model=0  NSsites=7 8  fix_omega=0  omega=1  icode=0  cleandata=1   # NSsites "7 8" = the M7-vs-M8 LRT
codeml <codeml.ctl>
```
Read ω: ω < 1 = purifying (most genes), ω ≈ 1 = neutral, ω > 1 = positive selection — and only believe ω > 1 if the LRT (e.g. M8 vs M7) is significant. Report ω per model with the LRT, not a bare number.

## Step 4 — interpret the tree

- Read **support**: from IQ-TREE the script reports two metrics — ultrafast bootstrap (UFBoot, 0–100, ≥ 95 = well-supported) **and** SH-aLRT (0–100, ≥ 80 = well-supported); a clade is solid when both pass. The `--fast`/FastTree path instead writes **SH-like local support on a 0–1 scale** (≈ ≥ 0.95 strong) — a different metric, so don't compare its 0–1 values against the 0–100 UFBoot rule. Call clades only where support holds, and say what's unresolved.
- Branch lengths are substitutions/site — a long bare branch can be a fast-evolving lineage or a misaligned/paralogous sequence; check the alignment before reading biology into it.
- A gene tree is not a species tree — note when topology could reflect HGT/incomplete lineage sorting rather than organismal history.

## Step 5 — provenance

Record the substitution model IQ-TREE chose, the bootstrap setting, and tool versions (MAFFT/trimAl/IQ-TREE; pal2nal/PAML for selection). The bundled script prints the tree ones; carry the PAML ones into the methods.

## House rules (shared across vivarium)

- **Never auto-install** tools; name what's missing and let the user decide.
- Don't `rm` intermediates (alignments, IQ-TREE files, codeml output); move to the project's `_deleted/` if cleanup is needed.
- Report facts; tie clade claims to support values, don't over-read unsupported branches, and keep ω > 1 claims behind a significant LRT.
