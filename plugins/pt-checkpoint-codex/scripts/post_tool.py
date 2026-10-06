"""Silently track successful file edits without injecting per-tool reminders."""
from pathlib import Path
import re
from common import hook_main, initialize, project_root
from runtime import entry, tracking


def run(data):
    root = project_root(data)
    tool_input = data.get("tool_input", {})
    if not isinstance(tool_input, dict):
        return
    response = data.get("tool_response")
    if isinstance(response, dict) and (response.get("isError") or response.get("error")):
        return
    paths = []
    raw = tool_input.get("file_path")
    if isinstance(raw, str):
        paths.append(raw)
    if data.get("tool_name") == "apply_patch":
        command = tool_input.get("command")
        if isinstance(command, str):
            paths.extend(re.findall(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$", command, re.MULTILINE))
    meaningful = False
    for raw in paths:
        path = Path(raw)
        if not path.is_absolute():
            path = Path(data.get("cwd") or root) / path
        path = path.resolve()
        if not path.is_relative_to(root):
            continue
        relative = str(path.relative_to(root))
        if relative.startswith(".claude/checkpoint") or relative in (".claude/AGENT_STATE.md", ".claude/AGENT_STATE.md.bak"):
            continue
        meaningful = True
    if not meaningful:
        return
    initialize(root)
    with tracking(root) as sessions:
        current = entry(sessions, root, data.get("session_id", "default"))
        current["generation"] += 1


if __name__ == "__main__":
    hook_main(run)
