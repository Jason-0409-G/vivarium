#!/bin/bash
# prep.sh — vivarium-prep bundled runner for the light/moderate steps.
#   stats     seqkit assembly QC (contigs, length, N50, GC, longest) -> tidy TSV (one row per genome)
#   annotate  Prokka gene + basic-function annotation of one genome -> GFF/FAA/FFN
# Assembly (Flye), completeness (CheckM2), eggNOG and dbCAN are heavy/absent and are scaffolded by the SKILL.
# Runs in the bio_tools conda env. Never auto-installs anything.
set -eu

need() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: '$1' not on PATH. Activate bio_tools or install it (do NOT auto-install)." >&2; exit 1; }; }

SUB="${1:-}"
[ -n "$SUB" ] || { echo "ERROR: need a subcommand: stats | annotate" >&2; exit 1; }
shift

case "$SUB" in
  stats)
    GENOME=""; INDIR=""; OUT="genome_stats.tsv"
    while [ $# -gt 0 ]; do case "$1" in
      --genome) GENOME="$2"; shift 2;;
      --indir)  INDIR="$2";  shift 2;;
      --out)    OUT="$2";    shift 2;;
      *) echo "ERROR: unknown arg: $1" >&2; exit 2;;
    esac; done
    need seqkit
    OUTDIR="$(dirname "$OUT")"; [ -d "$OUTDIR" ] || { echo "ERROR: output dir does not exist: $OUTDIR" >&2; exit 1; }
    FILES=""
    if [ -n "$GENOME" ]; then
      [ -f "$GENOME" ] || { echo "ERROR: --genome not found: $GENOME" >&2; exit 1; }
      FILES="$GENOME"
    elif [ -n "$INDIR" ]; then
      [ -d "$INDIR" ] || { echo "ERROR: --indir not a directory: $INDIR" >&2; exit 1; }
      FILES=$(find "$INDIR" -maxdepth 1 \( -name "*.fna" -o -name "*.fa" -o -name "*.fasta" \) | sort)
      [ -n "$FILES" ] || { echo "ERROR: no FASTA genomes in $INDIR" >&2; exit 1; }
    else
      echo "ERROR: provide --genome <file> or --indir <dir>" >&2; exit 1
    fi
    # seqkit stats -a (all) -T (tab) gives: file format type num_seqs sum_len min_len avg_len max_len Q1 Q2 Q3 sum_gap N50 ... GC(%) ...
    # shellcheck disable=SC2086
    seqkit stats -a -T $FILES > "$OUT"
    NG=$(( $(wc -l < "$OUT") - 1 ))
    echo "=== vivarium-prep stats done ===" >&2
    echo "tool:    seqkit ($(seqkit version 2>&1 | head -1))" >&2
    echo "genomes: $NG -> $OUT  (columns incl. num_seqs, sum_len, N50, GC(%), max_len, sum_gap)" >&2
    ;;

  annotate)
    GENOME=""; OUT=""; PREFIX="genome"; CPUS=4
    while [ $# -gt 0 ]; do case "$1" in
      --genome) GENOME="$2"; shift 2;;
      --out)    OUT="$2";    shift 2;;
      --prefix) PREFIX="$2"; shift 2;;
      --cpus)   CPUS="$2";   shift 2;;
      *) echo "ERROR: unknown arg: $1" >&2; exit 2;;
    esac; done
    [ -f "$GENOME" ] || { echo "ERROR: --genome not found: $GENOME" >&2; exit 1; }
    [ -n "$OUT" ] || { echo "ERROR: --out <outdir> is required" >&2; exit 1; }
    need prokka
    # Prokka's shebang is `#!/usr/bin/env perl`; under `conda activate`, /usr/bin can shadow the env's
    # perl so its BioPerl is invisible ("Can't locate Bio/Root/Version.pm"). Put the conda env bin first
    # for the Prokka call so the env perl + BioPerl resolve.
    PPATH="${CONDA_PREFIX:+$CONDA_PREFIX/bin:}$PATH"
    echo "running Prokka on $GENOME (~1-3 min) ..." >&2
    if ! PATH="$PPATH" prokka --force --outdir "$OUT" --prefix "$PREFIX" --cpus "$CPUS" "$GENOME" >"$OUT.prokka.log" 2>&1; then
      tail -5 "$OUT.prokka.log" >&2 2>/dev/null || true; echo "ERROR: prokka failed (see $OUT.prokka.log)" >&2; exit 1
    fi
    NCDS=$(grep -c "^>" "$OUT/$PREFIX.faa" 2>/dev/null || echo "?")
    echo "=== vivarium-prep annotate done ===" >&2
    echo "tool:    prokka ($(PATH="$PPATH" prokka --version 2>&1 | head -1))" >&2
    echo "out:     $OUT/$PREFIX.{gff,faa,ffn,tsv}  ($NCDS CDS)  -> .faa feeds vivarium-compare, .gff feeds synteny" >&2
    ;;

  *) echo "ERROR: unknown subcommand '$SUB' (use stats | annotate)" >&2; exit 1;;
esac
