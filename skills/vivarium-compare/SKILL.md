---
name: vivarium-compare
description: >-
  Compare a set of microbial genomes: genome relatedness (ANI/AAI), shared vs unique gene content (orthology /
  pangenome / core-accessory via OrthoFinder), and genome structure (synteny / rearrangements via MUMmer). Use whenever
  the user wants to know how similar two or more genomes are, whether two strains are the same species, which genes are
  shared or unique to a strain, build orthogroups or a pangenome, or align genomes to see synteny. Triggers on phrases
  like "compare these genomes", "ANI/AAI between", "are these the same species", "which genes are unique to strain X",
  "core and accessory genome", "run OrthoFinder", "pangenome", "synteny / genome alignment", "比较这些基因组", "算 ANI/AAI",
  "是不是同一个种", "哪些基因是 X 独有的", "核心/附属基因组", "共线性". Light steps (FastANI, MUMmer) run locally in the
  bio_tools conda env and produce tables ready for vivarium-report; the heavy step (OrthoFinder) is scaffolded as a
  ready-to-run command. Part of the vivarium comparative-genomics skill set.
---

# vivarium-compare — genome relatedness, gene content, and structure

Answer the three questions of comparative genomics — *how related?*, *what gene content do they share or not?*, *is the structure conserved?* — and return tables a reviewer can read, plus figures via vivarium-report. Light analyses run now in the `bio_tools` env; the one slow step (OrthoFinder) is handed back as an exact command rather than blocking the session.

## Step 1 — pick the comparison

| Question | Analysis | Tool | Weight |
|---|---|---|---|
| How similar are these genomes? Same species? | **ANI** (nucleotide identity) | FastANI | light → run (bundled) |
| Relatedness at the protein level (more sensitive, distant taxa) | **AAI** | EzAAI | light → run |
| What genes are shared vs unique? Core/accessory? Pangenome? | **orthology** | OrthoFinder | heavy → **scaffold** |
| Is gene order / structure conserved? Rearrangements? | **synteny** | MUMmer (nucmer) | moderate → run (bundled) |

ANI ≥ ~95% is the conventional same-species boundary (Jain et al. 2018) — state it, don't assume it.

## Step 2 — run the light steps (bundled `compare.sh`)

Call the script under this skill's directory by full path (Claude's cwd is the user's project).

**ANI, all-vs-all → a square matrix** (drop it straight into vivarium-report `heatmap`):
```bash
bash <skill-dir>/scripts/compare.sh ani --indir <genomes_dir> --out ani_matrix.tsv
#   or an explicit list:  --list genomes.txt   (one genome path per line)
```
The matrix has genome names (file stem) on both axes, ANI% in cells, 100 on the diagonal. FastANI does not report pairs below ~80% ANI; those cells are written as `NA` (the heatmap blanks them) — say so rather than implying zero similarity.

**AAI, all-vs-all → a square matrix** (protein-level, more sensitive for distant taxa; ~10-15 s/genome to extract proteomes):
```bash
bash <skill-dir>/scripts/compare.sh aai --indir <genomes_dir> --out aai_matrix.tsv   # or --list genomes.txt
```
Same matrix shape as ANI (feeds vivarium-report `heatmap`). `ani` also accepts `--frag` (FastANI fragment length, default 3000) and `--threads` (default 4) as power-user flags.

**Synteny, one genome pair → tidy coords** (for a dot/alignment plot):
```bash
bash <skill-dir>/scripts/compare.sh synteny --ref A.fna --query B.fna --out synteny_coords.tsv [--minlen 1000]
```
Output columns: `ref_start ref_end qry_start qry_end len_ref len_qry pct_id ref_contig qry_contig`. Reverse-strand blocks have `qry_start > qry_end`.

## Step 3 — scaffold the heavy step (OrthoFinder)

OrthoFinder needs **protein FASTAs** (one `.faa` per genome in a folder) and takes minutes-to-hours, so don't silently run it. Hand the user the exact command, the resource hint, and how to read the result:

```bash
# inputs: a folder with one <genome>.faa per genome
orthofinder -f <proteomes_dir> -t <threads> -og        # -og stops after orthogroups (faster) if no species tree needed
```
For a handful of small bacterial proteomes (≤ ~10 × ~4k genes) it finishes in tens of minutes — offer to run it in the background if the user wants to wait; for more/larger, scaffold and let them run it on a workstation/cluster. First verify it launches (`orthofinder -h`); some conda installs are missing a runtime dependency (e.g. numpy) and the env needs it added before the command will run — flag that, don't auto-install. Key outputs: `Orthogroups/Orthogroups.GeneCount.tsv` (orthogroup × genome counts → core/accessory) and `Orthogroups_UnassignedGenes.tsv`. Derive **core** (present in all), **accessory** (some), and **strain-unique** (one) sets from the GeneCount table.

> A "unique gene" count is only as good as its reference set — say which genomes it is unique *relative to*. Use OrthoFinder orthogroups, not reciprocal-best-hit BLAST, for a defensible pangenome.

## Step 4 — interpret, then visualize

- **ANI/AAI**: report the focal pair, the species-boundary call (with the 95% threshold cited), and the cluster structure. Hand the matrix to `vivarium-report heatmap --vmin/--vmax` so the meaningful range isn't washed out.
- **Orthology**: report core / accessory / unique counts and what's unique *relative to which genomes*; a category breakdown of the unique set is a job for the annotation (vivarium-prep) outputs, not invented here.
- **Synteny**: report conserved blocks vs rearrangements/inversions; don't over-read a few broken contigs as biology if the assembly is fragmented.

## Step 5 — provenance

Record tool + version + the exact command for each step (FastANI/MUMmer/OrthoFinder versions) so the numbers are methods-ready. The bundled script prints these.

## House rules (shared across vivarium)

- **Never auto-install** tools; name what's missing and let the user decide.
- Don't `rm` intermediates (nucmer `.delta`, OrthoFinder working dirs); move to the project's `_deleted/` if cleanup is needed.
- Report facts; keep the species call tied to the threshold, and don't extrapolate gene-content differences into function without the annotation evidence.
