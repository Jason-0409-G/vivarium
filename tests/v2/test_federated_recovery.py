import unittest

from skills.vivarium.vivarium_v2.errors import IntegrityError
from skills.vivarium.vivarium_v2.events import Event, ZERO_HASH
from skills.vivarium.vivarium_v2.reducers import (
    empty_project_state_root,
    federate,
    reduce_project_cut,
    reduce_project_validity,
    reduce_run,
    reduce_run_validity,
)
from skills.vivarium.vivarium_v2.state import AnalysisState, ProjectPrefixes


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
HASH_D = "sha256:" + "d" * 64


LEDGERS = {
    "truth": ("project-truth", "TRUTH_LEDGER_GENESIS"),
    "decision": ("project-decision", "DECISION_LEDGER_GENESIS"),
    "work": ("project-work", "WORK_LEDGER_GENESIS"),
    "memory": ("project-memory", "MEMORY_LEDGER_GENESIS"),
    "run_registry": ("project-run-registry", "RUN_REGISTRY_LEDGER_GENESIS"),
}


def event(events, ledger_id, event_type, payload, event_id=None):
    sequence = len(events)
    return Event.build(
        ledger_id=ledger_id,
        event_seq=sequence,
        event_id=event_id or f"{ledger_id}-{sequence}",
        event_type=event_type,
        tx_id=f"tx-{ledger_id}-{sequence}",
        prev_event_hash=events[-1].event_hash if events else ZERO_HASH,
        recorded_at=f"2026-07-18T00:00:{sequence:02d}Z",
        effective_at=f"2026-07-18T00:00:{sequence:02d}Z",
        payload=payload,
    )


def genesis_prefixes():
    prefixes = {}
    for namespace, (ledger_id, event_type) in LEDGERS.items():
        first = event(
            (),
            ledger_id,
            event_type,
            {
                "activated_objects": [],
                "canonical_dependency_edges": [],
                "initial_state_root": empty_project_state_root(namespace),
                "locked_policy_digest": "sha256:" + "f" * 64,
            },
        )
        prefixes[namespace] = (first,)
    return prefixes


def as_prefixes(prefixes):
    return ProjectPrefixes(**prefixes)


def prepared_run(run_id="run-1", dependency_heads=()):
    events = ()
    first = event(
        events,
        f"run:{run_id}",
        "RUN_LEDGER_GENESIS",
        {
            "run_id": run_id,
            "analysis_state": "PLANNED",
            "attempt_id": "attempt-1",
            "branch_id": "branch-1",
            "request_key": "request-1",
            "intent_key": "intent-1",
            "execution_key": "execution-1",
            "local_execution_key": "local-execution-1",
            "submission_key": "submission-1",
            "operation_keys": [],
            "merge_policy_digest": HASH_A,
        },
    )
    events = (first,)
    if dependency_heads:
        frozen = event(
            events,
            f"run:{run_id}",
            "ATTEMPT_DEPENDENCIES_FROZEN",
            {
                "attempt_id": "attempt-1",
                "direct_dependency_heads": list(dependency_heads),
                "dependency_closure": list(dependency_heads),
            },
        )
        events += (frozen,)
    trace = (
        ("CONTRACT_FROZEN", {"event_digest": HASH_B}),
        ("CANDIDATE_PREPARED", {"event_digest": HASH_B}),
        ("LOCAL_EXECUTION_INTENT", {"event_digest": HASH_B}),
        (
            "LOCAL_WRAPPER_ATTACHED",
            {"event_digest": HASH_B, "attachment_kind": "new_wrapper"},
        ),
        (
            "TERMINAL_EVIDENCE_FROZEN",
            {"event_digest": HASH_B, "evidence_kind": "terminal_cut"},
        ),
    )
    for event_type, payload in trace:
        next_event = event(events, f"run:{run_id}", event_type, payload)
        events += (next_event,)
    evidence = event(
        events,
        f"run:{run_id}",
        "EVIDENCE_CUT_FROZEN",
        {"evidence_cut_id": f"cut-{run_id}", "head_digest": "sha256:" + "b" * 64},
    )
    events += (evidence,)
    classification = event(
        events,
        f"run:{run_id}",
        "COMPLETION_CLASSIFIED",
        {
            "classification_id": f"classification-{run_id}",
            "evidence_cut_id": f"cut-{run_id}",
            "evidence_cut_digest": HASH_B,
            "outcome": "success",
        },
    )
    events += (classification,)
    proof = event(
        events,
        f"run:{run_id}",
        "COMPLETION_SUCCESS_PROVEN",
        {
            "classification_id": f"classification-{run_id}",
            "classification_event_id": classification.event_id,
            "classification_event_hash": classification.event_hash,
            "evidence_cut_id": f"cut-{run_id}",
            "evidence_cut_digest": HASH_B,
            "completion_proof_id": f"proof-{run_id}",
            "completion_proof_digest": HASH_C,
            "bundle_digest": HASH_D,
        },
    )
    events += (proof,)
    for event_type in ("VALIDATION_PASSED", "CHECKER_ALLOCATED", "CHECKER_QUORUM_PASSED"):
        next_event = event(
            events, f"run:{run_id}", event_type, {"event_digest": HASH_B}
        )
        events += (next_event,)
    prepare = event(
        events,
        f"run:{run_id}",
        "COMMIT_PREPARED",
        {
            "commit_tx_id": f"commit-{run_id}",
            "evidence_cut_id": f"cut-{run_id}",
            "evidence_cut_digest": "sha256:" + "b" * 64,
            "origin_state": "COMMITTING",
        },
    )
    return (*events, prepare), evidence, prepare


