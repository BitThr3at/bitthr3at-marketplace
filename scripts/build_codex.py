"""Build the self-contained Codex package from canonical shared source files."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
FILES = ("common.py", "discovery.py", "runtime.py", "state.py", "session_start.py", "checkpoint.py", "post_tool.py", "codex_hook.py")


def build():
    destination = ROOT / "plugins/pt-checkpoint-codex"
    (destination / "scripts").mkdir(exist_ok=True)
    (destination / "schemas").mkdir(exist_ok=True)
    for filename in FILES:
        shutil.copyfile(ROOT / "scripts" / filename, destination / "scripts" / filename)
    shutil.copyfile(ROOT / "schemas/discovery.schema.json", destination / "schemas/discovery.schema.json")
    shutil.copyfile(ROOT / "LICENSE", destination / "LICENSE")
    print("Built pt-checkpoint-codex shared runtime")


if __name__ == "__main__":
    build()
