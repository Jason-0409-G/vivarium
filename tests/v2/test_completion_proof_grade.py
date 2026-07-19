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


if __name__ == "__main__":
    unittest.main()
