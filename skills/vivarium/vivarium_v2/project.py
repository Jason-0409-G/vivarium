from __future__ import annotations

import base64
import fcntl
import os
import tempfile
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from ._project_support import _object_projection, empty_project_state_root
from ._replay_common import ACTIVE_ROOT_DOMAIN, GENESIS_LEDGER_IDS, GENESIS_TYPES
from .canonical import canonical_bytes, domain_hash, durable_replace
from .errors import IntegrityError
from .events import Event, ZERO_HASH
from .ledger import Ledger
from .reducers import federate, reduce_project_cut, reduce_project_validity, reduce_run, reduce_run_validity
from .state import (
    AnalysisState,
    COMMIT_ABORT_REASON_TARGET,
    COMPLETION_ABORT_OUTCOME,
    DependencyHead,
    FederatedState,
    ProjectPrefixes,
    ProjectObjectHead,
    ProjectSemanticCut,
    RunLocalState,
)


PROJECT_LEDGERS = (
    ("truth", "TRUTH_LEDGER_GENESIS"),
    ("decision", "DECISION_LEDGER_GENESIS"),
    ("work", "WORK_LEDGER_GENESIS"),
    ("memory", "MEMORY_LEDGER_GENESIS"),
    ("run-registry", "RUN_REGISTRY_LEDGER_GENESIS"),
)
COMMIT_CRASH_POINTS = (
    "artifact_write",
    "artifact_fsync",
    "prepare_fsync",
    "project_complete_cut_fsync",
    "projection_replace",
)
DEFAULT_POLICY_DIGEST = domain_hash(
    "vivarium-project-policy/v1", {"policy": "task4-default"}
)
INBOX_LIMIT = 4096


@dataclass(frozen=True)
class BranchHead:
    branch_id: str
    state_snapshot_id: str
    generation: int
    ancestry: tuple[str, ...]
    parent_branch_id: str | None = None
    specification_delta_digest: str | None = None


@dataclass(frozen=True)
class PreparedCommit:
    commit_tx_id: str
    run_id: str
    branch_id: str
    stage_key: str
    expected_branch_head: str
    expected_generation: int
    new_state_snapshot_id: str
    artifact_base64: str
    artifact_digest: str
    expected_work_root: str
    new_work_root: str
    acceptance_contract_digest: str
    evidence_bundle_digest: str
    payload_root_digest: str
    completion_claim_digest: str
    completion_proof_digest: str
    completion_grade: str
    execution_evidence_cut_digest: str
    validator_report_digest: str
    review_digests: tuple[str, ...]
    quorum_decision_digest: str
    budget_digest: str
    context_project_revision: int
    knowledge_dependency_vector_digest: str
    expected_dependency_closure_digest: str
    dependencies: tuple[DependencyHead, ...]
    checker_quorum_valid: bool
    budget_available: bool
    completion_success: bool
    locked_policy_digest: str
    evidence_cut_id: str
    evidence_cut_digest: str
    prepare_event_id: str = ""
    prepare_event_hash: str = ""


@dataclass(frozen=True)
class InboxReceipt:
    observation_id: str
    recheck_tx_id: str
    event: Event
    analysis_state: str
    oversize: bool


@dataclass(frozen=True)
class RecoveryState:
    project_cut: ProjectSemanticCut
    run_local_states: tuple[RunLocalState, ...]
    federated_states: tuple[FederatedState, ...]
    federated_state_root: str
    default_retrievable: bool
    analysis_state: str
    external_invocations: int = 0


FaultInjector = Callable[[str], None]


def _branch_projection(branch: BranchHead) -> dict[str, Any]:
    value = asdict(branch)
    value["ancestry"] = list(branch.ancestry)
    return value


