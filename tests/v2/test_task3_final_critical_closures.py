import unittest
from dataclasses import replace

from skills.vivarium.vivarium_v2.errors import IntegrityError
from skills.vivarium.vivarium_v2.reducers import (
    federate,
    reduce_project_cut,
    reduce_project_validity,
    reduce_run,
    reduce_run_validity,
)
from skills.vivarium.vivarium_v2.state import AnalysisState
from tests.v2.test_task3_review_closures import (
    HASH_A,
    HASH_B,
    HASH_C,
    HASH_D,
    activation,
    append,
    evidence_and_prepare,
    prefixes,
    project_genesis,
    run_genesis,
)
from tests.v2.test_task3_rereview_closures import commit_event_payload, prepared_local


def advance_to_collecting(events):
    trace = (
        ("CONTRACT_FROZEN", {"event_digest": HASH_A}),
        ("CANDIDATE_PREPARED", {"event_digest": HASH_A}),
        ("LOCAL_EXECUTION_INTENT", {"event_digest": HASH_A}),
        (
            "LOCAL_WRAPPER_ATTACHED",
            {"event_digest": HASH_A, "attachment_kind": "new_wrapper"},
        ),
        (
            "TERMINAL_EVIDENCE_FROZEN",
            {"event_digest": HASH_A, "evidence_kind": "terminal_cut"},
        ),
    )
    for event_type, payload in trace:
        events = append(events, events[0].ledger_id, event_type, payload)
    return events


def dependency_freeze_payload(revision, cut_root, direct, closure):
    return {
        "attempt_id": "attempt-1",
        "project_revision": revision,
        "project_semantic_cut_root": cut_root,
        "direct_dependency_heads": list(direct),
        "dependency_closure": list(closure),
    }


