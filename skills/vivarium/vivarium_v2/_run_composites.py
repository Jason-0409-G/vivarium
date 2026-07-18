from __future__ import annotations

from typing import Any

from .errors import IntegrityError
from .events import Event, ZERO_HASH
from .state import (
    AnalysisState,
    DuplicateScope,
    EVENT_CONTRACT_BY_TYPE,
    ExternalClientState,
    MutationClientRecord,
    ObligationRecord,
    derive_transition,
)
from ._replay_common import (
    _analysis_value,
    _client_value,
    _obligation_value,
    _require_dict,
    _require_digest,
    _require_string,
)

def _apply_typed_composite(
    event: Event,
    payload: dict[str, Any],
    composite: str,
    analysis_state: AnalysisState,
    obligations: dict[str, ObligationRecord],
    clients: dict[str, MutationClientRecord],
    duplicate_scopes: dict[str, DuplicateScope],
) -> tuple[
    AnalysisState,
    dict[str, ObligationRecord],
    dict[str, MutationClientRecord],
    dict[str, DuplicateScope],
]:
    analysis_delta = _require_dict(payload["analysis_delta"], "analysis_delta")
    contract = EVENT_CONTRACT_BY_TYPE[event.event_type]
    selector_mapping = (
        dict(dict(contract.selector_guards)[payload[contract.selector_field]])
        if contract.selector_field is not None
        else {"analysis": None}
    )
    if "analysis" not in selector_mapping:
        if analysis_delta:
            raise IntegrityError("typed selector forbids an analysis delta")
        target_analysis = analysis_state
    else:
        if set(analysis_delta) != {"expected_state", "new_state"}:
            raise IntegrityError("typed composite analysis_delta has an invalid field set")
        expected_analysis = _analysis_value(
            _require_string(analysis_delta, "expected_state"), "analysis expected_state"
        )
        target_analysis = _analysis_value(
            _require_string(analysis_delta, "new_state"), "analysis new_state"
        )
        if expected_analysis != analysis_state:
            raise IntegrityError("typed composite analysis CAS precondition failed")
        analysis_transition = derive_transition(
            "analysis", analysis_state.value, event.event_type, payload
        )
        if analysis_transition is None or analysis_transition.to_state != target_analysis.value:
            raise IntegrityError("typed composite analysis target is not machine-derived")

    raw_obligations = payload["obligation_deltas"]
    raw_clients = payload["client_deltas"]
    if not isinstance(raw_obligations, list) or not isinstance(raw_clients, list):
        raise IntegrityError("typed composite delta collections must be lists")
    if composite in {"duplicate_detected", "submission_reconciled", "duplicate_arbitrated"}:
        if not raw_obligations:
            raise IntegrityError("typed composite requires its cross-object obligation delta")
    if composite == "operation_reconciled" and payload["operation_result"] == "cancel_terminal":
        if len(raw_obligations) != 2 or not raw_clients:
            raise IntegrityError("cancel-terminal composite requires cancel, parent, and client deltas")

    scope_key = _require_string(payload, "side_effect_scope_key")
    scoped_obligation_ids = tuple(payload.get("scoped_obligation_ids", ()))
    scoped_client_ids = tuple(payload.get("scoped_client_ids", ()))
    if list(scoped_obligation_ids) != sorted(scoped_obligation_ids) or len(scoped_obligation_ids) != len(set(scoped_obligation_ids)):
        raise IntegrityError("scoped obligation IDs must be sorted and unique")
    if list(scoped_client_ids) != sorted(scoped_client_ids) or len(scoped_client_ids) != len(set(scoped_client_ids)):
        raise IntegrityError("scoped client IDs must be sorted and unique")

    if composite in {"duplicate_detected", "submission_reconciled", "duplicate_arbitrated"}:
        submission_id = _require_string(payload, "submission_obligation_id")
        submission = obligations.get(submission_id)
        if (
            submission is None
            or submission.obligation_kind != "submission"
            or submission.side_effect_scope_key != scope_key
        ):
            raise IntegrityError("submission identity is outside the side-effect scope")
    if composite == "duplicate_detected":
        if scope_key in duplicate_scopes:
            raise IntegrityError("duplicate side-effect scope may only be frozen once")
        if submission_id not in scoped_obligation_ids:
            raise IntegrityError("duplicate scope omits its submission obligation")
        if any(
            obligations.get(identity) is None
            or obligations[identity].side_effect_scope_key != scope_key
            for identity in scoped_obligation_ids
        ) or any(
            clients.get(identity) is None
            or clients[identity].side_effect_scope_key != scope_key
            for identity in scoped_client_ids
        ):
            raise IntegrityError("duplicate scope contains an unrelated object")
    elif composite == "duplicate_arbitrated":
        frozen_scope = duplicate_scopes.get(scope_key)
        if (
            frozen_scope is None
            or frozen_scope.submission_obligation_id != submission_id
            or frozen_scope.obligation_ids != scoped_obligation_ids
            or frozen_scope.client_ids != scoped_client_ids
        ):
            raise IntegrityError("duplicate arbitration scope disagrees with frozen detection")
    elif composite == "operation_reconciled":
        operation_id = _require_string(payload, "operation_obligation_id")
        parent_id = _require_string(payload, "parent_obligation_id")
        client_id = _require_string(payload, "external_client_id")
        operation_key = _require_string(payload, "operation_key")
        operation = obligations.get(operation_id)
        parent = obligations.get(parent_id)
        client = clients.get(client_id)
        if (
            operation is None
            or parent is None
            or client is None
            or operation.operation_key != operation_key
            or operation.parent_obligation_id != parent_id
            or client.operation_key != operation_key
            or operation.side_effect_scope_key != scope_key
            or parent.side_effect_scope_key != scope_key
            or client.side_effect_scope_key != scope_key
        ):
            raise IntegrityError("operation, parent, and client identities are not one frozen scope")

    staged_obligations = dict(obligations)
    obligation_ids: list[str] = []
    obligation_kinds: list[str] = []
    for raw in raw_obligations:
        delta = _require_dict(raw, "obligation delta")
        expected_fields = {
            "obligation_id", "obligation_kind", "expected_state", "new_state",
            "expected_head_digest", "new_head_digest",
        }
        if set(delta) != expected_fields:
            raise IntegrityError("typed obligation delta has an invalid field set")
        obligation_id = _require_string(delta, "obligation_id")
        obligation_kind = _require_string(delta, "obligation_kind")
        obligation_ids.append(obligation_id)
        obligation_kinds.append(obligation_kind)
        current = staged_obligations.get(obligation_id)
        if current is None or current.obligation_kind != obligation_kind:
            raise IntegrityError("typed obligation delta references an unknown object")
        expected = _obligation_value(
            _require_string(delta, "expected_state"), "obligation expected_state"
        )
        target = _obligation_value(
            _require_string(delta, "new_state"), "obligation new_state"
        )
        if current.state != expected or current.head_digest != _require_digest(delta, "expected_head_digest"):
            raise IntegrityError("typed obligation delta CAS precondition failed")
        transition = derive_transition(
            "obligation", current.state.value, event.event_type, payload
        )
        if transition is None or transition.to_state != target.value:
            raise IntegrityError("typed obligation target is not machine-derived")
        staged_obligations[obligation_id] = ObligationRecord(
            obligation_id,
            obligation_kind,
            target,
            _require_digest(delta, "new_head_digest"),
            current.side_effect_scope_key,
            current.operation_key,
            current.parent_obligation_id,
        )
    if obligation_ids != sorted(obligation_ids) or len(obligation_ids) != len(set(obligation_ids)):
        raise IntegrityError("typed obligation deltas must be sorted and unique")
    if composite == "operation_reconciled" and payload["operation_result"] == "cancel_terminal":
        if sorted(obligation_kinds) != ["cancellation", "submission"]:
            raise IntegrityError("cancel-terminal composite must update cancel and parent submission")

    staged_clients = dict(clients)
    client_ids: list[str] = []
    for raw in raw_clients:
        delta = _require_dict(raw, "client delta")
        expected_fields = {
            "operation_key", "expected_state", "new_state",
            "expected_head_digest", "new_head_digest",
        }
        if set(delta) != expected_fields:
            raise IntegrityError("typed client delta has an invalid field set")
        operation_key = _require_string(delta, "operation_key")
        client_ids.append(operation_key)
        current = staged_clients.get(operation_key)
        if current is None:
            raise IntegrityError("typed client delta references an unknown operation")
        expected = _client_value(
            _require_string(delta, "expected_state"), "client expected_state"
        )
        target = _client_value(_require_string(delta, "new_state"), "client new_state")
        if current.state != expected or current.head_digest != _require_digest(delta, "expected_head_digest"):
            raise IntegrityError("typed client delta CAS precondition failed")
        transition = derive_transition(
            "external_client", current.state.value, event.event_type, payload
        )
        if transition is None or transition.to_state != target.value:
            raise IntegrityError("typed client target is not machine-derived")
        staged_clients[operation_key] = MutationClientRecord(
            operation_key,
            target,
            _require_digest(delta, "new_head_digest"),
            current.side_effect_scope_key,
        )
    if client_ids != sorted(client_ids) or len(client_ids) != len(set(client_ids)):
        raise IntegrityError("typed client deltas must be sorted and unique")
    if composite == "submission_reconciled":
        if obligation_ids != [submission_id] or client_ids:
            raise IntegrityError("submission reconciliation has an invalid exact delta set")
    elif composite == "duplicate_detected":
        if tuple(obligation_ids) != scoped_obligation_ids or client_ids:
            raise IntegrityError("duplicate detection has an invalid exact delta set")
    elif composite == "duplicate_arbitrated":
        if tuple(obligation_ids) != scoped_obligation_ids:
            raise IntegrityError("duplicate arbitration omits a scoped obligation")
    elif composite == "operation_reconciled":
        expected_obligation_ids = (
            sorted((operation_id, parent_id))
            if payload["operation_result"] == "cancel_terminal"
            else [operation_id]
        )
        expected_client_ids = (
            [client_id] if payload["operation_result"] == "cancel_terminal" else []
        )
        if obligation_ids != expected_obligation_ids or client_ids != expected_client_ids:
            raise IntegrityError("operation reconciliation has an invalid exact delta set")
    if composite == "duplicate_arbitrated":
        open_clients = {
            key
            for key, value in clients.items()
            if key in scoped_client_ids
            and value.state != ExternalClientState.TERMINAL_DRAINED
        }
        if set(client_ids) != open_clients:
            raise IntegrityError("duplicate arbitration must close every client debt")
    staged_scopes = dict(duplicate_scopes)
    if composite == "duplicate_detected":
        staged_scopes[scope_key] = DuplicateScope(
            scope_key,
            submission_id,
            scoped_obligation_ids,
            scoped_client_ids,
            event.event_id,
            event.event_hash,
        )
    return target_analysis, staged_obligations, staged_clients, staged_scopes


