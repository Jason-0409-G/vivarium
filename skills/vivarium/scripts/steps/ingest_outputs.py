#!/usr/bin/env python3
"""Zero-dependency ingest step for scaffolded (heavy / uninstalled-tool) stages.

A heavy V1 stage (Prokka, OrthoFinder, IQ-TREE, dN/dS, ...) is run by the user in
their bioinformatics environment; they drop the outputs into the attempt
workspace, and this deterministic process seals them into the durable loop. It is
the stage's real argv, so the harness produces a genuine ExecutionEvidenceCut over
the user-supplied outputs -- a committed stage whose evidence is those outputs,
indistinguishable downstream from an inline-computed one.

It runs in the workspace (cwd) and verifies every expected output exists and is a
non-empty regular file; missing or empty -> non-zero exit so the loop fails closed.

Usage: python3 ingest_outputs.py <expected_output> [<expected_output> ...]
"""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    expected = argv[1:]
    if not expected:
        sys.stderr.write("ingest_outputs: no expected outputs given\n")
        return 2
    missing = []
    for name in expected:
        path = Path(name)
        if not path.is_file() or path.stat().st_size == 0:
            missing.append(name)
    if missing:
        sys.stderr.write(
            "ingest_outputs: missing or empty expected outputs: "
            + ", ".join(missing)
            + "\n"
        )
        return 2
    sys.stdout.write(f"ingested {len(expected)} scaffolded output(s)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
