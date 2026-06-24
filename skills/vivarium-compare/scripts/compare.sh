#!/bin/bash
# compare.sh — vivarium-compare bundled runner for the light/moderate steps.
#   ani      FastANI all-vs-all over a genome set  -> square ANI matrix TSV (feeds vivarium-report heatmap)
#   aai      EzAAI all-vs-all over a genome set     -> square AAI matrix TSV (more sensitive; ~10-15s/genome to extract)
#   synteny  nucmer + show-coords for one genome pair -> tidy coords table
# OrthoFinder (orthology) is heavy and is scaffolded by the SKILL, not run here.
# Runs in the bio_tools conda env. Never auto-installs anything.
set -eu

need() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: '$1' not on PATH. Activate bio_tools or install it (do NOT auto-install)." >&2; exit 1; }; }
PY="/opt/anaconda3/bin/python"; [ -x "$PY" ] || PY="python3"

SUB="${1:-}"
[ -n "$SUB" ] || { echo "ERROR: need a subcommand: ani | aai | synteny" >&2; exit 1; }
shift

case "$SUB" in
  ani)
    INDIR=""; LIST=""; OUT="ani_matrix.tsv"; FRAG=3000; THREADS=4
    while [ $# -gt 0 ]; do case "$1" in
      --indir)   INDIR="$2";   shift 2;;
      --list)    LIST="$2";    shift 2;;
      --out)     OUT="$2";     shift 2;;
      --frag)    FRAG="$2";    shift 2;;
      --threads) THREADS="$2"; shift 2;;
      *) echo "ERROR: unknown arg: $1" >&2; exit 2;;
    esac; done
    need fastANI
    WORK="$(mktemp -d)"; GLIST="$WORK/genomes.txt"
    if [ -n "$LIST" ]; then
      [ -f "$LIST" ] || { echo "ERROR: --list not found: $LIST" >&2; exit 1; }
      cp "$LIST" "$GLIST"
    elif [ -n "$INDIR" ]; then
      [ -d "$INDIR" ] || { echo "ERROR: --indir not a directory: $INDIR" >&2; exit 1; }
      find "$INDIR" -maxdepth 1 \( -name "*.fna" -o -name "*.fa" -o -name "*.fasta" \) | sort > "$GLIST"
    else
      echo "ERROR: provide --indir <dir> or --list <file>" >&2; exit 1
    fi
    N=$(grep -c . "$GLIST" 2>/dev/null || true); [ -n "$N" ] || N=0
    [ "$N" -ge 2 ] || { echo "ERROR: need >=2 genomes (found $N)" >&2; exit 1; }
    OUTDIR="$(dirname "$OUT")"; [ -d "$OUTDIR" ] || { echo "ERROR: output dir does not exist: $OUTDIR" >&2; exit 1; }
    echo "running FastANI all-vs-all on $N genomes ..." >&2
    if ! fastANI --ql "$GLIST" --rl "$GLIST" --fragLen "$FRAG" -t "$THREADS" -o "$WORK/raw.tsv" 2>"$WORK/log"; then
      tail -3 "$WORK/log" >&2; echo "ERROR: fastANI failed (see above)" >&2; exit 1
    fi
    "$PY" - "$WORK/raw.tsv" "$GLIST" "$OUT" <<'PY'
import sys, os
raw, glist, out = sys.argv[1:4]
def stem(p): return os.path.splitext(os.path.basename(p.strip()))[0]
entries = [l.strip() for l in open(glist) if l.strip()]
names = [stem(e) for e in entries]
idx = {os.path.abspath(e): stem(e) for e in entries}
def lab(p):
    p = p.strip()
    return idx.get(os.path.abspath(p), stem(p))
M = {a: {b: ("100.00" if a == b else "NA") for b in names} for a in names}
for line in open(raw):
    f = line.rstrip("\n").split("\t")
    if len(f) < 3: continue
    q, r = lab(f[0]), lab(f[1])
    if q in M and r in M[q]:
        try: M[q][r] = f"{float(f[2]):.2f}"
        except ValueError: pass
with open(out, "w") as o:
    o.write("\t" + "\t".join(names) + "\n")
    for a in names:
        o.write(a + "\t" + "\t".join(M[a][b] for b in names) + "\n")
