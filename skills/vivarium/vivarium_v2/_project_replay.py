from __future__ import annotations

from dataclasses import replace
from typing import Any

from ._replay_common import (
    ACTIVE_ROOT_DOMAIN,
    GENESIS_LEDGER_IDS,
    GENESIS_TYPES,
    LEDGER_REDUCER_DIGESTS,
    _dependency,
    _require_dict,
    _require_digest,
    _require_int,
    _require_string,
    _verify_event_prefix,
)
from ._project_support import (
    PROJECT_CUT_DOMAIN,
    _compute_invalidation,
    _object_projection,
    _project_cut_root_with_snapshots,
    _project_object,
    _project_graph,
    _project_validity_values_v2,
    empty_project_state_root,
)
from ._run_state_support import _new_attempt_from_payload
from .canonical import domain_hash
from .errors import IntegrityError
from .events import Event, ZERO_HASH
from .state import (
    AnalysisState,
    AttemptDependencyDelta,
    DependencyHead,
    ProjectObjectHead,
    ProjectOverlay,
    ProjectPrefixes,
    ProjectRevisionSnapshot,
    ProjectRevisionAction,
    ProjectSemanticCut,
    validate_event_payload,
)

def _canonical_dependency_closure_at_revision(
    objects: dict[tuple[str, str], ProjectObjectHead],
    direct: tuple[DependencyHead, ...],
) -> tuple[DependencyHead, ...]:
    reachable: dict[tuple[str, str], DependencyHead] = {}
    pending = [(item.namespace, item.object_id) for item in direct]
    while pending:
        identity = pending.pop()
        if identity in reachable:
            continue
        current = objects.get(identity)
        if current is None:
            raise IntegrityError("dependency delta references an inactive project object")
        reachable[identity] = DependencyHead(
            current.namespace, current.object_id, current.object_head
        )
        pending.extend((item.namespace, item.object_id) for item in current.dependencies)
    return tuple(sorted(reachable.values()))


def _parse_dependency_delta(
    payload: dict[str, Any], objects: dict[tuple[str, str], ProjectObjectHead]
) -> AttemptDependencyDelta:
    raw = _require_dict(payload["dependency_delta"], "dependency_delta")
    expected_fields = {
        "expected_direct_dependency_heads",
        "expected_dependency_closure",
        "new_direct_dependency_heads",
        "new_dependency_closure",
        "expected_logical_scope_key",
        "new_logical_scope_key",
        "expected_project_revision_baseline",
        "new_project_revision_baseline",
        "expected_project_semantic_cut_root_baseline",
        "new_project_semantic_cut_root_baseline",
    }
    if set(raw) != expected_fields:
        raise IntegrityError("correction dependency delta has an invalid field set")

    def dependencies(field):
        values = raw[field]
        if not isinstance(values, list):
            raise IntegrityError("correction dependency delta lists must be arrays")
        parsed = tuple(sorted(_dependency(item) for item in values))
        if len(parsed) != len({(item.namespace, item.object_id) for item in parsed}):
            raise IntegrityError("correction dependency identities must be unique")
        return parsed

    expected_direct = dependencies("expected_direct_dependency_heads")
    expected_closure = dependencies("expected_dependency_closure")
    new_direct = dependencies("new_direct_dependency_heads")
    new_closure = dependencies("new_dependency_closure")
    canonical = _canonical_dependency_closure_at_revision(objects, new_direct)
    if new_closure != canonical:
        raise IntegrityError("correction dependency closure is not canonical at its revision")
    expected_revision = _require_int(raw, "expected_project_revision_baseline")
    new_revision = _require_int(raw, "new_project_revision_baseline")
    if (
        new_revision != payload["project_revision"] - 1
        or new_revision < expected_revision
    ):
        raise IntegrityError("correction project baseline revision is inconsistent")
    return AttemptDependencyDelta(
        expected_direct,
        expected_closure,
        new_direct,
        new_closure,
        _require_string(raw, "expected_logical_scope_key"),
        _require_string(raw, "new_logical_scope_key"),
        expected_revision,
        new_revision,
        _require_digest(raw, "expected_project_semantic_cut_root_baseline"),
        _require_digest(raw, "new_project_semantic_cut_root_baseline"),
    )


