import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from skills.vivarium.vivarium_v2.canonical import domain_hash
from skills.vivarium.vivarium_v2.roles import QuorumPolicy, decide_gate
from tests.v2.support import (
    checker_assignment,
    checker_receipt,
    passing_checker_review,
    sealed_role_fixture,
)


class CheckerQuorumTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.fixture = sealed_role_fixture(Path(self.temp.name) / "project")

    def tearDown(self):
        self.temp.cleanup()

    def _gate(
        self,
        assignments,
        reviews,
        receipts,
        *,
        policy=None,
        validator_seal=None,
        validator_hard_gates_passed=True,
    ):
        fixture = self.fixture
        return decide_gate(
            fixture["store"],
            fixture["bundle"],
            validator_seal or fixture["validator_seal"],
            mission_digest=fixture["mission_digest"],
            rubric_digest=fixture["rubric_digest"],
            acceptance_contract_digest=fixture["acceptance_contract_digest"],
            completion_claim_digest=fixture["completion_claim_digest"],
            assignments=assignments,
            reviews=reviews,
            capability_receipts=receipts,
            policy=policy or QuorumPolicy("L1", 1, True, False),
            validator_hard_gates_passed=validator_hard_gates_passed,
        )

    def _pair(self, checker_id, namespace, assignment_id):
        receipt = checker_receipt(checker_id, namespace)
        assignment = checker_assignment(self.fixture, receipt, assignment_id)
        return receipt, assignment, passing_checker_review(assignment, receipt)

    def test_l1_allows_one_hard_isolated_review_only_under_explicit_policy(self):
        receipt, assignment, review = self._pair("checker-1", "ns-1", "a-1")
        decision = self._gate((assignment,), (review,), (receipt,))
        self.assertEqual(decision.outcome, "pass")
        decision = self._gate(
            (assignment,),
            (review,),
            (receipt,),
            policy=QuorumPolicy("L1", 1, False, False),
        )
        self.assertEqual(decision.outcome, "fail")
        self.assertIn("l1_single_review_requires_hard_isolation", decision.reasons)

    def test_l2_requires_two_independent_attested_namespaces(self):
        first = self._pair("checker-1", "ns-1", "a-1")
        second = self._pair("checker-2", "ns-2", "a-2")
        decision = self._gate(
            (first[1], second[1]),
            (first[2], second[2]),
            (first[0], second[0]),
            policy=QuorumPolicy("L2", 2, True, True),
        )
        self.assertEqual(decision.outcome, "pass")
        self.assertEqual(len(decision.accepted_review_digests), 2)

    def test_soft_isolation_fails_even_if_policy_does_not_repeat_the_hard_requirement(self):
        first = self._pair("checker-1", "ns-1", "a-1")
        soft_receipt = checker_receipt(
            "checker-2", "ns-2", isolation_level="soft"
        )
        soft_assignment = checker_assignment(self.fixture, soft_receipt, "a-2")
        soft_review = passing_checker_review(soft_assignment, soft_receipt)
        decision = self._gate(
            (first[1], soft_assignment),
            (first[2], soft_review),
            (first[0], soft_receipt),
            policy=QuorumPolicy("L2", 2, False, True),
        )
        self.assertEqual(decision.outcome, "fail")
        self.assertIn("soft_isolation", decision.reasons)

    def test_duplicate_assignment_or_namespace_fails(self):
        first = self._pair("checker-1", "ns-1", "a-1")
        duplicate_assignment = self._gate(
            (first[1], first[1]),
            (first[2],),
            (first[0],),
            policy=QuorumPolicy("L2", 2, True, True),
        )
        self.assertEqual(duplicate_assignment.outcome, "fail")
        self.assertIn("duplicate_assignment", duplicate_assignment.reasons)

        second = self._pair("checker-2", "ns-1", "a-2")
        duplicate_namespace = self._gate(
            (first[1], second[1]),
            (first[2], second[2]),
            (first[0], second[0]),
            policy=QuorumPolicy("L2", 2, True, True),
        )
        self.assertEqual(duplicate_namespace.outcome, "fail")
        self.assertIn("duplicate_namespace", duplicate_namespace.reasons)

    def test_all_authority_bindings_and_hard_validator_status_fail_closed(self):
        receipt, assignment, _ = self._pair("checker-1", "ns-1", "a-1")
        forged_digest = domain_hash("vivarium-test-forged/v1", {})
        for field in (
            "evidence_bundle_digest",
            "validator_seal_digest",
            "rubric_digest",
            "completion_claim_digest",
        ):
            forged_assignment = replace(assignment, **{field: forged_digest})
            forged_review = passing_checker_review(forged_assignment, receipt)
            with self.subTest(field=field):
                decision = self._gate(
                    (forged_assignment,), (forged_review,), (receipt,)
                )
                self.assertEqual(decision.outcome, "fail")
                self.assertIn("assignment_binding_mismatch", decision.reasons)

        review = passing_checker_review(assignment, receipt)
        validator_mismatch = replace(
            self.fixture["validator_seal"], evidence_bundle_digest=forged_digest
        )
        self.assertEqual(
            self._gate(
                (assignment,),
                (review,),
                (receipt,),
                validator_seal=validator_mismatch,
            ).outcome,
            "fail",
        )
        self.assertEqual(
            self._gate(
                (assignment,),
                (review,),
                (receipt,),
                validator_hard_gates_passed=False,
            ).outcome,
            "fail",
        )

    def test_major_or_critical_minority_and_insufficient_quorum_fail(self):
        first = self._pair("checker-1", "ns-1", "a-1")
        second = self._pair("checker-2", "ns-2", "a-2")
        third = self._pair("checker-3", "ns-3", "a-3")
        critical = passing_checker_review(
            third[1], third[0], severities=("Critical",)
        )
        minority = self._gate(
            (first[1], second[1], third[1]),
            (first[2], second[2], critical),
            (first[0], second[0], third[0]),
            policy=QuorumPolicy("L2", 2, True, True),
        )
        self.assertEqual(minority.outcome, "fail")
        self.assertIn("major_or_critical_finding", minority.reasons)

        critical_quorum = self._gate(
            (first[1], third[1]),
            (first[2], critical),
            (first[0], third[0]),
            policy=QuorumPolicy("L2", 2, True, True),
        )
        self.assertEqual(len(critical_quorum.accepted_review_digests), 1)
        self.assertIn("insufficient_quorum", critical_quorum.reasons)

        insufficient = self._gate(
            (first[1], second[1]),
            (first[2],),
            (first[0], second[0]),
            policy=QuorumPolicy("L2", 2, True, True),
        )
        self.assertEqual(insufficient.outcome, "fail")
        self.assertIn("insufficient_quorum", insufficient.reasons)


if __name__ == "__main__":
    unittest.main()
