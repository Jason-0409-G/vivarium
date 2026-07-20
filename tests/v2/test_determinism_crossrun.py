"""P3 regression: a deterministic stage re-run in two independent stores must
produce byte-identical SEALED execution digests, not just identical output.

Before the fix, the OS pid leaked into process_or_job_ref, process_receipt_digest,
sentinel_digest and local_executor_identity_digest, so every cut-derived sealed
digest differed across runs even for a zero-dependency deterministic step.
"""
import sys
import tempfile
import unittest
from pathlib import Path

from skills.vivarium.vivarium_v2.loop import perform_one_step
from skills.vivarium.vivarium_v2.project import ProjectStore
from skills.vivarium.vivarium_v2.steps import run_local_step
from tests.v2.support import FrozenClock

REPO = Path(__file__).resolve().parents[2]
GENOME = REPO / "tests" / "data" / "genomes" / "S_vesiculosa_M7.fna"
STATS = REPO / "skills" / "vivarium" / "scripts" / "steps" / "genome_stats.py"


def _run_once():
    import sys

    temp = tempfile.TemporaryDirectory()
    store = ProjectStore.init(Path(temp.name) / "s", FrozenClock("2026-07-20T00:00:00Z"))
    store.register_run("run-1", analysis_state="EXECUTION_PENDING")
    result = run_local_step(
        store,
        run_id="run-1",
        stage_id="stage-1",
        attempt_id="attempt-1",
        argv=(sys.executable, str(STATS), str(GENOME)),
    )
    cut = result.evidence_cut
    return temp, cut


class CrossRunDeterminismTests(unittest.TestCase):
    @unittest.skipUnless(GENOME.is_file() and STATS.is_file(), "fixtures absent")
    def test_sealed_cut_digest_reproduces_across_independent_runs(self):
        t1, cut1 = _run_once()
        self.addCleanup(t1.cleanup)
        t2, cut2 = _run_once()
        self.addCleanup(t2.cleanup)
        # sanity: both classified success on the same deterministic output
        self.assertEqual(cut1.exit_code, 0)
        self.assertEqual(cut2.exit_code, 0)
        # the sealed execution-evidence cut digest must NOT depend on the OS pid
        self.assertEqual(
            cut1.execution_evidence_cut_digest,
            cut2.execution_evidence_cut_digest,
            "sealed cut digest must reproduce across runs of a deterministic stage",
        )

    @unittest.skipUnless(GENOME.is_file() and STATS.is_file(), "fixtures absent")
    def test_committed_bundle_digest_reproduces_across_independent_runs(self):
        # The full committed path (evidence bundle -> ... -> STAGE_COMMITTED) must
        # also be pid-independent: the raw process-receipt artifact (which carries
        # the OS pid) is excluded from the sealed bundle.
        def _commit_once():
            temp = tempfile.TemporaryDirectory()
            self.addCleanup(temp.cleanup)
            store = ProjectStore.init(Path(temp.name) / "s", FrozenClock("2026-07-20T00:00:00Z"))
            store.register_run("run-1", analysis_state="EXECUTION_PENDING")
            step = perform_one_step(
                store,
                run_id="run-1",
                stage_id="stage-1",
                attempt_id="attempt-1",
                argv=(sys.executable, str(STATS), str(GENOME)),
            )
            self.assertTrue(step.committed)
            return step.stage_committed_event.payload

        a = _commit_once()
        b = _commit_once()
        self.assertEqual(
            a["evidence_bundle_digest"], b["evidence_bundle_digest"],
            "committed evidence bundle digest must reproduce across runs",
        )
        self.assertEqual(
            a["object_head"], b["object_head"],
            "committed object head must reproduce across runs",
        )


if __name__ == "__main__":
    unittest.main()
