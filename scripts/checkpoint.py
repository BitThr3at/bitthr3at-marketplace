"""Request one consolidation per Stop cycle without inventing discoveries."""
import json
import os
from common import append_log, fingerprint, hook_main, initialize, instructions, project_root
from runtime import entry, tracking


def run(data: dict) -> None:
    if data.get("stop_hook_active") is True:
        return
    root = project_root(data)
    initialize(root)
    mode = os.environ.get("PT_CHECKPOINT_STOP_MODE", "changes")
    if mode not in ("changes", "always", "off"):
        raise ValueError("PT_CHECKPOINT_STOP_MODE must be changes, always, or off")
    if mode == "off":
        return
    session_id = data.get("session_id", "default")
    with tracking(root) as sessions:
        current = entry(sessions, root, session_id)
        signature = fingerprint(root)
        requested = [signature, current["generation"]]
        if mode == "changes" and (
            (signature == current["baseline"] and not current["generation"])
            or current["requested"] == requested
        ):
            return
        current["requested"] = requested
    append_log(root, "stop checkpoint requested")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext":
        "Before finishing, consolidate meaningful progress into the persistent checkpoint. "
        "If nothing changed, do not invent or duplicate records. " + instructions(root, session_id)}}))


if __name__ == "__main__":
    hook_main(run)
