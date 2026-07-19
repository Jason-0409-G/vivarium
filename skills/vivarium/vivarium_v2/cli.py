from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from .errors import VivariumError
from .loop import perform_one_step
from .project import ProjectStore
from .steps import run_local_step

STATS_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "steps" / "genome_stats.py"


def _utc_clock() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _open_store(root: Path) -> ProjectStore:
    if root.exists():
        return ProjectStore(root, _utc_clock)
    return ProjectStore.init(root, _utc_clock)


def _ensure_execution_pending(store: ProjectStore, run_id: str) -> None:
    if run_id not in store._registered_run_ids():
        store.register_run(run_id, analysis_state="EXECUTION_PENDING")


def _cmd_run_step(args: argparse.Namespace) -> int:
    inputs = [Path(item).resolve() for item in args.genome]
    for path in inputs:
        if not path.is_file():
            raise VivariumError(f"input is not a file: {path}")
    if not STATS_SCRIPT.is_file():
        raise VivariumError(f"genome-stats step script is missing: {STATS_SCRIPT}")
    store = _open_store(Path(args.root).resolve())
    _ensure_execution_pending(store, args.run_id)
    result = run_local_step(
        store,
        run_id=args.run_id,
        stage_id=args.stage,
        attempt_id=args.attempt,
        argv=(sys.executable, str(STATS_SCRIPT), *(str(path) for path in inputs)),
    )
    workspace = (
        store.root / "runs" / args.run_id / "attempts" / args.stage / args.attempt / "workspace"
    )
    cut = result.evidence_cut
    sys.stdout.write(f"outcome: {result.classification.outcome}\n")
    sys.stdout.write(f"execution_evidence_cut_digest: {cut.execution_evidence_cut_digest}\n")
    sys.stdout.write(f"exit_code: {cut.exit_code}\n")
    if result.proof is not None:
        sys.stdout.write(f"completion_proof_digest: {result.proof.completion_proof_digest}\n")
    stats = workspace / "stats.tsv"
    if stats.is_file():
        sys.stdout.write(f"--- {stats} ---\n{stats.read_text(encoding='ascii')}")
    if result.classification.outcome != "success":
        return VivariumError("execution did not classify as success").exit_code
    return 0


def _cmd_commit_step(args: argparse.Namespace) -> int:
    inputs = [Path(item).resolve() for item in args.genome]
    for path in inputs:
        if not path.is_file():
            raise VivariumError(f"input is not a file: {path}")
    if not STATS_SCRIPT.is_file():
        raise VivariumError(f"genome-stats step script is missing: {STATS_SCRIPT}")
    store = _open_store(Path(args.root).resolve())
    _ensure_execution_pending(store, args.run_id)
    step = perform_one_step(
        store,
        run_id=args.run_id,
        stage_id=args.stage,
        attempt_id=args.attempt,
        argv=(sys.executable, str(STATS_SCRIPT), *(str(path) for path in inputs)),
    )
    sys.stdout.write(f"outcome: {step.result.classification.outcome}\n")
    sys.stdout.write(f"validation: {step.validation_outcome}\n")
    sys.stdout.write(f"committed: {step.committed}\n")
    if step.committed and step.stage_committed_event is not None:
        payload = step.stage_committed_event.payload
        sys.stdout.write(f"stage_committed_object: {payload['object_id']}\n")
        sys.stdout.write(f"object_head: {payload['object_head']}\n")
        sys.stdout.write(f"evidence_bundle_digest: {payload['evidence_bundle_digest']}\n")
    workspace = (
        store.root / "runs" / args.run_id / "attempts" / args.stage / args.attempt / "workspace"
    )
    stats = workspace / "stats.tsv"
    if stats.is_file():
        sys.stdout.write(f"--- {stats} ---\n{stats.read_text(encoding='ascii')}")
    return 0 if step.committed else VivariumError("stage did not commit").exit_code


def _stage_parser(prog: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, add_help=True)
    parser.add_argument("--root", required=True, help="project store directory")
    parser.add_argument("--run-id", required=True, dest="run_id")
    parser.add_argument("--stage", default="stage-1")
    parser.add_argument("--attempt", default="attempt-1")
    parser.add_argument(
        "--genome",
        required=True,
        nargs="+",
        help="one or more FASTA (.fna) genome files to compute stats for",
    )
    return parser


_COMMANDS = {
    "run-step": _cmd_run_step,
    "commit-step": _cmd_commit_step,
}


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv or ())
    try:
        if not args:
            raise VivariumError("V2 command required")
        command, rest = args[0], args[1:]
        handler = _COMMANDS.get(command)
        if handler is None:
            raise VivariumError(f"unknown V2 command: {command}")
        return handler(_stage_parser(f"vivarium v2 {command}").parse_args(rest))
    except VivariumError as error:
        sys.stderr.write(f"ERROR: {error}\n")
        return error.exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
