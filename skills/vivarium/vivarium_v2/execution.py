from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, domain_hash, durable_replace
from .errors import IntegrityError
from .state import AnalysisState


EXECUTION_EVIDENCE_CUT_SCHEMA = "vivarium.execution-evidence-cut/v1"
COMPLETION_PROOF_SCHEMA = "vivarium.completion-proof/v1"
LOCAL_CRASH_POINTS = (
    "before_intent_fsync",
    "after_intent_before_wrapper_start",
    "after_receipt_before_attach",
    "after_child_spawn",
    "after_wrapper_exit_before_quiescence",
    "after_classification_before_proof",
)


def _tuple_of_strings(value: tuple[str, ...], field: str) -> tuple[str, ...]:
    if not isinstance(value, tuple) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise IntegrityError(f"{field} must be a tuple of non-empty strings")
    return value


def _is_digest(value: str) -> bool:
    return isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


_AUTHORITY_OBJECT_DOMAINS = {
    "maker-assignment": "vivarium-maker-assignment/v1",
    "maker-harness-completion": "vivarium-maker-harness-completion-receipt/v1",
    "capability-revocation": "vivarium-capability-revocation-receipt/v1",
    "sealed-output-bundle": "vivarium-sealed-output-bundle/v1",
    "output-quiescence": "vivarium-output-quiescence-manifest/v1",
}


def persist_execution_authority_object(
    store: Any, kind: str, body: dict[str, Any]
) -> str:
    domain = _AUTHORITY_OBJECT_DOMAINS.get(kind)
    if domain is None or not isinstance(body, dict):
        raise IntegrityError("execution authority object kind/body is invalid")
    digest = domain_hash(domain, body)
    durable_replace(
        Path(store.root) / "artifacts" / f"{digest[7:]}.{kind}.json",
        canonical_bytes(body),
    )
    return digest


def _authority_object_resolves(store: Any, kind: str, digest: str) -> bool:
    domain = _AUTHORITY_OBJECT_DOMAINS[kind]
    if not _is_digest(digest):
        return False
    path = Path(store.root) / "artifacts" / f"{digest[7:]}.{kind}.json"
    try:
        raw = path.read_bytes()
        body = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(body, dict)
        and canonical_bytes(body) == raw
        and domain_hash(domain, body) == digest
    )


@dataclass(frozen=True)
class ExecutionIntent:
    execution_intent_id: str
    run_id: str
    stage_id: str
    attempt_id: str
    execution_mode: str
    argv: tuple[str, ...]
    cwd_digest: str
    environment_digest: str
    execution_request_key: str

    def __post_init__(self) -> None:
        _tuple_of_strings(self.argv, "argv")

    @property
    def execution_intent_digest(self) -> str:
        return domain_hash(
            "vivarium-execution-intent/v1",
            {
                "execution_intent_id": self.execution_intent_id,
                "run_id": self.run_id,
                "stage_id": self.stage_id,
                "attempt_id": self.attempt_id,
                "execution_mode": self.execution_mode,
                "argv": list(self.argv),
                "cwd_digest": self.cwd_digest,
                "environment_digest": self.environment_digest,
                "execution_request_key": self.execution_request_key,
            },
        )


@dataclass(frozen=True)
class ProcessReceipt:
    execution_intent_id: str
    boot_id: str
    pid: int
    process_group_id: int
    process_start_identity: str
    stdout_digest: str
    stderr_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.execution_intent_id, str) or not self.execution_intent_id:
            raise IntegrityError("process receipt requires an execution intent ID")
        if not isinstance(self.boot_id, str) or not self.boot_id:
            raise IntegrityError("process receipt requires a boot identity")
        if not isinstance(self.process_start_identity, str) or not self.process_start_identity:
            raise IntegrityError("process receipt requires a process start identity")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in (self.pid, self.process_group_id)
        ):
            raise IntegrityError("process receipt PID identities must be positive integers")
        if not _is_digest(self.stdout_digest) or not _is_digest(self.stderr_digest):
            raise IntegrityError("process receipt output digests are invalid")

    @property
    def process_receipt_digest(self) -> str:
        return domain_hash(
            "vivarium-process-receipt/v1",
            {
                "execution_intent_id": self.execution_intent_id,
                "boot_id": self.boot_id,
                "pid": self.pid,
                "process_group_id": self.process_group_id,
                "process_start_identity": self.process_start_identity,
                "stdout_digest": self.stdout_digest,
                "stderr_digest": self.stderr_digest,
            },
        )


