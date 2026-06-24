#!/bin/bash
# vivarium_search.sh — run a local sequence similarity search (BLAST/DIAMOND) and
# emit a tidy, named-column hit table + provenance. Part of the vivarium skill set.
#
# Usage:
#   bash vivarium_search.sh --query Q.fasta --target T.fasta --type prot|nucl \
#        [--tool auto|blastp|blastn|tblastn|blastx|diamond] [--evalue 1e-5] [--out hits.tsv]
#
# Runs in the bio_tools conda env. Never auto-installs anything.
# Note: the diamond path here is protein-vs-protein (blastp) only. For cross-type
# searches use --tool blastx (nucl query vs protein target) or tblastn (protein query vs nucl target).
set -eu

QUERY=""; TARGET=""; TYPE=""; TOOL="auto"; EVALUE="1e-5"; OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --query)  QUERY="$2";  shift 2;;
    --target) TARGET="$2"; shift 2;;
    --type)   TYPE="$2";   shift 2;;
    --tool)   TOOL="$2";   shift 2;;
    --evalue) EVALUE="$2"; shift 2;;
    --out)    OUT="$2";    shift 2;;
    *) echo "ERROR: unknown arg: $1" >&2; exit 2;;
  esac
done

[ -f "$QUERY" ]  || { echo "ERROR: query FASTA not found: $QUERY" >&2; exit 1; }
[ -f "$TARGET" ] || { echo "ERROR: target FASTA not found: $TARGET" >&2; exit 1; }
case "$TYPE" in prot|nucl) ;; *) echo "ERROR: --type must be 'prot' or 'nucl'" >&2; exit 1;; esac
[ -n "$OUT" ] || OUT="vivarium_search_hits.tsv"
OUTDIR="$(dirname "$OUT")"; [ -d "$OUTDIR" ] || { echo "ERROR: output directory does not exist: $OUTDIR" >&2; exit 1; }

COLS="qseqid sseqid pident length evalue bitscore qcovhsp"

# Sniff the target's residue alphabet so a wrong --type/--tool errors out loudly
# instead of silently producing a meaningless "0 hits".
TGT_ALPHA="$(head -2000 "$TARGET" | awk '/^>/{next}{seq=seq $0} END{
  n=length(seq); if(n==0){print "unknown"; exit}
  a=gsub(/[ACGTNUacgtnu]/,"",seq); if(a/n>0.9) print "nucl"; else print "prot"}')"

NSEQ=$(grep -c '^>' "$TARGET" 2>/dev/null || true); [ -n "$NSEQ" ] || NSEQ=0

if [ "$TOOL" = "auto" ]; then
  if [ "$TYPE" = "prot" ]; then
    if [ "$NSEQ" -gt 100000 ]; then TOOL="diamond"; else TOOL="blastp"; fi
  else
    TOOL="blastn"
  fi
fi

# diamond here is protein-vs-protein (blastp) only — refuse nucleotide cross-searches
if [ "$TOOL" = "diamond" ] && [ "$TYPE" != "prot" ]; then
  echo "ERROR: the diamond path is protein-vs-protein (blastp) only. Use '--tool blastx' (nucl query vs protein target) or '--tool tblastn' (protein query vs nucl target) instead." >&2
  exit 1
fi

case "$TOOL" in
  blastp)  DBTYPE=prot;;
  blastx)  DBTYPE=prot;;
  tblastn) DBTYPE=nucl;;
  blastn)  DBTYPE=nucl;;
  diamond) DBTYPE=prot;;
  *) echo "ERROR: unsupported --tool '$TOOL'" >&2; exit 1;;
esac

# If the target alphabet contradicts the DB we're about to build, the search would be
# meaningless — warn loudly rather than returning a confident wrong "0 hits".
if [ "$TGT_ALPHA" != "unknown" ] && [ "$TGT_ALPHA" != "$DBTYPE" ]; then
  echo "WARNING: target looks like '$TGT_ALPHA' but tool '$TOOL' needs a '$DBTYPE' database — results may be meaningless. Re-check --type/--tool." >&2
fi

need() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: '$1' not on PATH. Activate bio_tools or install it (do NOT auto-install)." >&2; exit 1; }; }

WORK="$(mktemp -d)"

if [ "$TOOL" = "diamond" ]; then
  need diamond
  diamond makedb --in "$TARGET" --db "$WORK/db" >/dev/null
  CMD="diamond blastp --sensitive -q $QUERY -d <db> -e $EVALUE --outfmt 6 $COLS -o $OUT"
  diamond blastp --sensitive -q "$QUERY" -d "$WORK/db" -e "$EVALUE" --outfmt 6 $COLS -o "$WORK/raw.tsv" >/dev/null
  VER="diamond $(diamond version 2>/dev/null | grep -oE '[0-9][0-9.]*' | head -1)"
else
  need makeblastdb; need "$TOOL"
  makeblastdb -in "$TARGET" -dbtype "$DBTYPE" -out "$WORK/db" >/dev/null
  CMD="$TOOL -query $QUERY -db <db> -evalue $EVALUE -outfmt \"6 $COLS\" -out $OUT"
  "$TOOL" -query "$QUERY" -db "$WORK/db" -evalue "$EVALUE" -outfmt "6 $COLS" -out "$WORK/raw.tsv"
  VER=$("$TOOL" -version 2>/dev/null | head -1)
fi

printf '%s\n' "$(echo "$COLS" | tr ' ' '\t')" > "$OUT"
cat "$WORK/raw.tsv" >> "$OUT"
NHITS=$(( $(wc -l < "$OUT") - 1 ))

echo "=== vivarium-search done ==="
echo "tool:    $TOOL"
echo "version: $VER"
echo "command: $CMD"
echo "hits:    $NHITS rows -> $OUT"
echo "(scratch DB left in $WORK — OS temp dir, no rm needed)"
