import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from common import initialize
from discovery import append_record, read_records, validate_record
from discovery import STATUS, TYPES, CONFIDENCE, FIELDS


def record():
    return dict(type="observation", status="confirmed", target="example.com", value="test", summary="Synthetic observation", evidence=[], confidence="confirmed", source="test", metadata={})


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="checkpoint spaces ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def hook(self, name, data):
        return subprocess.run([sys.executable, str(REPO / "scripts" / name)], input=json.dumps(data), text=True, capture_output=True, cwd=self.root)

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
        output = self.hook("checkpoint.py", {"cwd": str(self.root), "stop_hook_active": False})
        self.assertEqual(json.loads(output.stdout)["decision"], "block")
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
            env=dict(os.environ, CLAUDE_PLUGIN_ROOT=str(plugin_path)), cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["hookEventName"], "SessionStart")


if __name__ == "__main__":
    unittest.main()