@dataclass(frozen=True)
class AgentOnlyEvidence:
    maker_terminal_success: bool
    child_count: int
    capability_revocation_receipt_digest: str
    sealed_output_bundle_digest: str
    output_quiescence_manifest_digest: str
    requested_capabilities: tuple[str, ...]
    observed_capabilities: tuple[str, ...]
    maker_assignment_digest: str
    maker_harness_identity_digest: str
    maker_harness_completion_receipt_digest: str
    profile_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.maker_terminal_success, bool):
            raise IntegrityError("maker_terminal_success must be boolean")
        if isinstance(self.child_count, bool) or not isinstance(self.child_count, int):
            raise IntegrityError("child_count must be an integer")
        if self.child_count < 0:
            raise IntegrityError("child_count cannot be negative")
        _tuple_of_strings(self.requested_capabilities, "requested_capabilities")
        _tuple_of_strings(self.observed_capabilities, "observed_capabilities")

    @property
    def agent_only_evidence_digest(self) -> str:
        return domain_hash(
            "vivarium-agent-only-evidence/v1",
            {
                "maker_terminal_success": self.maker_terminal_success,
                "child_count": self.child_count,
                "capability_revocation_receipt_digest": self.capability_revocation_receipt_digest,
                "sealed_output_bundle_digest": self.sealed_output_bundle_digest,
                "output_quiescence_manifest_digest": self.output_quiescence_manifest_digest,
                "requested_capabilities": list(self.requested_capabilities),
                "observed_capabilities": list(self.observed_capabilities),
                "maker_assignment_digest": self.maker_assignment_digest,
                "maker_harness_identity_digest": self.maker_harness_identity_digest,
                "maker_harness_completion_receipt_digest": self.maker_harness_completion_receipt_digest,
                "profile_digest": self.profile_digest,
            },
        )


@dataclass(frozen=True)
class ExecutionEvidenceCut:
    schema_version: str
    execution_intent_id: str
    run_id: str
    stage_id: str
    attempt_id: str
    execution_kind: str
    process_or_job_ref: str
    terminal_evidence_refs: tuple[str, ...]
    failure_flags: tuple[str, ...]
    absence_evidence: tuple[str, ...]
    exit_code: int | None
    signal: int | None
    oom: bool
    preempted: bool
    cancelled: bool
    maker_assignment_digest: str
    maker_harness_identity_digest: str
    maker_harness_completion_receipt_digest: str
    capability_revocation_receipt_digest: str
    local_executor_identity_digest: str
    profile_digest: str
    scheduler_fingerprint: str
    sentinel_digest: str
    output_quiescence_manifest_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != EXECUTION_EVIDENCE_CUT_SCHEMA:
            raise IntegrityError("execution evidence cut has an unsupported schema")
        _tuple_of_strings(self.terminal_evidence_refs, "terminal_evidence_refs")
        _tuple_of_strings(self.failure_flags, "failure_flags")
        _tuple_of_strings(self.absence_evidence, "absence_evidence")
        if isinstance(self.exit_code, bool) or (
            self.exit_code is not None and not isinstance(self.exit_code, int)
        ):
            raise IntegrityError("exit_code must be an integer or null")
        if isinstance(self.signal, bool) or (
            self.signal is not None and not isinstance(self.signal, int)
        ):
            raise IntegrityError("signal must be an integer or null")
        if not all(isinstance(value, bool) for value in (self.oom, self.preempted, self.cancelled)):
            raise IntegrityError("terminal flags must be booleans")

    def _canonical_body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "execution_intent_id": self.execution_intent_id,
            "run_id": self.run_id,
            "stage_id": self.stage_id,
            "attempt_id": self.attempt_id,
            "execution_kind": self.execution_kind,
            "process_or_job_ref": self.process_or_job_ref,
            "terminal_evidence_refs": list(self.terminal_evidence_refs),
            "failure_flags": list(self.failure_flags),
            "absence_evidence": list(self.absence_evidence),
            "exit_code": self.exit_code,
            "signal": self.signal,
            "oom": self.oom,
            "preempted": self.preempted,
            "cancelled": self.cancelled,
            "maker_assignment_digest": self.maker_assignment_digest,
            "maker_harness_identity_digest": self.maker_harness_identity_digest,
            "maker_harness_completion_receipt_digest": self.maker_harness_completion_receipt_digest,
            "capability_revocation_receipt_digest": self.capability_revocation_receipt_digest,
            "local_executor_identity_digest": self.local_executor_identity_digest,
            "profile_digest": self.profile_digest,
            "scheduler_fingerprint": self.scheduler_fingerprint,
            "sentinel_digest": self.sentinel_digest,
            "output_quiescence_manifest_digest": self.output_quiescence_manifest_digest,
        }

    @property
    def execution_evidence_cut_digest(self) -> str:
        return domain_hash("vivarium-execution-evidence-cut/v1", self._canonical_body())


@dataclass(frozen=True)
class CompletionClassification:
    outcome: str
    authority: str
    evidence_cut_digest: str
    absence_evidence_digest: str

    @property
    def completion_classification_digest(self) -> str:
        return domain_hash(
            "vivarium-completion-classification-v2/v1",
            {
                "outcome": self.outcome,
                "authority": self.authority,
                "evidence_cut_digest": self.evidence_cut_digest,
                "absence_evidence_digest": self.absence_evidence_digest,
            },
        )


