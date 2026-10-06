"""Initialize project state and inject resume instructions into Claude context."""
import json
from common import hook_main, initialize, instructions, project_root
from runtime import entry, tracking


def run(data: dict) -> None:
    root = project_root(data)
    initialize(root)
    session_id = data.get("session_id", "default")
    with tracking(root) as sessions:
        entry(sessions, root, session_id)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart", "additionalContext": instructions(root, session_id)
    }}))


if __name__ == "__main__":
    hook_main(run)
