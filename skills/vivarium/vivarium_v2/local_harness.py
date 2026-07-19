"""Real local-process execution harness.

The LocalExecutionBroker (execution.py) is a complete, crash-safe orchestration:
it persists the intent, appends the ledger events, freezes the terminal evidence
cut, classifies completion and builds the proof. The only piece it delegates is
the *harness* — the thing that actually starts an OS process and reports its
terminal state. Tests use FakeLocalHarness with canned values; this module is the
real one: it spawns intent.argv with subprocess in its own session/process group,
waits for it, checks descendant containment and output quiescence, and reports
terminal evidence in exactly the shape _cut_from_terminal requires, so the broker
turns a real process into a real ExecutionEvidenceCut.

Honesty of the terminal report is the trust boundary. Two guards back it:
containment is measured by process-group liveness, and output quiescence by a
bounded settle-and-rehash (a double snapshot of the workspace manifest). A
descendant that migrates to its own session (setsid/double-fork) can evade the
pgroup check, but if it is still writing outputs the rehash catches the mutating
tree and the step is reported non-quiescent (fail closed). Fully containing such
escapes needs OS-level isolation (cgroups / subreaper) and is Task-5 work.

Terminal evidence is also persisted durably, so a fresh harness after a crash
re-derives the identical cut on recovery instead of failing the identity check.
"""

from __future__ import annotations

import base64
import json
import os
import platform
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from .canonical import canonical_bytes, domain_hash, durable_replace
from .errors import IntegrityError
from .execution import ExecutionIntent, ProcessReceipt

LOCAL_QUIESCENCE_SCHEMA = "vivarium.local-quiescence-receipt/v1"
DEFAULT_OUTPUT_QUIESCENCE_SECONDS = 0.1


def _content_digest(domain: str, data: bytes) -> str:
    return domain_hash(domain, base64.b64encode(data).decode("ascii"))


def _safe_identity(value: str, field: str) -> str:
    if not isinstance(value, str) or not value or "/" in value or ".." in value:
        raise IntegrityError(f"{field} is not a safe stable identity")
    return value


def _host_boot_id() -> str:
    """A stable-per-boot host identity. Uses the kernel boot id where available
    (Linux), otherwise a stable proxy derived from the host name so a receipt can
    still be identity-matched within a session."""
    try:
        value = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
        if value:
            return value
    except OSError:
        pass
    return "host-" + domain_hash("vivarium-host-boot/v1", platform.node() or "unknown")[7:23]