@dataclass(frozen=True)
class CompletionProof:
    schema_version: str
    completion_classification_digest: str
    completion_claim_digest: str
    execution_kind: str
    success_grade: str
    authority: str
    execution_evidence_cut_digest: str
    maker_harness_identity_digest: str
    maker_harness_completion_receipt_digest: str
    capability_revocation_receipt_digest: str
    local_executor_identity_digest: str
    profile_digest: str
    scheduler_fingerprint: str
    sentinel_digest: str
    output_quiescence_manifest_digest: str

    def _canonical_body(self) -> dict[str, str]:
        return {
            "schema_version": self.schema_version,
            "completion_classification_digest": self.completion_classification_digest,
            "completion_claim_digest": self.completion_claim_digest,
            "execution_kind": self.execution_kind,
            "success_grade": self.success_grade,
            "authority": self.authority,
            "execution_evidence_cut_digest": self.execution_evidence_cut_digest,
            "maker_harness_identity_digest": self.maker_harness_identity_digest,
            "maker_harness_completion_receipt_digest": self.maker_harness_completion_receipt_digest,
            "capability_revocation_receipt_digest": self.capability_revocation_receipt_digest,
            "local_executor_identity_digest": self.local_executor_identity_digest,
            "profile_digest": self.profile_digest,
            "scheduler_fingerprint": self.scheduler_fingerprint,
            "sentinel_digest": self.sentinel_digest,
            "output_quiescence_manifest_digest": self.output_quiescence_manifest_digest,
        }

    @property
    def completion_proof_digest(self) -> str:
        return domain_hash("vivarium-completion-proof/v1", self._canonical_body())


def _absence_digest(cut: ExecutionEvidenceCut) -> str:
    return domain_hash(
        "vivarium-execution-absence-evidence/v1", list(cut.absence_evidence)
    )


def _success_authority(cut: ExecutionEvidenceCut) -> str | None:
    required_common = (
        cut.terminal_evidence_refs
        and _is_digest(cut.profile_digest)
        and _is_digest(cut.output_quiescence_manifest_digest)
        and "outputs_quiescent" in cut.absence_evidence
    )
    if not required_common:
        return None
    if cut.execution_kind == "agent_only":
        required = (
            cut.process_or_job_ref == ""
            and "no_live_tasks" in cut.absence_evidence
            and "capabilities_revoked" in cut.absence_evidence
            and all(
                _is_digest(value)
                for value in (
                    cut.maker_assignment_digest,
                    cut.maker_harness_identity_digest,
                    cut.maker_harness_completion_receipt_digest,
                    cut.capability_revocation_receipt_digest,
                )
            )
        )
        return "maker_harness_receipt" if required else None
    if cut.execution_kind == "local_process":
        required = (
            bool(cut.process_or_job_ref)
            and "process_exited" in cut.absence_evidence
            and _is_digest(cut.local_executor_identity_digest)
            and _is_digest(cut.sentinel_digest)
        )
        return "local_process_receipt" if required else None
    if cut.execution_kind == "scheduler_job":
        required = (
            bool(cut.process_or_job_ref)
            and "scheduler_terminal" in cut.absence_evidence
            and _is_digest(cut.scheduler_fingerprint)
            and _is_digest(cut.sentinel_digest)
        )
        return "scheduler_terminal_accounting" if required else None
    return None


def classify_completion(cut: ExecutionEvidenceCut) -> CompletionClassification:
    if not isinstance(cut, ExecutionEvidenceCut):
        raise IntegrityError("completion classification requires an execution evidence cut")
    outcome: str
    if cut.cancelled:
        outcome = "cancelled"
    elif cut.preempted:
        outcome = "preempted"
    elif cut.oom or "oom" in cut.failure_flags or "resource" in cut.failure_flags:
        outcome = "failure_resource"
    elif cut.signal is not None:
        outcome = "failure_retryable"
    elif cut.exit_code is not None and cut.exit_code != 0:
        outcome = "failure_permanent"
    elif "retryable" in cut.failure_flags:
        outcome = "failure_retryable"
    elif cut.failure_flags:
        outcome = "failure_permanent"
    else:
        authority = _success_authority(cut)
        needs_exit = cut.execution_kind in {"local_process", "scheduler_job"}
        if needs_exit and cut.exit_code is None:
            outcome = "unknown_finality"
        elif authority is None:
            outcome = "unknown_finality"
        else:
            outcome = "success"
    authority = _success_authority(cut) if outcome == "success" else "terminal_evidence"
    return CompletionClassification(
        outcome,
        authority or "insufficient_terminal_authority",
        cut.execution_evidence_cut_digest,
        _absence_digest(cut),
    )


_SUCCESS_GRADE_BY_KIND = {
    "agent_only": "authoritative_agent_harness",
    "local_process": "authoritative_local_process",
    "scheduler_job": "authoritative_accounting",
}


