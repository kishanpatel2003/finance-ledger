"""Synthetic end-to-end CLI checks; no existing ledger is opened."""
import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class ImportBehaviorTests(unittest.TestCase):
    def test_synthetic_demo_import_is_idempotent_and_scores(self):
        with tempfile.TemporaryDirectory() as scratch:
            env = dict(os.environ, MINT_HOME=scratch)
            csv = str(Path(scratch) / "demo.csv")
            def run(*args):
                result = subprocess.run([sys.executable, "-m", "mint", *args], cwd=ROOT,
                                        env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return result.stdout
            run("demo", csv)
            first = run("import-csv", csv, "--source", "demo")
            second = run("import-csv", csv, "--source", "demo")
            self.assertGreater(json.loads(first)["added"], 0)
            self.assertEqual(json.loads(second)["added"], 0)
            self.assertEqual(json.loads(second)["duplicates"], json.loads(first)["added"])
            run("character", "build", "--name", "Synthetic Baseline")
            self.assertTrue(run("week", "--days", "7").strip())
            self.assertTrue(run("status").strip())

if __name__ == "__main__":
    unittest.main()
