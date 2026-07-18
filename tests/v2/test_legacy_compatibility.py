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


if __name__ == "__main__":
    unittest.main()
