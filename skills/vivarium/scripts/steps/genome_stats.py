#!/usr/bin/env python3
"""Zero-dependency genome statistics step.

A deliberately dependency-free bioinformatics step so the Vivarium loop can run a
real OS process end to end without needing seqkit/prokka installed. Reads one or
more FASTA (.fna/.fasta) files and writes a `stats.tsv` with per-genome contig
count, total length, GC%, and N50 into the current working directory (the attempt
workspace the harness runs us in).

Usage: python3 genome_stats.py <genome.fna> [<genome2.fna> ...]
"""

from __future__ import annotations

import sys
from pathlib import Path


def _iter_contigs(path: Path):
    length = 0
    gc = 0
    started = False
    with path.open("r", encoding="ascii", errors="ignore") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if started:
                    yield length, gc
                length = 0
                gc = 0
                started = True
                continue
            started = True
            length += len(line)
            gc += sum(1 for base in line.upper() if base in "GC")
    if started:
        yield length, gc


def _n50(lengths: list[int]) -> int:
    if not lengths:
        return 0
    ordered = sorted(lengths, reverse=True)
    half = sum(ordered) / 2
    running = 0
    for value in ordered:
        running += value
        if running >= half:
            return value
    return ordered[-1]


def genome_stats(path: Path) -> dict[str, object]:
    lengths = []
    gc_total = 0
    for length, gc in _iter_contigs(path):
        lengths.append(length)
        gc_total += gc
    total = sum(lengths)
    gc_percent = round(100.0 * gc_total / total, 4) if total else 0.0
    return {
        "genome": path.name,
        "contigs": len(lengths),
        "total_length": total,
        "gc_percent": gc_percent,
        "n50": _n50(lengths),
    }


COLUMNS = ("genome", "contigs", "total_length", "gc_percent", "n50")


def main(argv: list[str]) -> int:
    inputs = [Path(item) for item in argv[1:]]
    if not inputs:
        sys.stderr.write("genome_stats: no input FASTA given\n")
        return 2
    rows = []
    for path in inputs:
        if not path.is_file():
            sys.stderr.write(f"genome_stats: not a file: {path}\n")
            return 2
        rows.append(genome_stats(path))
    lines = ["\t".join(COLUMNS)]
    for row in rows:
        lines.append("\t".join(str(row[column]) for column in COLUMNS))
    output = Path("stats.tsv")
    output.write_text("\n".join(lines) + "\n", encoding="ascii")
    sys.stdout.write(f"wrote {output} with {len(rows)} genome(s)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
