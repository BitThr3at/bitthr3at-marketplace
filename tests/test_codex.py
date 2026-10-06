"""Codex package and hook contract tests; no model connection required."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "plugins/pt-checkpoint-codex"
sys.path.insert(0, str(REPO / "scripts"))
from build_codex import FILES


class CodexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="codex checkpoint spaces ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        self.environment = dict(os.environ, PLUGIN_ROOT=str(PACKAGE), PLUGIN_DATA=str(self.root / "plugin-data"), PT_CHECKPOINT_STOP_MODE="changes")
        self.environment.pop("PT_CHECKPOINT_PROJECT_DIR", None)
        # An inherited Claude root must never redirect Codex checkpoint writes.
        self.environment["CLAUDE_PROJECT_DIR"] = str(REPO)

    def hook(self, event, **fields):
        payload = dict(session_id="test-session", cwd=str(self.project), hook_event_name=event)
        payload.update(fields)
        hooks = json.loads((PACKAGE / "hooks/hooks.json").read_text())["hooks"]
        command = hooks[event][0]["hooks"][0]["command"]
        return subprocess.run(["/bin/sh", "-c", command], input=json.dumps(payload),
            capture_output=True, text=True, env=self.environment, cwd=self.project)

    def start(self):
        result = self.hook("SessionStart")
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]

    def test_package_is_self_contained_and_in_sync(self):
        for filename in FILES:
            self.assertEqual((PACKAGE / "scripts" / filename).read_bytes(), (REPO / "scripts" / filename).read_bytes(), f"rebuild Codex runtime: {filename}")
        self.assertEqual((PACKAGE / "schemas/discovery.schema.json").read_bytes(), (REPO / "schemas/discovery.schema.json").read_bytes())
        self.assertEqual((PACKAGE / "LICENSE").read_bytes(), (REPO / "LICENSE").read_bytes())
        manifest = json.loads((PACKAGE / "plugin.json").read_text())
        overlay = json.loads((PACKAGE / ".codex-plugin/plugin.json").read_text())
        self.assertEqual(manifest["name"], overlay["name"])
        self.assertEqual(manifest["version"], overlay["version"])
        self.assertLessEqual(len(manifest["extensions"]["com.openai"]["interface"]["shortDescription"]), 30)
        marketplace = json.loads((REPO / ".agents/plugins/marketplace.json").read_text())
        self.assertEqual((REPO / marketplace["plugins"][0]["source"]["path"]).resolve(), PACKAGE)

    def test_initialization_and_idle_stop(self):
        context = self.start()
        self.assertIn(str(self.project / ".claude/AGENT_STATE.md"), context)
        self.assertIn("codex:test-session", context)
        self.assertIn(str(PACKAGE / "scripts/state.py"), context)
        result = self.hook("Stop", stop_hook_active=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_apply_patch_tracks_changes_and_codex_continuation(self):
        self.start()
        result = self.hook("PostToolUse", tool_name="apply_patch", tool_input={"command": "*** Begin Patch\n*** Add File: evidence/proof.txt\n+Synthetic evidence\n*** End Patch"}, tool_response={"success": True})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        result = self.hook("Stop", stop_hook_active=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["decision"], "block")
        self.assertIn("discovery.py", output["reason"])
        self.assertEqual(self.hook("Stop", stop_hook_active=True).stdout, "")
        self.assertEqual(self.hook("Stop", stop_hook_active=False).stdout, "")

    def test_project_remains_pinned_outside_starting_directory(self):
        self.start()
        another = self.root / "other"
        another.mkdir()
        self.hook("PostToolUse", cwd=str(another), tool_name="apply_patch", tool_input={"command": f"*** Update File: {self.project / 'result.md'}\n@@\n-old\n+new"})
        result = self.hook("Stop", cwd=str(another))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(self.project / ".claude/AGENT_STATE.md"), result.stdout)
        self.assertFalse((another / ".claude").exists())

    def test_patch_filters_bookkeeping_and_external_paths(self):
        self.start()
        for patch in ("*** Update File: .claude/checkpoint-draft.md\n@@\n-old\n+new", "*** Add File: ../outside.txt\n+x"):
            self.hook("PostToolUse", tool_name="apply_patch", tool_input={"command": patch})
        self.assertEqual(self.hook("Stop").stdout, "")
        self.hook("PostToolUse", tool_name="apply_patch", tool_input={"command": "*** Add File: result.md\n+x"}, tool_response={"isError": True})
        self.assertEqual(self.hook("Stop").stdout, "")

    def test_codex_state_writer_acknowledges_correct_session(self):
        self.start()
        self.hook("PostToolUse", tool_name="apply_patch", tool_input={"command": "*** Add File: report.md\n+x"})
        command = [sys.executable, str(PACKAGE / "scripts/state.py"), "--project", str(self.project)]
        snapshot = subprocess.run(command + ["read"], capture_output=True, text=True)
        self.assertEqual(snapshot.returncode, 0, snapshot.stderr)
        state = json.loads(snapshot.stdout)
        draft = self.project / ".claude/checkpoint-draft.md"
        draft.write_text(state["content"] + "\nSynthetic saved result.\n", encoding="utf-8")
        result = subprocess.run(command + ["update", "--expected-sha256", state["sha256"], "--file", str(draft), "--session-id", "codex:test-session"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.hook("Stop").stdout, "")

    def test_new_codex_session_reuses_saved_state(self):
        self.start()
        state = self.project / ".claude/AGENT_STATE.md"
        previous = state.read_bytes()
        result = self.hook("SessionStart", session_id="fresh-session")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("codex:fresh-session", result.stdout)
        self.assertEqual(state.read_bytes(), previous)


if __name__ == "__main__":
    unittest.main()
