"""High-level step API: run one real local execution through the durable engine.

This lifts the broker + real harness into a single call a caller (CLI, or a future
orchestrator loop) can use to execute one stage's command as a real OS process and
get back durable, crash-safe execution evidence (a classified ExecutionEvidenceCut
and, on success, a CompletionProof). It is the execution primitive the loop is
built on; committing the result into the project ledger is the next layer.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .canonical import domain_hash
from .execution import ExecutionIntent, LocalExecutionBroker, LocalExecutionResult
from .local_harness import LocalProcessHarness


def run_local_step(
    store,
    *,
    run_id: str,
    argv: Sequence[str],
    stage_id: str = "stage-1",
    attempt_id: str = "attempt-1",
    execution_intent_id: str | None = None,
    request_key: str | None = None,
    env: Mapping[str, str] | None = None,
) -> LocalExecutionResult:
    """Run argv as a real local process in the attempt workspace and freeze its
    durable execution evidence. The run must already be EXECUTION_PENDING on its
    active attempt (the broker enforces this). Idempotent under recovery: the same
    intent id re-derives the identical cut and never re-runs the process."""
    argv = tuple(argv)
    if not argv:
        raise ValueError("run_local_step requires a non-empty argv")
    intent = ExecutionIntent(
        execution_intent_id or f"exec:{run_id}:{stage_id}:{attempt_id}",
        run_id,
        stage_id,
        attempt_id,
        "local",
        argv,
        domain_hash(
            "vivarium-execution-cwd/v1",
            {"run_id": run_id, "stage_id": stage_id, "attempt_id": attempt_id},
        ),
        domain_hash("vivarium-execution-environment/v1", {"argv0": argv[0]}),
        request_key or f"request:{run_id}:{stage_id}:{attempt_id}",
    )
    broker = LocalExecutionBroker(store, LocalProcessHarness(store.root, env=env))
    return broker.run_or_recover(intent)


__all__ = ["run_local_step"]
