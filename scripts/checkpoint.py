"""Request one consolidation per Stop cycle without inventing discoveries."""
import fcntl
import json
import os
from common import checked_path, hook_main, initialize, instructions, project_root, timestamp


def run(data: dict) -> None:
    if data.get("stop_hook_active") is True:
        return
    root = project_root(data)
    initialize(root)
    path = checked_path(root, ".claude/checkpoint.log")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.write(timestamp() + " stop checkpoint requested\n")
        stream.flush()
    print(json.dumps({"decision": "block", "reason":
        "Before finishing, consolidate meaningful progress into the persistent checkpoint. "
        "If nothing changed, do not invent or duplicate records. " + instructions(root)}))


if __name__ == "__main__":
    hook_main(run)
