# PT Checkpoint

A Claude Code plugin for persistent project state across fresh sessions.
SessionStart creates state files without overwriting existing content and tells
Claude to read prior state. A manual command consolidates progress. Stop requests
consolidation after recorded changes, guarded against recursive or duplicate reminders.
The scripts never infer discoveries from transcripts: Claude writes the summary
and explicitly appends evidence-backed records.

Requires Python 3.9+, macOS or Linux (POSIX `flock`), and Claude Code 2.1.289+
(including Stop context feedback and project-path substitution). Runtime
uses only Python's standard library, with no network calls or telemetry.

## Install

For local development, without changing installed plugins:

```bash
claude --plugin-dir /absolute/path/to/bitthr3at-marketplace
```

For a local marketplace installation:

```bash
claude plugin marketplace add /absolute/path/to/bitthr3at-marketplace
claude plugin install pt-checkpoint@bitthr3at-marketplace
claude plugin list
```

Install from GitHub:

```bash
claude plugin marketplace add BitThr3at/bitthr3at-marketplace
claude plugin install pt-checkpoint@bitthr3at-marketplace
```

Enable, update, and remove using:

```bash
claude plugin enable pt-checkpoint@bitthr3at-marketplace
claude plugin marketplace update bitthr3at-marketplace
claude plugin update pt-checkpoint@bitthr3at-marketplace
claude plugin uninstall pt-checkpoint@bitthr3at-marketplace
```

