from __future__ import annotations

from pathlib import Path

from skills.vivarium.vivarium_v2.project import COMMIT_CRASH_POINTS, PreparedCommit, ProjectStore
from skills.vivarium.vivarium_v2.canonical import domain_hash
from skills.vivarium.vivarium_v2.execution import (
    AgentOnlyEvidence,
    EXECUTION_EVIDENCE_CUT_SCHEMA,
    ExecutionEvidenceCut,
    ExecutionIntent,
    ProcessReceipt,
    persist_execution_authority_object,
)


class FrozenClock:
    def __init__(self, value: str):
        self.value = value

    def __call__(self) -> str:
        return self.value


class InjectedCrash(RuntimeError):
    pass


def fixture_store_at_revision(root: Path, revision: int) -> ProjectStore:
    store = ProjectStore.init(root, FrozenClock("2026-07-18T00:00:00Z"))
    if revision:
        store.register_run("run-1", analysis_state="COLLECTING")
    namespaces = ("truth", "decision", "work", "memory", "run-registry")
    while store.capture()[0].project_revision < revision:
        store.append_fixture_event(
            namespaces[(store.capture()[0].project_revision - 1) % len(namespaces)]
        )
    return store


def valid_prepared_commit(
    store: ProjectStore, *, run_id: str = "run-1", **overrides
) -> PreparedCommit:
    if not store.capture()[1]:
        store.register_run(run_id, analysis_state="COLLECTING")
    return store.prepare_commit(valid_commit_request(run_id, **overrides))


def valid_commit_request(run_id: str = "run-1", **overrides):
    tx_id = overrides.get("commit_tx_id", "commit-1")
    digest = lambda name: domain_hash(f"vivarium-test-{name}/v1", {"tx": tx_id})
    return {
        "run_id": run_id,
        "commit_tx_id": tx_id,
        "evidence_bundle_digest": digest("bundle"),
        "completion_claim_digest": digest("claim"),
        "completion_proof_digest": digest("proof"),
        "validator_report_digest": digest("validator"),
        "review_digests": (digest("review"),),
        "quorum_decision_digest": digest("quorum"),
        "budget_digest": digest("budget"),
        "checker_quorum_valid": True,
        "budget_available": True,
        "completion_success": True,
        **overrides,
    }


def prepared_fixture(root: Path) -> ProjectStore:
    store = ProjectStore.init(root, FrozenClock("2026-07-18T00:00:00Z"))
    store.register_run("run-1", analysis_state="COLLECTING")
    prepared = valid_prepared_commit(store)
    store._test_prepared_commit = prepared
    return store


def execution_evidence_cut(**overrides) -> ExecutionEvidenceCut:
    digest = lambda name: domain_hash(f"vivarium-test-execution-{name}/v1", {})
    values = {
        "schema_version": EXECUTION_EVIDENCE_CUT_SCHEMA,
        "execution_intent_id": "execution-1",
        "run_id": "run-1",
        "stage_id": "stage-1",
        "attempt_id": "attempt-1",
        "execution_kind": "local_process",
        "process_or_job_ref": "local:boot:123:start",
        "terminal_evidence_refs": (digest("receipt"), digest("terminal")),
        "failure_flags": (),
        "absence_evidence": ("process_exited", "outputs_quiescent"),
        "exit_code": 0,
        "signal": None,
        "oom": False,
        "preempted": False,
        "cancelled": False,
        "maker_assignment_digest": digest("maker-assignment-absent"),
        "maker_harness_identity_digest": digest("maker-harness-absent"),
        "maker_harness_completion_receipt_digest": digest("maker-receipt-absent"),
        "capability_revocation_receipt_digest": digest("revocation-absent"),
        "local_executor_identity_digest": digest("local-executor"),
        "profile_digest": digest("profile"),
        "scheduler_fingerprint": digest("scheduler-absent"),
        "sentinel_digest": digest("sentinel-absent"),
        "output_quiescence_manifest_digest": digest("quiescence"),
    }
    values.update(overrides)
    return ExecutionEvidenceCut(**values)


def local_execution_intent(**overrides) -> ExecutionIntent:
    values = {
        "execution_intent_id": "local-execution-1",
        "run_id": "run-1",
        "stage_id": "stage-1",
        "attempt_id": "attempt-1",
        "execution_mode": "local",
        "argv": ("fake-tool", "--version"),
        "cwd_digest": domain_hash("vivarium-test-cwd/v1", {}),
        "environment_digest": domain_hash("vivarium-test-environment/v1", {}),
        "execution_request_key": "local-request-1",
    }
    values.update(overrides)
    return ExecutionIntent(**values)


def agent_only_intent(**overrides) -> ExecutionIntent:
    values = {
        "execution_mode": "agent_only",
        "argv": ("agent-task",),
        "execution_request_key": "agent-request-1",
    }
    values.update(overrides)
    return local_execution_intent(**values)