def _output_manifest_digest(workspace: Path) -> str:
    entries = []
    for path in sorted(workspace.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        body = path.read_bytes()
        entries.append(
            {
                "relative_path": path.relative_to(workspace).as_posix(),
                "content_digest": _content_digest("vivarium-output-file/v1", body),
                "size": len(body),
            }
        )
    return domain_hash("vivarium-output-quiescence-manifest/v1", entries)


class LocalProcessHarness:
    """Runs intent.argv to completion in the attempt workspace, in its own
    session so descendants are contained, and reports real terminal evidence."""

    def __init__(
        self,
        root: str | Path,
        *,
        output_quiescence_seconds: float = DEFAULT_OUTPUT_QUIESCENCE_SECONDS,
    ):
        self.root = Path(root)
        self.output_quiescence_seconds = output_quiescence_seconds
        self._state: dict[str, dict[str, Any]] = {}

    def _attempt_dir(self, intent: ExecutionIntent, leaf: str) -> Path:
        run_id = _safe_identity(intent.run_id, "run_id")
        stage_id = _safe_identity(intent.stage_id, "stage_id")
        attempt_id = _safe_identity(intent.attempt_id, "attempt_id")
        directory = (
            self.root / "runs" / run_id / "attempts" / stage_id / attempt_id / leaf
        )
        resolved = directory.resolve()
        if self.root.resolve() not in resolved.parents and resolved != self.root.resolve():
            raise IntegrityError("attempt directory escapes the store root")
        return directory

    def workspace(self, intent: ExecutionIntent) -> Path:
        return self._attempt_dir(intent, "workspace")

    def _durable_state_path(self, execution_intent_id: str) -> Path:
        token = domain_hash("vivarium-local-harness-terminal/v1", execution_intent_id)[7:]
        return self.root / "artifacts" / "harness-terminals" / f"{token}.json"

    def _load_state(self, execution_intent_id: str) -> dict[str, Any] | None:
        if execution_intent_id in self._state:
            return self._state[execution_intent_id]
        path = self._durable_state_path(execution_intent_id)
        try:
            body = json.loads(path.read_bytes().decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        try:
            receipt = ProcessReceipt(**body["receipt"])
        except (TypeError, KeyError, ValueError):
            return None
        state = {
            "receipt": receipt,
            "terminal": body["terminal"],
            "process_group_id": body["process_group_id"],
        }
        self._state[execution_intent_id] = state
        return state

    def start_wrapper(
        self,
        intent: ExecutionIntent,
        persist_receipt_callback: Callable[[ProcessReceipt], None],
        crash_at: str | None = None,
    ) -> ProcessReceipt:
        if not intent.argv:
            raise IntegrityError("local execution intent has no argv to run")
        workspace = self.workspace(intent)
        logs = self._attempt_dir(intent, "execution_logs")
        workspace.mkdir(parents=True, exist_ok=True)
        logs.mkdir(parents=True, exist_ok=True)
        stdout_path = logs / "wrapper.stdout"
        stderr_path = logs / "wrapper.stderr"
        with open(stdout_path, "wb") as out, open(stderr_path, "wb") as err:
            process = subprocess.Popen(
                list(intent.argv),
                cwd=str(workspace),
                stdout=out,
                stderr=err,
                start_new_session=True,
            )
            pid = process.pid
            # start_new_session makes the child its own session/group leader.
            process_group_id = pid
            returncode = process.wait()
        boot_id = _host_boot_id()
        stdout_bytes = stdout_path.read_bytes()
        stderr_bytes = stderr_path.read_bytes()
        receipt = ProcessReceipt(
            intent.execution_intent_id,
            boot_id,
            pid,
            process_group_id,
            f"{boot_id}:{pid}:start",
            _content_digest("vivarium-process-stdout/v1", stdout_bytes),
            _content_digest("vivarium-process-stderr/v1", stderr_bytes),
        )
        persist_receipt_callback(receipt)
        if crash_at == "after_receipt_before_attach":
            raise RuntimeError(crash_at)
        terminal = self._terminal_value(
            intent, receipt, workspace, returncode, process_group_id
        )
        self._state[intent.execution_intent_id] = {
            "receipt": receipt,
            "terminal": terminal,
            "process_group_id": process_group_id,
        }
        durable_replace(
            self._durable_state_path(intent.execution_intent_id),
            canonical_bytes(
                {
                    "receipt": asdict(receipt),
                    "terminal": terminal,
                    "process_group_id": process_group_id,
                }
            ),
        )
        return receipt

    @staticmethod
    def _process_group_alive(process_group_id: int) -> bool:
        try:
            os.killpg(process_group_id, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _output_quiescent(self, workspace: Path) -> tuple[str, bool]:
        """Return (manifest_digest, quiescent). Quiescent means a second snapshot
        after a bounded settle window matches the first -- catching an output tree
        a still-running (possibly session-escaped) descendant is mutating."""
        before = _output_manifest_digest(workspace)
        if self.output_quiescence_seconds > 0:
            time.sleep(self.output_quiescence_seconds)
        after = _output_manifest_digest(workspace)
        return after, before == after

    def _terminal_value(
        self,
        intent: ExecutionIntent,
        receipt: ProcessReceipt,
        workspace: Path,
        returncode: int,
        process_group_id: int,
    ) -> dict[str, Any]:
        exit_code = returncode if returncode >= 0 else None
        signal_number = -returncode if returncode < 0 else None
        manifest_digest, settled = self._output_quiescent(workspace)
        descendants_alive = self._process_group_alive(process_group_id)
        # Report contained+quiescent only when the process group is empty AND the
        # output tree stopped changing across the settle window. A non-zero count
        # makes the broker reject quiescence, so a live/escaped writer fails closed.
        observed_descendant_count = 0 if (settled and not descendants_alive) else 1
        containment_refs: list[str] = []
        quiescence = {
            "schema_version": LOCAL_QUIESCENCE_SCHEMA,
            "execution_intent_id": intent.execution_intent_id,
            "process_receipt_digest": receipt.process_receipt_digest,
            "stdout_digest": receipt.stdout_digest,
            "stderr_digest": receipt.stderr_digest,
            "output_quiescence_manifest_digest": manifest_digest,
            "observed_descendant_count": observed_descendant_count,
            "containment_refs": containment_refs,
        }
        sentinel_digest = domain_hash(
            "vivarium-local-sentinel/v1",
            {
                "execution_intent_id": intent.execution_intent_id,
                "process_start_identity": receipt.process_start_identity,
                "exit_code": exit_code,
                "signal": signal_number,
            },
        )
        return {
            "exit_code": exit_code,
            "signal": signal_number,
            "oom": False,
            "preempted": False,
            "cancelled": False,
            "sentinel_digest": sentinel_digest,
            "output_quiescence_manifest_digest": manifest_digest,
            "terminal_evidence_refs": [receipt.stdout_digest, receipt.stderr_digest],
            "process_terminal": True,
            "quiescence_receipt": quiescence,
            "quiescence_receipt_digest": domain_hash(
                "vivarium-local-quiescence-receipt/v1", quiescence
            ),
        }

    def identity_matches(self, receipt: ProcessReceipt) -> bool:
        stored = self._load_state(receipt.execution_intent_id)
        return stored is not None and stored["receipt"] == receipt

    def collect_terminal(self, receipt: ProcessReceipt) -> dict[str, Any] | None:
        stored = self._load_state(receipt.execution_intent_id)
        return stored["terminal"] if stored is not None else None

    def reap_descendants(self, receipt: ProcessReceipt) -> dict[str, Any]:
        stored = self._load_state(receipt.execution_intent_id)
        group = stored["process_group_id"] if stored is not None else receipt.process_group_id
        if self._process_group_alive(group):
            return {"observed_descendant_count": 1, "containment_refs": [f"pgid:{group}"]}
        return {"observed_descendant_count": 0, "containment_refs": []}


__all__ = ["LocalProcessHarness", "LOCAL_QUIESCENCE_SCHEMA"]
