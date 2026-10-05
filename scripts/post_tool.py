"""Silently track successful file edits without injecting per-tool reminders."""
from pathlib import Path
from common import hook_main, initialize, project_root
from runtime import entry, tracking


def run(data):
    root = project_root(data)
    raw = data.get("tool_input", {}).get("file_path")
    if not isinstance(raw, str):
        return
    path = Path(raw)
    if not path.is_absolute():
        path = Path(data.get("cwd") or root) / path
    path = path.resolve()
    if not path.is_relative_to(root):
        return
    relative = str(path.relative_to(root))
    if relative.startswith(".claude/checkpoint") or relative in (".claude/AGENT_STATE.md", ".claude/AGENT_STATE.md.bak"):
        return
    initialize(root)
    with tracking(root) as sessions:
        current = entry(sessions, root, data.get("session_id", "default"))
        current["generation"] += 1


if __name__ == "__main__":
    hook_main(run)
