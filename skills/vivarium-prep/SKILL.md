---
name: vivarium-prep
description: >-
  Get genomes ready for comparative analysis: assess assembly quality (contigs, N50, GC, length, completeness), and
  annotate genes and function (Prokka, eggNOG, dbCAN/CAZy). Use whenever the user wants genome statistics or QC, to
  check how good an assembly is, to assemble long reads, to annotate a genome, to call genes, or to get COG/KEGG/CAZy
  function tables before comparing genomes. Triggers on phrases like "genome stats / QC", "what's the N50 / GC / contig
  count", "how good is this assembly", "annotate this genome", "run Prokka / eggNOG / dbCAN", "call genes", "assemble
  these reads", "基因组质控/统计", "N50/GC/contig 数", "组装质量怎么样", "注释这个基因组", "跑 Prokka/eggNOG/dbCAN",
  "CAZy/COG/KEGG 注释". Light QC runs locally in the bio_tools conda env; heavy steps (assembly, eggNOG, dbCAN) are
  scaffolded as ready-to-run commands. Part of the vivarium comparative-genomics skill set.
---

# vivarium-prep — assembly QC and annotation

Take raw reads or draft genomes to the state the rest of vivarium needs: a quality-assessed assembly and gene/function annotation. Fast QC runs now in `bio_tools`; slow steps (Flye assembly, eggNOG, dbCAN) are handed back as exact commands so they don't block the session.

## Step 1 — where are we in the pipeline?

```
reads --(assembly: Flye, heavy)--> contigs --(QC: stats + CheckM2)--> genome --(annotation: Prokka -> eggNOG/dbCAN)--> features
```
Most users arrive with a genome already and want **QC + annotation**. Start there unless they have raw reads.

## Step 2 — assembly QC (bundled, fast)

```bash
bash <skill-dir>/scripts/prep.sh stats --genome <genome.fna> --out genome_stats.tsv
#   or a whole folder:  --indir <genomes_dir>   (one row per genome -> feeds vivarium-report bars)
```
Reports per genome: contigs, total length, N50, GC%, longest contig, gaps. A closed bacterial genome is 1–few contigs with N50 ≈ genome size; hundreds of contigs / low N50 means a fragmented draft — say which, because it changes how much to trust downstream synteny and unique-gene calls.

**Completeness/contamination (CheckM2)** is the other half of QC but is *not* installed in this env, so scaffold it:
```bash
checkm2 predict --input <genomes_dir> --output-directory checkm2_out -x fna --threads <N>
```
Read `quality_report.tsv` → Completeness ≥ ~95% and Contamination ≤ ~5% is a sound MAG/isolate; flag anything below.

## Step 3 — assembly (Flye, heavy → scaffold)

Flye is not installed here and assembly is long-running; scaffold it rather than running:
```bash
flye --pacbio-hifi <reads.fq.gz> --out-dir flye_out --threads <N>      # HiFi; use --nano-raw / --nano-hq for ONT
```
Then QC the result with Step 2. (Match the read-type flag to the platform — HiFi vs ONT.)

## Step 4 — annotation

**Genes + basic function — Prokka (bundled, runnable, ~1–3 min/genome):**
```bash
bash <skill-dir>/scripts/prep.sh annotate --genome <genome.fna> --out <outdir> --prefix <name>
```
Produces `<name>.gff/.faa/.ffn/.tsv` — the `.faa` proteome feeds vivarium-compare (orthology/AAI) and the `.gff` feeds synteny gene tracks.

**Deeper function — eggNOG (COG/KEGG) and dbCAN (CAZy) — heavy → scaffold:**
```bash
emapper.py -i <proteome.faa> -o <name> --output_dir eggnog_out --cpu <N>          # COG/KEGG, needs the eggNOG DB
run_dbcan CAZyme_annotation --mode protein --input_raw_data <proteome.faa> --output_dir dbcan_out --db_dir <dbCAN_db> --methods diamond,hmm,dbCANsub --threads <N>   # CAZy (dbCAN v5.x CLI)
```
> **CAZy counting**: take a family as present only when ≥2 of dbCAN's tools (HMMER/DIAMOND/dbCAN_sub) agree — the genus-wide "cellulase absent" / family-count claims depend on this 2-tool consensus, so record which rule you used in the methods.

## Step 5 — interpret + provenance

- State assembly quality plainly (closed vs fragmented; completeness/contamination if CheckM2 was run) before anyone builds conclusions on it.
- Record tool + version + command for every step (Prokka/eggNOG/dbCAN versions) — the bundled script prints the QC/Prokka ones; carry the scaffolded ones into the methods.

## House rules (shared across vivarium)

- **Never auto-install** tools or databases; name what's missing (CheckM2, Flye, the eggNOG/dbCAN DBs) and let the user decide.
- Don't `rm` intermediates (Prokka/assembly dirs); move to the project's `_deleted/` if cleanup is needed.
- Report facts; an annotation count is a prediction — don't promote "has gene X" to "does function X" without the downstream evidence.
