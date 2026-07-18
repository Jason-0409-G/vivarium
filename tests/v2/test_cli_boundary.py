import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path("skills/vivarium/scripts/orchestrate.py").resolve()
ERRORS = Path("skills/vivarium/vivarium_v2/errors.py")


class CliBoundaryTests(unittest.TestCase):
    def test_v2_without_subcommand_returns_v2_error_and_preserves_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = Path(td) / "run_manifest.json"
            original = '{"sentinel": true}\n'
            manifest.write_text(original, encoding="utf-8")

            result = subprocess.run(
                ["python3", str(SCRIPT), "v2"],
                text=True,
                capture_output=True,
                check=False,
                cwd=td,
            )

            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            self.assertIn("ERROR: V2 command required", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(manifest.read_text(encoding="utf-8"), original)

    def test_v2_unknown_subcommand_returns_v2_error(self):
        result = subprocess.run(
            ["python3", str(SCRIPT), "v2", "unknown"],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("ERROR: unknown V2 command: unknown", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_error_types_have_stable_exit_codes(self):
        self.assertTrue(ERRORS.is_file(), "V2 error module must exist")
        from skills.vivarium.vivarium_v2.errors import (
            IntegrityError,
            PolicyError,
            RecoveryRequired,
            VivariumError,
        )

        self.assertEqual(VivariumError.exit_code, 2)
        self.assertEqual(IntegrityError.exit_code, 3)
        self.assertEqual(PolicyError.exit_code, 4)
        self.assertEqual(RecoveryRequired.exit_code, 5)


if __name__ == "__main__":
    unittest.main()
