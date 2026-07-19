import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from skills.vivarium.vivarium_v2.errors import IntegrityError
from skills.vivarium.vivarium_v2.roles import (
    QuorumPolicy,
    assert_role_write_allowed,
    build_checker_assignment,
    decide_gate,
)
from tests.v2.support import (
    checker_assignment,
    checker_receipt,
    passing_checker_review,
    sealed_role_fixture,
)


class RoleIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.fixture = sealed_role_fixture(Path(self.temp.name) / "project")

    def tearDown(self):
        self.temp.cleanup()

    def _gate(self, assignment, review, receipt):
        fixture = self.fixture
        return decide_gate(
            fixture["store"],
            fixture["bundle"],
            fixture["validator_seal"],
            mission_digest=fixture["mission_digest"],
            rubric_digest=fixture["rubric_digest"],
            acceptance_contract_digest=fixture["acceptance_contract_digest"],
            completion_claim_digest=fixture["completion_claim_digest"],
            assignments=(assignment,),
            reviews=(review,),
            capability_receipts=(receipt,),
            policy=QuorumPolicy("L1", 1, True, False),
        )

    def test_role_write_boundaries_exclude_canonical_and_candidate_cross_writes(self):
        assert_role_write_allowed("maker", "candidate_payload")
        assert_role_write_allowed("checker", "checker_review")
        assert_role_write_allowed("orchestrator", "canonical_ledger")
        with self.assertRaises(IntegrityError):
            assert_role_write_allowed("maker", "canonical_ledger")
        with self.assertRaises(IntegrityError):
            assert_role_write_allowed("checker", "candidate_payload")

    def test_checker_packet_excludes_maker_chat_and_self_score_and_binds_authority(self):
        receipt = checker_receipt()
        assignment = checker_assignment(self.fixture, receipt)
        self.assertEqual(assignment.mission_digest, self.fixture["mission_digest"])
        self.assertEqual(assignment.rubric_digest, self.fixture["rubric_digest"])
        self.assertEqual(
            assignment.acceptance_contract_digest,
            self.fixture["acceptance_contract_digest"],
        )
        self.assertEqual(
            assignment.execution_evidence_cut_digest,
            self.fixture["bundle"].execution_evidence_cut_digest,
        )
        self.assertEqual(
            assignment.validator_seal_digest,
            self.fixture["validator_seal"].validator_seal_digest,
        )
        packet = dict(assignment.__dict__)
        for forbidden in ("maker_chat", "maker_self_score"):
            with self.subTest(forbidden=forbidden), self.assertRaises(IntegrityError):
                build_checker_assignment({**packet, forbidden: "never"}, receipt)
        with self.assertRaises(FrozenInstanceError):
            assignment.rubric_digest = "changed"

    def test_live_unresolved_and_soft_checker_capabilities_fail_closed(self):
        cases = (
            checker_receipt(live_capabilities=("workspace_write",)),
            checker_receipt(unresolved_capabilities=("network",)),
            checker_receipt(isolation_level="soft"),
        )
        for index, receipt in enumerate(cases):
            with self.subTest(receipt=receipt):
                assignment = checker_assignment(
                    self.fixture, receipt, assignment_id=f"assignment-{index}"
                )
                review = passing_checker_review(assignment, receipt)
                self.assertEqual(self._gate(assignment, review, receipt).outcome, "fail")


if __name__ == "__main__":
    unittest.main()