def build_completion_proof(
    classification: CompletionClassification, cut: ExecutionEvidenceCut
) -> CompletionProof:
    canonical = classify_completion(cut)
    if classification != canonical:
        raise IntegrityError("completion classification does not bind the evidence cut")
    if classification.outcome != "success":
        raise IntegrityError("completion proofs may only be built for success")
    try:
        success_grade = _SUCCESS_GRADE_BY_KIND[cut.execution_kind]
    except KeyError as exc:
        raise IntegrityError("completion proof has no grade for execution kind") from exc
    claim_digest = domain_hash(
        "vivarium-completion-claim/v1",
        {
            "classification_digest": classification.completion_classification_digest,
            "execution_evidence_cut_digest": cut.execution_evidence_cut_digest,
            "run_id": cut.run_id,
            "stage_id": cut.stage_id,
            "attempt_id": cut.attempt_id,
        },
    )
    return CompletionProof(
        COMPLETION_PROOF_SCHEMA,
        classification.completion_classification_digest,
        claim_digest,
        cut.execution_kind,
        success_grade,
        classification.authority,
        cut.execution_evidence_cut_digest,
        cut.maker_harness_identity_digest,
        cut.maker_harness_completion_receipt_digest,
        cut.capability_revocation_receipt_digest,
        cut.local_executor_identity_digest,
        cut.profile_digest,
        cut.scheduler_fingerprint,
        cut.sentinel_digest,
        cut.output_quiescence_manifest_digest,
    )


@dataclass(frozen=True)
class LocalExecutionResult:
    intent: ExecutionIntent
    receipt: ProcessReceipt
    evidence_cut: ExecutionEvidenceCut
    classification: CompletionClassification
    proof: CompletionProof | None


@dataclass(frozen=True)
class AgentOnlyCompletionResult:
    intent: ExecutionIntent
    evidence: AgentOnlyEvidence
    evidence_cut: ExecutionEvidenceCut
    classification: CompletionClassification
    proof: CompletionProof | None


