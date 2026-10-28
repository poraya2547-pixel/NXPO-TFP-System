"""Offline negative controls for shell runners; never invokes real Docker."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]


class RunnerExitTest(unittest.TestCase):
    def test_suite_status_is_propagated(self):
        for script in ("test_in_image.sh", "api_tests.sh"):
            for case in ("pass", "pytest_fail", "parity_fail", "missing"):
                if script == "api_tests.sh" and case == "parity_fail":
                    continue
                with self.subTest(script=script, case=case), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    scripts = root / "tools/refactor"
                    scripts.mkdir(parents=True)
                    shutil.copyfile(REPO / "tools/refactor" / script, scripts / script)
                    stub = root / "docker"
                    stub.write_text('''#!/bin/sh
set -eu
if [ "$1" = image ]; then echo sha256:test; exit 0; fi
case "$*" in *" down "*) exit 0 ;; esac
out="$FAKE_ROOT/private/verification/result"
if [ "$FAKE_CASE" = missing ]; then exit 0; fi
status=0
if [ "$FAKE_CASE" = pytest_fail ]; then status=1; fi
echo "$status" > "$out/pytest_backend.exit"
echo "$status" > "$out/pytest_api.exit"
status=0
if [ "$FAKE_CASE" = parity_fail ]; then status=1; fi
echo "$status" > "$out/parity_cli.exit"
''')
                    stub.chmod(0o700)
                    env = dict(os.environ, PATH=f"{root}:{os.environ['PATH']}",
                               FAKE_ROOT=str(root), FAKE_CASE=case)
                    run = subprocess.run(["sh", str(scripts / script), "sha256:test", "result"],
                                         env=env, capture_output=True, text=True)
                    self.assertEqual(run.returncode == 0, case == "pass", run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
