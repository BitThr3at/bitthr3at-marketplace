"""Initialize project state and inject resume instructions into Claude context."""
import json
from common import hook_main, initialize, instructions, project_root


def run(data: dict) -> None:
    root = project_root(data)
    initialize(root)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart", "additionalContext": instructions(root)
    }}))


if __name__ == "__main__":
    hook_main(run)
