import tempfile
import unittest
from pathlib import Path

from skills.vivarium.vivarium_v2.errors import IntegrityError
from skills.vivarium.vivarium_v2.project import ProjectStore
from tests.v2.support import FrozenClock, fixture_store_at_revision, valid_prepared_commit


class ProjectRevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"

    def tearDown(self):
        self.temp.cleanup()

    def test_bootstrap_and_global_revision(self):
        store = ProjectStore.init(self.root, FrozenClock("2026-07-18T00:00:00Z"))
        cut = store.capture()[0]
        self.assertEqual(cut.project_revision, 0)
        self.assertTrue(
            all("project_revision" not in event.payload for event in store.genesis_events())
        )
        observed = [
            store.append_fixture_event(name).payload["project_revision"]
            for name in ("truth", "decision", "work", "memory", "run-registry")
        ]
        self.assertEqual(observed, [1, 2, 3, 4, 5])
        before = store.capture()[0].project_revision
        handoff = store.append_fixture_event("handoff")
        self.assertNotIn("project_revision", handoff.payload)
        self.assertEqual(store.capture()[0].project_revision, before)

    def test_commit_consumes_next_revision(self):
        store = fixture_store_at_revision(self.root, 17)
        event = store.complete_commit(valid_prepared_commit(store))
        self.assertEqual(event.payload["project_revision"], 18)

    def test_init_refuses_any_existing_path(self):
        self.root.mkdir()
        with self.assertRaises(IntegrityError):
            ProjectStore.init(self.root, FrozenClock("2026-07-18T00:00:00Z"))


if __name__ == "__main__":
    unittest.main()