class LocalExecutionBroker:
    def __init__(self, store: Any, harness: Any, *, crash_at: str | None = None):
        if crash_at is not None and crash_at not in LOCAL_CRASH_POINTS:
            raise IntegrityError("unknown local execution crash point")
        self.store = store
        self.harness = harness
        self.crash_at = crash_at
        self._fired = False

    def _crash(self, point: str) -> None:
        if self.crash_at == point and not self._fired:
            self._fired = True
            raise RuntimeError(point)

    @staticmethod
    def _safe_identity(value: str, field: str) -> str:
        if not isinstance(value, str) or not value or "/" in value or ".." in value:
            raise IntegrityError(f"{field} is not a safe stable identity")
        return value

    def _paths(self, intent: ExecutionIntent) -> dict[str, Path]:
        run_id = self._safe_identity(intent.run_id, "run_id")
        stage_id = self._safe_identity(intent.stage_id, "stage_id")
        attempt_id = self._safe_identity(intent.attempt_id, "attempt_id")
        token = domain_hash(
            "vivarium-local-execution-object-name/v1", intent.execution_intent_id
        )[7:]
        directory = (
            Path(self.store.root)
            / "runs"
            / run_id
            / "attempts"
            / stage_id
            / attempt_id
            / "execution_logs"
        )
        return {
            "directory": directory,
            "intent": directory / f"{token}.execution-intent.json",
            "receipt": directory / f"{token}.process-receipt.json",
            "agent_evidence": directory / f"{token}.agent-only-evidence.json",
            "quiescence": directory / f"{token}.local-quiescence-receipt.json",
            "cut": directory / f"{token}.execution-evidence-cut.json",
            "classification": directory / f"{token}.completion-classification.json",
            "proof": directory / f"{token}.completion-proof.json",
        }

    @staticmethod
    def _persist(path: Path, value: Any) -> None:
        body = asdict(value)
        for field, item in tuple(body.items()):
            if isinstance(item, tuple):
                body[field] = list(item)
        durable_replace(path, canonical_bytes(body))

    @staticmethod
    def _read(path: Path, cls: Any) -> Any:
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise IntegrityError("durable execution object is unreadable") from exc
        annotations = getattr(cls, "__annotations__", {})
        for field in (
            "argv",
            "terminal_evidence_refs",
            "failure_flags",
            "absence_evidence",
            "requested_capabilities",
            "observed_capabilities",
        ):
            if field in annotations and field in body:
                body[field] = tuple(body[field])
        try:
            return cls(**body)
        except (TypeError, ValueError) as exc:
            raise IntegrityError("durable execution object has invalid fields") from exc

    def _active_local(self, intent: ExecutionIntent) -> Any:
        _, locals_ = self.store.capture()
        local = next((item for item in locals_ if item.run_id == intent.run_id), None)
        if local is None or local.active_attempt_id != intent.attempt_id:
            raise IntegrityError("execution intent does not bind the active registered attempt")
        return local

    def _append_once(self, intent: ExecutionIntent, event_type: str, payload: dict[str, Any]):
        ledger = self.store._run_ledger(intent.run_id)
        existing = next(
            (
                event
                for event in ledger.recover().events
                if event.tx_id == intent.execution_intent_id
                and event.event_type == event_type
            ),
            None,
        )
        if existing is not None:
            if existing.payload != payload:
                raise IntegrityError("local execution event bytes disagree on recovery")
            return existing
        event = self.store._append(
            ledger, event_type, payload, intent.execution_intent_id
        )
        self.store.capture()
        return event

    def _intent_event(self, intent: ExecutionIntent) -> None:
        self._append_once(
            intent,
            "LOCAL_EXECUTION_INTENT",
            {
                "event_digest": intent.execution_intent_digest,
                "execution_intent_id": intent.execution_intent_id,
                "execution_intent_digest": intent.execution_intent_digest,
                "attempt_id": intent.attempt_id,
            },
        )

    def _durable_uncertain(self, intent: ExecutionIntent, reason: str) -> None:
        payload = {
            "event_digest": domain_hash(
                "vivarium-local-execution-uncertain/v1",
                {"execution_intent_id": intent.execution_intent_id, "reason": reason},
            ),
            "execution_intent_id": intent.execution_intent_id,
            "uncertainty_reason": reason,
        }
        self._append_once(intent, "LOCAL_START_DEFERRED", payload)

    def run_or_recover(self, intent: ExecutionIntent) -> LocalExecutionResult:
        if not isinstance(intent, ExecutionIntent) or intent.execution_mode != "local":
            raise IntegrityError("local broker requires a local ExecutionIntent")
        local = self._active_local(intent)
        paths = self._paths(intent)
        with self.store._ordered_locks(execution_id=intent.execution_intent_id):
            if paths["intent"].exists():
                stored = self._read(paths["intent"], ExecutionIntent)
                if stored != intent:
                    raise IntegrityError("execution intent ID is bound to different bytes")
                return self._recover_locked(stored, paths)
            if local.analysis_state != AnalysisState.EXECUTION_PENDING:
                raise IntegrityError("new local execution requires EXECUTION_PENDING")
            self._crash("before_intent_fsync")
            self._persist(paths["intent"], intent)
            self._intent_event(intent)
            self._crash("after_intent_before_wrapper_start")

            def persist_receipt(receipt: ProcessReceipt) -> None:
                if receipt.execution_intent_id != intent.execution_intent_id:
                    raise IntegrityError("wrapper receipt binds a different execution intent")
                self._persist(paths["receipt"], receipt)

            self.harness.start_wrapper(
                intent, persist_receipt, crash_at=self.crash_at
            )
            return self._recover_locked(intent, paths)

    def recover(self, execution_intent_id: str) -> LocalExecutionResult:
        candidates = tuple(
            Path(self.store.root).glob(
                "runs/*/attempts/*/*/execution_logs/*.execution-intent.json"
            )
        )
        matches = []
        for path in candidates:
            intent = self._read(path, ExecutionIntent)
            if intent.execution_intent_id == execution_intent_id:
                matches.append(intent)
        if len(matches) != 1:
            raise IntegrityError("execution intent recovery identity is not unique")
        intent = matches[0]
        self._active_local(intent)
        paths = self._paths(intent)
        with self.store._ordered_locks(execution_id=execution_intent_id):
            return self._recover_locked(intent, paths)

    def _recover_locked(
        self, intent: ExecutionIntent, paths: dict[str, Path]
    ) -> LocalExecutionResult:
        self._intent_event(intent)
        if not paths["receipt"].exists():
            self._durable_uncertain(intent, "receipt_absent_attach_only")
            raise IntegrityError("local recovery is attach-only and receipt is absent")
        receipt = self._read(paths["receipt"], ProcessReceipt)
        if (
            receipt.execution_intent_id != intent.execution_intent_id
            or not self.harness.identity_matches(receipt)
        ):
            self._durable_uncertain(intent, "process_identity_mismatch")
            raise IntegrityError("local recovery process identity does not match")
        self._append_once(
            intent,
            "LOCAL_WRAPPER_ATTACHED",
            {
                "event_digest": receipt.process_receipt_digest,
                "attachment_kind": "recovered_wrapper",
                "execution_intent_id": intent.execution_intent_id,
                "process_receipt_digest": receipt.process_receipt_digest,
                "attempt_id": intent.attempt_id,
            },
        )
        terminal = self.harness.collect_terminal(receipt)
        if terminal is None:
            raise IntegrityError("local terminal evidence is not yet durable")
        reap_result = self.harness.reap_descendants(receipt)
        cut = self._cut_from_terminal(intent, receipt, terminal, reap_result, paths)
        if paths["cut"].exists():
            if self._read(paths["cut"], ExecutionEvidenceCut) != cut:
                raise IntegrityError("execution evidence cut bytes disagree on recovery")
        else:
            self._persist(paths["cut"], cut)
        self._append_once(
            intent,
            "TERMINAL_EVIDENCE_FROZEN",
            {
                "event_digest": cut.execution_evidence_cut_digest,
                "evidence_kind": "terminal_cut",
                "execution_intent_id": intent.execution_intent_id,
                "process_receipt_digest": receipt.process_receipt_digest,
                "execution_evidence_cut_digest": cut.execution_evidence_cut_digest,
                "attempt_id": intent.attempt_id,
            },
        )
        self._append_once(
            intent,
            "EVIDENCE_CUT_FROZEN",
            {
                "evidence_cut_id": f"execution-cut:{intent.execution_intent_id}",
                "head_digest": cut.execution_evidence_cut_digest,
            },
        )
        classification = classify_completion(cut)
        if paths["classification"].exists():
            if self._read(paths["classification"], CompletionClassification) != classification:
                raise IntegrityError("completion classification bytes disagree on recovery")
        else:
            self._persist(paths["classification"], classification)
        classification_event = self._append_once(
            intent,
            "COMPLETION_CLASSIFIED",
            {
                "classification_id": f"classification:{intent.execution_intent_id}",
                "evidence_cut_id": f"execution-cut:{intent.execution_intent_id}",
                "evidence_cut_digest": cut.execution_evidence_cut_digest,
                "outcome": classification.outcome,
            },
        )
        if classification.outcome != "success":
            return LocalExecutionResult(intent, receipt, cut, classification, None)
        self._crash("after_classification_before_proof")
        proof = build_completion_proof(classification, cut)
        if paths["proof"].exists():
            if self._read(paths["proof"], CompletionProof) != proof:
                raise IntegrityError("completion proof bytes disagree on recovery")
        else:
            self._persist(paths["proof"], proof)
        local = self._active_local(intent)
        durable_classification = next(
            item
            for item in local.completion_classifications
            if item.event_id == classification_event.event_id
        )
        self._append_once(
            intent,
            "COMPLETION_PROOF_RECORDED",
            {
                "completion_proof_id": f"proof:{intent.execution_intent_id}",
                "completion_proof_digest": proof.completion_proof_digest,
                "classification_id": durable_classification.classification_id,
                "classification_event_id": durable_classification.event_id,
                "classification_event_hash": durable_classification.event_hash,
                "classification_digest": durable_classification.classification_digest,
                "evidence_cut_id": durable_classification.evidence_cut_id,
                "evidence_cut_digest": durable_classification.evidence_cut_digest,
            },
        )
        return LocalExecutionResult(intent, receipt, cut, classification, proof)

    def _cut_from_terminal(
        self,
        intent: ExecutionIntent,
        receipt: ProcessReceipt,
        terminal: dict[str, Any],
        reap_result: Any,
        paths: dict[str, Path],
    ) -> ExecutionEvidenceCut:
        required = {
            "exit_code",
            "signal",
            "oom",
            "preempted",
            "cancelled",
            "sentinel_digest",
            "output_quiescence_manifest_digest",
            "terminal_evidence_refs",
            "process_terminal",
            "quiescence_receipt",
            "quiescence_receipt_digest",
        }
        if not isinstance(terminal, dict) or set(terminal) != required:
            raise IntegrityError("local harness terminal evidence has invalid fields")
        failure_flags = []
        if terminal["oom"]:
            failure_flags.append("oom")
        process_terminal = terminal["process_terminal"] is True
        if not process_terminal:
            failure_flags.append("process_not_terminal")
        containment_closed = (
            isinstance(reap_result, dict)
            and set(reap_result) == {"observed_descendant_count", "containment_refs"}
            and reap_result["observed_descendant_count"] == 0
            and tuple(reap_result["containment_refs"]) == ()
        )
        if not containment_closed:
            failure_flags.append("descendant_containment_open")
        quiescence_body = terminal["quiescence_receipt"]
        expected_quiescence = {
            "schema_version": "vivarium.local-quiescence-receipt/v1",
            "execution_intent_id": intent.execution_intent_id,
            "process_receipt_digest": receipt.process_receipt_digest,
            "stdout_digest": receipt.stdout_digest,
            "stderr_digest": receipt.stderr_digest,
            "output_quiescence_manifest_digest": terminal[
                "output_quiescence_manifest_digest"
            ],
            "observed_descendant_count": 0,
            "containment_refs": [],
        }
        quiescence_valid = (
            isinstance(quiescence_body, dict)
            and quiescence_body == expected_quiescence
            and _is_digest(terminal["quiescence_receipt_digest"])
            and domain_hash(
                "vivarium-local-quiescence-receipt/v1", quiescence_body
            )
            == terminal["quiescence_receipt_digest"]
        )
        if quiescence_valid:
            raw = canonical_bytes(quiescence_body)
            if paths["quiescence"].exists():
                quiescence_valid = paths["quiescence"].read_bytes() == raw
            else:
                durable_replace(paths["quiescence"], raw)
            quiescence_valid = quiescence_valid and paths["quiescence"].read_bytes() == raw
        if not quiescence_valid:
            failure_flags.append("quiescence_receipt_invalid")
        terminal_refs = tuple(terminal["terminal_evidence_refs"])
        if quiescence_valid:
            terminal_refs = (*terminal_refs, terminal["quiescence_receipt_digest"])
        absence_evidence = []
        if process_terminal:
            absence_evidence.append("process_exited")
        if quiescence_valid and containment_closed:
            absence_evidence.append("outputs_quiescent")
        return ExecutionEvidenceCut(
            EXECUTION_EVIDENCE_CUT_SCHEMA,
            intent.execution_intent_id,
            intent.run_id,
            intent.stage_id,
            intent.attempt_id,
            "local_process",
            f"{receipt.boot_id}:{receipt.pid}:{receipt.process_start_identity}",
            terminal_refs,
            tuple(failure_flags),
            tuple(absence_evidence),
            terminal["exit_code"],
            terminal["signal"],
            terminal["oom"],
            terminal["preempted"],
            terminal["cancelled"],
            domain_hash("vivarium-local-maker-absence/v1", {}),
            domain_hash("vivarium-local-harness-absence/v1", {}),
            domain_hash("vivarium-local-harness-receipt-absence/v1", {}),
            domain_hash("vivarium-local-capability-revocation-absence/v1", {}),
            domain_hash(
                "vivarium-local-executor-identity/v1",
                {
                    "boot_id": receipt.boot_id,
                    "process_start_identity": receipt.process_start_identity,
                },
            ),
            domain_hash(
                "vivarium-local-execution-profile/v1",
                {
                    "cwd_digest": intent.cwd_digest,
                    "environment_digest": intent.environment_digest,
                },
            ),
            domain_hash("vivarium-local-scheduler-absence/v1", {}),
            terminal["sentinel_digest"],
            terminal["output_quiescence_manifest_digest"],
        )