def agent_only_evidence(store=None, **overrides) -> AgentOnlyEvidence:
    digest = lambda name: domain_hash(f"vivarium-test-agent-{name}/v1", {})
    authority = {}
    if store is not None:
        authority = {
            "maker_assignment_digest": persist_execution_authority_object(
                store, "maker-assignment", {"assignment": "agent-task", "attempt_id": "attempt-1"}
            ),
            "maker_harness_completion_receipt_digest": persist_execution_authority_object(
                store,
                "maker-harness-completion",
                {"execution_intent_id": "local-execution-1", "terminal": True},
            ),
            "capability_revocation_receipt_digest": persist_execution_authority_object(
                store,
                "capability-revocation",
                {"execution_intent_id": "local-execution-1", "revoked": True},
            ),
            "sealed_output_bundle_digest": persist_execution_authority_object(
                store,
                "sealed-output-bundle",
                {"execution_intent_id": "local-execution-1", "sealed": True},
            ),
            "output_quiescence_manifest_digest": persist_execution_authority_object(
                store,
                "output-quiescence",
                {"execution_intent_id": "local-execution-1", "quiescent": True},
            ),
        }
    values = {
        "maker_terminal_success": True,
        "child_count": 0,
        "capability_revocation_receipt_digest": digest("revocation"),
        "sealed_output_bundle_digest": digest("output-bundle"),
        "output_quiescence_manifest_digest": digest("quiescence"),
        "requested_capabilities": ("workspace_read", "workspace_write"),
        "observed_capabilities": ("workspace_read", "workspace_write"),
        "maker_assignment_digest": digest("assignment"),
        "maker_harness_identity_digest": digest("harness"),
        "maker_harness_completion_receipt_digest": digest("completion"),
        "profile_digest": digest("profile"),
        **authority,
    }
    values.update(overrides)
    return AgentOnlyEvidence(**values)


class FakeLocalHarness:
    def __init__(self, *, exit_code=0, signal=None, oom=False):
        self.main_start_count = 0
        self.descendant_count = 0
        self.reaped_descendant_count = 0
        self.identity_valid = True
        self.exit_code = exit_code
        self.signal = signal
        self.oom = oom
        self._receipts = {}
        self._terminal = {}

    def _terminal_value(self, intent, receipt):
        digest = lambda name: domain_hash(
            f"vivarium-test-local-{name}/v1",
            {"execution_intent_id": intent.execution_intent_id},
        )
        quiescence = {
            "schema_version": "vivarium.local-quiescence-receipt/v1",
            "execution_intent_id": intent.execution_intent_id,
            "process_receipt_digest": receipt.process_receipt_digest,
            "stdout_digest": receipt.stdout_digest,
            "stderr_digest": receipt.stderr_digest,
            "output_quiescence_manifest_digest": digest("quiescence"),
            "observed_descendant_count": 0,
            "containment_refs": [],
        }
        return {
            "exit_code": self.exit_code,
            "signal": self.signal,
            "oom": self.oom,
            "preempted": False,
            "cancelled": False,
            "sentinel_digest": digest("sentinel"),
            "output_quiescence_manifest_digest": digest("quiescence"),
            "terminal_evidence_refs": (digest("terminal"), digest("logs")),
            "process_terminal": True,
            "quiescence_receipt": quiescence,
            "quiescence_receipt_digest": domain_hash(
                "vivarium-local-quiescence-receipt/v1", quiescence
            ),
        }

    def start_wrapper(self, intent, persist_receipt_callback, crash_at=None):
        digest = lambda name: domain_hash(
            f"vivarium-test-local-{name}/v1",
            {"execution_intent_id": intent.execution_intent_id},
        )
        receipt = ProcessReceipt(
            intent.execution_intent_id,
            "boot-test",
            4101,
            4101,
            "boot-test:4101:start-1",
            digest("stdout"),
            digest("stderr"),
        )
        self._receipts[intent.execution_intent_id] = receipt
        persist_receipt_callback(receipt)
        if crash_at == "after_receipt_before_attach":
            raise RuntimeError(crash_at)
        self.main_start_count += 1
        self._terminal[intent.execution_intent_id] = self._terminal_value(intent, receipt)
        if crash_at in {"after_child_spawn", "after_wrapper_exit_before_quiescence"}:
            self.descendant_count += 1
            raise RuntimeError(crash_at)
        return receipt

    def identity_matches(self, receipt):
        return self.identity_valid and self._receipts.get(
            receipt.execution_intent_id
        ) == receipt

    def collect_terminal(self, receipt):
        return self._terminal.get(receipt.execution_intent_id)

    def reap_descendants(self, receipt):
        self.reaped_descendant_count += self.descendant_count
        self.descendant_count = 0
        return {"observed_descendant_count": 0, "containment_refs": ()}


def inject_once(store: ProjectStore, point: str) -> None:
    if point not in COMMIT_CRASH_POINTS:
        raise ValueError(point)
    fired = False

    def injector(observed: str) -> None:
        nonlocal fired
        if observed == point and not fired:
            fired = True
            raise InjectedCrash(point)

    store.fault_injector = injector
    try:
        store.complete_commit(store._test_prepared_commit)
    except InjectedCrash:
        pass
    finally:
        store.fault_injector = None
    if not fired:
        raise AssertionError(f"fault point was not reached: {point}")


__all__ = [
    "COMMIT_CRASH_POINTS",
    "FrozenClock",
    "FakeLocalHarness",
    "agent_only_evidence",
    "agent_only_intent",
    "fixture_store_at_revision",
    "execution_evidence_cut",
    "local_execution_intent",
    "inject_once",
    "prepared_fixture",
    "valid_prepared_commit",
    "valid_commit_request",
]
