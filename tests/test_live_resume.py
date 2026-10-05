"""Opt-in model integration test; normal CI never spends model credits."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
import uuid

REPO = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get("PT_CHECKPOINT_LIVE_TEST") == "1", "opt-in Claude model integration test")
class LiveResumeTest(unittest.TestCase):
    def test_fresh_session_reads_checkpoint(self):
        with tempfile.TemporaryDirectory(prefix="pt-live-resume-") as directory:
            root = Path(directory)
            marker = "resume-" + uuid.uuid4().hex
            state_script = shlex.quote(str(REPO / "scripts/state.py"))
            ledger_script = shlex.quote(str(REPO / "scripts/discovery.py"))
            def session(prompt):
                environment = dict(os.environ, PT_CHECKPOINT_STOP_MODE="changes")
                environment.pop("CLAUDE_PROJECT_DIR", None)
                command = ["claude", "-p", "--plugin-dir", str(REPO),
                    "--session-id", str(uuid.uuid4()), "--tools", "Read,Write,Bash",
                    "--allowedTools", "Read", "Write",
                    f"Bash(python3 {state_script} *)", f"Bash(python3 {ledger_script} *)",
                    "--", prompt]
                result = subprocess.run(command, cwd=root, env=environment,
                    capture_output=True, text=True, timeout=180)
                self.assertEqual(result.returncode, 0, "Claude session failed; inspect local authentication and tool permissions")
                return result.stdout
            session(
                "This is a synthetic plugin integration test with no external targets. "
                f"Record the exact resume marker {marker} in the checkpoint Resume point, "
                "append one synthetic observation to the ledger through discovery.py, and "
                "save the full state through state.py with its expected revision. "
                "Use the plugin's injected instructions. Complete the checkpoint now."
            )
            state = root / ".claude/AGENT_STATE.md"
            self.assertIn(marker, state.read_text(encoding="utf-8"))
            records = [json.loads(line) for line in (root / "discoveries.jsonl").read_text().splitlines()]
            self.assertTrue(records)
            answer = session("Read the project's saved checkpoint and return only the exact resume marker stored in its Resume point. Do not modify files.")
            self.assertIn(marker, answer)
