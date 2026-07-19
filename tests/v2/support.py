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
from skills.vivarium.vivarium_v2.evidence import (
    persist_writer_closure,
    seal_evidence_bundle,
    seal_validator_evidence,
)
from skills.vivarium.vivarium_v2.roles import (
    CapabilityReceipt,
    build_checker_assignment,
    build_checker_review,
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


def _seal_commit_bundle(store, tx_id):
    identity = {
        "run_id": "run-1",
        "stage_id": f"stage-{tx_id}",
        "attempt_id": f"attempt-{tx_id}",
        "execution_intent_id": f"execution-{tx_id}",
    }
    workspace = (
        store.root
        / "runs"
        / "run-1"
        / "attempts"
        / identity["stage_id"]
        / identity["attempt_id"]
        / "workspace"
    )
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "result.txt").write_bytes(b"result\n")
    (workspace / "execution.log").write_bytes(b"complete\n")
    relative = lambda path: path.relative_to(store.root).as_posix()
    bundle = seal_evidence_bundle(
        store,
        **identity,
        execution_evidence_cut_digest=domain_hash(
            "vivarium-test-commit-cut/v1", {"tx": tx_id}
        ),
        payload_paths=(relative(workspace / "result.txt"),),
        log_paths=(relative(workspace / "execution.log"),),
        writer_closure_digest=persist_writer_closure(
            store, {**identity, "writer_closed": True}
        ),
        capability_revocation_receipt_digest=persist_execution_authority_object(
            store, "capability-revocation", {**identity, "revoked": True}
        ),
        authority_role="validator",
    )
    return bundle.evidence_bundle_digest


def valid_prepared_commit(
    store: ProjectStore, *, run_id: str = "run-1", **overrides
) -> PreparedCommit:
    if not store.capture()[1]:
        store.register_run(run_id, analysis_state="COLLECTING")
    if "evidence_bundle_digest" not in overrides:
        overrides["evidence_bundle_digest"] = _seal_commit_bundle(
            store, overrides.get("commit_tx_id", "commit-1")
        )
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


def evidence_sealing_fixture(root: Path):
    store = ProjectStore.init(root, FrozenClock("2026-07-19T00:00:00Z"))
    store.register_run("run-1", analysis_state="COLLECTING")
    directory = (
        store.root
        / "runs"
        / "run-1"
        / "attempts"
        / "stage-1"
        / "attempt-1"
        / "workspace"
    )
    directory.mkdir(parents=True)
    payload_a = directory / "a-result.txt"
    payload_b = directory / "b-result.txt"
    log = directory / "execution.log"
    payload_a.write_bytes(b"alpha\n")
    payload_b.write_bytes(b"beta\n")
    log.write_bytes(b"complete\n")
    identity = {
        "run_id": "run-1",
        "stage_id": "stage-1",
        "attempt_id": "attempt-1",
        "execution_intent_id": "execution-1",
    }
    writer_closure_digest = persist_writer_closure(
        store, {**identity, "writer_closed": True}
    )
    revocation_digest = persist_execution_authority_object(
        store, "capability-revocation", {**identity, "revoked": True}
    )
    relative = lambda path: path.relative_to(store.root).as_posix()
    return {
        "store": store,
        "directory": directory,
        "payload_paths": (relative(payload_b), relative(payload_a)),
        "log_paths": (relative(log),),
        "identity": identity,
        "execution_evidence_cut_digest": domain_hash(
            "vivarium-test-evidence-cut/v1", identity
        ),
        "writer_closure_digest": writer_closure_digest,
        "capability_revocation_receipt_digest": revocation_digest,
    }


def sealed_role_fixture(root: Path):
    fixture = evidence_sealing_fixture(root)
    bundle = seal_evidence_bundle(
        fixture["store"],
        **fixture["identity"],
        execution_evidence_cut_digest=fixture["execution_evidence_cut_digest"],
        payload_paths=fixture["payload_paths"],
        log_paths=fixture["log_paths"],
        writer_closure_digest=fixture["writer_closure_digest"],
        capability_revocation_receipt_digest=fixture[
            "capability_revocation_receipt_digest"
        ],
        authority_role="validator",
    )
    validator_seal = seal_validator_evidence(
        fixture["store"],
        bundle,
        validator_id="validator-1",
        validation_outcome="pass",
        findings={"hard_gates": "pass"},
    )
    fixture.update(
        {
            "bundle": bundle,
            "validator_seal": validator_seal,
            "mission_digest": domain_hash("vivarium-test-mission/v1", {}),
            "rubric_digest": domain_hash("vivarium-test-rubric/v1", {}),
            "acceptance_contract_digest": domain_hash(
                "vivarium-test-acceptance-contract/v1", {}
            ),
            "completion_claim_digest": domain_hash(
                "vivarium-test-completion-claim/v1", {}
            ),
        }
    )
    return fixture


def checker_receipt(
    checker_id: str = "checker-1",
    namespace: str = "checker-namespace-1",
    **overrides,
) -> CapabilityReceipt:
    values = {
        "receipt_id": f"receipt-{checker_id}",
        "role": "checker",
        "principal_id": checker_id,
        "capability_namespace": namespace,
        "granted_capabilities": ("checker_review_write",),
        "live_capabilities": (),
        "unresolved_capabilities": (),
        "isolation_level": "hard",
    }
    values.update(overrides)
    return CapabilityReceipt(**values)


def checker_assignment(fixture, receipt, assignment_id="assignment-1", **overrides):
    packet = {
        "assignment_id": assignment_id,
        "checker_id": receipt.principal_id,
        "capability_namespace": receipt.capability_namespace,
        "mission_digest": fixture["mission_digest"],
        "rubric_digest": fixture["rubric_digest"],
        "acceptance_contract_digest": fixture["acceptance_contract_digest"],
        "evidence_bundle_digest": fixture["bundle"].evidence_bundle_digest,
        "execution_evidence_cut_digest": fixture[
            "bundle"
        ].execution_evidence_cut_digest,
        "validator_seal_digest": fixture["validator_seal"].validator_seal_digest,
        "completion_claim_digest": fixture["completion_claim_digest"],
        "capability_receipt_digest": receipt.capability_receipt_digest,
    }
    packet.update(overrides)
    return build_checker_assignment(packet, receipt)


def passing_checker_review(assignment, receipt, **overrides):
    return build_checker_review(assignment, receipt, **overrides)


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
    "evidence_sealing_fixture",
    "sealed_role_fixture",
    "checker_receipt",
    "checker_assignment",
    "passing_checker_review",
    "local_execution_intent",
    "inject_once",
    "prepared_fixture",
    "valid_prepared_commit",
    "valid_commit_request",
]
