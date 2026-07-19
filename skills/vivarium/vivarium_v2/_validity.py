from __future__ import annotations

from dataclasses import replace

from ._project_support import (
    PROJECT_VALIDITY_REDUCER_DIGEST,
    _compute_invalidation,
    _project_validity_values_v2,
    _validate_project_snapshot_binding,
    _validate_overlay_binding,
    _validate_successor_attempt,
)
from ._run_state_support import _attempt_projection
from .canonical import domain_hash
from .errors import IntegrityError
from .events import ZERO_HASH
RELEVANT_PROJECT_INPUT_DOMAIN = "vivarium-relevant-project-validity-input/v1"
RUN_VALIDITY_DOMAIN = "vivarium-run-validity-slice/v1"
RUN_VALIDITY_REDUCER_DIGEST = domain_hash(
    "vivarium-reducer-definition/v1", {"reducer": "run-validity", "version": 1}
)

from .state import (
    AnalysisState,
    AttemptState,
    DependencyHead,
    ProjectRevisionAction,
    ProjectSemanticCut,
    ProjectValidity,
    RelevantProjectInput,
    RunLocalState,
    RunValiditySlice,
    derive_transition,
    match_transition,
)


def reduce_project_validity(cut: ProjectSemanticCut) -> ProjectValidity:
    if not isinstance(cut, ProjectSemanticCut):
        raise IntegrityError("project validity requires a frozen semantic cut")
    _validate_project_snapshot_binding(cut)
    invalidation = _compute_invalidation(cut.active_object_heads, set(cut.invalidation_closure))
    digest, root, edges, descendants = _project_validity_values_v2(
        cut.active_object_heads, invalidation, cut.locked_policy_digest
    )
    if (
        digest != cut.project_validity_reducer_digest
        or root != cut.project_validity_root
        or invalidation != cut.invalidation_closure
    ):
        raise IntegrityError("project semantic cut carries inconsistent validity fields")
    if (
        len(cut.revision_snapshots) != cut.project_revision + 1
        or tuple(item.project_revision for item in cut.revision_snapshots)
        != tuple(range(cut.project_revision + 1))
    ):
        raise IntegrityError("project semantic cut lacks complete revision snapshots")
    for snapshot in cut.revision_snapshots:
        snapshot_invalidation = _compute_invalidation(
            snapshot.active_object_heads, set(snapshot.invalidation_closure)
        )
        snapshot_digest, snapshot_root, _, _ = _project_validity_values_v2(
            snapshot.active_object_heads,
            snapshot_invalidation,
            snapshot.locked_policy_digest,
        )
        if (
            snapshot_invalidation != snapshot.invalidation_closure
            or snapshot_digest != snapshot.project_validity_reducer_digest
            or snapshot_root != snapshot.project_validity_root
        ):
            raise IntegrityError("project revision snapshot has invalid validity fields")
    final_snapshot = cut.revision_snapshots[-1]
    if (
        final_snapshot.project_semantic_cut_root != cut.project_semantic_cut_root
        or final_snapshot.active_object_heads != cut.active_object_heads
        or final_snapshot.invalidation_closure != cut.invalidation_closure
        or final_snapshot.locked_policy_digest != cut.locked_policy_digest
        or final_snapshot.project_validity_root != cut.project_validity_root
        or final_snapshot.project_validity_reducer_digest
        != cut.project_validity_reducer_digest
    ):
        raise IntegrityError("final project revision snapshot disagrees with semantic cut")
    return ProjectValidity(
        cut.active_object_heads,
        invalidation,
        edges,
        descendants,
        cut.locked_policy_digest,
        digest,
        root,
    )


