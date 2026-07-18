import unittest

from skills.vivarium.vivarium_v2.errors import IntegrityError
from skills.vivarium.vivarium_v2.execution import (
    build_completion_proof,
    classify_completion,
)
from tests.v2.support import execution_evidence_cut


class CompletionClassifierTests(unittest.TestCase):
    def test_success_classification_and_proof_are_deterministic(self):
        cut = execution_evidence_cut()
        first = classify_completion(cut)
        second = classify_completion(cut)

        self.assertEqual(first, second)
        self.assertEqual(first.outcome, "success")
        self.assertEqual(first.evidence_cut_digest, cut.execution_evidence_cut_digest)
        self.assertEqual(
            build_completion_proof(first, cut), build_completion_proof(second, cut)
        )

    def test_oom_signal_nonzero_and_unknown_are_never_success(self):
        cases = (
            execution_evidence_cut(oom=True),
            execution_evidence_cut(signal=9),
            execution_evidence_cut(exit_code=23),
            execution_evidence_cut(exit_code=None),
        )
        for cut in cases:
            with self.subTest(cut=cut):
                classification = classify_completion(cut)
                self.assertNotEqual(classification.outcome, "success")
                with self.assertRaises(IntegrityError):
                    build_completion_proof(classification, cut)

    def test_forged_success_classification_cannot_build_a_proof(self):
        cut = execution_evidence_cut(exit_code=None)
        forged = classify_completion(execution_evidence_cut())

        with self.assertRaises(IntegrityError):
            build_completion_proof(forged, cut)


if __name__ == "__main__":
    unittest.main()
