from __future__ import annotations

from typing import Any

from .canonical import domain_hash
from .errors import IntegrityError
from .state import (
    AttemptState,
    ProjectObjectHead,
    ProjectOverlay,
    ProjectRevisionSnapshot,
    ProjectSemanticCut,
    RunLocalState,
)
from ._replay_common import (
    ACTIVE_ROOT_DOMAIN,
    GENESIS_TYPES,
    PROJECT_VALIDITY_DOMAIN,
    PROJECT_VALIDITY_REDUCER_DIGEST,
    _dependency,
    _dependency_projection,
    _require_string,
)

PROJECT_CUT_DOMAIN = "vivarium-project-semantic-cut/v1"
PROJECT_REVISION_SNAPSHOT_CHAIN_DOMAIN = (
    "vivarium-project-revision-snapshot-chain/v1"
)

def _project_object(namespace: str, payload: dict[str, Any]) -> ProjectObjectHead:
    required = {"object_type", "object_id", "object_head", "dependencies"}
    if not required <= set(payload):
        raise IntegrityError("semantic activation fields are incomplete")
    raw_dependencies = payload["dependencies"]
    if not isinstance(raw_dependencies, list):
        raise IntegrityError("semantic activation dependencies must be a list")
    dependencies = tuple(sorted(_dependency(raw) for raw in raw_dependencies))
    if len(dependencies) != len({(item.namespace, item.object_id) for item in dependencies}):
        raise IntegrityError("semantic activation dependencies must be unique")
    return ProjectObjectHead(
        namespace,
        _require_string(payload, "object_type"),
        _require_string(payload, "object_id"),
        _require_string(payload, "object_head"),
        dependencies,
        payload.get("run_id") if isinstance(payload.get("run_id"), str) else None,
    )


def _object_projection(item: ProjectObjectHead) -> dict[str, Any]:
    return {
        "namespace": item.namespace,
        "object_type": item.object_type,
        "object_id": item.object_id,
        "object_head": item.object_head,
        "dependencies": [_dependency_projection(dep) for dep in item.dependencies],
        "owner_run_id": item.owner_run_id,
    }


def _revision_snapshot_projection(
    snapshot: ProjectRevisionSnapshot, *, include_cut_root: bool
) -> dict[str, Any]:
    projection = {
        "project_revision": snapshot.project_revision,
        "active_object_heads": [
            _object_projection(item) for item in snapshot.active_object_heads
        ],
        "invalidation_closure": list(snapshot.invalidation_closure),
        "locked_policy_digest": snapshot.locked_policy_digest,
        "project_validity_root": snapshot.project_validity_root,
        "project_validity_reducer_digest": (
            snapshot.project_validity_reducer_digest
        ),
    }
    if include_cut_root:
        projection["project_semantic_cut_root"] = snapshot.project_semantic_cut_root
    return projection


def _project_cut_root_with_snapshots(
    cut: ProjectSemanticCut,
    snapshots: tuple[ProjectRevisionSnapshot, ...],
) -> str:
    snapshot_chain_digest = domain_hash(
        PROJECT_REVISION_SNAPSHOT_CHAIN_DOMAIN,
        [
            _revision_snapshot_projection(
                snapshot, include_cut_root=index < len(snapshots) - 1
            )
            for index, snapshot in enumerate(snapshots)
        ],
    )
    projection = {
        "project_revision": cut.project_revision,
        "truth_event_seq": cut.truth_event_seq,
        "truth_event_hash": cut.truth_event_hash,
        "active_truth_root": cut.active_truth_root,
        "active_fact_vector_digest": cut.active_fact_vector_digest,
        "truth_reducer_digest": cut.truth_reducer_digest,
        "decision_event_seq": cut.decision_event_seq,
        "decision_event_hash": cut.decision_event_hash,
        "active_decision_root": cut.active_decision_root,
        "decision_reducer_digest": cut.decision_reducer_digest,
        "work_state_event_seq": cut.work_state_event_seq,
        "work_state_event_hash": cut.work_state_event_hash,
        "active_work_root": cut.active_work_root,
        "project_work_reducer_digest": cut.project_work_reducer_digest,
        "memory_event_seq": cut.memory_event_seq,
        "memory_event_hash": cut.memory_event_hash,
        "active_memory_root": cut.active_memory_root,
        "memory_reducer_digest": cut.memory_reducer_digest,
        "run_registry_event_seq": cut.run_registry_event_seq,
        "run_registry_event_hash": cut.run_registry_event_hash,
        "active_run_registry_root": cut.active_run_registry_root,
        "run_registry_reducer_digest": cut.run_registry_reducer_digest,
        "locked_policy_digest": cut.locked_policy_digest,
        "project_validity_root": cut.project_validity_root,
        "project_validity_reducer_digest": cut.project_validity_reducer_digest,
        "revision_snapshot_chain_digest": snapshot_chain_digest,
    }
    return domain_hash(PROJECT_CUT_DOMAIN, projection)


def _validate_project_snapshot_binding(cut: ProjectSemanticCut) -> None:
    snapshots = cut.revision_snapshots
    if (
        len(snapshots) != cut.project_revision + 1
        or tuple(item.project_revision for item in snapshots)
        != tuple(range(cut.project_revision + 1))
        or snapshots[-1].project_semantic_cut_root
        != cut.project_semantic_cut_root
        or _project_cut_root_with_snapshots(cut, snapshots)
        != cut.project_semantic_cut_root
    ):
        raise IntegrityError("project revision snapshot chain is not authenticated")