def federated(local, cut):
    validity = reduce_project_validity(cut)
    run_slice = reduce_run_validity(cut, validity, local)
    return federate(local, cut, validity, run_slice)


def commit_payload(revision, run_id, prepare, evidence):
    return {
        "project_revision": revision,
        "run_id": run_id,
        "run_event_id": prepare.event_id,
        "run_event_hash": prepare.event_hash,
        "commit_tx_id": f"commit-{run_id}",
        "prepare_event_id": prepare.event_id,
        "prepare_event_hash": prepare.event_hash,
        "evidence_cut_id": f"cut-{run_id}",
        "evidence_cut_digest": "sha256:" + "b" * 64,
        "object_type": "stage",
        "object_id": f"stage-{run_id}",
        "object_head": f"stage-{run_id}-v1",
        "dependencies": [],
    }


class FederatedRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.prepared_run_events, self.evidence, self.prepare = prepared_run()
        base = genesis_prefixes()
        self.project_before_commit = reduce_project_cut(as_prefixes(base))
        commit = event(
            base["work"],
            "project-work",
            "STAGE_COMMITTED",
            commit_payload(1, "run-1", self.prepare, self.evidence),
        )
        base["work"] += (commit,)
        self.committed_prefixes = base
        self.project_after_commit = reduce_project_cut(as_prefixes(base))

    def test_project_commit_overlays_unchanged_run_tail(self):
        local = reduce_run(self.prepared_run_events)
        before = federated(local, self.project_before_commit)
        after = federated(local, self.project_after_commit)

        self.assertEqual(before.analysis_state, AnalysisState.COMMITTING)
        self.assertEqual(after.analysis_state, AnalysisState.COMMITTED)
        self.assertEqual(before.run_local_state_root, after.run_local_state_root)
        self.assertNotEqual(before.federated_state_root, after.federated_state_root)

    def test_handoff_is_audit_only_and_does_not_change_semantic_cut(self):
        prefixes = dict(self.committed_prefixes)
        handoff = event(
            prefixes["work"],
            "project-work",
            "HANDOFF_PUBLISHED",
            {"artifact_digest": "sha256:" + "d" * 64},
        )
        prefixes["work"] += (handoff,)

        after_handoff = reduce_project_cut(as_prefixes(prefixes))

        self.assertEqual(
            after_handoff.project_semantic_cut_root,
            self.project_after_commit.project_semantic_cut_root,
        )
        self.assertEqual(after_handoff.work_state_event_hash, self.project_after_commit.work_state_event_hash)

    def test_inboxed_observation_blocks_before_opened(self):
        inboxed = event(
            self.prepared_run_events,
            "run:run-1",
            "POSTCOMMIT_OBSERVATION_INBOXED",
            {
                "observation_id": "observation-1",
                "observed_object_id": "stage-run-1",
                "observation_digest": "sha256:" + "e" * 64,
            },
        )
        state = reduce_run((*self.prepared_run_events, inboxed))

        self.assertTrue(state.postcommit_intake_blockers)
        self.assertFalse(federated(state, self.project_after_commit).default_retrievable)

    def test_missing_project_commit_binding_fails_closed(self):
        prefixes = genesis_prefixes()
        payload = commit_payload(1, "run-1", self.prepare, self.evidence)
        payload.pop("prepare_event_hash")
        commit = event(prefixes["work"], "project-work", "STAGE_COMMITTED", payload)
        prefixes["work"] += (commit,)

        with self.assertRaises(IntegrityError):
            reduce_project_cut(as_prefixes(prefixes))

    def test_project_commit_binding_must_be_reachable_from_run_prefix(self):
        local = reduce_run(self.prepared_run_events)
        prefixes = genesis_prefixes()
        payload = commit_payload(1, "run-1", self.prepare, self.evidence)
        payload["run_event_hash"] = "sha256:" + "9" * 64
        commit = event(prefixes["work"], "project-work", "STAGE_COMMITTED", payload)
        prefixes["work"] += (commit,)
        cut = reduce_project_cut(as_prefixes(prefixes))

        with self.assertRaises(IntegrityError):
            federated(local, cut)

    def test_project_commit_transaction_must_match_durable_preparation(self):
        local = reduce_run(self.prepared_run_events)
        prefixes = genesis_prefixes()
        payload = commit_payload(1, "run-1", self.prepare, self.evidence)
        payload["commit_tx_id"] = "different-commit"
        commit = event(prefixes["work"], "project-work", "STAGE_COMMITTED", payload)
        prefixes["work"] += (commit,)
        cut = reduce_project_cut(as_prefixes(prefixes))

        with self.assertRaises(IntegrityError):
            federated(local, cut)

    def test_project_correction_creates_planned_attempt_without_rewriting_run_tail(self):
        stale_event = event(
            self.prepared_run_events,
            "run:run-1",
            "CONTEXT_STALE",
            {"event_digest": HASH_B, "staleness_scope": "commit_point"},
        )
        local = reduce_run((*self.prepared_run_events, stale_event))
        prefixes = genesis_prefixes()
        correction = event(
            prefixes["work"],
            "project-work",
            "CORRECTION_BRANCH_CREATED",
            {
                "project_revision": 1,
                "object_type": "branch",
                "object_id": "branch-run-1-correction",
                "object_head": "branch-run-1-correction-v1",
                "dependencies": [],
                "run_id": "run-1",
                "run_event_id": stale_event.event_id,
                "run_event_hash": stale_event.event_hash,
                "correction_id": "correction-1",
                "prior_attempt_id": "attempt-1",
                "attempt_id": "attempt-2",
                "branch_id": "branch-2",
                "request_key": "request-2",
                "intent_key": "intent-2",
                "execution_key": "execution-2",
                "local_execution_key": "local-execution-2",
                "submission_key": "submission-2",
                "operation_keys": ["operation-2"],
            },
        )
        prefixes["work"] += (correction,)
        cut = reduce_project_cut(as_prefixes(prefixes))

        corrected = federated(local, cut)

        self.assertEqual(local.analysis_state, AnalysisState.STALE_CONTEXT)
        self.assertEqual(corrected.analysis_state, AnalysisState.PLANNED)
        self.assertEqual(corrected.run_local_state_root, local.run_local_state_root)

    def recheck_payload(self, revision, event_type):
        payload = commit_payload(revision, "run-1", self.prepare, self.evidence)
        payload.pop("commit_tx_id")
        payload["recheck_tx_id"] = "recheck-1"
        payload["object_head"] = f"stage-run-1-{event_type.lower()}"
        payload["target_namespace"] = "work"
        payload["target_object_id"] = "stage-run-1"
        if event_type == "opened":
            payload["recheck_scope"] = "own_stage"
        elif event_type == "refreshed":
            payload["refresh_result"] = "own_success"
        return payload

    def test_completion_recheck_open_and_refresh_are_project_overlays(self):
        local = reduce_run(self.prepared_run_events)
        prefixes = dict(self.committed_prefixes)
        opened = event(
            prefixes["work"],
            "project-work",
            "COMPLETION_RECHECK_OPENED",
            self.recheck_payload(2, "opened"),
        )
        prefixes["work"] += (opened,)
        opened_state = federated(local, reduce_project_cut(as_prefixes(prefixes)))
        refreshed = event(
            prefixes["work"],
            "project-work",
            "COMPLETION_PROOF_REFRESHED",
            self.recheck_payload(3, "refreshed"),
        )
        prefixes["work"] += (refreshed,)
        refreshed_state = federated(local, reduce_project_cut(as_prefixes(prefixes)))

        self.assertEqual(opened_state.analysis_state, AnalysisState.COMPLETION_RECHECK_PENDING)
        self.assertFalse(opened_state.default_retrievable)
        self.assertEqual(refreshed_state.analysis_state, AnalysisState.COMMITTED)
        self.assertTrue(refreshed_state.default_retrievable)

    def test_completion_recheck_revoke_stales_retrieval(self):
        local = reduce_run(self.prepared_run_events)
        prefixes = dict(self.committed_prefixes)
        opened = event(
            prefixes["work"],
            "project-work",
            "COMPLETION_RECHECK_OPENED",
            self.recheck_payload(2, "opened"),
        )
        prefixes["work"] += (opened,)
        revoked = event(
            prefixes["work"],
            "project-work",
            "COMPLETION_PROOF_REVOKED",
            self.recheck_payload(3, "revoked"),
        )
        prefixes["work"] += (revoked,)

        revoked_state = federated(local, reduce_project_cut(as_prefixes(prefixes)))

        self.assertEqual(revoked_state.analysis_state, AnalysisState.STALE_COMPLETION)
        self.assertFalse(revoked_state.default_retrievable)

    def test_replay_is_root_identical(self):
        one_local = reduce_run(self.prepared_run_events)
        two_local = reduce_run(self.prepared_run_events)
        one = federated(one_local, self.project_after_commit)
        two = federated(two_local, self.project_after_commit)

        self.assertEqual(one_local, two_local)
        self.assertEqual(one, two)


if __name__ == "__main__":
    unittest.main()
