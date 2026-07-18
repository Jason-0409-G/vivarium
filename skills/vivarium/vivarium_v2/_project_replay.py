from __future__ import annotations

from typing import Any

from ._reducer_support import (
    ACTIVE_ROOT_DOMAIN,
    GENESIS_LEDGER_IDS,
    GENESIS_TYPES,
    LEDGER_REDUCER_DIGESTS,
    _compute_invalidation,
    _new_attempt_from_payload,
    _object_projection,
    _project_object,
    _project_validity_values_v2,
    _require_dict,
    _require_int,
    _require_string,
    _verify_event_prefix,
    empty_project_state_root,
)
from .canonical import domain_hash
from .errors import IntegrityError
from .events import Event
from .state import (
    AnalysisState,
    ProjectObjectHead,
    ProjectOverlay,
    ProjectPrefixes,
    ProjectRevisionAction,
    ProjectSemanticCut,
    validate_event_payload,
)

PROJECT_CUT_DOMAIN = "vivarium-project-semantic-cut/v1"


def reduce_project_cut(prefixes: ProjectPrefixes) -> ProjectSemanticCut:
    if not isinstance(prefixes, ProjectPrefixes):
        raise IntegrityError("project prefixes must use frozen ProjectPrefixes")
    locked_policies: set[str] = set()
    semantic: list[tuple[int, str, Event, dict[str, Any], Any]] = []
    semantic_tails: dict[str, Event] = {}
    for namespace in GENESIS_TYPES:
        events = _verify_event_prefix(
            getattr(prefixes, namespace),
            genesis_type=GENESIS_TYPES[namespace],
            ledger_id=GENESIS_LEDGER_IDS[namespace],
        )
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
    for revision, namespace, item, payload, contract in semantic:
        active_object = _project_object(namespace, payload)
        objects[(namespace, active_object.object_id)] = active_object
        identity = f"{namespace}:{active_object.object_id}"
        if contract.action == "invalidate_object":
            explicit_invalid.add(identity)
        else:
            explicit_invalid.discard(identity)
        if contract.action == "lock_policy":
            locked_policy = _require_string(payload, "locked_policy_digest")
        overlay = None
        if contract.action in {"project_overlay", "project_correction", "project_recheck"}:
            if contract.action == "project_correction":
                transaction_id = _require_string(payload, "correction_id")
                successor = _new_attempt_from_payload(
                    payload,
                    AnalysisState.PLANNED,
                    _require_string(payload, "prior_attempt_id"),
                )
                guard = "new_branch_created"
                prepare_event_id = prepare_event_hash = evidence_cut_id = evidence_cut_digest = ""
                target_namespace = target_object_id = ""
            else:
                successor = None
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
                    guard = dict(
                        dict(contract.selector_guards)[payload[contract.selector_field]]
                    ).get("analysis", "")
                else:
                    guard = ""
            overlay = ProjectOverlay(
                revision,
                item.event_type,
                _require_string(payload, "run_id"),
                _require_string(payload, "run_event_id"),
                _require_string(payload, "run_event_hash"),
                transaction_id,
                prepare_event_id,
                prepare_event_hash,
                evidence_cut_id,
                evidence_cut_digest,
                guard,
                target_namespace,
                target_object_id,
                successor,
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
        invalidation,
        validity_root,
        validity_digest,
        cut_root,
    )
