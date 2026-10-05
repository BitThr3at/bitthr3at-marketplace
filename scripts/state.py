"""Read revisions and atomically update Markdown state with conflict detection."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import sys
from common import HEADINGS, append_log, atomic_write, checked_path, initialize, locked, project_root
from runtime import acknowledge


def revision(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def update_state(root, content: str, expected: str) -> str:
    headings = set(re.findall(r"^## (.+)$", content, re.MULTILINE))
    if not set(HEADINGS).issubset(headings):
        raise ValueError("draft must contain all checkpoint section headings")
    with locked(root, ".claude/checkpoint-state.lock"):
        path = checked_path(root, ".claude/AGENT_STATE.md")
        previous = path.read_bytes()
        if revision(previous) != expected:
            raise ValueError("state revision conflict: reread the current state and merge changes")
        encoded = content.encode("utf-8")
        if encoded != previous:
            atomic_write(checked_path(root, ".claude/AGENT_STATE.md.bak"), previous)
            atomic_write(path, encoded, stat.S_IMODE(path.stat().st_mode))
        return revision(encoded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("read")
    update = commands.add_parser("update")
    update.add_argument("--file", required=True, help="UTF-8 draft file; never the live state file")
    update.add_argument("--expected-sha256", required=True)
    update.add_argument("--session-id")
    ack = commands.add_parser("acknowledge")
    ack.add_argument("--session-id", required=True)
    args = parser.parse_args()
    try:
        root = project_root(explicit=args.project)
        initialize(root)
        if args.command == "read":
            with locked(root, ".claude/checkpoint-state.lock"):
                content = checked_path(root, ".claude/AGENT_STATE.md").read_bytes()
            print(json.dumps({"sha256": revision(content), "content": content.decode("utf-8")}, ensure_ascii=False))
        else:
            if args.command == "update":
                draft = Path(args.file).resolve(strict=True)
                if draft == checked_path(root, ".claude/AGENT_STATE.md").resolve():
                    raise ValueError("draft must be separate from the live state file")
                result = update_state(root, draft.read_text(encoding="utf-8"), args.expected_sha256)
                # State has committed. Bookkeeping failure must not imply the write failed.
                try:
                    if args.session_id:
                        acknowledge(root, args.session_id)
                    append_log(root, "checkpoint saved")
                except (OSError, ValueError, TypeError) as exc:
                    print(f"pt-checkpoint: state saved; bookkeeping failed: {exc}", file=sys.stderr)
                print(json.dumps({"saved": True, "sha256": result}))
            else:
                acknowledge(root, args.session_id)
                append_log(root, "checkpoint acknowledged")
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(1, f"pt-checkpoint: {exc}\n")


if __name__ == "__main__":
    main()
