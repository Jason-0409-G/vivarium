import unittest

from skills.vivarium.vivarium_v2.errors import IntegrityError
from skills.vivarium.vivarium_v2.execution import (
    build_completion_proof,
    classify_completion,
)
from tests.v2.support import execution_evidence_cut


class CompletionProofGradeTests(unittest.TestCase):
    def test_grade_reflects_execution_kind_not_a_bare_literal(self):
        # M-11 (audit): success_grade was hard-coded to the non-schema literal
        # "L1"; it must be the closed grade that matches the execution kind.
        cut = execution_evidence_cut()  # local_process success cut
        proof = build_completion_proof(classify_completion(cut), cut)
        self.assertEqual(proof.success_grade, "authoritative_local_process")
        self.assertNotEqual(proof.success_grade, "L1")

    def test_local_success_requires_a_valid_sentinel(self):
        # M-12 (audit): local_process success ignored the sentinel, unlike the
        # scheduler branch. A local cut without a valid sentinel is not success.
        cut = execution_evidence_cut(sentinel_digest="sentinel-missing")
        self.assertEqual(classify_completion(cut).outcome, "unknown_finality")


if __name__ == "__main__":
    unittest.main()