_AGENT_ONLY_CAPABILITIES = frozenset(
    {"workspace_read", "workspace_write", "artifact_read", "artifact_write"}
)


def complete_agent_only(
    store: Any, intent: ExecutionIntent, evidence: AgentOnlyEvidence
) -> AgentOnlyCompletionResult:
    if not isinstance(intent, ExecutionIntent) or intent.execution_mode != "agent_only":
        raise IntegrityError("agent-only completion requires an agent_only intent")
    if not isinstance(evidence, AgentOnlyEvidence):
        raise IntegrityError("agent-only completion requires frozen evidence")
    broker = LocalExecutionBroker(store, None)
    local = broker._active_local(intent)
    paths = broker._paths(intent)
    with store._ordered_locks(execution_id=intent.execution_intent_id):
        if paths["intent"].exists():
            if broker._read(paths["intent"], ExecutionIntent) != intent:
                raise IntegrityError("agent execution intent bytes disagree on recovery")
        else:
            if local.analysis_state != AnalysisState.MAKING:
                raise IntegrityError("new agent-only completion requires MAKING")
            broker._persist(paths["intent"], intent)
        if paths["agent_evidence"].exists():
            if broker._read(paths["agent_evidence"], AgentOnlyEvidence) != evidence:
                raise IntegrityError("agent-only evidence bytes disagree on recovery")
        else:
            broker._persist(paths["agent_evidence"], evidence)
        broker._append_once(
            intent,
            "AGENT_EXECUTION_COMPLETED",
            {
                "event_digest": evidence.agent_only_evidence_digest,
                "execution_intent_id": intent.execution_intent_id,
                "agent_only_evidence_digest": evidence.agent_only_evidence_digest,
                "attempt_id": intent.attempt_id,
            },
        )
        authority_failures = tuple(
            field
            for field, kind, digest in (
                ("maker_assignment_unresolved", "maker-assignment", evidence.maker_assignment_digest),
                (
                    "maker_completion_unresolved",
                    "maker-harness-completion",
                    evidence.maker_harness_completion_receipt_digest,
                ),
                (
                    "capability_revocation_unresolved",
                    "capability-revocation",
                    evidence.capability_revocation_receipt_digest,
                ),
                (
                    "sealed_output_bundle_unresolved",
                    "sealed-output-bundle",
                    evidence.sealed_output_bundle_digest,
                ),
                (
                    "output_quiescence_unresolved",
                    "output-quiescence",
                    evidence.output_quiescence_manifest_digest,
                ),
            )
            if not _authority_object_resolves(store, kind, digest)
        )
        cut = _agent_only_cut(intent, evidence, authority_failures)
        if paths["cut"].exists():
            if broker._read(paths["cut"], ExecutionEvidenceCut) != cut:
                raise IntegrityError("agent evidence cut bytes disagree on recovery")
        else:
            broker._persist(paths["cut"], cut)
        cut_id = f"execution-cut:{intent.execution_intent_id}"
        broker._append_once(
            intent,
            "EVIDENCE_CUT_FROZEN",
            {"evidence_cut_id": cut_id, "head_digest": cut.execution_evidence_cut_digest},
        )
        classification = classify_completion(cut)
        if paths["classification"].exists():
            if broker._read(paths["classification"], CompletionClassification) != classification:
                raise IntegrityError("agent classification bytes disagree on recovery")
        else:
            broker._persist(paths["classification"], classification)
        classification_event = broker._append_once(
            intent,
            "COMPLETION_CLASSIFIED",
            {
                "classification_id": f"classification:{intent.execution_intent_id}",
                "evidence_cut_id": cut_id,
                "evidence_cut_digest": cut.execution_evidence_cut_digest,
                "outcome": classification.outcome,
            },
        )
        if classification.outcome != "success":
            return AgentOnlyCompletionResult(
                intent, evidence, cut, classification, None
            )
        proof = build_completion_proof(classification, cut)
        if paths["proof"].exists():
            if broker._read(paths["proof"], CompletionProof) != proof:
                raise IntegrityError("agent completion proof bytes disagree on recovery")
        else:
            broker._persist(paths["proof"], proof)
        local = broker._active_local(intent)
        durable_classification = next(
            item
            for item in local.completion_classifications
            if item.event_id == classification_event.event_id
        )
        broker._append_once(
            intent,
            "COMPLETION_PROOF_RECORDED",
            {
                "completion_proof_id": f"proof:{intent.execution_intent_id}",
                "completion_proof_digest": proof.completion_proof_digest,
                "classification_id": durable_classification.classification_id,
                "classification_event_id": durable_classification.event_id,
                "classification_event_hash": durable_classification.event_hash,
                "classification_digest": durable_classification.classification_digest,
                "evidence_cut_id": durable_classification.evidence_cut_id,
                "evidence_cut_digest": durable_classification.evidence_cut_digest,
            },
        )
        return AgentOnlyCompletionResult(intent, evidence, cut, classification, proof)


