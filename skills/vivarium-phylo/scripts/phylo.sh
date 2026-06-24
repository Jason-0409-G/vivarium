#!/bin/bash
# phylo.sh — vivarium-phylo bundled runner.
#   tree   MAFFT -> trimAl -> IQ-TREE (or FastTree with --fast): homologous multi-FASTA -> ML tree
# PAML dN/dS selection is heavy/fiddly and is scaffolded by the SKILL, not run here.
# Runs in the bio_tools conda env. Never auto-installs anything.
set -eu

need() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: '$1' not on PATH. Activate bio_tools or install it (do NOT auto-install)." >&2; exit 1; }; }

SUB="${1:-}"
[ -n "$SUB" ] || { echo "ERROR: need a subcommand: tree" >&2; exit 1; }
shift

case "$SUB" in
  tree)
    INPUT=""; OUT=""; FAST=0; BB=1000; THREADS="AUTO"
    while [ $# -gt 0 ]; do case "$1" in
      --input)   INPUT="$2";   shift 2;;
      --out)     OUT="$2";     shift 2;;
      --fast)    FAST=1;       shift 1;;
      --bb)      BB="$2";      shift 2;;
      --threads) THREADS="$2"; shift 2;;
      *) echo "ERROR: unknown arg: $1" >&2; exit 2;;
    esac; done
    [ -f "$INPUT" ] || { echo "ERROR: --input not found: $INPUT" >&2; exit 1; }
    [ -n "$OUT" ]   || { echo "ERROR: --out <prefix> is required" >&2; exit 1; }
    OUTDIR="$(dirname "$OUT")"; [ -d "$OUTDIR" ] || { echo "ERROR: output dir does not exist: $OUTDIR" >&2; exit 1; }
    need mafft; need trimal
    NSEQ=$(grep -c '^>' "$INPUT" 2>/dev/null || true); [ -n "$NSEQ" ] || NSEQ=0
    [ "$NSEQ" -ge 4 ] || { echo "ERROR: a tree needs >=4 sequences (found $NSEQ). For 2-3, just align." >&2; exit 1; }

    echo "[1/3] MAFFT align ($NSEQ sequences) ..." >&2
    mafft --auto "$INPUT" > "$OUT.aln" 2>"$OUT.mafft.log" || { tail -3 "$OUT.mafft.log" >&2; echo "ERROR: mafft failed" >&2; exit 1; }
    echo "[2/3] trimAl (-automated1) ..." >&2
    trimal -in "$OUT.aln" -out "$OUT.trim.aln" -automated1 2>"$OUT.trimal.log" || { tail -3 "$OUT.trimal.log" >&2; echo "ERROR: trimal failed" >&2; exit 1; }
    # guard: if trimAl removed (almost) all columns, fall back to the untrimmed alignment
    TRIMLEN=$(awk '/^>/{if(s){print length(s); exit}} !/^>/{s=s $0}' "$OUT.trim.aln" 2>/dev/null || echo 0)
    TREEALN="$OUT.trim.aln"
    if [ -z "$TRIMLEN" ] || [ "$TRIMLEN" -lt 20 ]; then
      echo "WARNING: trimAl left only ${TRIMLEN:-0} columns; using the untrimmed alignment for the tree." >&2
      TREEALN="$OUT.aln"
    fi

    if [ "$FAST" -eq 1 ]; then
      need FastTree
      echo "[3/3] FastTree (LG) ..." >&2
      FastTree -lg "$TREEALN" > "$OUT.treefile" 2>"$OUT.fasttree.log" || { tail -3 "$OUT.fasttree.log" >&2; echo "ERROR: FastTree failed" >&2; exit 1; }
      TOOL="FastTree -lg"; VER="$(FastTree 2>&1 | grep -i version | head -1 || echo FastTree)"
    else
      need iqtree
      [ "$BB" -ge 1000 ] || { echo "ERROR: --bb must be >=1000 (IQ-TREE ultrafast-bootstrap minimum)" >&2; exit 1; }
      echo "[3/3] IQ-TREE (ModelFinder + $BB UFBoot + SH-aLRT) ..." >&2
      iqtree -s "$TREEALN" -m MFP -B "$BB" -alrt 1000 -T "$THREADS" --prefix "$OUT" -redo >"$OUT.iqtree.run.log" 2>&1 || { tail -5 "$OUT.iqtree.run.log" >&2; echo "ERROR: iqtree failed (see $OUT.iqtree.run.log)" >&2; exit 1; }
      TOOL="IQ-TREE -m MFP -B $BB -alrt 1000"; VER="$(iqtree --version 2>&1 | grep -i version | head -1 || echo IQ-TREE)"
      MODEL=$(grep -m1 "Best-fit model" "$OUT.iqtree" 2>/dev/null | sed 's/.*: //' || true)
      [ -n "${MODEL:-}" ] && echo "model:   $MODEL (ModelFinder)" >&2
    fi

    echo "=== vivarium-phylo tree done ===" >&2
    echo "tool:    $VER" >&2
    echo "command: mafft --auto -> trimal -automated1 -> $TOOL" >&2
    echo "out:     $OUT.aln  $OUT.trim.aln  $OUT.treefile" >&2
    ;;

  *) echo "ERROR: unknown subcommand '$SUB' (use tree)" >&2; exit 1;;
esac