def reduce_run_validity(
    cut: ProjectSemanticCut, validity: ProjectValidity, local: RunLocalState
) -> RunValiditySlice:
    expected_validity = reduce_project_validity(cut)
    if validity != expected_validity:
        raise IntegrityError("run validity received mismatched project validity")
    if not isinstance(local, RunLocalState):
        raise IntegrityError("run validity requires frozen run-local output")
    attempts = {item.attempt_id: item for item in local.attempts}
    active_attempt_id = local.active_attempt_id
    blockers: set[str] = set()
    recheck_baseline: dict[str, AnalysisState] = {}
    operational_escalated = False
    current_heads: dict[tuple[str, str], str] = {}
    def active_attempt() -> AttemptState:
        return attempts[active_attempt_id]

    def set_effective_state(value: AnalysisState) -> None:
        attempts[active_attempt_id] = replace(active_attempt(), analysis_state=value)

    snapshots_by_revision = {
        item.project_revision: item for item in cut.revision_snapshots
    }

    def validate_attempt_baseline(attempt: AttemptState) -> None:
        baseline = attempt.project_revision_baseline
        if baseline < 0 or baseline > cut.project_revision:
            raise IntegrityError("attempt project baseline revision is outside the semantic cut")
        unfrozen = (
            baseline == 0
            and attempt.project_semantic_cut_root_baseline == ZERO_HASH
            and not attempt.direct_dependency_heads
            and not attempt.dependency_closure
        )
        if unfrozen:
            return
        snapshot = snapshots_by_revision[baseline]
        if (
            attempt.project_semantic_cut_root_baseline
            != snapshot.project_semantic_cut_root
        ):
            raise IntegrityError("attempt project baseline root is not authenticated")
        active = {
            (item.namespace, item.object_id): item
            for item in snapshot.active_object_heads
        }
        for dependency in attempt.direct_dependency_heads:
            current = active.get((dependency.namespace, dependency.object_id))
            if current is None or current.object_head != dependency.object_head:
                raise IntegrityError("attempt direct head is not active at its baseline")
        reachable: dict[tuple[str, str], DependencyHead] = {}
        pending = [
            (item.namespace, item.object_id)
            for item in attempt.direct_dependency_heads
        ]
        while pending:
            identity = pending.pop()
            if identity in reachable:
                continue
            current = active.get(identity)
            if current is None:
                raise IntegrityError("attempt closure is missing at its baseline")
            reachable[identity] = DependencyHead(
                current.namespace, current.object_id, current.object_head
            )
            pending.extend(
                (item.namespace, item.object_id) for item in current.dependencies
            )
        if tuple(sorted(reachable.values())) != attempt.dependency_closure:
            raise IntegrityError("attempt closure is not canonical at its baseline")

    validate_attempt_baseline(active_attempt())

    def action_relation(action: ProjectRevisionAction) -> str | None:
        overlay = action.overlay
        if overlay is None:
            return None
        if overlay.run_id == local.run_id:
            return "owner"
        if (
            overlay.event_type.startswith("COMPLETION_")
            and local.run_id in overlay.affected_run_ids
        ):
            return "descendant"
        if (
            overlay.event_type == "ROLLBACK_COMMITTED"
            and local.run_id in overlay.affected_run_ids
        ):
            return "owner"
        return None

    def overlay_transition(overlay, guard):
        source = active_attempt().analysis_state.value
        if guard:
            transition = match_transition(
                "analysis", source, overlay.event_type, guard
            )
        else:
            transition = derive_transition("analysis", source, overlay.event_type, {})
        if transition is None or transition.owner_ledger != "project":
            raise IntegrityError("project overlay has no machine-owned transition")
        return transition

    for action in cut.revision_actions:
        if action.project_revision <= active_attempt().project_revision_baseline:
            continue
        identity = (action.namespace, action.object_id)
        is_recheck_record = action.event_type.startswith("COMPLETION_")
        if not is_recheck_record:
            current_heads[identity] = action.object_head
        dependency_expectations = {
            (item.namespace, item.object_id): item.object_head
            for item in active_attempt().dependency_closure
        }
        if (
            not is_recheck_record
            and identity in dependency_expectations
            and action.object_head != dependency_expectations[identity]
        ):
            if active_attempt().analysis_state not in {
                AnalysisState.PLANNED,
                AnalysisState.STALE_BRANCH,
                AnalysisState.STALE_CONTEXT,
                AnalysisState.STALE_COMPLETION,
            }:
                set_effective_state(AnalysisState.STALE_CONTEXT)
        if (
            action.policy_digest is not None
            and action.policy_digest != local.merge_policy_digest
            and active_attempt().analysis_state not in {
                AnalysisState.PLANNED,
                AnalysisState.STALE_BRANCH,
                AnalysisState.STALE_CONTEXT,
                AnalysisState.STALE_COMPLETION,
            }
        ):
            set_effective_state(AnalysisState.STALE_CONTEXT)
        overlay = action.overlay
        relation = action_relation(action)
        if overlay is None or relation is None:
            continue
        guard = overlay.owner_guard if relation == "owner" else overlay.descendant_guard
        if overlay.event_type != "ROLLBACK_COMMITTED":
            _validate_overlay_binding(local, overlay)
        if overlay.event_type == "STAGE_COMMITTED":
            transition = overlay_transition(overlay, guard)
            set_effective_state(AnalysisState(transition.to_state))
        elif overlay.event_type == "CORRECTION_BRANCH_CREATED":
            successor = overlay.successor_attempt
            if successor is None or successor.prior_attempt_id != active_attempt_id:
                raise IntegrityError("project correction lacks a bound successor attempt")
            if active_attempt().analysis_state not in {
                AnalysisState.STALE_BRANCH,
                AnalysisState.STALE_CONTEXT,
                AnalysisState.STALE_COMPLETION,
            }:
                raise IntegrityError("project correction cannot replace a non-stale attempt")
            dependency_delta = overlay.dependency_delta
            if dependency_delta is None or (
                active_attempt().direct_dependency_heads
                != dependency_delta.expected_direct_dependency_heads
                or active_attempt().dependency_closure
                != dependency_delta.expected_dependency_closure
                or active_attempt().logical_scope_key
                != dependency_delta.expected_logical_scope_key
                or active_attempt().project_revision_baseline
                != dependency_delta.expected_project_revision_baseline
                or active_attempt().project_semantic_cut_root_baseline
                != dependency_delta.expected_project_semantic_cut_root_baseline
            ):
                raise IntegrityError("project correction dependency CAS does not match prior attempt")
            transition = overlay_transition(overlay, guard)
            if transition.to_state != AnalysisState.PLANNED.value:
                raise IntegrityError("project correction target is not PLANNED")
            _validate_successor_attempt(successor, attempts, active_attempt_id)
            attempts[successor.attempt_id] = successor
            active_attempt_id = successor.attempt_id
            validate_attempt_baseline(active_attempt())
            blockers.clear()
            recheck_baseline.clear()
            operational_escalated = False
        elif overlay.event_type == "COMPLETION_RECHECK_OPENED":
            if overlay.transaction_id in blockers:
                raise IntegrityError("recheck transaction blocker may only be opened once")
            if not blockers:
                recheck_baseline[active_attempt_id] = active_attempt().analysis_state
            blockers.add(overlay.transaction_id)
            if len(blockers) == 1:
                transition = match_transition(
                    "analysis",
                    active_attempt().analysis_state.value,
                    overlay.event_type,
                    guard,
                )
                set_effective_state(AnalysisState(transition.to_state))
            else:
                if guard not in {
                    "additional_complete_cut_durable",
                    "downstream_dependency_suspended",
                }:
                    raise IntegrityError("additional recheck OPEN has the wrong typed scope")
                transition = overlay_transition(overlay, guard)
                set_effective_state(AnalysisState(transition.to_state))
        elif overlay.event_type == "COMPLETION_PROOF_REFRESHED":
            if overlay.transaction_id not in blockers:
                raise IntegrityError("recheck REFRESH has no matching blocker")
            blockers.remove(overlay.transaction_id)
            if blockers:
                if guard != "refresh_blocker_removed_others_remain":
                    raise IntegrityError("partial recheck REFRESH has the wrong typed result")
                transition = overlay_transition(overlay, guard)
                set_effective_state(AnalysisState(transition.to_state))
            else:
                baseline = recheck_baseline.pop(active_attempt_id, None)
                if baseline is None:
                    raise IntegrityError("recheck REFRESH lost first-suspension baseline")
                transition = overlay_transition(overlay, guard)
                if AnalysisState(transition.to_state) != baseline:
                    raise IntegrityError("recheck REFRESH does not restore first baseline")
                set_effective_state(baseline)
                operational_escalated = False
        elif overlay.event_type == "COMPLETION_PROOF_REVOKED":
            if overlay.transaction_id not in blockers:
                raise IntegrityError("recheck REVOKE has no matching blocker")
            blockers.remove(overlay.transaction_id)
            transition = overlay_transition(overlay, guard)
            set_effective_state(AnalysisState(transition.to_state))
            operational_escalated = False
        elif overlay.event_type == "COMPLETION_RECHECK_DEFERRED":
            if overlay.transaction_id not in blockers:
                raise IntegrityError("deferred recheck has no matching blocker")
            transition = overlay_transition(overlay, guard)
            set_effective_state(AnalysisState(transition.to_state))
            operational_escalated = True
        elif overlay.event_type == "ROLLBACK_COMMITTED":
            if active_attempt().analysis_state != AnalysisState.COMMITTED:
                raise IntegrityError("rollback may only invalidate a committed run")
            set_effective_state(AnalysisState.STALE_BRANCH)

    active = active_attempt()
    edges_by_source: dict[str, set[str]] = {}
    for source, dependency in validity.dependency_edges:
        edges_by_source.setdefault(source, set()).add(dependency)
    canonical_identities: set[str] = set()
    pending = [
        f"{item.namespace}:{item.object_id}" for item in active.direct_dependency_heads
    ]
    while pending:
        identity = pending.pop()
        if identity in canonical_identities:
            continue
        canonical_identities.add(identity)
        pending.extend(edges_by_source.get(identity, ()))
    claimed_identities = {
        f"{item.namespace}:{item.object_id}" for item in active.dependency_closure
    }
    if claimed_identities != canonical_identities:
        raise IntegrityError("attempt dependency closure is not canonical for project validity")
    current = {
        (item.namespace, item.object_id): item for item in validity.active_object_heads
    }
    invalid = set(validity.invalidation_closure)
    relevant: list[RelevantProjectInput] = []
    reasons: list[str] = []
    for dependency in active.dependency_closure:
        value = current.get((dependency.namespace, dependency.object_id))
        invalidated = f"{dependency.namespace}:{dependency.object_id}" in invalid
        active_head = value.object_head if value else None
        relevant.append(
            RelevantProjectInput(
                dependency.namespace,
                dependency.object_id,
                dependency.object_head,
                active_head,
                invalidated,
            )
        )
        if value is None:
            reasons.append(f"missing:{dependency.namespace}:{dependency.object_id}")
        elif active_head != dependency.object_head:
            reasons.append(f"head_changed:{dependency.namespace}:{dependency.object_id}")
        elif invalidated:
            reasons.append(f"invalidated:{dependency.namespace}:{dependency.object_id}")
    ordered_relevant = tuple(sorted(relevant))
    ordered_reasons = tuple(sorted(reasons))
    if ordered_reasons and active.analysis_state not in {
        AnalysisState.PLANNED,
        AnalysisState.STALE_BRANCH,
        AnalysisState.STALE_CONTEXT,
        AnalysisState.STALE_COMPLETION,
    }:
        set_effective_state(AnalysisState.STALE_CONTEXT)
        active = active_attempt()
    if local.postcommit_escalations:
        set_effective_state(AnalysisState.ESCALATED)
        operational_escalated = True
        active = active_attempt()
    relevant_root = domain_hash(
        RELEVANT_PROJECT_INPUT_DOMAIN,
        {
            "locked_policy_digest": validity.locked_policy_digest,
            "relevant_project_inputs": [
                {
                    "namespace": item.namespace,
                    "object_id": item.object_id,
                    "expected_head": item.expected_head,
                    "active_head": item.active_head,
                    "invalidated": item.invalidated,
                }
                for item in ordered_relevant
            ],
        },
    )
    ordered_attempts = tuple(attempts.values())
    output = {
        "state": active.analysis_state.value,
        "attempts": [_attempt_projection(item) for item in ordered_attempts],
        "active_attempt_id": active_attempt_id,
        "completion_recheck_blockers": sorted(blockers),
        "operational_escalated": operational_escalated,
        "validity_reasons": list(ordered_reasons),
    }
    projection = {
        "run_id": local.run_id,
        "ledger_id": local.ledger_id,
        "run_event_seq": local.run_event_seq,
        "run_event_hash": local.run_event_hash,
        "run_local_state_root": local.run_local_state_root,
        "attempt_dependency_heads_root": local.attempt_dependency_heads_root,
        "relevant_project_validity_input_root": relevant_root,
        "run_validity_reducer_digest": RUN_VALIDITY_REDUCER_DIGEST,
        "run_validity_output": output,
    }
    root = domain_hash(RUN_VALIDITY_DOMAIN, projection)
    return RunValiditySlice(
        local.run_id,
        local.ledger_id,
        local.run_event_seq,
        local.run_event_hash,
        local.run_local_state_root,
        local.attempt_dependency_heads_root,
        ordered_relevant,
        relevant_root,
        RUN_VALIDITY_REDUCER_DIGEST,
        active.analysis_state,
        ordered_attempts,
        active_attempt_id,
        tuple(sorted(blockers)),
        operational_escalated,
        ordered_reasons,
        root,
    )