@dataclass
class ProjectStore:
    root: Path
    clock: Any
    fault_injector: FaultInjector | None = None
    inbox_limit: int = INBOX_LIMIT

    @classmethod
    def init(
        cls,
        root: Path,
        clock: Any,
        *,
        locked_policy_digest: str = DEFAULT_POLICY_DIGEST,
    ) -> ProjectStore:
        root = Path(root)
        if root.exists():
            raise IntegrityError("project initialization refuses an existing path")
        root.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{root.name}.init-", dir=root.parent))
        for relative in ("ledgers", "runs", "locks", "quarantine", "artifacts", "projections"):
            (staging / relative).mkdir()
        durable_replace(staging / "ledgers" / "transactions.jsonl", b"")
        store = cls(staging, clock)
        for namespace, event_type in PROJECT_LEDGERS:
            canonical_namespace = namespace.replace("-", "_")
            ledger = store._project_ledger(namespace)
            store._append(
                ledger,
                event_type,
                {
                    "activated_objects": [],
                    "canonical_dependency_edges": [],
                    "initial_state_root": empty_project_state_root(canonical_namespace),
                    "locked_policy_digest": locked_policy_digest,
                },
                f"genesis-{namespace}",
            )
        store._write_projection()
        os.replace(staging, root)
        directory_fd = os.open(root.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return cls(root, clock)

    def _now(self) -> str:
        value = self.clock() if callable(self.clock) else self.clock.now()
        if not isinstance(value, str):
            raise IntegrityError("clock must return a UTC timestamp string")
        return value

    def _project_ledger(self, namespace: str) -> Ledger:
        canonical = namespace.replace("-", "_")
        if canonical not in GENESIS_LEDGER_IDS:
            raise IntegrityError("unknown project ledger namespace")
        filename = namespace.replace("_", "-") + ".jsonl"
        return Ledger(self.root / "ledgers" / filename, GENESIS_LEDGER_IDS[canonical])

    def _run_ledger(self, run_id: str) -> Ledger:
        return Ledger(self.root / "runs" / run_id / "events.jsonl", f"run:{run_id}")

    def _transaction_ledger(self) -> Ledger:
        return Ledger(self.root / "ledgers" / "transactions.jsonl", "project-transactions")

    def _append(self, ledger: Ledger, event_type: str, payload: dict[str, Any], tx_id: str) -> Event:
        recovered = ledger.recover()
        if recovered.quarantined_tail:
            ledger.quarantine_tail(self.root / "quarantine")
            raise IntegrityError("cannot append beyond a torn ledger tail")
        events = tuple(recovered.events)
        sequence = len(events)
        timestamp = self._now()
        event = Event.build(
            ledger_id=ledger.ledger_id,
            event_seq=sequence,
            event_id=f"{ledger.ledger_id}:{sequence}:{tx_id}:{event_type}",
            event_type=event_type,
            tx_id=tx_id,
            prev_event_hash=ZERO_HASH if not events else events[-1].event_hash,
            recorded_at=timestamp,
            effective_at=timestamp,
            payload=payload,
        )
        ledger.append(event)
        return event

    @contextmanager
    def _ordered_locks(
        self, *, branch_id: str | None = None, execution_id: str | None = None
    ) -> Iterator[None]:
        names = ["00-project-knowledge"]
        if branch_id is not None:
            names.append(f"20-branch-{branch_id}")
        if execution_id is not None:
            names.append(f"30-execution-{execution_id}")
        with ExitStack() as stack:
            handles = []
            for name in names:
                path = self.root / "locks" / f"{name}.lock"
                handle = stack.enter_context(path.open("a+b"))
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                handles.append(handle)
            try:
                yield
            finally:
                for handle in reversed(handles):
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _fault(self, point: str) -> None:
        if self.fault_injector is not None:
            self.fault_injector(point)

    def _prefixes(self) -> ProjectPrefixes:
        values: dict[str, tuple[Event, ...]] = {}
        for namespace, _ in PROJECT_LEDGERS:
            result = self._project_ledger(namespace).recover()
            if result.quarantined_tail:
                self._project_ledger(namespace).quarantine_tail(self.root / "quarantine")
                raise IntegrityError("project ledger has a torn tail")
            values[namespace.replace("-", "_")] = tuple(result.events)
        return ProjectPrefixes(**values)

    def capture(self) -> tuple[ProjectSemanticCut, Sequence[RunLocalState]]:
        cut = reduce_project_cut(self._prefixes())
        run_ids = tuple(
            event.payload["object_id"]
            for event in self._project_ledger("run-registry").recover().events
            if event.event_type == "RUN_REGISTERED"
        )
        locals_: list[RunLocalState] = []
        for run_id in run_ids:
            result = self._run_ledger(run_id).recover()
            if result.quarantined_tail:
                self._run_ledger(run_id).quarantine_tail(self.root / "quarantine")
                raise IntegrityError("registered run ledger has a torn tail")
            locals_.append(reduce_run(tuple(result.events)))
        return cut, tuple(locals_)

    def genesis_events(self) -> tuple[Event, ...]:
        return tuple(self._project_ledger(name).recover().events[0] for name, _ in PROJECT_LEDGERS)

    def append_fixture_event(self, namespace: str) -> Event:
        if namespace == "handoff":
            with self._ordered_locks():
                return self._append(
                    self._project_ledger("work"),
                    "HANDOFF_PUBLISHED",
                    {"artifact_digest": domain_hash("vivarium-handoff/v1", {"audit": True})},
                    "fixture-handoff",
                )
        canonical = namespace.replace("_", "-")
        event_types = {
            "truth": "FACT_ACTIVATED",
            "decision": "DECISION_ACTIVATED",
            "work": "STAGE_COMMITTED",
            "memory": "MEMORY_ACTIVATED",
            "run-registry": "RUN_REGISTRY_ACTIVATED",
        }
        if canonical not in event_types:
            raise IntegrityError("unknown fixture namespace")
        with self._ordered_locks():
            cut = reduce_project_cut(self._prefixes())
            revision = cut.project_revision + 1
            identity = f"fixture-{canonical}-{revision}"
            payload: dict[str, Any] = {
                "project_revision": revision,
                "object_type": "fixture",
                "object_id": identity,
                "object_head": f"head-{revision}",
                "dependencies": [],
            }
            if canonical == "work":
                payload.update(
                    {
                        "run_id": "fixture-run",
                        "run_event_id": "fixture-run-event",
                        "run_event_hash": domain_hash("vivarium-fixture/v1", {"run": revision}),
                        "commit_tx_id": f"fixture-commit-{revision}",
                        "prepare_event_id": "fixture-prepare",
                        "prepare_event_hash": domain_hash("vivarium-fixture/v1", {"prepare": revision}),
                        "evidence_cut_id": "fixture-cut",
                        "evidence_cut_digest": domain_hash("vivarium-fixture/v1", {"cut": revision}),
                    }
                )
            return self._append(
                self._project_ledger(canonical), event_types[canonical], payload, identity
            )

    def register_run(
        self,
        run_id: str,
        *,
        analysis_state: str = "PLANNED",
        branch_id: str = "branch-1",
    ) -> Event:
        if not run_id or "/" in run_id or ".." in run_id:
            raise IntegrityError("run_id is not a safe stable identifier")
        with self._ordered_locks(branch_id=branch_id):
            run_dir = self.root / "runs" / run_id
            if run_dir.exists():
                events = tuple(self._run_ledger(run_id).recover().events)
                already_registered = run_id in self._registered_run_ids()
                if (
                    already_registered
                    or len(events) != 1
                    or events[0].event_type != "RUN_LEDGER_GENESIS"
                    or events[0].payload.get("run_id") != run_id
                ):
                    raise IntegrityError("run is already registered or partial bytes mismatch")
                genesis = events[0]
                analysis_state = genesis.payload["analysis_state"]
                branch_id = genesis.payload["branch_id"]
            else:
                run_dir.mkdir(parents=True)
                runs_fd = os.open(self.root / "runs", os.O_RDONLY)
                try:
                    os.fsync(runs_fd)
                finally:
                    os.close(runs_fd)
                policy_digest = reduce_project_cut(self._prefixes()).locked_policy_digest
                genesis = self._append(
                    self._run_ledger(run_id),
                    "RUN_LEDGER_GENESIS",
                    {
                        "run_id": run_id,
                        "analysis_state": analysis_state,
                        "attempt_id": "attempt-1",
                        "branch_id": branch_id,
                        "logical_scope_key": f"scope:{run_id}",
                        "request_key": f"request:{run_id}:1",
                        "intent_key": f"intent:{run_id}:1",
                        "execution_key": f"execution:{run_id}:1",
                        "local_execution_key": f"local:{run_id}:1",
                        "submission_key": f"submission:{run_id}:1",
                        "operation_keys": [],
                        "merge_policy_digest": policy_digest,
                    },
                    f"run-genesis-{run_id}",
                )
            registration = {
                "run_id": run_id,
                "ledger_id": genesis.ledger_id,
                "ledger_path": f"runs/{run_id}/events.jsonl",
                "side_effect_scope_namespace": f"run:{run_id}",
            }
            registration_bytes = canonical_bytes(registration)
            registration_digest = domain_hash("vivarium-run-registration/v1", registration)
            durable_replace(
                self.root / "artifacts" / f"{registration_digest[7:]}.registration.json",
                registration_bytes,
            )
            revision = reduce_project_cut(self._prefixes()).project_revision + 1
            return self._append(
                self._project_ledger("run-registry"),
                "RUN_REGISTERED",
                {
                    "project_revision": revision,
                    "object_type": "run-registration",
                    "object_id": run_id,
                    "object_head": registration_digest,
                    "dependencies": [],
                },
                f"register-{run_id}",
            )

    def _transactions(self, event_type: str | None = None) -> tuple[Event, ...]:
        events = tuple(self._transaction_ledger().recover().events)
        return events if event_type is None else tuple(e for e in events if e.event_type == event_type)

    def _branch_heads(self) -> dict[str, BranchHead]:
        heads: dict[str, BranchHead] = {"branch-1": BranchHead("branch-1", ZERO_HASH, 0, (ZERO_HASH,))}
        for event in self._project_ledger("work").recover().events[1:]:
            payload = event.payload
            if event.event_type == "STAGE_COMMITTED" and "branch_id" in payload:
                prior = heads[payload["branch_id"]]
                heads[payload["branch_id"]] = BranchHead(
                    prior.branch_id,
                    payload["new_state_snapshot_id"],
                    payload["new_generation"],
                    (*prior.ancestry, payload["new_state_snapshot_id"]),
                    prior.parent_branch_id,
                    prior.specification_delta_digest,
                )
            elif event.event_type == "ROLLBACK_COMMITTED":
                prior = heads[payload["branch_id"]]
                target_index = prior.ancestry.index(payload["target_checkpoint_id"])
                heads[payload["branch_id"]] = replace(
                    prior,
                    state_snapshot_id=payload["target_checkpoint_id"],
                    generation=payload["new_generation"],
                    ancestry=prior.ancestry[: target_index + 1],
                )
            elif event.event_type == "BRANCH_FORKED":
                parent = heads[payload["parent_branch_id"]]
                checkpoint_index = parent.ancestry.index(
                    payload["parent_checkpoint_id"]
                )
                heads[payload["branch_id"]] = BranchHead(
                    payload["branch_id"],
                    payload["parent_checkpoint_id"],
                    0,
                    parent.ancestry[: checkpoint_index + 1],
                    payload["parent_branch_id"],
                    payload["specification_delta_digest"],
                )
        return heads

    def branch_head(self, branch_id: str = "branch-1") -> BranchHead:
        try:
            return self._branch_heads()[branch_id]
        except KeyError as exc:
            raise IntegrityError("unknown branch") from exc

    def _normalize_commit(self, request: Mapping[str, Any]) -> PreparedCommit:
        required_authority = {
            "evidence_bundle_digest",
            "completion_claim_digest",
            "completion_proof_digest",
            "validator_report_digest",
            "review_digests",
            "quorum_decision_digest",
            "budget_digest",
            "checker_quorum_valid",
            "budget_available",
            "completion_success",
        }
        if not required_authority <= set(request):
            raise IntegrityError("commit request lacks explicit durable authority fields")
        cut, locals_ = self.capture()
        run_id = str(request.get("run_id") or (locals_[0].run_id if len(locals_) == 1 else ""))
        if not run_id:
            raise IntegrityError("commit requires one registered run_id")
        branch_id = str(request.get("branch_id", "branch-1"))
        branch = self.branch_head(branch_id)
        sequence = len(self._transactions("COMMIT_INTENT")) + 1
        tx_id = str(request.get("commit_tx_id", f"commit-{sequence}"))
        artifact = request.get("artifact_bytes", b"artifact")
        if isinstance(artifact, str):
            artifact = artifact.encode("utf-8")
        if not isinstance(artifact, bytes):
            raise IntegrityError("artifact_bytes must be bytes or text")
        artifact_base64 = base64.b64encode(artifact).decode("ascii")
        artifact_digest = domain_hash("vivarium-artifact/v1", artifact_base64)
        dependencies = tuple(
            sorted(
                item if isinstance(item, DependencyHead) else DependencyHead(**item)
                for item in request.get("dependencies", ())
            )
        )
        dependency_projection = [asdict(item) for item in dependencies]
        new_snapshot = str(
            request.get(
                "new_state_snapshot_id",
                domain_hash("vivarium-state-snapshot/v1", {"tx": tx_id, "artifact": artifact_digest}),
            )
        )
        staged_object = ProjectObjectHead(
            "work",
            "stage",
            str(request.get("stage_key", f"stage:{run_id}")),
            new_snapshot,
            dependencies,
            run_id,
        )
        next_work_objects = tuple(
            sorted(
                (
                    item
                    for item in cut.active_object_heads
                    if not (
                        item.namespace == "work"
                        and item.object_id == staged_object.object_id
                    )
                ),
            )
        ) + (staged_object,)
        next_work_root = domain_hash(
            ACTIVE_ROOT_DOMAIN,
            {
                "namespace": "work",
                "objects": [
                    _object_projection(item)
                    for item in sorted(next_work_objects)
                    if item.namespace == "work"
                ],
            },
        )
        digest = lambda label: str(
            request.get(label, domain_hash(f"vivarium-{label.replace('_', '-')}/v1", {"tx": tx_id}))
        )
        return PreparedCommit(
            tx_id,
            run_id,
            branch_id,
            staged_object.object_id,
            str(request.get("expected_branch_head", branch.state_snapshot_id)),
            int(request.get("expected_generation", branch.generation)),
            new_snapshot,
            artifact_base64,
            artifact_digest,
            str(request.get("expected_work_root", cut.active_work_root)),
            str(request.get("new_work_root", next_work_root)),
            digest("acceptance_contract_digest"),
            str(request["evidence_bundle_digest"]),
            str(request.get("payload_root_digest", artifact_digest)),
            str(request["completion_claim_digest"]),
            str(request["completion_proof_digest"]),
            str(request.get("completion_grade", "L1")),
            digest("execution_evidence_cut_digest"),
            str(request["validator_report_digest"]),
            tuple(sorted(request["review_digests"])),
            str(request["quorum_decision_digest"]),
            str(request["budget_digest"]),
            int(request.get("context_project_revision", cut.project_revision)),
            str(
                request.get(
                    "knowledge_dependency_vector_digest",
                    domain_hash("vivarium-knowledge-vector/v1", dependency_projection),
                )
            ),
            str(
                request.get(
                    "expected_dependency_closure_digest",
                    domain_hash("vivarium-dependency-closure/v1", dependency_projection),
                )
            ),
            dependencies,
            bool(request["checker_quorum_valid"]),
            bool(request["budget_available"]),
            bool(request["completion_success"]),
            str(request.get("locked_policy_digest", cut.locked_policy_digest)),
            str(request.get("evidence_cut_id", f"cut:{tx_id}")),
            str(request.get("evidence_cut_digest", digest("evidence_cut_digest"))),
        )

    def prepare_commit(self, request: Mapping[str, Any] | PreparedCommit) -> PreparedCommit:
        prepared = request if isinstance(request, PreparedCommit) else self._normalize_commit(request)
        with self._ordered_locks(branch_id=prepared.branch_id, execution_id=prepared.commit_tx_id):
            existing = next(
                (e for e in self._transactions("COMMIT_INTENT") if e.payload["commit_tx_id"] == prepared.commit_tx_id),
                None,
            )
            if existing is not None:
                stored = self._prepared_from_payload(existing.payload)
                if replace(stored, prepare_event_id="", prepare_event_hash="") != replace(
                    prepared, prepare_event_id="", prepare_event_hash=""
                ):
                    raise IntegrityError("commit_tx_id is already bound to different bytes")
                return self._resume_preparation(stored)
            self._append(
                self._transaction_ledger(),
                "COMMIT_INTENT",
                self._prepared_payload(prepared),
                prepared.commit_tx_id,
            )
            return self._resume_preparation(prepared)

    def _resume_preparation(self, prepared: PreparedCommit) -> PreparedCommit:
        if (
            not prepared.completion_success
            or not prepared.checker_quorum_valid
            or not prepared.budget_available
        ):
            raise IntegrityError("commit intent does not authorize a success preparation")
        self._write_artifact(prepared)
        run_ledger = self._run_ledger(prepared.run_id)

        def append_once(event_type: str, payload: dict[str, Any]) -> Event:
            existing = next(
                (
                    event
                    for event in run_ledger.recover().events
                    if event.tx_id == prepared.commit_tx_id
                    and event.event_type == event_type
                ),
                None,
            )
            if existing is not None:
                if existing.payload != payload:
                    raise IntegrityError("resumed commit authority bytes do not match")
                return existing
            return self._append(run_ledger, event_type, payload, prepared.commit_tx_id)

        local = reduce_run(tuple(run_ledger.recover().events))
        evidence = append_once(
            "EVIDENCE_CUT_FROZEN",
            {
                "evidence_cut_id": prepared.evidence_cut_id,
                "head_digest": prepared.evidence_cut_digest,
            },
        )
        authority_chain_types = {
            "EVIDENCE_BUNDLE_FROZEN",
            "COMPLETION_CLASSIFIED",
            "COMPLETION_PROOF_RECORDED",
            "COMPLETION_SUCCESS_PROVEN",
            "VALIDATOR_REPORT_SEALED",
            "VALIDATION_PASSED",
            "CHECKER_ALLOCATED",
            "CHECKER_REVIEW_SEALED",
            "QUORUM_DECISION_SEALED",
            "CHECKER_QUORUM_PASSED",
        }
        authority_chain_started = any(
            event.tx_id == prepared.commit_tx_id
            and event.event_type in authority_chain_types
            for event in run_ledger.recover().events
        )
        if local.analysis_state == AnalysisState.COLLECTING or authority_chain_started:
            bundle = append_once(
                "EVIDENCE_BUNDLE_FROZEN",
                {
                    "bundle_id": f"bundle:{prepared.commit_tx_id}",
                    "bundle_digest": prepared.evidence_bundle_digest,
                    "evidence_cut_id": prepared.evidence_cut_id,
                    "evidence_cut_event_id": evidence.event_id,
                    "evidence_cut_event_hash": evidence.event_hash,
                    "evidence_cut_digest": prepared.evidence_cut_digest,
                },
            )
            classification_event = append_once(
                "COMPLETION_CLASSIFIED",
                {
                    "classification_id": f"classification:{prepared.commit_tx_id}",
                    "evidence_cut_id": prepared.evidence_cut_id,
                    "evidence_cut_digest": prepared.evidence_cut_digest,
                    "outcome": "success",
                },
            )
            classified = reduce_run(tuple(run_ledger.recover().events))
            classification = classified.completion_classifications[-1]
            proof = append_once(
                "COMPLETION_PROOF_RECORDED",
                {
                    "completion_proof_id": f"proof:{prepared.commit_tx_id}",
                    "completion_proof_digest": prepared.completion_proof_digest,
                    "classification_id": classification.classification_id,
                    "classification_event_id": classification_event.event_id,
                    "classification_event_hash": classification_event.event_hash,
                    "classification_digest": classification.classification_digest,
                    "evidence_cut_id": prepared.evidence_cut_id,
                    "evidence_cut_digest": prepared.evidence_cut_digest,
                },
            )
            append_once(
                "COMPLETION_SUCCESS_PROVEN",
                {
                    "completion_proof_id": f"proof:{prepared.commit_tx_id}",
                    "completion_proof_event_id": proof.event_id,
                    "completion_proof_event_hash": proof.event_hash,
                    "completion_proof_digest": prepared.completion_proof_digest,
                    "bundle_id": f"bundle:{prepared.commit_tx_id}",
                    "bundle_event_id": bundle.event_id,
                    "bundle_event_hash": bundle.event_hash,
                    "bundle_digest": prepared.evidence_bundle_digest,
                },
            )
            report = append_once(
                "VALIDATOR_REPORT_SEALED",
                {
                    "validator_report_id": f"validator:{prepared.commit_tx_id}",
                    "validator_report_digest": prepared.validator_report_digest,
                    "completion_proof_id": f"proof:{prepared.commit_tx_id}",
                    "completion_proof_event_id": proof.event_id,
                    "completion_proof_event_hash": proof.event_hash,
                    "completion_proof_digest": prepared.completion_proof_digest,
                    "bundle_id": f"bundle:{prepared.commit_tx_id}",
                    "bundle_event_id": bundle.event_id,
                    "bundle_event_hash": bundle.event_hash,
                    "bundle_digest": prepared.evidence_bundle_digest,
                    "validation_outcome": "pass",
                },
            )
            append_once(
                "VALIDATION_PASSED",
                {
                    "validator_report_id": f"validator:{prepared.commit_tx_id}",
                    "validator_report_event_id": report.event_id,
                    "validator_report_event_hash": report.event_hash,
                    "validator_report_digest": prepared.validator_report_digest,
                },
            )
            append_once(
                "CHECKER_ALLOCATED",
                {
                    "event_digest": domain_hash(
                        "vivarium-checker-allocation/v1", {"tx": prepared.commit_tx_id}
                    )
                },
            )
            review = append_once(
                "CHECKER_REVIEW_SEALED",
                {
                    "checker_review_id": f"review:{prepared.commit_tx_id}",
                    "checker_review_digest": prepared.review_digests[0],
                    "validator_report_id": f"validator:{prepared.commit_tx_id}",
                    "validator_report_event_id": report.event_id,
                    "validator_report_event_hash": report.event_hash,
                    "validator_report_digest": prepared.validator_report_digest,
                    "review_outcome": "pass",
                },
            )
            quorum = append_once(
                "QUORUM_DECISION_SEALED",
                {
                    "quorum_decision_id": f"quorum:{prepared.commit_tx_id}",
                    "quorum_decision_digest": prepared.quorum_decision_digest,
                    "validator_report_id": f"validator:{prepared.commit_tx_id}",
                    "validator_report_event_id": report.event_id,
                    "validator_report_event_hash": report.event_hash,
                    "validator_report_digest": prepared.validator_report_digest,
                    "checker_review_id": f"review:{prepared.commit_tx_id}",
                    "checker_review_event_id": review.event_id,
                    "checker_review_event_hash": review.event_hash,
                    "checker_review_digest": prepared.review_digests[0],
                    "quorum_outcome": "pass",
                    "budget_available": prepared.budget_available,
                    "budget_digest": prepared.budget_digest,
                    "completion_claim_digest": prepared.completion_claim_digest,
                },
            )
            append_once(
                "CHECKER_QUORUM_PASSED",
                {
                    "quorum_decision_id": f"quorum:{prepared.commit_tx_id}",
                    "quorum_decision_event_id": quorum.event_id,
                    "quorum_decision_event_hash": quorum.event_hash,
                    "quorum_decision_digest": prepared.quorum_decision_digest,
                },
            )
            local = reduce_run(tuple(run_ledger.recover().events))
        if local.analysis_state not in {
            AnalysisState.COMMITTING,
            AnalysisState.RECOVERY_REQUIRED,
        }:
            raise IntegrityError("commit authority chain cannot reach preparation")
        prepare_event = append_once(
            "COMMIT_PREPARED",
            {
                "commit_tx_id": prepared.commit_tx_id,
                "evidence_cut_id": prepared.evidence_cut_id,
                "evidence_cut_digest": prepared.evidence_cut_digest,
                "origin_state": "COMMITTING",
            },
        )
        self._fault("prepare_fsync")
        reduce_run(tuple(run_ledger.recover().events))
        return replace(
            prepared,
            prepare_event_id=prepare_event.event_id,
            prepare_event_hash=prepare_event.event_hash,
        )

    def _write_artifact(self, prepared: PreparedCommit) -> None:
        data = base64.b64decode(prepared.artifact_base64)
        final = self.root / "artifacts" / f"{prepared.artifact_digest[7:]}.artifact"
        if final.exists():
            if final.read_bytes() != data:
                raise IntegrityError("content-addressed artifact bytes disagree")
            return
        staging = self.root / "artifacts" / f".staging-{prepared.commit_tx_id}-{len(self._transactions())}"
        if staging.exists():
            with staging.open("rb") as handle:
                if handle.read() != data:
                    raise IntegrityError("staged artifact bytes disagree on recovery")
                self._fault("artifact_write")
                os.fsync(handle.fileno())
                self._fault("artifact_fsync")
        else:
            with staging.open("xb") as handle:
                handle.write(data)
                self._fault("artifact_write")
                handle.flush()
                os.fsync(handle.fileno())
                self._fault("artifact_fsync")
        os.replace(staging, final)
        directory_fd = os.open(final.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def _prepared_payload(self, prepared: PreparedCommit) -> dict[str, Any]:
        payload = asdict(prepared)
        payload["dependencies"] = [asdict(item) for item in prepared.dependencies]
        payload["review_digests"] = list(prepared.review_digests)
        payload.pop("prepare_event_id", None)
        payload.pop("prepare_event_hash", None)
        return payload

    def _prepared_from_payload(self, payload: Mapping[str, Any]) -> PreparedCommit:
        values = dict(payload)
        values["dependencies"] = tuple(DependencyHead(**item) for item in values["dependencies"])
        values["review_digests"] = tuple(values["review_digests"])
        return PreparedCommit(**values)

    def _with_prepare_authority(self, prepared: PreparedCommit) -> PreparedCommit:
        local = reduce_run(tuple(self._run_ledger(prepared.run_id).recover().events))
        authority = next(
            (item for item in local.preparations if item.commit_tx_id == prepared.commit_tx_id),
            None,
        )
        if authority is None:
            return prepared
        return replace(
            prepared,
            prepare_event_id=authority.prepare_event_id,
            prepare_event_hash=authority.prepare_event_hash,
        )

    def _intent(self, commit: PreparedCommit | str) -> PreparedCommit:
        tx_id = commit.commit_tx_id if isinstance(commit, PreparedCommit) else commit
        event = next(
            (item for item in self._transactions("COMMIT_INTENT") if item.payload["commit_tx_id"] == tx_id),
            None,
        )
        if event is None:
            raise IntegrityError("commit has no durable intent")
        return self._with_prepare_authority(self._prepared_from_payload(event.payload))

    def _outcome(self, tx_id: str) -> Event | None:
        for event in self._project_ledger("work").recover().events:
            if event.event_type == "STAGE_COMMITTED" and event.payload.get("commit_tx_id") == tx_id:
                return event
        for run_id in self._registered_run_ids():
            for event in self._run_ledger(run_id).recover().events:
                if event.event_type == "STAGE_COMMIT_ABORTED" and event.payload.get("commit_tx_id") == tx_id:
                    return event
        return None

    def _validate_commit(self, prepared: PreparedCommit) -> tuple[ProjectSemanticCut, RunLocalState]:
        cut, locals_ = self.capture()
        local = next((item for item in locals_ if item.run_id == prepared.run_id), None)
        if local is None:
            raise IntegrityError("commit run is not registered")
        branch = self.branch_head(prepared.branch_id)
        if (branch.state_snapshot_id, branch.generation) != (
            prepared.expected_branch_head,
            prepared.expected_generation,
        ):
            raise IntegrityError("branch head or generation CAS failed")
        if prepared.expected_work_root != cut.active_work_root:
            raise IntegrityError("work root CAS failed")
        if prepared.locked_policy_digest != cut.locked_policy_digest:
            raise IntegrityError("locked policy changed")
        active = {(item.namespace, item.object_id): item.object_head for item in cut.active_object_heads}
        if any(active.get((item.namespace, item.object_id)) != item.object_head for item in prepared.dependencies):
            raise IntegrityError("knowledge dependency vector changed")
        projection = [asdict(item) for item in prepared.dependencies]
        if prepared.expected_dependency_closure_digest != domain_hash(
            "vivarium-dependency-closure/v1", projection
        ):
            raise IntegrityError("dependency closure digest is stale")
        if prepared.knowledge_dependency_vector_digest != domain_hash(
            "vivarium-knowledge-vector/v1", projection
        ):
            raise IntegrityError("knowledge dependency vector digest is stale")
        authority = next(
            (item for item in local.preparations if item.commit_tx_id == prepared.commit_tx_id and item.active),
            None,
        )
        if (
            authority is None
            or authority.prepare_event_id != prepared.prepare_event_id
            or authority.prepare_event_hash != prepared.prepare_event_hash
            or authority.evidence_cut_id != prepared.evidence_cut_id
            or authority.evidence_cut_digest != prepared.evidence_cut_digest
        ):
            raise IntegrityError("durable prepare authority is invalid")
        attempt_id = local.active_attempt_id
        classification = next(
            (
                item
                for item in reversed(local.completion_classifications)
                if item.attempt_id == attempt_id
                and item.evidence_cut_id == prepared.evidence_cut_id
                and item.evidence_cut_digest == prepared.evidence_cut_digest
            ),
            None,
        )
        proof = next(
            (
                item
                for item in reversed(local.completion_proof_heads)
                if item.attempt_id == attempt_id
                and item.evidence_cut_id == prepared.evidence_cut_id
                and item.evidence_cut_digest == prepared.evidence_cut_digest
            ),
            None,
        )
        report = next(
            (
                item
                for item in reversed(local.validator_report_heads)
                if item.attempt_id == attempt_id
                and proof is not None
                and item.completion_proof_id == proof.completion_proof_id
            ),
            None,
        )
        reviews = tuple(
            item
            for item in local.checker_review_heads
            if item.attempt_id == attempt_id
            and report is not None
            and item.validator_report_id == report.validator_report_id
            and item.review_outcome == "pass"
        )
        quorum = next(
            (
                item
                for item in reversed(local.quorum_decision_heads)
                if item.attempt_id == attempt_id
                and report is not None
                and item.validator_report_id == report.validator_report_id
                and item.quorum_outcome == "pass"
            ),
            None,
        )
        quorum_event = next(
            (
                event
                for event in self._run_ledger(prepared.run_id).recover().events
                if quorum is not None and event.event_id == quorum.event_id
            ),
            None,
        )
        if (
            local.analysis_state
            not in {AnalysisState.COMMITTING, AnalysisState.RECOVERY_REQUIRED}
            or classification is None
            or classification.outcome != "success"
            or proof is None
            or proof.completion_proof_digest != prepared.completion_proof_digest
            or report is None
            or report.validation_outcome != "pass"
            or report.validator_report_digest != prepared.validator_report_digest
            or tuple(sorted(item.checker_review_digest for item in reviews))
            != prepared.review_digests
            or quorum is None
            or quorum.quorum_decision_digest != prepared.quorum_decision_digest
            or quorum_event is None
            or quorum_event.payload.get("budget_available") is not True
            or quorum_event.payload.get("budget_digest") != prepared.budget_digest
            or quorum_event.payload.get("completion_claim_digest")
            != prepared.completion_claim_digest
        ):
            raise IntegrityError("active attempt lacks durable commit authority")
        artifact = self.root / "artifacts" / f"{prepared.artifact_digest[7:]}.artifact"
        if not artifact.exists() or domain_hash(
            "vivarium-artifact/v1", base64.b64encode(artifact.read_bytes()).decode("ascii")
        ) != prepared.artifact_digest:
            raise IntegrityError("artifact durability validation failed")
        return cut, local

    def complete_commit(self, commit: PreparedCommit | str) -> Event:
        prepared = self._intent(commit)
        with self._ordered_locks(branch_id=prepared.branch_id, execution_id=prepared.commit_tx_id):
            outcome = self._outcome(prepared.commit_tx_id)
            if outcome is not None:
                if outcome.event_type == "STAGE_COMMITTED":
                    return outcome
                raise IntegrityError("aborted transaction cannot commit")
            # These gates make every durability boundary independently injectable
            # even when a caller begins with an already durable preparation.
            self._fault("artifact_write")
            self._fault("artifact_fsync")
            self._fault("prepare_fsync")
            cut, _ = self._validate_commit(prepared)
            event = self._append(
                self._project_ledger("work"),
                "STAGE_COMMITTED",
                {
                    "project_revision": cut.project_revision + 1,
                    "object_type": "stage",
                    "object_id": prepared.stage_key,
                    "object_head": prepared.new_state_snapshot_id,
                    "dependencies": [asdict(item) for item in prepared.dependencies],
                    "run_id": prepared.run_id,
                    "run_event_id": prepared.prepare_event_id,
                    "run_event_hash": prepared.prepare_event_hash,
                    "commit_tx_id": prepared.commit_tx_id,
                    "prepare_event_id": prepared.prepare_event_id,
                    "prepare_event_hash": prepared.prepare_event_hash,
                    "evidence_cut_id": prepared.evidence_cut_id,
                    "evidence_cut_digest": prepared.evidence_cut_digest,
                    "branch_id": prepared.branch_id,
                    "expected_branch_head": prepared.expected_branch_head,
                    "expected_generation": prepared.expected_generation,
                    "new_generation": prepared.expected_generation + 1,
                    "new_state_snapshot_id": prepared.new_state_snapshot_id,
                    "expected_work_root": prepared.expected_work_root,
                    "new_work_root": prepared.new_work_root,
                    "acceptance_contract_digest": prepared.acceptance_contract_digest,
                    "evidence_bundle_digest": prepared.evidence_bundle_digest,
                    "payload_root_digest": prepared.payload_root_digest,
                    "completion_claim_digest": prepared.completion_claim_digest,
                    "completion_proof_digest": prepared.completion_proof_digest,
                    "completion_grade": prepared.completion_grade,
                    "execution_evidence_cut_digest": prepared.execution_evidence_cut_digest,
                    "validator_report_digest": prepared.validator_report_digest,
                    "review_digests": list(prepared.review_digests),
                    "context_project_revision": prepared.context_project_revision,
                    "knowledge_dependency_vector_digest": prepared.knowledge_dependency_vector_digest,
                    "expected_dependency_closure_digest": prepared.expected_dependency_closure_digest,
                    "canonical_dependency_edges": [
                        [
                            f"work:{prepared.stage_key}",
                            f"{item.namespace}:{item.object_id}",
                        ]
                        for item in prepared.dependencies
                    ],
                    "checker_quorum_valid": prepared.checker_quorum_valid,
                    "budget_available": prepared.budget_available,
                },
                prepared.commit_tx_id,
            )
            self._fault("project_complete_cut_fsync")
            reduce_project_cut(self._prefixes())
            self._write_projection()
            self._fault("projection_replace")
            return event

    def abort_commit(
        self,
        commit: PreparedCommit | str,
        abort_reason: str,
        *,
        sealed_failure_digest: str | None = None,
    ) -> Event:
        prepared = self._intent(commit)
        if abort_reason not in COMMIT_ABORT_REASON_TARGET:
            raise IntegrityError("commit abort reason is not closed")
        with self._ordered_locks(branch_id=prepared.branch_id, execution_id=prepared.commit_tx_id):
            outcome = self._outcome(prepared.commit_tx_id)
            if outcome is not None:
                if outcome.event_type == "STAGE_COMMIT_ABORTED":
                    return outcome
                raise IntegrityError("committed transaction cannot abort")
            local = reduce_run(tuple(self._run_ledger(prepared.run_id).recover().events))
            authority = next(
                item for item in local.preparations if item.commit_tx_id == prepared.commit_tx_id
            )
            payload: dict[str, Any] = {
                "commit_tx_id": prepared.commit_tx_id,
                "prepare_event_id": authority.prepare_event_id,
                "prepare_event_hash": authority.prepare_event_hash,
                "abort_reason": abort_reason,
                "analysis_from": local.analysis_state.value,
                "analysis_target": COMMIT_ABORT_REASON_TARGET[abort_reason].value,
                "sealed_failure_digest": sealed_failure_digest
                or domain_hash("vivarium-sealed-commit-failure/v1", {"reason": abort_reason}),
                "preparation_delta": {"from": "ACTIVE", "to": "INACTIVE"},
            }
            if abort_reason in COMPLETION_ABORT_OUTCOME:
                classification_event = self._append(
                    self._run_ledger(prepared.run_id),
                    "COMPLETION_CLASSIFIED",
                    {
                        "classification_id": f"classification:{prepared.commit_tx_id}:{abort_reason}",
                        "evidence_cut_id": prepared.evidence_cut_id,
                        "evidence_cut_digest": prepared.evidence_cut_digest,
                        "outcome": COMPLETION_ABORT_OUTCOME[abort_reason],
                    },
                    prepared.commit_tx_id,
                )
                classified = reduce_run(tuple(self._run_ledger(prepared.run_id).recover().events))
                classification = classified.completion_classifications[-1]
                payload.update(
                    {
                        "analysis_from": classified.analysis_state.value,
                        "completion_classification_id": classification.classification_id,
                        "completion_classification_digest": classification.classification_digest,
                        "sealed_failure_digest": classification.classification_digest,
                    }
                )
            event = self._append(
                self._run_ledger(prepared.run_id),
                "STAGE_COMMIT_ABORTED",
                payload,
                prepared.commit_tx_id,
            )
            reduce_run(tuple(self._run_ledger(prepared.run_id).recover().events))
            return event

    def inbox_observation(
        self,
        run_id: str,
        observed_object_id: str,
        raw: bytes | str | Mapping[str, Any],
        *,
        observation_id: str | None = None,
        source: str = "passive",
        authority: str = "local",
    ) -> InboxReceipt:
        body = raw if isinstance(raw, bytes) else (
            raw.encode("utf-8") if isinstance(raw, str) else canonical_bytes(dict(raw))
        )
        digest = domain_hash("vivarium-postcommit-observation/v1", base64.b64encode(body).decode("ascii"))
        observation_id = observation_id or f"observation-{len(self.business_event_types()) + 1}"
        recheck_tx_id = f"recheck:{observation_id}"
        oversize = len(body) > self.inbox_limit
        encoded = base64.b64encode(body[: self.inbox_limit]).decode("ascii")
        candidate = next(
            (
                event
                for event in reversed(self._project_ledger("work").recover().events)
                if event.event_type == "STAGE_COMMITTED"
                and event.payload.get("run_id") == run_id
                and event.payload.get("object_id") == observed_object_id
            ),
            None,
        )
        if candidate is None:
            raise IntegrityError("observation target is not an active committed object")
        with self._ordered_locks(
            branch_id=candidate.payload.get("branch_id", "branch-1"),
            execution_id=recheck_tx_id,
        ):
            commit_event = next(
                (
                    event
                    for event in reversed(self._project_ledger("work").recover().events)
                    if event.event_type == "STAGE_COMMITTED"
                    and event.payload.get("run_id") == run_id
                    and event.payload.get("object_id") == observed_object_id
                ),
                None,
            )
            if commit_event is None:
                raise IntegrityError("observation target is not an active committed object")
            branch_id = commit_event.payload.get("branch_id", "branch-1")
            branch = self.branch_head(branch_id)
            cut = reduce_project_cut(self._prefixes())
            active_object = next(
                (
                    item
                    for item in cut.active_object_heads
                    if item.namespace == "work"
                    and item.object_id == observed_object_id
                    and item.owner_run_id == run_id
                ),
                None,
            )
            if (
                commit_event.payload.get("new_state_snapshot_id") not in branch.ancestry
                or active_object is None
                or active_object.object_head != commit_event.payload.get("object_head")
            ):
                raise IntegrityError("observation target is not an active committed object")
            payload = {
                "observation_id": observation_id,
                "observed_object_id": observed_object_id,
                "observation_digest": digest,
                "canonical_raw_base64": encoded,
                "observed_size": len(body),
                "oversize": oversize,
                "source": source,
                "authority": authority,
                "target_commit_tx_id": commit_event.payload["commit_tx_id"],
                "target_completion_proof_digest": commit_event.payload[
                    "completion_proof_digest"
                ],
                "recheck_tx_id": recheck_tx_id,
                "truncation_evidence_digest": domain_hash(
                    "vivarium-inbox-truncation/v1",
                    {"digest": digest, "size": len(body), "limit": self.inbox_limit},
                ),
            }
            existing = next(
                (
                    item
                    for item in self._run_ledger(run_id).recover().events
                    if item.event_type == "POSTCOMMIT_OBSERVATION_INBOXED"
                    and item.payload.get("observation_id") == observation_id
                ),
                None,
            )
            if existing is not None:
                if existing.payload != payload:
                    raise IntegrityError("observation ID was reused with different content")
                return InboxReceipt(
                    observation_id,
                    recheck_tx_id,
                    existing,
                    "ESCALATED" if oversize else "BLOCKED_POSTCOMMIT_INTAKE",
                    oversize,
                )
            event = self._append(
                self._run_ledger(run_id),
                "POSTCOMMIT_OBSERVATION_INBOXED",
                payload,
                recheck_tx_id,
            )
        return InboxReceipt(
            observation_id,
            recheck_tx_id,
            event,
            "ESCALATED" if oversize else "BLOCKED_POSTCOMMIT_INTAKE",
            oversize,
        )

    def open_recheck(self, run_id: str, observation_id: str) -> Event:
        run_events = tuple(self._run_ledger(run_id).recover().events)
        inbox = next(
            (event for event in run_events if event.event_type == "POSTCOMMIT_OBSERVATION_INBOXED" and event.payload["observation_id"] == observation_id),
            None,
        )
        if inbox is None:
            raise IntegrityError("observation is not inboxed")
        if inbox.payload.get("oversize"):
            raise IntegrityError("oversize observation remains fail-closed")
        recheck_tx_id = inbox.payload.get("recheck_tx_id", f"recheck:{observation_id}")
        existing = next(
            (
                event
                for event in self._project_ledger("work").recover().events
                if event.event_type == "COMPLETION_RECHECK_OPENED"
                and event.payload["recheck_tx_id"] == recheck_tx_id
            ),
            None,
        )
        if existing is not None:
            if not any(
                e.event_type == "POSTCOMMIT_OBSERVATION_OPENED"
                and e.payload["observation_id"] == observation_id
                for e in run_events
            ):
                self._append(
                    self._run_ledger(run_id),
                    "POSTCOMMIT_OBSERVATION_OPENED",
                    {"observation_id": observation_id},
                    recheck_tx_id,
                )
            return existing
        commit = next(
            event
            for event in reversed(self._project_ledger("work").recover().events)
            if event.event_type == "STAGE_COMMITTED"
            and event.payload.get("commit_tx_id") == inbox.payload.get("target_commit_tx_id")
        )
        prepared = self._intent(commit.payload["commit_tx_id"])
        with self._ordered_locks(branch_id=prepared.branch_id, execution_id=recheck_tx_id):
            cut = reduce_project_cut(self._prefixes())
            event = self._append(
                self._project_ledger("work"),
                "COMPLETION_RECHECK_OPENED",
                {
                    "project_revision": cut.project_revision + 1,
                    "object_type": "recheck",
                    "object_id": commit.payload["object_id"],
                    "object_head": commit.payload["object_head"],
                    "dependencies": commit.payload["dependencies"],
                    "run_id": run_id,
                    "run_event_id": inbox.event_id,
                    "run_event_hash": inbox.event_hash,
                    "recheck_tx_id": recheck_tx_id,
                    "recheck_scope": "own_stage",
                    "target_namespace": "work",
                    "target_object_id": commit.payload["object_id"],
                    "prepare_event_id": prepared.prepare_event_id,
                    "prepare_event_hash": prepared.prepare_event_hash,
                    "evidence_cut_id": prepared.evidence_cut_id,
                    "evidence_cut_digest": prepared.evidence_cut_digest,
                    "observation_id": observation_id,
                    "observation_digest": inbox.payload["observation_digest"],
                    "target_commit_tx_id": commit.payload["commit_tx_id"],
                },
                recheck_tx_id,
            )
            reduce_project_cut(self._prefixes())
            self._append(
                self._run_ledger(run_id),
                "POSTCOMMIT_OBSERVATION_OPENED",
                {"observation_id": observation_id},
                recheck_tx_id,
            )
            return event

    def rollback(
        self,
        branch_id: str,
        target_checkpoint_id: str,
        *,
        expected_head: str | None = None,
        expected_generation: int | None = None,
        invalidated_roots: Sequence[str] = (),
    ) -> Event:
        with self._ordered_locks(branch_id=branch_id):
            branch = self.branch_head(branch_id)
            expected_head = branch.state_snapshot_id if expected_head is None else expected_head
            expected_generation = branch.generation if expected_generation is None else expected_generation
            if (expected_head, expected_generation) != (branch.state_snapshot_id, branch.generation):
                raise IntegrityError("rollback branch CAS failed")
            if target_checkpoint_id not in branch.ancestry:
                raise IntegrityError("rollback target is not an ancestor checkpoint")
            target_index = branch.ancestry.index(target_checkpoint_id)
            invalidated = set(branch.ancestry[target_index + 1 :])
            affected_run_ids = tuple(
                sorted(
                    {
                        event.payload["run_id"]
                        for event in self._project_ledger("work").recover().events
                        if event.event_type == "STAGE_COMMITTED"
                        and event.payload.get("branch_id") == branch_id
                        and event.payload.get("object_head") in invalidated
                    }
                )
            )
            if not affected_run_ids:
                raise IntegrityError("rollback does not invalidate any committed run")
            cut = reduce_project_cut(self._prefixes())
            event = self._append(
                self._project_ledger("work"),
                "ROLLBACK_COMMITTED",
                {
                    "project_revision": cut.project_revision + 1,
                    "object_type": "branch",
                    "object_id": f"branch:{branch_id}",
                    "object_head": target_checkpoint_id,
                    "dependencies": [],
                    "branch_id": branch_id,
                    "expected_branch_head": expected_head,
                    "expected_generation": expected_generation,
                    "target_checkpoint_id": target_checkpoint_id,
                    "new_generation": expected_generation + 1,
                    "invalidated_roots": sorted(invalidated),
                    "affected_run_ids": list(affected_run_ids),
                },
                f"rollback:{branch_id}:{expected_generation + 1}",
            )
            reduce_project_cut(self._prefixes())
            self._write_projection()
            return event

    def fork(
        self,
        parent_branch_id: str,
        new_branch_id: str,
        *,
        parent_checkpoint_id: str | None = None,
        specification_delta: Mapping[str, Any] | str = "no-change",
    ) -> Event:
        with self._ordered_locks(branch_id=parent_branch_id):
            if new_branch_id in self._branch_heads():
                raise IntegrityError("fork branch_id must be new and immutable")
            parent = self.branch_head(parent_branch_id)
            checkpoint = parent.state_snapshot_id if parent_checkpoint_id is None else parent_checkpoint_id
            if checkpoint not in parent.ancestry:
                raise IntegrityError("fork checkpoint is not in parent ancestry")
            delta_digest = domain_hash("vivarium-specification-delta/v1", specification_delta)
            cut = reduce_project_cut(self._prefixes())
            event = self._append(
                self._project_ledger("work"),
                "BRANCH_FORKED",
                {
                    "project_revision": cut.project_revision + 1,
                    "object_type": "branch",
                    "object_id": f"branch:{new_branch_id}",
                    "object_head": checkpoint,
                    "dependencies": [],
                    "branch_id": new_branch_id,
                    "parent_branch_id": parent_branch_id,
                    "parent_checkpoint_id": checkpoint,
                    "parent_state_root": parent.state_snapshot_id,
                    "initial_generation": 0,
                    "specification_delta_digest": delta_digest,
                },
                f"fork:{new_branch_id}",
            )
            reduce_project_cut(self._prefixes())
            self._write_projection()
            return event

    def _registered_run_ids(self) -> tuple[str, ...]:
        return tuple(
            event.payload["object_id"]
            for event in self._project_ledger("run-registry").recover().events
            if event.event_type == "RUN_REGISTERED"
        )

    def recover(self) -> RecoveryState:
        registered = set(self._registered_run_ids())
        for run_dir in sorted((self.root / "runs").iterdir()):
            if run_dir.is_dir() and run_dir.name not in registered:
                events = tuple(self._run_ledger(run_dir.name).recover().events)
                if len(events) == 1 and events[0].event_type == "RUN_LEDGER_GENESIS":
                    self.register_run(
                        run_dir.name,
                        analysis_state=events[0].payload["analysis_state"],
                        branch_id=events[0].payload["branch_id"],
                    )
        for intent in self._transactions("COMMIT_INTENT"):
            prepared = self._with_prepare_authority(self._prepared_from_payload(intent.payload))
            prior_run_commit = any(
                event.event_type == "STAGE_COMMITTED"
                and event.payload.get("run_id") == prepared.run_id
                and event.payload.get("commit_tx_id") != prepared.commit_tx_id
                for event in self._project_ledger("work").recover().events
            )
            if prior_run_commit:
                continue
            if not prepared.prepare_event_id:
                prepared = self.prepare_commit(prepared)
            if self._outcome(prepared.commit_tx_id) is None:
                try:
                    self.complete_commit(prepared)
                except IntegrityError:
                    self.abort_commit(prepared, "HUMAN_JUDGMENT_REQUIRED")
        for run_id in self._registered_run_ids():
            local = reduce_run(tuple(self._run_ledger(run_id).recover().events))
            for observation_id in local.postcommit_intake_blockers:
                event = next(
                    e
                    for e in self._run_ledger(run_id).recover().events
                    if e.event_type == "POSTCOMMIT_OBSERVATION_INBOXED"
                    and e.payload["observation_id"] == observation_id
                )
                if not event.payload.get("oversize"):
                    self.open_recheck(run_id, observation_id)
        cut, locals_ = self.capture()
        validity = reduce_project_validity(cut)
        federated: list[FederatedState] = []
        for local in locals_:
            run_validity = reduce_run_validity(cut, validity, local)
            federated.append(federate(local, cut, validity, run_validity))
        aggregate = domain_hash(
            "vivarium-project-recovery/v1",
            {
                "project_semantic_cut_root": cut.project_semantic_cut_root,
                "federated_state_roots": [item.federated_state_root for item in federated],
                "branches": [_branch_projection(item) for item in sorted(self._branch_heads().values(), key=lambda x: x.branch_id)],
            },
        )
        oversize = any(
            event.event_type == "POSTCOMMIT_OBSERVATION_INBOXED"
            and event.payload.get("oversize")
            and not any(
                opened.event_type == "POSTCOMMIT_OBSERVATION_OPENED"
                and opened.payload["observation_id"] == event.payload["observation_id"]
                for opened in self._run_ledger(run_id).recover().events
            )
            for run_id in self._registered_run_ids()
            for event in self._run_ledger(run_id).recover().events
        )
        analysis = (
            "ESCALATED"
            if oversize
            else federated[0].analysis_state.value
            if len(federated) == 1
            else "PROJECT"
        )
        state = RecoveryState(
            cut,
            tuple(locals_),
            tuple(federated),
            aggregate,
            not oversize and all(item.default_retrievable for item in federated),
            analysis,
        )
        self._write_projection(state)
        return state

    def _write_projection(self, state: RecoveryState | None = None) -> None:
        branches = [_branch_projection(item) for item in sorted(self._branch_heads().values(), key=lambda x: x.branch_id)]
        payload: dict[str, Any] = {"branches": branches}
        if state is not None:
            payload.update(
                {
                    "project_semantic_cut_root": state.project_cut.project_semantic_cut_root,
                    "federated_state_root": state.federated_state_root,
                    "default_retrievable": state.default_retrievable,
                    "analysis_state": state.analysis_state,
                }
            )
        durable_replace(self.root / "projections" / "state.json", canonical_bytes(payload))

    def business_event_types(self) -> list[str]:
        types: list[str] = []
        for namespace, _ in PROJECT_LEDGERS:
            types.extend(event.event_type for event in self._project_ledger(namespace).recover().events[1:])
        for run_id in self._registered_run_ids():
            types.extend(event.event_type for event in self._run_ledger(run_id).recover().events[1:])
        return types


ProjectStoreInit = Callable[[Path, Any], ProjectStore]
ProjectCapture = Callable[[ProjectStore], tuple[ProjectSemanticCut, Sequence[RunLocalState]]]
