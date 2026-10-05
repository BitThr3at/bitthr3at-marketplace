# PT Checkpoint

A Claude Code plugin for persistent project state across fresh sessions.
SessionStart creates state files without overwriting existing content and tells
Claude to read prior state. A manual command consolidates progress. Stop requests
one final consolidation per response cycle, guarded against recursive stops.
The scripts never infer discoveries from transcripts: Claude writes the summary
and explicitly appends evidence-backed records.

Requires Python 3.9+, macOS or Linux (POSIX `flock`), and Claude Code with plugin
support. CLI manifest validation was tested with Claude Code 2.1.289. Runtime
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
- `.claude/checkpoint.log`: timestamped Stop reminders, created at first Stop.

Run `/pt-checkpoint:checkpoint` after meaningful progress. Claude plugin
commands are namespaced; `/checkpoint` alone is not the guaranteed plugin command.
Close Claude and start a fresh session in the same directory to resume. Hooks
inject file paths and instructions, not file contents; Claude must read the state
before continuing. Checkpoint completion depends on Claude successfully writing
the files. Abrupt process termination may prevent the Stop hook from running.

`Stop` fires when Claude finishes a response, not only when the process exits.
The hook emits `decision: block` once to request consolidation and returns silently
when `stop_hook_active` is true. It does not fabricate state or verify that Claude
obeyed. PostToolUse is omitted in v1 to avoid reminders after trivial operations.
The log is append-only; archive it manually if it becomes large.

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

## Privacy and scope

State can contain confidential target details. Decide whether to commit it and
evidence; suggested project `.gitignore` entries are:

```gitignore
.claude/AGENT_STATE.md
.claude/checkpoint.log
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
- Wrong directory: hooks use payload `cwd`, falling back to process cwd. Check
  the injected absolute state paths. State is per working directory, not Git root.
- JSONL error: `validate` reports the first bad line or duplicate ID. Preserve a
  backup and review it manually. The plugin will not truncate or repair it.
- Path issues: hook script paths quote `${CLAUDE_PLUGIN_ROOT}` to support spaces.
  Run from a normal writable directory; persistence symlinks are rejected.
- Permission errors: hooks report errors on stderr and exit nonzero. Fix directory
  ownership/access; existing populated or empty state files remain unchanged.
- Old Claude Code: upgrade if plugin commands or hook fields are unsupported.

```bash
python3 -m unittest discover -s tests -v
claude plugin validate .claude-plugin/plugin.json
claude plugin validate .claude-plugin/marketplace.json
```

To verify the actual model workflow, start with `--plugin-dir` in a disposable
project, ask Claude to checkpoint a synthetic completed task, exit, and start a
fresh session. Confirm it reads the saved Resume point and reuses completed work.
This requires a working model connection; unit tests simulate hooks and filesystem
behavior but do not establish model compliance or remote GitHub installation.