def _agent_only_cut(
    intent: ExecutionIntent,
    evidence: AgentOnlyEvidence,
    authority_failures: tuple[str, ...] = (),
) -> ExecutionEvidenceCut:
    requested = {value.lower() for value in evidence.requested_capabilities}
    observed = {value.lower() for value in evidence.observed_capabilities}
    disallowed = sorted((requested | observed) - _AGENT_ONLY_CAPABILITIES)
    failures = list(authority_failures)
    if not evidence.maker_terminal_success:
        failures.append("maker_terminal_not_success")
    if evidence.child_count:
        failures.append("live_child_tasks")
    if not _is_digest(evidence.capability_revocation_receipt_digest):
        failures.append("capability_revocation_missing")
    if not _is_digest(evidence.sealed_output_bundle_digest):
        failures.append("sealed_output_bundle_missing")
    if not _is_digest(evidence.output_quiescence_manifest_digest):
        failures.append("output_quiescence_missing")
    if disallowed:
        failures.append("disallowed_capability:" + ",".join(disallowed))
    absence = []
    if evidence.child_count == 0:
        absence.append("no_live_tasks")
    if _is_digest(evidence.capability_revocation_receipt_digest):
        absence.append("capabilities_revoked")
    if _is_digest(evidence.output_quiescence_manifest_digest):
        absence.append("outputs_quiescent")
    if not disallowed:
        absence.append("no_external_capabilities")
    return ExecutionEvidenceCut(
        EXECUTION_EVIDENCE_CUT_SCHEMA,
        intent.execution_intent_id,
        intent.run_id,
        intent.stage_id,
        intent.attempt_id,
        "agent_only",
        "",
        tuple(
            value
            for value in (
                evidence.maker_harness_completion_receipt_digest,
                evidence.capability_revocation_receipt_digest,
                evidence.sealed_output_bundle_digest,
            )
            if _is_digest(value)
        ),
        tuple(failures),
        tuple(absence),
        None,
        None,
        False,
        False,
        False,
        evidence.maker_assignment_digest,
        evidence.maker_harness_identity_digest,
        evidence.maker_harness_completion_receipt_digest,
        evidence.capability_revocation_receipt_digest,
        domain_hash("vivarium-agent-local-executor-absence/v1", {}),
        evidence.profile_digest,
        domain_hash("vivarium-agent-scheduler-absence/v1", {}),
        domain_hash("vivarium-agent-sentinel-absence/v1", {}),
        evidence.output_quiescence_manifest_digest,
    )
__all__ = [
    "COMPLETION_PROOF_SCHEMA",
    "EXECUTION_EVIDENCE_CUT_SCHEMA",
    "LOCAL_CRASH_POINTS",
    "AgentOnlyCompletionResult",
    "AgentOnlyEvidence",
    "CompletionClassification",
    "CompletionProof",
    "ExecutionEvidenceCut",
    "ExecutionIntent",
    "LocalExecutionBroker",
    "LocalExecutionResult",
    "ProcessReceipt",
    "build_completion_proof",
    "classify_completion",
    "complete_agent_only",
    "persist_execution_authority_object",
]