def _affected_recheck_scope(
    objects: dict[tuple[str, str], ProjectObjectHead],
    target_namespace: str,
    target_object_id: str,
    owner_run_id: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    target = f"{target_namespace}:{target_object_id}"
    _, descendant_items = _project_graph(tuple(sorted(objects.values())))
    affected_objects = tuple(sorted({target, *dict(descendant_items).get(target, ())}))
    by_identity = {
        f"{item.namespace}:{item.object_id}": item for item in objects.values()
    }
    affected_runs = {owner_run_id}
    affected_runs.update(
        item.owner_run_id
        for identity in affected_objects
        if (item := by_identity.get(identity)) is not None
        and item.owner_run_id is not None
    )
    return affected_objects, tuple(sorted(affected_runs))


def _validate_snapshot_dependencies(direct, closure, snapshot, label):
    objects = {
        (item.namespace, item.object_id): item
        for item in snapshot.active_object_heads
    }
    for dependency in direct:
        current = objects.get((dependency.namespace, dependency.object_id))
        if current is None or current.object_head != dependency.object_head:
            raise IntegrityError(f"correction {label} direct head is not authenticated")
    if _canonical_dependency_closure_at_revision(objects, direct) != closure:
        raise IntegrityError(f"correction {label} closure is not authenticated")


def reduce_project_cut(prefixes: ProjectPrefixes) -> ProjectSemanticCut:
    return _reduce_project_cut(prefixes, build_revision_snapshots=True)


def _reduce_project_cut(
    prefixes: ProjectPrefixes, *, build_revision_snapshots: bool
) -> ProjectSemanticCut:
    if not isinstance(prefixes, ProjectPrefixes):
        raise IntegrityError("project prefixes must use frozen ProjectPrefixes")
    locked_policies: set[str] = set()
    semantic: list[tuple[int, str, Event, dict[str, Any], Any]] = []
    semantic_tails: dict[str, Event] = {}
    verified_prefixes: dict[str, tuple[Event, ...]] = {}
    for namespace in GENESIS_TYPES:
        events = _verify_event_prefix(
            getattr(prefixes, namespace),
            genesis_type=GENESIS_TYPES[namespace],
            ledger_id=GENESIS_LEDGER_IDS[namespace],
        )
        verified_prefixes[namespace] = events
        genesis = _require_dict(events[0].payload, f"{namespace} genesis payload")
        contract = validate_event_payload(events[0].event_type, genesis, "project")
        if contract.namespace != namespace:
            raise IntegrityError("project genesis event is in the wrong reducer namespace")
        if genesis["initial_state_root"] != empty_project_state_root(namespace):
            raise IntegrityError("project genesis empty-state root is inconsistent")
        if "project_revision" in genesis:
            raise IntegrityError("project genesis may not assert a semantic revision")
        locked_policies.add(_require_string(genesis, "locked_policy_digest"))
        semantic_tails[namespace] = events[0]
        for item in events[1:]:
            payload = _require_dict(item.payload, f"{item.event_type} payload")
            contract = validate_event_payload(item.event_type, payload, "project")
            if contract.namespace != namespace:
                raise IntegrityError("project event is in the wrong reducer namespace")
            if contract.action == "audit_only":
                continue
            revision = _require_int(payload, "project_revision")
            if revision <= 0:
                raise IntegrityError("semantic project revisions must be positive")
            semantic.append((revision, namespace, item, payload, contract))
            semantic_tails[namespace] = item
    if len(locked_policies) != 1:
        raise IntegrityError("project genesis anchors disagree on locked policy")
    locked_policy = next(iter(locked_policies))
    semantic.sort(key=lambda value: value[0])
    revisions = [value[0] for value in semantic]
    if revisions != list(range(1, len(semantic) + 1)):
        raise IntegrityError("project semantic revisions must form one cross-ledger sequence")

    objects: dict[tuple[str, str], ProjectObjectHead] = {}
    explicit_invalid: set[str] = set()
    overlays: list[ProjectOverlay] = []
    revision_actions: list[ProjectRevisionAction] = []
    branch_heads: dict[str, tuple[str, int]] = {}
    branch_ancestry: dict[str, tuple[str, ...]] = {}
    open_recheck_scopes: dict[
        tuple[str, str], tuple[tuple[str, ...], tuple[str, ...]]
    ] = {}
    task4_commits: dict[str, tuple[str, str, str, str]] = {}
    opened_observations: dict[tuple[str, str], tuple[str, str]] = {}
    for revision, namespace, item, payload, contract in semantic:
        task4_commit_fields = {
            "branch_id",
            "expected_branch_head",
            "expected_generation",
            "new_generation",
            "new_state_snapshot_id",
            "expected_work_root",
            "new_work_root",
            "acceptance_contract_digest",
            "evidence_bundle_digest",
            "payload_root_digest",
            "completion_claim_digest",
            "completion_proof_digest",
            "completion_grade",
            "execution_evidence_cut_digest",
            "validator_report_digest",
            "review_digests",
            "context_project_revision",
            "knowledge_dependency_vector_digest",
            "expected_dependency_closure_digest",
            "canonical_dependency_edges",
            "checker_quorum_valid",
            "budget_available",
        }
        present_task4_fields = task4_commit_fields & set(payload)
        if (
            item.event_type == "STAGE_COMMITTED"
            and present_task4_fields
            and present_task4_fields != task4_commit_fields
        ):
            raise IntegrityError("stage commit Task 4 authority fields are incomplete")
        if item.event_type == "STAGE_COMMITTED" and "branch_id" in payload:
            branch_id = _require_string(payload, "branch_id")
            current_head, current_generation = branch_heads.get(
                branch_id, (ZERO_HASH, 0)
            )
            current_work_root = domain_hash(
                ACTIVE_ROOT_DOMAIN,
                {
                    "namespace": "work",
                    "objects": [
                        _object_projection(value)
                        for value in sorted(objects.values())
                        if value.namespace == "work"
                    ],
                },
            )
            if (
                payload["expected_branch_head"] != current_head
                or payload["expected_generation"] != current_generation
                or payload["new_generation"] != current_generation + 1
                or payload["new_state_snapshot_id"] != payload["object_head"]
                or payload["expected_work_root"] != current_work_root
                or not payload["checker_quorum_valid"]
                or not payload["budget_available"]
                or payload["review_digests"] != sorted(set(payload["review_digests"]))
            ):
                raise IntegrityError("stage commit CAS/authority is inconsistent")
            branch_heads[branch_id] = (
                payload["new_state_snapshot_id"], payload["new_generation"]
            )
            branch_ancestry[branch_id] = (
                *branch_ancestry.get(branch_id, (ZERO_HASH,)),
                payload["new_state_snapshot_id"],
            )
            commit_tx_id = _require_string(payload, "commit_tx_id")
            if commit_tx_id in task4_commits:
                raise IntegrityError("stage commit transaction IDs must be unique")
            task4_commits[commit_tx_id] = (
                _require_string(payload, "run_id"),
                _require_string(payload, "object_id"),
                branch_id,
                _require_string(payload, "new_state_snapshot_id"),
            )
        elif item.event_type == "ROLLBACK_COMMITTED":
            branch_id = _require_string(payload, "branch_id")
            current = branch_heads.get(branch_id, (ZERO_HASH, 0))
            if (
                payload["expected_branch_head"] != current[0]
                or payload["expected_generation"] != current[1]
                or payload["new_generation"] != current[1] + 1
                or payload["object_head"] != payload["target_checkpoint_id"]
                or payload["target_checkpoint_id"]
                not in branch_ancestry.get(branch_id, (ZERO_HASH,))
            ):
                raise IntegrityError("rollback branch CAS/ancestry is inconsistent")
            branch_heads[branch_id] = (
                payload["target_checkpoint_id"], payload["new_generation"]
            )
            lineage = branch_ancestry.get(branch_id, (ZERO_HASH,))
            branch_ancestry[branch_id] = lineage[
                : lineage.index(payload["target_checkpoint_id"]) + 1
            ]
        elif item.event_type == "BRANCH_FORKED":
            branch_id = _require_string(payload, "branch_id")
            parent_id = _require_string(payload, "parent_branch_id")
            parent = branch_heads.get(parent_id, (ZERO_HASH, 0))
            if (
                branch_id in branch_heads
                or payload["initial_generation"] != 0
                or payload["parent_state_root"] != parent[0]
                or payload["parent_checkpoint_id"]
                not in branch_ancestry.get(parent_id, (ZERO_HASH,))
                or payload["object_head"] != payload["parent_checkpoint_id"]
            ):
                raise IntegrityError("fork parent binding is inconsistent")
            branch_heads[branch_id] = (payload["object_head"], 0)
            parent_lineage = branch_ancestry.get(parent_id, (ZERO_HASH,))
            checkpoint_index = parent_lineage.index(payload["parent_checkpoint_id"])
            branch_ancestry[branch_id] = parent_lineage[: checkpoint_index + 1]
        active_object = _project_object(namespace, payload)
        mutates_object = contract.action != "project_recheck"
        if mutates_object:
            objects[(namespace, active_object.object_id)] = active_object
        if item.event_type == "STAGE_COMMITTED" and "branch_id" in payload:
            new_work_root = domain_hash(
                ACTIVE_ROOT_DOMAIN,
                {
                    "namespace": "work",
                    "objects": [
                        _object_projection(value)
                        for value in sorted(objects.values())
                        if value.namespace == "work"
                    ],
                },
            )
            canonical_edges = [
                [
                    f"work:{active_object.object_id}",
                    f"{dependency.namespace}:{dependency.object_id}",
                ]
                for dependency in active_object.dependencies
            ]
            dependency_projection = [
                {
                    "namespace": dependency.namespace,
                    "object_id": dependency.object_id,
                    "object_head": dependency.object_head,
                }
                for dependency in active_object.dependencies
            ]
            if (
                payload["new_work_root"] != new_work_root
                or payload["canonical_dependency_edges"] != canonical_edges
                or payload["expected_dependency_closure_digest"]
                != domain_hash(
                    "vivarium-dependency-closure/v1", dependency_projection
                )
                or payload["knowledge_dependency_vector_digest"]
                != domain_hash("vivarium-knowledge-vector/v1", dependency_projection)
            ):
                raise IntegrityError("stage commit work/dependency binding is inconsistent")
        identity = f"{namespace}:{active_object.object_id}"
        if mutates_object:
            if contract.action == "invalidate_object":
                explicit_invalid.add(identity)
            else:
                explicit_invalid.discard(identity)
        if contract.action == "lock_policy":
            locked_policy = _require_string(payload, "locked_policy_digest")
        overlay = None
        if contract.action in {"project_overlay", "project_correction", "project_recheck"}:
            run_id = _require_string(payload, "run_id")
            if contract.action == "project_correction":
                transaction_id = _require_string(payload, "correction_id")
                dependency_delta = _parse_dependency_delta(payload, objects)
                successor = _new_attempt_from_payload(
                    payload,
                    AnalysisState.PLANNED,
                    _require_string(payload, "prior_attempt_id"),
                    logical_scope_key=dependency_delta.new_logical_scope_key,
                    direct_dependency_heads=dependency_delta.new_direct_dependency_heads,
                    dependency_closure=dependency_delta.new_dependency_closure,
                    project_revision_baseline=(
                        dependency_delta.new_project_revision_baseline
                    ),
                    project_semantic_cut_root_baseline=(
                        dependency_delta.new_project_semantic_cut_root_baseline
                    ),
                )
                owner_guard = "new_branch_created"
                descendant_guard = ""
                prepare_event_id = prepare_event_hash = evidence_cut_id = evidence_cut_digest = ""
                target_namespace = target_object_id = ""
                affected_object_ids = ()
                affected_run_ids = (run_id,)
            else:
                successor = None
                dependency_delta = None
                transaction_id = _require_string(
                    payload,
                    "commit_tx_id" if contract.action == "project_overlay" else "recheck_tx_id",
                )
                prepare_event_id = _require_string(payload, "prepare_event_id")
                prepare_event_hash = _require_string(payload, "prepare_event_hash")
                evidence_cut_id = _require_string(payload, "evidence_cut_id")
                evidence_cut_digest = _require_string(payload, "evidence_cut_digest")
                target_namespace = payload.get("target_namespace", namespace)
                target_object_id = payload.get("target_object_id", active_object.object_id)
                if contract.selector_field is not None:
                    mapping = dict(
                        dict(contract.selector_guards)[payload[contract.selector_field]]
                    )
                    owner_guard = mapping.get("analysis", "")
                    descendant_guard = mapping.get("analysis_descendant", "")
                else:
                    if item.event_type == "COMPLETION_PROOF_REVOKED":
                        owner_guard = "failure_unknown_disallowed_grade"
                        descendant_guard = "upstream_proof_revoked"
                    elif item.event_type == "COMPLETION_RECHECK_DEFERRED":
                        owner_guard = descendant_guard = "classification_cannot_finish_safely"
                    else:
                        owner_guard = descendant_guard = ""
                if contract.action == "project_recheck":
                    scope_key = (run_id, transaction_id)
                    if item.event_type == "COMPLETION_RECHECK_OPENED":
                        if scope_key in open_recheck_scopes:
                            raise IntegrityError("recheck transaction may only be opened once")
                        identity_fields = {
                            "observation_id",
                            "observation_digest",
                            "target_commit_tx_id",
                        }
                        present_identity = identity_fields & set(payload)
                        active_task4_targets = {
                            commit_tx_id
                            for commit_tx_id, record in task4_commits.items()
                            if record[0] == run_id
                            and record[1] == target_object_id
                            and record[3]
                            in branch_ancestry.get(record[2], (ZERO_HASH,))
                        }
                        if present_identity and present_identity != identity_fields:
                            raise IntegrityError("recheck observation identity is incomplete")
                        if active_task4_targets and present_identity != identity_fields:
                            raise IntegrityError(
                                "Task 4 recheck lacks its durable observation identity"
                            )
                        if present_identity:
                            observation_id = _require_string(payload, "observation_id")
                            observation_digest = _require_digest(
                                payload, "observation_digest"
                            )
                            target_commit_tx_id = _require_string(
                                payload, "target_commit_tx_id"
                            )
                            record = task4_commits.get(target_commit_tx_id)
                            if (
                                target_namespace != "work"
                                or record is None
                                or record[0] != run_id
                                or record[1] != target_object_id
                                or record[3]
                                not in branch_ancestry.get(record[2], (ZERO_HASH,))
                                or target_commit_tx_id not in active_task4_targets
                            ):
                                raise IntegrityError(
                                    "recheck observation targets a non-active commit"
                                )
                            observation_key = (run_id, observation_id)
                            observation_binding = (
                                observation_digest,
                                target_commit_tx_id,
                            )
                            if observation_key in opened_observations:
                                raise IntegrityError(
                                    "recheck observation may only be opened once"
                                )
                            opened_observations[observation_key] = observation_binding
                        affected_object_ids, affected_run_ids = _affected_recheck_scope(
                            objects, target_namespace, target_object_id, run_id
                        )
                        open_recheck_scopes[scope_key] = (
                            affected_object_ids, affected_run_ids
                        )
                    else:
                        frozen_scope = open_recheck_scopes.get(scope_key)
                        if frozen_scope is None:
                            raise IntegrityError("recheck action has no frozen OPEN scope")
                        affected_object_ids, affected_run_ids = frozen_scope
                        if item.event_type in {
                            "COMPLETION_PROOF_REFRESHED",
                            "COMPLETION_PROOF_REVOKED",
                        }:
                            del open_recheck_scopes[scope_key]
                else:
                    affected_object_ids = ()
                    affected_run_ids = (run_id,)
            overlay = ProjectOverlay(
                revision,
                item.event_type,
                run_id,
                _require_string(payload, "run_event_id"),
                _require_string(payload, "run_event_hash"),
                transaction_id,
                prepare_event_id,
                prepare_event_hash,
                evidence_cut_id,
                evidence_cut_digest,
                owner_guard,
                descendant_guard,
                target_namespace,
                target_object_id,
                affected_object_ids,
                affected_run_ids,
                successor,
                dependency_delta,
                item.event_id,
                item.event_hash,
            )
            overlays.append(overlay)
        if contract.action == "project_rollback":
            affected_run_ids = tuple(sorted(payload["affected_run_ids"]))
            if not affected_run_ids or len(affected_run_ids) != len(
                set(affected_run_ids)
            ):
                raise IntegrityError("rollback affected runs must be sorted and unique")
            overlay = ProjectOverlay(
                revision,
                item.event_type,
                affected_run_ids[0],
                "",
                "",
                item.tx_id,
                "",
                "",
                "",
                "",
                "rollback_invalidates_active_branch",
                "rollback_invalidates_active_branch",
                "work",
                active_object.object_id,
                tuple(sorted(payload["invalidated_roots"])),
                affected_run_ids,
                None,
                None,
                item.event_id,
                item.event_hash,
            )
            overlays.append(overlay)
        revision_actions.append(
            ProjectRevisionAction(
                revision,
                namespace,
                item.event_type,
                active_object.object_id,
                active_object.object_head,
                active_object.dependencies,
                payload.get("locked_policy_digest"),
                overlay,
            )
        )

    active_objects = tuple(sorted(objects.values()))
    invalidation = _compute_invalidation(active_objects, explicit_invalid)
    validity_digest, validity_root, _, _ = _project_validity_values_v2(
        active_objects, invalidation, locked_policy
    )
    active_roots = {
        namespace: domain_hash(
            ACTIVE_ROOT_DOMAIN,
            {
                "namespace": namespace,
                "objects": [
                    _object_projection(item)
                    for item in active_objects
                    if item.namespace == namespace
                ],
            },
        )
        for namespace in GENESIS_TYPES
    }
    active_fact_vector_digest = domain_hash(
        "vivarium-active-fact-vector/v1",
        [
            _object_projection(item)
            for item in active_objects
            if item.namespace == "truth" and item.object_type == "fact"
        ],
    )
    tails = semantic_tails
    projection = {
        "project_revision": len(semantic),
        "truth_event_seq": tails["truth"].event_seq,
        "truth_event_hash": tails["truth"].event_hash,
        "active_truth_root": active_roots["truth"],
        "active_fact_vector_digest": active_fact_vector_digest,
        "truth_reducer_digest": LEDGER_REDUCER_DIGESTS["truth"],
        "decision_event_seq": tails["decision"].event_seq,
        "decision_event_hash": tails["decision"].event_hash,
        "active_decision_root": active_roots["decision"],
        "decision_reducer_digest": LEDGER_REDUCER_DIGESTS["decision"],
        "work_state_event_seq": tails["work"].event_seq,
        "work_state_event_hash": tails["work"].event_hash,
        "active_work_root": active_roots["work"],
        "project_work_reducer_digest": LEDGER_REDUCER_DIGESTS["work"],
        "memory_event_seq": tails["memory"].event_seq,
        "memory_event_hash": tails["memory"].event_hash,
        "active_memory_root": active_roots["memory"],
        "memory_reducer_digest": LEDGER_REDUCER_DIGESTS["memory"],
        "run_registry_event_seq": tails["run_registry"].event_seq,
        "run_registry_event_hash": tails["run_registry"].event_hash,
        "active_run_registry_root": active_roots["run_registry"],
        "run_registry_reducer_digest": LEDGER_REDUCER_DIGESTS["run_registry"],
        "locked_policy_digest": locked_policy,
        "project_validity_root": validity_root,
        "project_validity_reducer_digest": validity_digest,
    }
    cut_root = domain_hash(PROJECT_CUT_DOMAIN, projection)
    revision_snapshots: tuple[ProjectRevisionSnapshot, ...] = ()
    if build_revision_snapshots:
        revision_by_event = {
            (event.ledger_id, event.event_id): revision
            for revision, _, event, _, _ in semantic
        }
        snapshots: list[ProjectRevisionSnapshot] = []
        for target_revision in range(len(semantic) + 1):
            truncated = {}
            for project_namespace, events in verified_prefixes.items():
                tail_seq = 0
                for event in events[1:]:
                    event_revision = revision_by_event.get(
                        (event.ledger_id, event.event_id)
                    )
                    if event_revision is not None and event_revision <= target_revision:
                        tail_seq = event.event_seq
                truncated[project_namespace] = events[: tail_seq + 1]
            historical = _reduce_project_cut(
                ProjectPrefixes(**truncated), build_revision_snapshots=False
            )
            provisional = ProjectRevisionSnapshot(
                target_revision,
                ZERO_HASH,
                historical.active_object_heads,
                historical.invalidation_closure,
                historical.locked_policy_digest,
                historical.project_validity_root,
                historical.project_validity_reducer_digest,
            )
            candidate_chain = (*snapshots, provisional)
            snapshots.append(
                replace(
                    provisional,
                    project_semantic_cut_root=_project_cut_root_with_snapshots(
                        historical, candidate_chain
                    ),
                )
            )
        revision_snapshots = tuple(snapshots)
        cut_root = revision_snapshots[-1].project_semantic_cut_root
        if (
            _project_cut_root_with_snapshots(historical, revision_snapshots)
            != cut_root
        ):
            raise IntegrityError("project revision snapshot chain is not authenticated")
        snapshots_by_revision = {
            snapshot.project_revision: snapshot for snapshot in revision_snapshots
        }
        for overlay in overlays:
            if overlay.event_type != "CORRECTION_BRANCH_CREATED":
                continue
            delta = overlay.dependency_delta
            if delta is None:
                raise IntegrityError("project correction lacks its dependency delta")
            new_baseline = snapshots_by_revision[overlay.project_revision - 1]
            if (
                delta.new_project_revision_baseline
                != new_baseline.project_revision
                or delta.new_project_semantic_cut_root_baseline
                != new_baseline.project_semantic_cut_root
            ):
                raise IntegrityError("correction new baseline is not an authenticated cut")
            expected_is_unfrozen = (
                delta.expected_project_revision_baseline == 0
                and delta.expected_project_semantic_cut_root_baseline == ZERO_HASH
                and not delta.expected_direct_dependency_heads
                and not delta.expected_dependency_closure
            )
            if not expected_is_unfrozen:
                expected_baseline = snapshots_by_revision.get(
                    delta.expected_project_revision_baseline
                )
                if (
                    expected_baseline is None
                    or delta.expected_project_semantic_cut_root_baseline
                    != expected_baseline.project_semantic_cut_root
                ):
                    raise IntegrityError(
                        "correction expected baseline is not an authenticated cut"
                    )
                _validate_snapshot_dependencies(
                    delta.expected_direct_dependency_heads,
                    delta.expected_dependency_closure,
                    expected_baseline,
                    "expected",
                )
            _validate_snapshot_dependencies(
                delta.new_direct_dependency_heads,
                delta.new_dependency_closure,
                new_baseline,
                "new",
            )
    return ProjectSemanticCut(
        len(semantic),
        tails["truth"].event_seq, tails["truth"].event_hash, active_roots["truth"],
        active_fact_vector_digest, LEDGER_REDUCER_DIGESTS["truth"],
        tails["decision"].event_seq, tails["decision"].event_hash,
        active_roots["decision"], LEDGER_REDUCER_DIGESTS["decision"],
        tails["work"].event_seq, tails["work"].event_hash, active_roots["work"],
        LEDGER_REDUCER_DIGESTS["work"],
        tails["memory"].event_seq, tails["memory"].event_hash, active_roots["memory"],
        LEDGER_REDUCER_DIGESTS["memory"],
        tails["run_registry"].event_seq, tails["run_registry"].event_hash,
        active_roots["run_registry"], LEDGER_REDUCER_DIGESTS["run_registry"],
        locked_policy,
        active_objects,
        tuple(overlays),
        tuple(revision_actions),
        revision_snapshots,
        invalidation,
        validity_root,
        validity_digest,
        cut_root,
    )
