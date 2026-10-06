# PT Checkpoint for Codex

A self-contained Codex plugin from BitThr3at Marketplace. It preserves project
state across fresh sessions using `.claude/AGENT_STATE.md` and the append-only
`discoveries.jsonl` ledger. The `.claude` directory name is intentionally retained
so Claude Code's `pt-checkpoint` plugin and this plugin can share one checkpoint.

Requires Python 3.9+, macOS/Linux, and a Codex release with plugin command hooks
(packaging tested with CLI 0.160.0). It uses no external Python dependencies,
network calls, or telemetry.

Install from the marketplace repository:

```bash
codex plugin marketplace add BitThr3at/bitthr3at-marketplace
codex plugin add pt-checkpoint-codex@bitthr3at-marketplace
```

For a checkout containing the latest unpublished changes, register its absolute
local path instead of the GitHub source. Restart Codex after installation.
Review and trust this plugin's hooks in `/hooks`; installation alone does not
trust them. The plugin never grants itself hook trust or changes permission rules.

Invoke the `pt-checkpoint` skill with `$pt-checkpoint`, selecting this plugin's
skill if another installed skill has the same name. SessionStart injects concrete
commands with the pinned project path and a `codex:`-prefixed session ID. Stop uses
Codex's documented `decision: block` continuation with its loop guard. PostToolUse
silently parses affected paths from `apply_patch` inputs. Bash-only and external
service progress still requires a manual checkpoint.

`PT_CHECKPOINT_STOP_MODE=changes` (default), `always`, or `off` controls reminders.
`PT_CHECKPOINT_PROJECT_DIR` explicitly selects the checkpoint project. Otherwise
the first SessionStart pins it; later events reuse that path from private bookkeeping
in the host-provided `PLUGIN_DATA` directory. The registry retains the last 128
session roots; an evicted session needs a new SessionStart before further hooks.
Neither the registry nor the reminder tracker contains assessment discoveries.

The ledger CLI validates records, assigns IDs/timestamps, and locks appends.
`state.py read` returns the Markdown and revision. `state.py update --file DRAFT
--expected-sha256 REVISION` saves atomically and preserves a previous-state backup.
Use the injected absolute commands and explicit project argument. Passing the
session ID to update acknowledges that session's pending reminder. On conflict,
reread and merge rather than overwriting another session's progress.

Protect the state, ledger, backup, logs, and evidence from accidental publication.
Never store raw secrets. Keep confirmed facts separate from hypotheses, and
explain superseded discoveries. Blocked actions do not expand authorization or
allow bypassing restrictions. Model compliance and uninterrupted saves are not
guaranteed by hooks.

The runtime files under `scripts/`, the ledger schema, and license are generated
from canonical source in the marketplace repository by `scripts/build_codex.py`.
Edit canonical source there and rebuild; tests reject a package whose runtime
has drifted. The Codex manifest, hook configuration, and skill are maintained
directly in this package.