class FinalCriticalClosures(unittest.TestCase):
    def test_revision_snapshot_chain_is_bound_to_the_semantic_cut_root(self):
        values = project_genesis()
        values["truth"] = append(
            values["truth"],
            "project-truth",
            "FACT_ACTIVATED",
            activation(1, "fact-A", "A1"),
        )
        values["truth"] = append(
            values["truth"],
            "project-truth",
            "FACT_ACTIVATED",
            activation(2, "fact-A", "A2"),
        )
        cut = reduce_project_cut(prefixes(values))
        forged_revision_one = replace(
            cut.revision_snapshots[2],
            project_revision=1,
            project_semantic_cut_root=HASH_D,
        )
        tampered = replace(
            cut,
            revision_snapshots=(
                cut.revision_snapshots[0],
                forged_revision_one,
                cut.revision_snapshots[2],
            ),
        )

        with self.assertRaises(IntegrityError):
            reduce_project_validity(tampered)

    def test_forged_older_baseline_cannot_claim_a_future_dependency_head(self):
        values = project_genesis()
        values["truth"] = append(
            values["truth"],
            "project-truth",
            "FACT_ACTIVATED",
            activation(1, "fact-A", "A1"),
        )
        values["truth"] = append(
            values["truth"],
            "project-truth",
            "FACT_ACTIVATED",
            activation(2, "fact-A", "A2"),
        )
        cut = reduce_project_cut(prefixes(values))
        future_head = {
            "namespace": "truth",
            "object_id": "fact-A",
            "object_head": "A2",
        }
        events = run_genesis("COMMITTED", run_id="forged-baseline")
        events = append(
            events,
            events[0].ledger_id,
            "ATTEMPT_DEPENDENCIES_FROZEN",
            dependency_freeze_payload(1, HASH_D, (future_head,), (future_head,)),
        )
        local = reduce_run(events)
        validity = reduce_project_validity(cut)

        with self.assertRaises(IntegrityError):
            reduce_run_validity(cut, validity, local)

    def test_prior_attempt_authority_chain_cannot_advance_retry_attempt(self):
        events = advance_to_collecting(run_genesis("PLANNED", run_id="authority-attempt"))
        events = append(
            events,
            events[0].ledger_id,
            "EVIDENCE_CUT_FROZEN",
            {"evidence_cut_id": "cut-1", "head_digest": HASH_A},
        )
        evidence = events[-1]
        events = append(
            events,
            events[0].ledger_id,
            "EVIDENCE_BUNDLE_FROZEN",
            {
                "bundle_id": "bundle-1",
                "bundle_digest": HASH_B,
                "evidence_cut_id": "cut-1",
                "evidence_cut_event_id": evidence.event_id,
                "evidence_cut_event_hash": evidence.event_hash,
                "evidence_cut_digest": HASH_A,
            },
        )
        bundle = events[-1]
        events = append(
            events,
            events[0].ledger_id,
            "COMPLETION_CLASSIFIED",
            {
                "classification_id": "success-1",
                "evidence_cut_id": "cut-1",
                "evidence_cut_digest": HASH_A,
                "outcome": "success",
            },
        )
        classification_event = events[-1]
        classification = reduce_run(events).completion_classifications[-1]
        events = append(
            events,
            events[0].ledger_id,
            "COMPLETION_PROOF_RECORDED",
            {
                "completion_proof_id": "proof-1",
                "completion_proof_digest": HASH_C,
                "classification_id": "success-1",
                "classification_event_id": classification_event.event_id,
                "classification_event_hash": classification_event.event_hash,
                "classification_digest": classification.classification_digest,
                "evidence_cut_id": "cut-1",
                "evidence_cut_digest": HASH_A,
            },
        )
        proof = events[-1]
        events = append(
            events,
            events[0].ledger_id,
            "COMPLETION_CLASSIFIED",
            {
                "classification_id": "retryable-1",
                "evidence_cut_id": "cut-1",
                "evidence_cut_digest": HASH_A,
                "outcome": "failure_retryable",
            },
        )
        events = append(
            events,
            events[0].ledger_id,
            "ATTEMPT_RETRY_CREATED",
            {
                "repair_kind": "retry_policy_budget_allow",
                "prior_attempt_id": "attempt-1",
                "attempt_id": "attempt-2",
                "branch_id": "branch-2",
                "request_key": "request-2",
                "intent_key": "intent-2",
                "execution_key": "execution-2",
                "local_execution_key": "local-2",
                "submission_key": "submission-2",
                "operation_keys": [],
            },
        )
        events = advance_to_collecting(events)
        forged = append(
            events,
            events[0].ledger_id,
            "COMPLETION_SUCCESS_PROVEN",
            {
                "completion_proof_id": "proof-1",
                "completion_proof_event_id": proof.event_id,
                "completion_proof_event_hash": proof.event_hash,
                "completion_proof_digest": HASH_C,
                "bundle_id": "bundle-1",
                "bundle_event_id": bundle.event_id,
                "bundle_event_hash": bundle.event_hash,
                "bundle_digest": HASH_B,
            },
        )

        with self.assertRaises(IntegrityError):
            reduce_run(forged)

    def test_dependency_history_before_freeze_baseline_does_not_stale_attempt(self):
        values = project_genesis()
        values["truth"] = append(
            values["truth"],
            "project-truth",
            "FACT_ACTIVATED",
            activation(1, "fact-A", "A1"),
        )
        values["truth"] = append(
            values["truth"],
            "project-truth",
            "FACT_ACTIVATED",
            activation(2, "fact-A", "A2"),
        )
        cut = reduce_project_cut(prefixes(values))
        dependency = {
            "namespace": "truth",
            "object_id": "fact-A",
            "object_head": "A2",
        }
        events = run_genesis("COMMITTED", run_id="freeze-baseline")
        events = append(
            events,
            events[0].ledger_id,
            "ATTEMPT_DEPENDENCIES_FROZEN",
            dependency_freeze_payload(
                cut.project_revision,
                cut.project_semantic_cut_root,
                (dependency,),
                (dependency,),
            ),
        )
        local = reduce_run(events)
        validity = reduce_project_validity(cut)
        run_slice = reduce_run_validity(cut, validity, local)

        self.assertEqual(run_slice.state, AnalysisState.COMMITTED)
        self.assertEqual(local.attempts[0].project_revision_baseline, 2)
        self.assertEqual(
            local.attempts[0].project_semantic_cut_root_baseline,
            cut.project_semantic_cut_root,
        )

    def test_recheck_preserves_real_dependency_head_and_suspends_child(self):
        _, owner_evidence, owner_prepare = prepared_local("baseline-owner")
        values = project_genesis()
        values["work"] = append(
            values["work"],
            "project-work",
            "STAGE_COMMITTED",
            commit_event_payload(
                1,
                "baseline-owner",
                owner_prepare,
                owner_evidence,
                "stage-baseline-owner",
            ),
        )
        baseline = reduce_project_cut(prefixes(values))
        upstream = {
            "namespace": "work",
            "object_id": "stage-baseline-owner",
            "object_head": "stage-baseline-owner-head-1",
        }
        child_events = run_genesis("COMMITTING", run_id="baseline-child")
        child_events = append(
            child_events,
            child_events[0].ledger_id,
            "ATTEMPT_DEPENDENCIES_FROZEN",
            dependency_freeze_payload(
                baseline.project_revision,
                baseline.project_semantic_cut_root,
                (upstream,),
                (upstream,),
            ),
        )
        child_events, child_evidence, child_prepare = evidence_and_prepare(
            child_events, commit_tx="commit-baseline-child"
        )
        child = reduce_run(child_events)
        values["work"] = append(
            values["work"],
            "project-work",
            "STAGE_COMMITTED",
            commit_event_payload(
                2,
                "baseline-child",
                child_prepare,
                child_evidence,
                "stage-baseline-child",
                (upstream,),
            ),
        )
        recheck = commit_event_payload(
            3,
            "baseline-owner",
            owner_prepare,
            owner_evidence,
            "stage-baseline-owner",
        )
        recheck.pop("commit_tx_id")
        recheck.update(
            {
                "recheck_tx_id": "recheck-baseline-owner",
                "recheck_scope": "own_stage",
                "target_namespace": "work",
                "target_object_id": "stage-baseline-owner",
            }
        )
        values["work"] = append(
            values["work"],
            "project-work",
            "COMPLETION_RECHECK_OPENED",
            recheck,
        )
        cut = reduce_project_cut(prefixes(values))
        validity = reduce_project_validity(cut)
        run_slice = reduce_run_validity(cut, validity, child)
        final = federate(child, cut, validity, run_slice)

        self.assertEqual(run_slice.state, AnalysisState.PENDING_COMPLETION_DEPENDENCY)
        self.assertEqual(final.analysis_state, AnalysisState.PENDING_COMPLETION_DEPENDENCY)
        heads = {
            (item.namespace, item.object_id): item.object_head
            for item in cut.active_object_heads
        }
        self.assertEqual(heads[("work", "stage-baseline-owner")], upstream["object_head"])


if __name__ == "__main__":
    unittest.main()
