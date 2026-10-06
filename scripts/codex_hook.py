"""Codex lifecycle adapter. Persistence utilities remain shared with Claude."""
import json
import os
from pathlib import Path
from common import atomic_write, checked_path, hook_main, locked, project_root
from runtime import session_key
import checkpoint
import post_tool
import session_start


def run(data: dict) -> None:
    session_id = data.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("Codex hook requires a nonempty session_id")
    data = dict(data, _checkpoint_host="codex", session_id="codex:" + session_id)
    handlers = {"SessionStart": session_start.run, "PostToolUse": post_tool.run, "Stop": checkpoint.run}
    event = data.get("hook_event_name")
    if event not in handlers:
        return
    directory = os.environ.get("PLUGIN_DATA")
    if not directory:
        raise ValueError("Codex plugin hooks require PLUGIN_DATA from the host")
    storage = Path(directory).resolve()
    storage.mkdir(parents=True, exist_ok=True, mode=0o700)
    with locked(storage, "checkpoint-projects.lock"):
        registry = checked_path(storage, "checkpoint-projects.json")
        projects = json.loads(registry.read_text(encoding="utf-8")) if registry.exists() else {}
        if not isinstance(projects, dict) or any(not isinstance(x, str) for x in projects.values()):
            raise ValueError("invalid Codex checkpoint project registry")
        key = session_key(data["session_id"])
        override = os.environ.get("PT_CHECKPOINT_PROJECT_DIR")
        if override:
            root = project_root(data, explicit=override)
        elif key in projects:
            root = project_root(explicit=projects[key])
        elif event == "SessionStart":
            root = project_root(data)
        else:
            raise ValueError("Codex session has no pinned checkpoint project; start or resume the session first")
        projects.pop(key, None)
        projects[key] = str(root)
        atomic_write(registry, json.dumps(dict(list(projects.items())[-128:])).encode())
    data["_checkpoint_project"] = str(root)
    handlers[event](data)


if __name__ == "__main__":
    hook_main(run)