def _apply_keyed_client_transition(
    event: Event,
    payload: dict[str, Any],
    clients: dict[str, MutationClientRecord],
) -> dict[str, MutationClientRecord]:
    scope_key = _require_string(payload, "side_effect_scope_key")
    raw_deltas = payload["client_deltas"]
    if not raw_deltas:
        raise IntegrityError("keyed client event requires one or more deltas")
    staged = dict(clients)
    identities: list[str] = []
    for raw in raw_deltas:
        delta = _require_dict(raw, "client delta")
        if set(delta) != {
            "operation_key", "expected_state", "new_state",
            "expected_head_digest", "new_head_digest",
        }:
            raise IntegrityError("keyed client delta has an invalid field set")
        key = _require_string(delta, "operation_key")
        identities.append(key)
        current = staged.get(key)
        current_state = current.state if current else ExternalClientState.NONE
        current_head = current.head_digest if current else ZERO_HASH
        expected = _client_value(delta["expected_state"], "client expected_state")
        target = _client_value(delta["new_state"], "client new_state")
        if (
            current_state != expected
            or current_head != _require_digest(delta, "expected_head_digest")
            or (current is not None and current.side_effect_scope_key != scope_key)
        ):
            raise IntegrityError("keyed client CAS precondition failed")
        transition = derive_transition(
            "external_client", current_state.value, event.event_type, payload
        )
        if transition is None or transition.to_state != target.value:
            raise IntegrityError("keyed client target is not machine-derived")
        staged[key] = MutationClientRecord(
            key, target, _require_digest(delta, "new_head_digest"), scope_key
        )
    if identities != sorted(identities) or len(identities) != len(set(identities)):
        raise IntegrityError("keyed client deltas must be sorted and unique")
    return staged
