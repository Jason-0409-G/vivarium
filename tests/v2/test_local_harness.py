import sys
import tempfile
import unittest
from pathlib import Path

from skills.vivarium.vivarium_v2.execution import LocalExecutionBroker
from skills.vivarium.vivarium_v2.local_harness import LocalProcessHarness
from skills.vivarium.vivarium_v2.project import ProjectStore
from tests.v2.support import FrozenClock, local_execution_intent


class LocalProcessHarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _store(self, name):
        store = ProjectStore.init(self.root / name, FrozenClock("2026-07-18T00:00:00Z"))
        store.register_run("run-1", analysis_state="EXECUTION_PENDING")
        return store

    def test_real_process_produces_a_success_cut(self):
        # A real OS process runs to completion in the attempt workspace and the
        # broker turns its real terminal evidence into a success ExecutionEvidenceCut.
        store = self._store("success")
        intent = local_execution_intent(
            argv=(sys.executable, "-c", "open('result.txt', 'w').write('hello vivarium')")
        )
        harness = LocalProcessHarness(store.root)
        result = LocalExecutionBroker(store, harness).run_or_recover(intent)

        self.assertEqual(result.classification.outcome, "success")
        self.assertIsNotNone(result.proof)
        self.assertEqual(result.evidence_cut.exit_code, 0)
        self.assertEqual(result.evidence_cut.execution_kind, "local_process")
        self.assertIn("process_exited", result.evidence_cut.absence_evidence)
        self.assertIn("outputs_quiescent", result.evidence_cut.absence_evidence)
        # the process REALLY ran and wrote a real file into the workspace
        self.assertEqual(
            (harness.workspace(intent) / "result.txt").read_text(encoding="utf-8"),
            "hello vivarium",
        )

    def test_nonzero_exit_produces_a_failure_cut(self):
        store = self._store("failure")
        intent = local_execution_intent(
            argv=(sys.executable, "-c", "import sys; sys.exit(3)")
        )
        result = LocalExecutionBroker(
            store, LocalProcessHarness(store.root)
        ).run_or_recover(intent)

        self.assertNotEqual(result.classification.outcome, "success")
        self.assertIsNone(result.proof)
        self.assertEqual(result.evidence_cut.exit_code, 3)

    def test_session_escaping_writer_is_not_reported_quiescent(self):
        # A descendant that setsid()s escapes the process-group containment check,
        # but if it is still writing outputs the settle-and-rehash catches the
        # mutating tree, so the step is NOT reported quiescent and cannot classify
        # success (honesty of the containment/quiescence report).
        store = self._store("escape")
        writer = (
            "import os,sys,time\n"
            "if os.fork()==0:\n"
            "    os.setsid()\n"
            "    for i in range(400):\n"
            "        open('out.txt','a').write(str(i)+'\\n')\n"
            "        time.sleep(0.005)\n"
            "    os._exit(0)\n"
            "sys.exit(0)\n"
        )
        intent = local_execution_intent(argv=(sys.executable, "-c", writer))
        harness = LocalProcessHarness(store.root, output_quiescence_seconds=0.2)
        result = LocalExecutionBroker(store, harness).run_or_recover(intent)
        self.assertNotEqual(result.classification.outcome, "success")
        self.assertNotIn("outputs_quiescent", result.evidence_cut.absence_evidence)

    def test_fresh_harness_recovers_the_cut_across_a_restart(self):
        # Terminal evidence is durable, so a fresh harness (a new process after a
        # crash) re-derives the identical cut on recovery instead of failing the
        # identity check and wedging the run.
        store = self._store("restart")
        intent = local_execution_intent(
            argv=(sys.executable, "-c", "open('r.txt','w').write('x')")
        )
        first = LocalExecutionBroker(store, LocalProcessHarness(store.root)).run_or_recover(
            intent
        )
        recovered = LocalExecutionBroker(
            store, LocalProcessHarness(store.root)
        ).recover(intent.execution_intent_id)
        self.assertEqual(
            recovered.evidence_cut.execution_evidence_cut_digest,
            first.evidence_cut.execution_evidence_cut_digest,
        )
        self.assertIsNotNone(recovered.proof)

    def test_recovery_reuses_the_same_cut_without_rerunning(self):
        # The intent is durable; recovering re-derives the identical cut and never
        # starts the process a second time.
        store = self._store("recover")
        intent = local_execution_intent(
            argv=(sys.executable, "-c", "open('r.txt','w').write('x')")
        )
        harness = LocalProcessHarness(store.root)
        broker = LocalExecutionBroker(store, harness)
        first = broker.run_or_recover(intent)
        recovered = broker.recover(intent.execution_intent_id)
        self.assertEqual(recovered.proof, first.proof)
        self.assertEqual(
            recovered.evidence_cut.execution_evidence_cut_digest,
            first.evidence_cut.execution_evidence_cut_digest,
        )


if __name__ == "__main__":
    unittest.main()