def _compute_invalidation(
    objects: tuple[ProjectObjectHead, ...], explicit: set[str]
) -> tuple[str, ...]:
    by_identity = {(item.namespace, item.object_id): item for item in objects}
    invalid = set(explicit)
    changed = True
    while changed:
        changed = False
        for item in objects:
            identity = f"{item.namespace}:{item.object_id}"
            if identity in invalid:
                continue
            for dependency in item.dependencies:
                active = by_identity.get((dependency.namespace, dependency.object_id))
                dep_identity = f"{dependency.namespace}:{dependency.object_id}"
                if (
                    active is None
                    or active.object_head != dependency.object_head
                    or dep_identity in invalid
                ):
                    invalid.add(identity)
                    changed = True
                    break
    return tuple(sorted(invalid))


def empty_project_state_root(namespace: str) -> str:
    if namespace not in GENESIS_TYPES:
        raise IntegrityError("unknown project reducer namespace")
    return domain_hash(
        ACTIVE_ROOT_DOMAIN, {"namespace": namespace, "objects": []}
    )


def _project_graph(
    objects: tuple[ProjectObjectHead, ...]
) -> tuple[tuple[tuple[str, str], ...], tuple[tuple[str, tuple[str, ...]], ...]]:
    edges = tuple(
        sorted(
            (
                f"{item.namespace}:{item.object_id}",
                f"{dependency.namespace}:{dependency.object_id}",
            )
            for item in objects
            for dependency in item.dependencies
        )
    )
    identities = {f"{item.namespace}:{item.object_id}" for item in objects}
    descendants = {identity: set() for identity in identities}
    for source, dependency in edges:
        descendants.setdefault(dependency, set()).add(source)
    changed = True
    while changed:
        changed = False
        for identity in list(descendants):
            expanded = set(descendants[identity])
            for child in tuple(expanded):
                expanded.update(descendants.get(child, ()))
            if expanded != descendants[identity]:
                descendants[identity] = expanded
                changed = True
    return edges, tuple(
        sorted((identity, tuple(sorted(values))) for identity, values in descendants.items())
    )


def _project_validity_values_v2(
    objects: tuple[ProjectObjectHead, ...], invalidation: tuple[str, ...], policy: str
) -> tuple[
    str,
    str,
    tuple[tuple[str, str], ...],
    tuple[tuple[str, tuple[str, ...]], ...],
]:
    edges, descendants = _project_graph(objects)
    projection = {
        "active_object_heads": [_object_projection(item) for item in objects],
        "invalidation_closure": list(invalidation),
        "dependency_edges": [list(item) for item in edges],
        "descendant_closure": [
            [identity, list(values)] for identity, values in descendants
        ],
        "locked_policy_digest": policy,
        "project_validity_reducer_digest": PROJECT_VALIDITY_REDUCER_DIGEST,
    }
    return (
        PROJECT_VALIDITY_REDUCER_DIGEST,
        domain_hash(PROJECT_VALIDITY_DOMAIN, projection),
        edges,
        descendants,
    )


def _validate_overlay_binding(local: RunLocalState, overlay: ProjectOverlay) -> None:
    if overlay.run_id != local.run_id:
        return
    reachable = {(item.event_id, item.event_hash) for item in local.reachable_run_events}
    if (overlay.run_event_id, overlay.run_event_hash) not in reachable:
        raise IntegrityError("project transition references an unreachable run event")
    if overlay.event_type == "CORRECTION_BRANCH_CREATED":
        return
    preparation = next(
        (
            item
            for item in local.preparations
            if item.prepare_event_id == overlay.prepare_event_id
            and item.prepare_event_hash == overlay.prepare_event_hash
        ),
        None,
    )
    if preparation is None or not preparation.active:
        raise IntegrityError("project transition references no active durable preparation")
    if (
        overlay.event_type == "STAGE_COMMITTED"
        and overlay.transaction_id != preparation.commit_tx_id
    ):
        raise IntegrityError("project commit transaction does not match durable preparation")
    if (
        preparation.evidence_cut_id != overlay.evidence_cut_id
        or preparation.evidence_cut_digest != overlay.evidence_cut_digest
    ):
        raise IntegrityError("project transition evidence binding disagrees with preparation")
    evidence = next(
        (item for item in local.evidence_cut_heads if item.evidence_cut_id == overlay.evidence_cut_id),
        None,
    )
    if evidence is None or evidence.head_digest != overlay.evidence_cut_digest:
        raise IntegrityError("project transition references an unreachable evidence cut")


def _validate_successor_attempt(
    successor: AttemptState, attempts: dict[str, AttemptState], prior_attempt_id: str
) -> None:
    if successor.prior_attempt_id != prior_attempt_id or successor.attempt_id in attempts:
        raise IntegrityError("project correction successor identity is inconsistent")
    for prior in attempts.values():
        if (
            successor.branch_id == prior.branch_id
            or successor.request_key == prior.request_key
            or successor.intent_key == prior.intent_key
            or successor.execution_key == prior.execution_key
            or successor.local_execution_key == prior.local_execution_key
            or successor.submission_key == prior.submission_key
            or set(successor.operation_keys) & set(prior.operation_keys)
        ):
            raise IntegrityError("project correction must allocate new attempt keys")
