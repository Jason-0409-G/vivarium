"""Real local-process execution harness.

The LocalExecutionBroker (execution.py) is a complete, crash-safe orchestration:
it persists the intent, appends the ledger events, freezes the terminal evidence
cut, classifies completion and builds the proof. The only piece it delegates is
the *harness* — the thing that actually starts an OS process and reports its
terminal state. Tests use FakeLocalHarness with canned values; this module is the
real one: it spawns intent.argv with subprocess in its own session/process group,
waits for it, hashes its outputs, and reports terminal evidence in exactly the
shape _cut_from_terminal requires, so the broker turns a real process into a real
ExecutionEvidenceCut.
"""

from __future__ import annotations

import base64
import os
import platform
import subprocess
from pathlib import Path
from typing import Any, Callable

from .canonical import canonical_bytes, domain_hash
from .errors import IntegrityError
from .execution import ExecutionIntent, ProcessReceipt

LOCAL_QUIESCENCE_SCHEMA = "vivarium.local-quiescence-receipt/v1"


def _content_digest(domain: str, data: bytes) -> str:
    return domain_hash(domain, base64.b64encode(data).decode("ascii"))


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

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._state: dict[str, dict[str, Any]] = {}

    def _attempt_dir(self, intent: ExecutionIntent, leaf: str) -> Path:
        return (
            self.root
            / "runs"
            / intent.run_id
            / "attempts"
            / intent.stage_id
            / intent.attempt_id
            / leaf
        )

    def workspace(self, intent: ExecutionIntent) -> Path:
        return self._attempt_dir(intent, "workspace")

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
        descendants_alive = self._process_group_alive(process_group_id)
        terminal = self._terminal_value(
            intent, receipt, workspace, returncode, descendants_alive
        )
        self._state[intent.execution_intent_id] = {
            "receipt": receipt,
            "terminal": terminal,
            "process_group_id": process_group_id,
        }
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

    def _terminal_value(
        self,
        intent: ExecutionIntent,
        receipt: ProcessReceipt,
        workspace: Path,
        returncode: int,
        descendants_alive: bool,
    ) -> dict[str, Any]:
        exit_code = returncode if returncode >= 0 else None
        signal_number = -returncode if returncode < 0 else None
        manifest_digest = _output_manifest_digest(workspace)
        observed_descendant_count = 1 if descendants_alive else 0
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
            "terminal_evidence_refs": (receipt.stdout_digest, receipt.stderr_digest),
            "process_terminal": True,
            "quiescence_receipt": quiescence,
            "quiescence_receipt_digest": domain_hash(
                "vivarium-local-quiescence-receipt/v1", quiescence
            ),
        }

    def identity_matches(self, receipt: ProcessReceipt) -> bool:
        stored = self._state.get(receipt.execution_intent_id)
        return stored is not None and stored["receipt"] == receipt

    def collect_terminal(self, receipt: ProcessReceipt) -> dict[str, Any] | None:
        stored = self._state.get(receipt.execution_intent_id)
        return stored["terminal"] if stored is not None else None

    def reap_descendants(self, receipt: ProcessReceipt) -> dict[str, Any]:
        stored = self._state.get(receipt.execution_intent_id)
        group = stored["process_group_id"] if stored is not None else receipt.process_group_id
        if self._process_group_alive(group):
            return {"observed_descendant_count": 1, "containment_refs": [f"pgid:{group}"]}
        return {"observed_descendant_count": 0, "containment_refs": []}


__all__ = ["LocalProcessHarness", "LOCAL_QUIESCENCE_SCHEMA"]