Restart Claude Code after updating. Maintainers should bump `plugin.json`'s
version for hosted releases. Installation follows the official
[marketplace documentation](https://code.claude.com/docs/en/plugin-marketplaces).

## Use

Start `claude` in the authorized project directory. It creates:

- `.claude/AGENT_STATE.md`: compact current checkpoint.
- `discoveries.jsonl`: append-only discovery history.
- `.claude/checkpoint.log`: reminder/save events, created on first logged checkpoint.
- `.claude/AGENT_STATE.md.bak`: previous state, created at first changed update.
- `.claude/checkpoint-runtime.json`: private, bounded per-session reminder tracking.
- `.claude/checkpoint-*.lock`: private advisory locks for state and bookkeeping.

Run `/pt-checkpoint:checkpoint` after meaningful progress. Claude plugin
commands are namespaced; `/checkpoint` alone is not the guaranteed plugin command.
Close Claude and start a fresh session in the same directory to resume. Hooks
inject file paths and instructions, not file contents; Claude must read the state
before continuing. Checkpoint completion depends on Claude successfully writing
the files. Abrupt process termination may prevent the Stop hook from running.

`Stop` fires when Claude finishes a response, not only when the process exits.
It emits `hookSpecificOutput.additionalContext` to request consolidation and returns
silently when `stop_hook_active` is true. The PostToolUse hook silently tracks
successful Write/Edit/MultiEdit calls in the pinned project; it emits no context.
Stop also detects changed state/ledger contents. It suppresses idle and duplicate
reminders. It does not detect Bash-only changes to other files or changes confined
to external services; use the manual command for those workflows.

Set `PT_CHECKPOINT_STOP_MODE=changes` (default), `always`, or `off` in Claude's
environment. `always` requests a checkpoint after every ordinary response;
`off` keeps initialization, tracking, and the manual command but disables Stop reminders.
The hook requests work rather than proving Claude completed it. The state utility
records successful saves or explicit acknowledgments. Logs rotate at 64 KiB,
retaining one previous segment as `.claude/checkpoint.log.1`.

Project location is pinned using Claude Code's `CLAUDE_PROJECT_DIR`, which stays
stable across directory/worktree changes. Explicit CLI `--project` overrides it.
Outside Claude, the CLI finds the nearest ancestor with a checkpoint before
falling back to the working directory. Worktrees share the session's starting
project checkpoint; use `--project` to intentionally select an independent one.

## Ledger CLI

Run scripts using their absolute installed/source path from the project directory:

```bash
python3 /path/to/plugin/scripts/discovery.py add \
  --type endpoint --status confirmed --target example.com \
  --value /api/v2/profile --summary 'Endpoint in supplied evidence' \
  --confidence confirmed --evidence evidence/profile-response.txt
python3 /path/to/plugin/scripts/discovery.py validate
python3 /path/to/plugin/scripts/discovery.py tail --count 20
python3 /path/to/plugin/scripts/discovery.py stats
```

Use `--project /path/to/project` **before** the subcommand to select another project.
Repeat `--evidence` for multiple paths; `--metadata` accepts a JSON object.
IDs and UTC timestamps are generated under an exclusive ledger lock. Appends
validate the existing ledger first and preserve it on validation errors. Each
record follows `schemas/discovery.schema.json`; runtime validation needs no extra
package. Evidence paths are references, not proof that a file exists or establishes
the claim. Confidence defaults to `unknown`; set it explicitly when justified.

Supported statuses: confirmed, hypothesis, tested, negative-result, blocked,
skipped, superseded. Append corrections with `--status superseded` and metadata
such as `'{"supersedes":"D-000001","reason":"New evidence"}'`; update the
summary without silently removing prior confirmed history. The CLI does not
deduplicate automatically. It scans the ledger on append, suitable for local
assessment histories rather than huge event streams. Locks coordinate this CLI's
writers; external editors must not modify the ledger concurrently.

## Atomic state updates

Automatic hooks and the manual command give Claude absolute utility paths and
explicit project arguments. To update state yourself:

```bash
python3 /path/to/plugin/scripts/state.py --project /path/to/project read
python3 /path/to/plugin/scripts/state.py --project /path/to/project update \
  --expected-sha256 SHA256_FROM_READ --file /path/to/checkpoint-draft.md
```

`read` returns the current Markdown and SHA-256 revision as JSON. Write your
updated full Markdown to a separate draft file, keeping all section headings.
Append significant ledger records first, then update state. The writer locks,
checks the expected revision, saves the prior content to a private backup, and
atomically replaces the state. A stale revision fails without changing state;
reread and merge. The previous state remains recoverable from `AGENT_STATE.md.bak`.
Its backup is replaced by the next changed update; this is not full version history.

Pass `--session-id SESSION_ID` to `update` to acknowledge the session's reminder.
For a reviewed checkpoint with no changes, use `state.py --project /path/to/project
acknowledge --session-id SESSION_ID`. File contents do not prove that facts were
preserved: Claude must review and explain any corrections. Concurrent writers
are protected only when they use this utility; direct edits bypass that protection.

## Privacy and scope

State can contain confidential target details. Decide whether to commit it and
evidence; suggested project `.gitignore` entries are:

```gitignore
.claude/AGENT_STATE.md
.claude/checkpoint.log
.claude/checkpoint.log.1
.claude/checkpoint-*
.claude/AGENT_STATE.md.bak
discoveries.jsonl
evidence/
```

Do not store passwords, tokens, or raw secrets. Files newly created by the scripts
use private permissions; existing permissions are preserved. Examples are synthetic.
The plugin does not expand authorization, bypass Claude safety behavior, or
guarantee a later model will perform a blocked action. Record blocked/skipped work
and continue other permitted tasks. It never modifies project `CLAUDE.md`.

## Troubleshooting and verification

- Python not found: install Python 3.9+ and ensure `python3` is on Claude's PATH.
- Hooks not firing: check `/hooks`, plugin enablement, and restart Claude. Inspect
  `claude --debug` logs; see the [hook reference](https://code.claude.com/docs/en/hooks).
- Wrong directory: check `CLAUDE_PROJECT_DIR` and the injected absolute paths.
  CLI `--project` selects a different root explicitly; hooks stay pinned to the
  session's starting project.
- JSONL error: `validate` reports the first bad line or duplicate ID. Preserve a
  backup and review it manually. The plugin will not truncate or repair it.
- Path issues: hook script paths quote `${CLAUDE_PLUGIN_ROOT}` to support spaces.
  Run from a normal writable directory; persistence symlinks are rejected.
- Permission errors: hooks report errors on stderr and exit nonzero. Fix directory
  ownership/access; existing populated or empty state files remain unchanged.
- Old Claude Code: upgrade if plugin commands or hook fields are unsupported.

```bash
python3 -m unittest discover -s tests -v
claude plugin validate --strict .claude-plugin/plugin.json
claude plugin validate --strict .claude-plugin/marketplace.json
claude plugin validate --strict commands
```

The optional live test starts two independent Claude sessions in a disposable
project. The first writes a random resume marker and ledger record; the second
must read that marker without receiving it in its prompt. It requires a working
Claude model connection and can incur model charges. It permits file tools and
the plugin's Python utility commands, and never bypasses permission checks.

```bash
PT_CHECKPOINT_LIVE_TEST=1 python3 -m unittest discover -s tests -p test_live_resume.py -v
```

Normal tests and CI skip live model calls. They cover hooks, file persistence,
directory changes, concurrent writes, and revision conflicts; they do not prove
model compliance or remote GitHub installation. CI also validates manifests and
commands strictly with a pinned Claude Code CLI version.
