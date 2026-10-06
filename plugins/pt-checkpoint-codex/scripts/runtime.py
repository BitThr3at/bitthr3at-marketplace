"""Small per-session reminder tracker. It contains no assessment discoveries."""
import hashlib
import json
from contextlib import contextmanager
from common import atomic_write, checked_path, fingerprint, locked


def session_key(session_id: str) -> str:
    return hashlib.sha256(session_id.encode()).hexdigest()


@contextmanager
def tracking(root):
    with locked(root, ".claude/checkpoint-runtime.lock"):
        path = checked_path(root, ".claude/checkpoint-runtime.json")
        sessions = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(sessions, dict) or any(not isinstance(x, dict) for x in sessions.values()):
            raise ValueError("invalid checkpoint reminder tracker")
        yield sessions
        # Retain recent sessions only; this is disposable bookkeeping, not history.
        sessions = dict(list(sessions.items())[-32:])
        atomic_write(path, json.dumps(sessions).encode())


def entry(sessions, root, session_id):
    key = session_key(session_id)
    if key not in sessions:
        sessions[key] = {"baseline": fingerprint(root), "generation": 0, "requested": None}
    return sessions[key]


def acknowledge(root, session_id):
    with tracking(root) as sessions:
        current = entry(sessions, root, session_id)
        current.update(baseline=fingerprint(root), generation=0, requested=None)