print(f"wrote {out} ({len(names)}x{len(names)} ANI matrix)")
PY
    echo "=== vivarium-compare ani done ===" >&2
    echo "tool:    fastANI ($(fastANI --version 2>&1 | head -1))" >&2
    echo "command: fastANI --ql <list> --rl <list> --fragLen $FRAG -t $THREADS -o <raw>" >&2
    echo "note:    NA = pair below FastANI's ~80% ANI reporting floor (not zero similarity)" >&2
    ;;

  aai)
    INDIR=""; LIST=""; OUT="aai_matrix.tsv"
    while [ $# -gt 0 ]; do case "$1" in
      --indir) INDIR="$2"; shift 2;;
      --list)  LIST="$2";  shift 2;;
      --out)   OUT="$2";   shift 2;;
      *) echo "ERROR: unknown arg: $1" >&2; exit 2;;
    esac; done
    need EzAAI
    WORK="$(mktemp -d)"; GLIST="$WORK/genomes.txt"; DBDIR="$WORK/db"; mkdir -p "$DBDIR"
    if [ -n "$LIST" ]; then
      [ -f "$LIST" ] || { echo "ERROR: --list not found: $LIST" >&2; exit 1; }
      cp "$LIST" "$GLIST"
    elif [ -n "$INDIR" ]; then
      [ -d "$INDIR" ] || { echo "ERROR: --indir not a directory: $INDIR" >&2; exit 1; }
      find "$INDIR" -maxdepth 1 \( -name "*.fna" -o -name "*.fa" -o -name "*.fasta" \) | sort > "$GLIST"
    else
      echo "ERROR: provide --indir <dir> or --list <file>" >&2; exit 1
    fi
    N=$(grep -c . "$GLIST" 2>/dev/null || true); [ -n "$N" ] || N=0
    [ "$N" -ge 2 ] || { echo "ERROR: need >=2 genomes (found $N)" >&2; exit 1; }
    OUTDIR="$(dirname "$OUT")"; [ -d "$OUTDIR" ] || { echo "ERROR: output dir does not exist: $OUTDIR" >&2; exit 1; }
    echo "extracting proteomes for $N genomes (EzAAI, ~10-15s each) ..." >&2
    while IFS= read -r g; do
      [ -n "$g" ] || continue
      lab="$(basename "$g")"; lab="${lab%.*}"
      if ! EzAAI extract -i "$g" -o "$DBDIR/$lab.db" -l "$lab" >"$WORK/extract.log" 2>&1; then
        tail -3 "$WORK/extract.log" >&2; echo "ERROR: EzAAI extract failed on $g" >&2; exit 1
      fi
    done < "$GLIST"
    echo "computing all-vs-all AAI ..." >&2
    if ! EzAAI calculate -i "$DBDIR" -j "$DBDIR" -o "$WORK/raw.tsv" >"$WORK/calc.log" 2>&1; then
      tail -3 "$WORK/calc.log" >&2; echo "ERROR: EzAAI calculate failed" >&2; exit 1
    fi
    "$PY" - "$WORK/raw.tsv" "$GLIST" "$OUT" <<'PY'
import sys, os
raw, glist, out = sys.argv[1:4]
def stem(p): return os.path.splitext(os.path.basename(p.strip()))[0]
names = [stem(l) for l in open(glist) if l.strip()]
M = {a: {b: "NA" for b in names} for a in names}
for line in open(raw):
    f = line.rstrip("\n").split("\t")
    if len(f) < 5 or f[0].strip() in ("ID 1", "ID"): continue   # skip header
    l1, l2, aai = f[2], f[3], f[4]
    if l1 in M and l2 in M[l1]:
        try: M[l1][l2] = f"{float(aai):.2f}"
        except ValueError: pass
for a in names:
    if M[a][a] == "NA": M[a][a] = "100.00"
with open(out, "w") as o:
    o.write("\t" + "\t".join(names) + "\n")
    for a in names:
        o.write(a + "\t" + "\t".join(M[a][b] for b in names) + "\n")
print(f"wrote {out} ({len(names)}x{len(names)} AAI matrix)")
PY
    echo "=== vivarium-compare aai done ===" >&2
    echo "tool:    EzAAI (extract per genome via Prodigal, then calculate)" >&2
    echo "command: EzAAI extract -i <genome> -o <label>.db -l <label> ; EzAAI calculate -i <dbdir> -j <dbdir> -o <raw>" >&2
    ;;

  synteny)
    REF=""; QUERY=""; OUT="synteny_coords.tsv"; MINLEN=1000
    while [ $# -gt 0 ]; do case "$1" in
      --ref)    REF="$2";    shift 2;;
      --query)  QUERY="$2";  shift 2;;
      --out)    OUT="$2";    shift 2;;
      --minlen) MINLEN="$2"; shift 2;;
      *) echo "ERROR: unknown arg: $1" >&2; exit 2;;
    esac; done
    [ -f "$REF" ]   || { echo "ERROR: --ref not found: $REF" >&2; exit 1; }
    [ -f "$QUERY" ] || { echo "ERROR: --query not found: $QUERY" >&2; exit 1; }
    OUTDIR="$(dirname "$OUT")"; [ -d "$OUTDIR" ] || { echo "ERROR: output dir does not exist: $OUTDIR" >&2; exit 1; }
    need nucmer; need show-coords
    WORK="$(mktemp -d)"
    if ! nucmer --maxmatch -p "$WORK/out" "$REF" "$QUERY" 2>"$WORK/log"; then
      tail -3 "$WORK/log" >&2; echo "ERROR: nucmer failed (see above)" >&2; exit 1
    fi
    # -r sort by ref, -c coverage cols, -l length cols, -T tab, -H no header
    # columns: S1 E1 S2 E2 LEN1 LEN2 %IDY LENR LENQ COVR COVQ TAGr TAGq
    show-coords -rclTH "$WORK/out.delta" > "$WORK/coords"
    printf "ref_start\tref_end\tqry_start\tqry_end\tlen_ref\tlen_qry\tpct_id\tref_contig\tqry_contig\n" > "$OUT"
    awk -F'\t' -v m="$MINLEN" 'NF>=13 && ($5+0)>=m {print $1"\t"$2"\t"$3"\t"$4"\t"$5"\t"$6"\t"$7"\t"$(NF-1)"\t"$NF}' "$WORK/coords" >> "$OUT"
    NB=$(( $(wc -l < "$OUT") - 1 ))
    echo "=== vivarium-compare synteny done ===" >&2
    echo "tool:    nucmer ($(nucmer --version 2>&1 | tr '\n' ' ' | sed 's/  */ /g'))" >&2
    echo "blocks:  $NB (>= ${MINLEN} bp) -> $OUT" >&2
    echo "note:    reverse-strand blocks have qry_start > qry_end" >&2
    ;;

  *) echo "ERROR: unknown subcommand '$SUB' (use ani | aai | synteny)" >&2; exit 1;;
esac
