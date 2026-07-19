import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path("skills/vivarium/scripts/orchestrate.py")


class LegacyCompatibilityTests(unittest.TestCase):
    def test_init_status_update_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            genomes = root / "genomes"
            genomes.mkdir()
            (genomes / "a.fna").write_text(">a\nACGT\n", encoding="utf-8")
            init = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "init",
                    "--goal",
                    "compare-genomes",
                    "--indir",
                    str(genomes),
                    "--workdir",
                    str(root),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(init.returncode, 0, init.stderr)
            manifest = root / "vivarium_run_compare-genomes" / "run_manifest.json"
            body = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual([s["status"] for s in body["stages"]], ["planned"] * 4)

            status = subprocess.run(
                ["python3", str(SCRIPT), "status", "--manifest", str(manifest)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertIn("progress: 0/4 stages done", status.stdout)

            update = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "update",
                    "--manifest",
                    str(manifest),
                    "--stage",
                    "1",
                    "--status",
                    "done",
                    "--command",
                    "seqkit stats",
                    "--version",
                    "seqkit 2.8",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(update.returncode, 0, update.stderr)
            updated = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(updated["stages"][0]["status"], "done")
            self.assertEqual(updated["stages"][0]["command"], "seqkit stats")
            self.assertEqual(updated["stages"][0]["version"], "seqkit 2.8")


    def test_legacy_cli_refuses_to_touch_a_v2_run(self):
        # M-1 (audit): legacy init --force / update must fail closed on a run
        # carrying a V2 marker (run_format.json) instead of overwriting it.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            genomes = root / "genomes"
            genomes.mkdir()
            (genomes / "a.fna").write_text(">a\nACGT\n", encoding="utf-8")
            rundir = root / "vivarium_run_compare-genomes"
            rundir.mkdir()
            (rundir / "run_format.json").write_text(
                json.dumps({"format": "vivarium.run/v2"}), encoding="utf-8"
            )
            manifest = rundir / "run_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "goal": "compare-genomes",
                        "stages": [
                            {"skill": "vivarium-prep", "action": "stats",
                             "weight": "light", "status": "planned",
                             "inputs": [], "outputs": [], "command": "",
                             "version": "", "qc": ""}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            before = hashlib.sha256(manifest.read_bytes()).hexdigest()

            init = subprocess.run(
                ["python3", str(SCRIPT), "init", "--goal", "compare-genomes",
                 "--indir", str(genomes), "--workdir", str(root), "--force"],
                text=True, capture_output=True, check=False,
            )
            self.assertNotEqual(init.returncode, 0)

            update = subprocess.run(
                ["python3", str(SCRIPT), "update", "--manifest", str(manifest),
                 "--stage", "1", "--status", "done"],
                text=True, capture_output=True, check=False,
            )
            self.assertNotEqual(update.returncode, 0)

            self.assertEqual(
                before, hashlib.sha256(manifest.read_bytes()).hexdigest()
            )


    def test_legacy_cli_fails_closed_on_a_corrupt_v2_marker(self):
        # re-verify MINOR: a present-but-unreadable run_format.json must fail
        # closed (refuse), not fail open.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rundir = root / "vivarium_run_compare-genomes"
            rundir.mkdir(parents=True)
            (rundir / "run_format.json").write_text("{ not json", encoding="utf-8")
            manifest = rundir / "run_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "goal": "compare-genomes",
                        "stages": [
                            {"skill": "vivarium-prep", "action": "stats",
                             "weight": "light", "status": "planned",
                             "inputs": [], "outputs": [], "command": "",
                             "version": "", "qc": ""}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            before = hashlib.sha256(manifest.read_bytes()).hexdigest()
            update = subprocess.run(
                ["python3", str(SCRIPT), "update", "--manifest", str(manifest),
                 "--stage", "1", "--status", "done"],
                text=True, capture_output=True, check=False,
            )
            self.assertNotEqual(update.returncode, 0)
            self.assertEqual(
                before, hashlib.sha256(manifest.read_bytes()).hexdigest()
            )


if __name__ == "__main__":
    unittest.main()
