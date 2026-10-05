import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from common import initialize
from discovery import append_record, read_records, validate_record
from discovery import STATUS, TYPES, CONFIDENCE, FIELDS
from common import TEMPLATE, append_log, project_root
from runtime import acknowledge
from state import revision, update_state


def record():
    return dict(type="observation", status="confirmed", target="example.com", value="test", summary="Synthetic observation", evidence=[], confidence="confirmed", source="test", metadata={})


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="checkpoint spaces ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def hook(self, name, data):
        return subprocess.run([sys.executable, str(REPO / "scripts" / name)], input=json.dumps(data), text=True, capture_output=True, cwd=self.root, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(self.root), PT_CHECKPOINT_STOP_MODE="changes"))

    def test_initialization_and_resume(self):
        first = self.hook("session_start.py", {"cwd": str(self.root), "unknown": True})
        self.assertEqual(first.returncode, 0, first.stderr)
        state = self.root / ".claude/AGENT_STATE.md"
        state.write_text("## Resume point\nReview saved result", encoding="utf-8")
        (self.root / "discoveries.jsonl").write_text("", encoding="utf-8")
        second = self.hook("session_start.py", {"cwd": str(self.root)})
        context = json.loads(second.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn(str(state), context)
        self.assertIn("Read the state", context)
        self.assertEqual(state.read_text(), "## Resume point\nReview saved result")
        self.assertFalse((self.root / "evidence").exists())

    def test_empty_state_preserved(self):
        initialize(self.root)
        state = self.root / ".claude/AGENT_STATE.md"
        state.write_text("")
        initialize(self.root)
        self.assertEqual(state.read_bytes(), b"")

    def test_append_and_missing_newline(self):
        first = append_record(self.root, record())
        ledger = self.root / "discoveries.jsonl"
        original = ledger.read_bytes().rstrip(b"\n")
        ledger.write_bytes(original)
        second = append_record(self.root, record())
        self.assertTrue(ledger.read_bytes().startswith(original + b"\n"))
        self.assertEqual(first["id"], "D-000001")
        self.assertEqual(second["id"], "D-000002")
        validate_record(first)
        with ledger.open() as stream:
            self.assertEqual(len(read_records(stream)), 2)

    def test_invalid_record_does_not_append(self):
        append_record(self.root, record())
        ledger = self.root / "discoveries.jsonl"
        original = ledger.read_bytes()
        for bad in (dict(record(), summary=" "), dict(record(), metadata=[]), dict(record(), evidence=[123])):
            with self.assertRaises(ValueError):
                append_record(self.root, bad)
            self.assertEqual(ledger.read_bytes(), original)

    def test_corruption_preserved(self):
        initialize(self.root)
        ledger = self.root / "discoveries.jsonl"
        ledger.write_bytes(b"broken\n")
        with self.assertRaisesRegex(ValueError, "line 1"):
            append_record(self.root, record())
        self.assertEqual(ledger.read_bytes(), b"broken\n")

    def test_concurrent_processes(self):
        initialize(self.root)
        command = [sys.executable, str(REPO / "scripts/discovery.py"), "add", "--type", "test", "--status", "tested", "--summary", "Synthetic test"]
        def add(_):
            return subprocess.run(command, cwd=self.root, capture_output=True, text=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(add, range(12)))
        for result in results:
            self.assertEqual(result.returncode, 0, result.stderr)
        with (self.root / "discoveries.jsonl").open() as stream:
            records = read_records(stream)
        self.assertEqual(len({r["id"] for r in records}), 12)

    def test_stop_guard_and_state_preservation(self):
        initialize(self.root)
        state = self.root / ".claude/AGENT_STATE.md"
        original = state.read_bytes()
        self.hook("session_start.py", {"cwd": str(self.root)})
        self.hook("post_tool.py", {"cwd": str(self.root), "tool_input": {"file_path": str(self.root / "report.md")}})
        output = self.hook("checkpoint.py", {"cwd": str(self.root), "stop_hook_active": False})
        self.assertEqual(json.loads(output.stdout)["hookSpecificOutput"]["hookEventName"], "Stop")
        log = (self.root / ".claude/checkpoint.log").read_bytes()
        output = self.hook("checkpoint.py", {"cwd": str(self.root), "stop_hook_active": True})
        self.assertEqual(output.returncode, 0)
        self.assertEqual(output.stdout, "")
        self.assertEqual(state.read_bytes(), original)
        self.assertEqual((self.root / ".claude/checkpoint.log").read_bytes(), log)

    def test_malformed_hook_input(self):
        result = self.hook("session_start.py", [])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("JSON object", result.stderr)

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as other:
            (self.root / ".claude").symlink_to(other, target_is_directory=True)
            with self.assertRaises(ValueError):
                initialize(self.root)
            self.assertFalse((Path(other) / "AGENT_STATE.md").exists())

    def test_cli_and_examples(self):
        append_record(self.root, record())
        for args in (("validate",), ("tail", "--count", "0"), ("stats",)):
            result = subprocess.run([sys.executable, str(REPO / "scripts/discovery.py"), *args], cwd=self.root, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        with (REPO / "examples/discoveries.example.jsonl").open() as stream:
            self.assertEqual(len(read_records(stream)), 1)

    def test_schema_matches_runtime(self):
        schema = json.loads((REPO / "schemas/discovery.schema.json").read_text())
        self.assertEqual(set(schema["required"]), set(FIELDS))
        for key, choices in (("status", STATUS), ("type", TYPES), ("confidence", CONFIDENCE)):
            self.assertEqual(schema["properties"][key]["enum"], list(choices))

    def test_configured_hook_command_with_spaces(self):
        # A symlink to the plugin exercises shell expansion without copying source.
        plugin_path = self.root / "plugin with spaces"
        plugin_path.symlink_to(REPO, target_is_directory=True)
        hooks = json.loads((REPO / "hooks/hooks.json").read_text())["hooks"]
        command = hooks["SessionStart"][0]["hooks"][0]["command"]
        result = subprocess.run(["/bin/sh", "-c", command],
            input=json.dumps({"cwd": str(self.root)}), text=True, capture_output=True,
            env=dict(os.environ, CLAUDE_PLUGIN_ROOT=str(plugin_path), CLAUDE_PROJECT_DIR=str(self.root)), cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["hookEventName"], "SessionStart")

    def test_pinned_root_after_cd(self):
        self.hook("session_start.py", {"cwd": str(self.root), "session_id": "a"})
        child = self.root / "child"
        child.mkdir()
        self.hook("post_tool.py", {"cwd": str(child), "session_id": "a", "tool_input": {"file_path": str(child / "result.md")}})
        result = self.hook("checkpoint.py", {"cwd": str(child), "session_id": "a"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(self.root.resolve() / ".claude/AGENT_STATE.md"), result.stdout)
        self.assertFalse((child / ".claude").exists())

    def test_idle_stop_is_silent(self):
        self.hook("session_start.py", {"cwd": str(self.root)})
        result = self.hook("checkpoint.py", {"cwd": str(self.root)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertFalse((self.root / ".claude/checkpoint.log").exists())

    def test_reminder_dedup_and_acknowledge(self):
        self.hook("session_start.py", {"cwd": str(self.root)})
        self.hook("post_tool.py", {"cwd": str(self.root), "tool_input": {"file_path": "evidence/result.txt"}})
        first = self.hook("checkpoint.py", {"cwd": str(self.root)})
        self.assertIn("discovery.py", first.stdout)
        self.assertIn("state.py", first.stdout)
        second = self.hook("checkpoint.py", {"cwd": str(self.root)})
        self.assertEqual(second.stdout, "")
        acknowledge(self.root, "default")
        self.assertEqual(self.hook("checkpoint.py", {"cwd": str(self.root)}).stdout, "")
        self.hook("post_tool.py", {"cwd": str(self.root), "tool_input": {"file_path": "next.md"}})
        self.assertTrue(self.hook("checkpoint.py", {"cwd": str(self.root)}).stdout)

    def test_ledger_changes_trigger_stop(self):
        self.hook("session_start.py", {"cwd": str(self.root)})
        append_record(self.root, record())
        self.assertTrue(self.hook("checkpoint.py", {"cwd": str(self.root)}).stdout)

    def test_atomic_state_update_backup_and_conflict(self):
        initialize(self.root)
        path = self.root / ".claude/AGENT_STATE.md"
        original = path.read_bytes()
        expected = revision(original)
        changed = TEMPLATE.replace("Review scope and existing evidence before starting new work.", "Review saved evidence.")
        update_state(self.root, changed, expected)
        self.assertEqual(path.read_text(), changed)
        self.assertEqual((self.root / ".claude/AGENT_STATE.md.bak").read_bytes(), original)
        with self.assertRaisesRegex(ValueError, "conflict"):
            update_state(self.root, TEMPLATE, expected)
        self.assertEqual(path.read_text(), changed)
        with self.assertRaisesRegex(ValueError, "headings"):
            update_state(self.root, "incomplete", revision(path.read_bytes()))

    def test_concurrent_state_writers(self):
        initialize(self.root)
        expected = revision((self.root / ".claude/AGENT_STATE.md").read_bytes())
        def write(number):
            try:
                update_state(self.root, TEMPLATE + f"\nSession {number}\n", expected)
                return "saved"
            except ValueError:
                return "conflict"
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(write, (1, 2)))
        self.assertCountEqual(outcomes, ["saved", "conflict"])

    def test_log_rotation(self):
        initialize(self.root)
        append_log(self.root, "first", limit=50)
        first = (self.root / ".claude/checkpoint.log").read_bytes()
        append_log(self.root, "second", limit=50)
        self.assertEqual((self.root / ".claude/checkpoint.log.1").read_bytes(), first)
        self.assertIn(b"second", (self.root / ".claude/checkpoint.log").read_bytes())

    def test_two_session_handoff_filesystem(self):
        self.hook("session_start.py", {"cwd": str(self.root), "session_id": "first"})
        append_record(self.root, record())
        path = self.root / ".claude/AGENT_STATE.md"
        update_state(self.root, TEMPLATE.replace("Review scope and existing evidence before starting new work.", "Resume synthetic task XYZ."), revision(path.read_bytes()))
        before = path.read_bytes()
        result = self.hook("session_start.py", {"cwd": str(self.root), "session_id": "fresh"})
        self.assertIn("Read the state", result.stdout)
        self.assertEqual(path.read_bytes(), before)
        self.assertIn(b"XYZ", path.read_bytes())

    def test_modes_and_invalid_configuration(self):
        initialize(self.root)
        for mode, expected_output in (("off", False), ("always", True)):
            result = subprocess.run([sys.executable, str(REPO / "scripts/checkpoint.py")],
                input=json.dumps({"cwd": str(self.root)}), text=True, capture_output=True,
                env=dict(os.environ, CLAUDE_PROJECT_DIR=str(self.root), PT_CHECKPOINT_STOP_MODE=mode))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(bool(result.stdout), expected_output)
        result = subprocess.run([sys.executable, str(REPO / "scripts/checkpoint.py")],
            input=json.dumps({"cwd": str(self.root)}), text=True, capture_output=True,
            env=dict(os.environ, CLAUDE_PROJECT_DIR=str(self.root), PT_CHECKPOINT_STOP_MODE="invalid"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be changes", result.stderr)

    def test_cli_root_fallback_and_override(self):
        initialize(self.root)
        child = self.root / "subdirectory"
        child.mkdir()
        with patch.dict(os.environ):
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
            self.assertEqual(project_root({"cwd": str(child)}), self.root.resolve())
            os.environ["CLAUDE_PROJECT_DIR"] = str(self.root)
            self.assertEqual(project_root(explicit=str(child)), child.resolve())

    def test_failed_atomic_replacement_preserves_state(self):
        initialize(self.root)
        path = self.root / ".claude/AGENT_STATE.md"
        original = path.read_bytes()
        from common import atomic_write
        with patch("common.os.replace", side_effect=OSError("simulated failure")):
            with self.assertRaises(OSError):
                atomic_write(path, b"changed")
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(list(path.parent.glob(".checkpoint-*")))

    def test_state_cli_update_acknowledges(self):
        self.hook("session_start.py", {"cwd": str(self.root)})
        self.hook("post_tool.py", {"cwd": str(self.root), "tool_input": {"file_path": "report.md"}})
        state = self.root / ".claude/AGENT_STATE.md"
        draft = self.root / "draft.md"
        draft.write_text(TEMPLATE + "\nSaved result.\n", encoding="utf-8")
        result = subprocess.run([sys.executable, str(REPO / "scripts/state.py"), "--project", str(self.root),
            "update", "--file", str(draft), "--expected-sha256", revision(state.read_bytes()),
            "--session-id", "default"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["saved"])
        self.assertEqual(self.hook("checkpoint.py", {"cwd": str(self.root)}).stdout, "")


if __name__ == "__main__":
    unittest.main()
