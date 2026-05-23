# Implementation Plan: Agent Cockpit

## 1. Implementation Principles

Build the tool as a small shell-based system first.

Use:

- Bash
- git worktrees
- tmux
- markdown files
- shell-compatible status files
- JSON files for shared quota state
- simple filesystem conventions

Avoid in the initial version:

- databases
- daemons
- web UI
- complex TUI frameworks
- automatic merging/rebasing
- role-specific agent abstractions

The tool should be easy to inspect, debug, and modify.

## 2. Target File Layout

### 2.1 User-Level Control Directory

```text
~/.agent-control/
├── config/
│   └── repos.env
├── status/
│   └── <slug>.status
├── logs/
│   └── <slug>.log
├── quotas/
│   └── claude.json
└── templates/
    ├── AGENTS.md.template
    ├── HANDOFF.md.template
    └── prompt.md.template
```

### 2.2 Workspace Directory

```text
~/agent-work/<slug>/
├── AGENTS.md
├── .agent/
│   ├── metadata.env
│   ├── status -> ~/.agent-control/status/<slug>.status
│   ├── HANDOFF.md
│   └── prompt.md
├── backend/
└── frontend/
```

The repositories inside the workspace are git worktrees.

## 3. Phase 0: Prerequisites and Assumptions

### 3.1 Required Tools

The user environment should have:

```bash
git
tmux
bash
sed
awk
grep
cut
watch
```

Optional later:

```bash
fzf
```

### 3.2 Default Paths

Use these defaults unless overridden by environment variables:

```bash
AGENT_CONTROL_HOME="$HOME/.agent-control"
AGENT_WORK_HOME="$HOME/agent-work"
AGENT_TMUX_SESSION="agents"
AGENT_BASE_BRANCH="origin/main"
AGENT_COMMAND="codex"
AGENT_QUOTA_PROVIDER="claude"
```

## 4. Phase 1: Foundation Scripts

Goal: implement the minimum viable cockpit system.

Scripts:

```text
agent-status
agent-blocked
agent-dashboard
agent-dashboard-quotas
agent-quota-update
agent-cockpit
agent-spawn
agent-jump
```

Recommended install path:

```text
~/.local/bin/
```

Make sure `~/.local/bin` is on `PATH`.

## 5. Phase 1.1: Bootstrap Configuration

### 5.1 Create `agent-init`

Optional but useful. This command creates the control directory and initial config.

Command:

```bash
agent-init
```

Creates:

```text
~/.agent-control/config/repos.env
~/.agent-control/status/
~/.agent-control/logs/
~/.agent-control/quotas/
~/.agent-control/templates/
~/agent-work/
```

Initial `repos.env`:

```bash
REPO_BACKEND_NAME="backend"
REPO_BACKEND_PATH="$HOME/projects/backend"
REPO_BACKEND_DEFAULT="true"

REPO_FRONTEND_NAME="frontend"
REPO_FRONTEND_PATH="$HOME/projects/frontend"
REPO_FRONTEND_DEFAULT="true"
```

Acceptance criteria:

- Running `agent-init` twice is safe.
- Existing config is not overwritten without confirmation.
- Missing directories are created.

## 6. Phase 1.2: Status Reporting

### 6.1 Implement `agent-status`

Command:

```bash
agent-status <slug> <state> <summary>
```

Example:

```bash
agent-status permissions-refactor WORKING "Inspecting backend permission checks"
```

Behavior:

- validate slug is present
- validate state is present
- accept summary as remaining arguments
- write `~/.agent-control/status/<slug>.status`
- preserve workspace/tmux metadata if discoverable

Status file example:

```bash
SLUG="permissions-refactor"
STATE="WORKING"
SUMMARY="Inspecting backend permission checks"
UPDATED_AT="2026-05-23 15:45:20"
WORKSPACE="$HOME/agent-work/permissions-refactor"
TMUX_SESSION="agents"
TMUX_WINDOW="permissions-refactor"
```

Implementation notes:

- Quote values safely.
- Use `date '+%Y-%m-%d %H:%M:%S'`.
- Create the status directory if missing.

Acceptance criteria:

- Status file is created.
- Re-running updates the same file.
- Dashboard can source or parse the file safely enough for trusted local usage.

### 6.2 Implement `agent-blocked`

Command:

```bash
agent-blocked <slug> <message>
```

Behavior:

- call `agent-status <slug> BLOCKED <message>`
- send a tmux display message if inside or connected to tmux
- print terminal bell

Example:

```bash
agent-blocked permissions-refactor "Need decision: should missing access return 403 or 404?"
```

Acceptance criteria:

- Dashboard shows the agent as blocked.
- User receives a visible tmux message or terminal bell.
- Command works even outside tmux, without failing.

## 7. Phase 1.3: Shared Claude Quota Tracking

Goal: add global quota state that is shared across all agent workspaces.

### 7.1 Implement `agent-quota-update`

Command:

```bash
agent-quota-update
```

Behavior:

- read JSON from stdin
- extract known Claude quota fields when present
- normalize the data into `~/.agent-control/quotas/claude.json`
- never fail loudly if fields are missing
- preserve an `updated_at` timestamp and `source`

The tool should support at least these candidate field paths:

```text
rate_limits.five_hour.used_percentage
rate_limits.five_hour.reset_at
rate_limits.seven_day.used_percentage
rate_limits.seven_day.reset_at
usage.five_hour.used_percentage
usage.five_hour.reset_at
usage.seven_day.used_percentage
usage.seven_day.reset_at
context_window.used_percentage
```

Only the shared 5-hour and 7-day quota data is required for the cockpit quota pane. Context-window data may be stored later but is not the main visualization.

Normalized output example:

```json
{
  "source": "claude-statusline",
  "updated_at": "2026-05-23T10:42:15+02:00",
  "five_hour": {
    "used_percentage": 36,
    "window_resets_at": "2026-05-23T14:30:00+02:00"
  },
  "seven_day": {
    "used_percentage": 69,
    "window_resets_at": "2026-05-23T00:00:00+02:00"
  },
  "raw_available": {
    "has_rate_limits": true,
    "has_usage": false,
    "has_context_window": true
  }
}
```

Acceptance criteria:

- Running `echo '{}' | agent-quota-update` does not fail.
- Missing quota fields result in `null` values or omitted fields, not a crash.
- A valid JSON file is written to `~/.agent-control/quotas/claude.json`.
- The dashboard can render even when this file is missing or incomplete.

### 7.2 Suggested Python Implementation

Use Python for JSON parsing because shell JSON parsing is fragile.

```python
#!/usr/bin/env python3
import json
import os
import sys
from datetime import datetime, timezone

BASE = os.path.expanduser("~/.agent-control")
QUOTA_DIR = os.path.join(BASE, "quotas")
QUOTA_FILE = os.path.join(QUOTA_DIR, "claude.json")

os.makedirs(QUOTA_DIR, exist_ok=True)

def get_nested(data, path, default=None):
    cur = data
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur

raw = sys.stdin.read().strip()
payload = json.loads(raw) if raw else {}

five_used = (
    get_nested(payload, ["rate_limits", "five_hour", "used_percentage"])
    or get_nested(payload, ["usage", "five_hour", "used_percentage"])
)
five_reset = (
    get_nested(payload, ["rate_limits", "five_hour", "reset_at"])
    or get_nested(payload, ["usage", "five_hour", "reset_at"])
)
seven_used = (
    get_nested(payload, ["rate_limits", "seven_day", "used_percentage"])
    or get_nested(payload, ["usage", "seven_day", "used_percentage"])
)
seven_reset = (
    get_nested(payload, ["rate_limits", "seven_day", "reset_at"])
    or get_nested(payload, ["usage", "seven_day", "reset_at"])
)

result = {
    "source": "claude-statusline",
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "five_hour": {
        "used_percentage": five_used,
        "window_resets_at": five_reset,
    },
    "seven_day": {
        "used_percentage": seven_used,
        "window_resets_at": seven_reset,
    },
    "raw_available": {
        "has_rate_limits": "rate_limits" in payload,
        "has_usage": "usage" in payload,
        "has_context_window": "context_window" in payload,
    },
}

with open(QUOTA_FILE, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2)
```

### 7.3 Claude Statusline Wrapper

If Claude Code statusline integration is available, configure it to call a wrapper:

```bash
~/.local/bin/claude-statusline
```

```bash
#!/usr/bin/env bash
set -euo pipefail

payload="$(cat)"
printf '%s' "$payload" | agent-quota-update >/dev/null 2>&1 || true

# Keep the visible Claude statusline short.
echo "agent-cockpit quota updated"
```

The implementation must not assume that every Claude session exposes quota data. Each session can attempt to update the same shared quota file; the latest valid snapshot is what the cockpit displays.

## 7. Phase 1.4: Dashboard

### 7.1 Implement `agent-dashboard`

Command:

```bash
agent-dashboard
```

Behavior:

- read `~/.agent-control/status/*.status`
- group by state in this order:
  - BLOCKED
  - NEEDS_FEEDBACK
  - FAILED
  - READY
  - WORKING
  - STARTING
  - PAUSED
  - DONE
- print slug, summary, timestamp, and workspace

Usage inside tmux:

```bash
watch -n 2 agent-dashboard
```

Acceptance criteria:

- Works when no agents exist.
- Works when one or many status files exist.
- Does not crash if a status file is partially written or missing fields.
- Puts attention states near the top.

### 7.2 Stale Working Detection

Optional for v1.1.

Behavior:

- If `STATE=WORKING` and `UPDATED_AT` is older than a configurable threshold, mark as stale visually.
- Default threshold: 30 minutes.

This can be implemented later.

## 8. Phase 1.5: Cockpit Tmux Session

### 8.1 Implement `agent-cockpit`

Command:

```bash
agent-cockpit
```

Behavior:

- create tmux session `agents` if it does not exist
- create or reuse window `cockpit`
- run dashboard in main pane
- provide a shell pane for commands
- attach or switch to the session

Suggested initial layout:

```text
cockpit
├── left: watch -n 2 agent-dashboard
└── right: shell
```

Implementation approach:

```bash
tmux new-session -d -s "$AGENT_TMUX_SESSION" -n cockpit
# left pane: dashboard
# right pane: shell
```

Acceptance criteria:

- Running `agent-cockpit` from outside tmux attaches to the session.
- Running it again does not create duplicate sessions.
- Cockpit shows dashboard and a shell.

## 9. Phase 1.6: Workspace Spawn

### 9.1 Implement `agent-spawn`

Modes:

Interactive:

```bash
agent-spawn
```

Non-interactive:

```bash
agent-spawn <slug> <repo> [repo...]
```

Examples:

```bash
agent-spawn permissions-refactor backend frontend
agent-spawn notification-bug backend
```

Interactive behavior:

1. Ask for slug.
2. Normalize and validate slug.
3. Load repo presets from config.
4. Show repositories with defaults selected.
5. Ask for selected repositories.
6. Show confirmation summary.
7. Create workspace.
8. Create worktrees.
9. Generate files.
10. Create tmux window.
11. Switch to tmux window.
12. Display prepared prompt and agent start command.

For v1, repository selection can be simple text input instead of a full checkbox UI:

```text
Available repositories:
  backend [default]
  frontend [default]
  docs

Repositories [backend frontend]:
```

Pressing Enter uses defaults.

### 9.2 Slug Normalization Function

Input:

```text
Permissions Refactor!
```

Output:

```text
permissions-refactor
```

Rules:

- lowercase
- spaces to hyphens
- remove unsupported characters
- collapse repeated hyphens
- trim leading/trailing hyphens

Acceptance criteria:

- Invalid slugs are rejected or normalized.
- Empty final slug prompts again.

### 9.3 Worktree Creation

For each repo:

```bash
git -C "$repo_path" fetch --prune
git -C "$repo_path" worktree add \
  -b "agent/$slug/$repo_name" \
  "$workspace/$repo_name" \
  "$AGENT_BASE_BRANCH"
```

Before running:

- verify repo path exists
- verify repo path is a git repo
- verify worktree path does not exist
- verify branch does not already exist locally

Acceptance criteria:

- Selected repositories appear as worktrees in workspace.
- Branches are created with predictable names.
- Failure in one repo does not silently continue.
- On failure, output clear cleanup instructions.

### 9.4 Metadata Generation

Generate:

```text
~/agent-work/<slug>/.agent/metadata.env
```

Fields:

```bash
SLUG="<slug>"
WORKSPACE="<workspace>"
REPOS="backend frontend"
TMUX_SESSION="agents"
TMUX_WINDOW="<slug>"
STATUS_FILE="$HOME/.agent-control/status/<slug>.status"
CREATED_AT="<timestamp>"
```

Also create status symlink:

```bash
ln -s "$status_file" "$workspace/.agent/status"
```

If symlink is awkward on Windows/WSL, copying is acceptable, but symlink is preferred.

### 9.5 Generate `AGENTS.md`

Generate workspace-level:

```text
~/agent-work/<slug>/AGENTS.md
```

Content sections:

- Workspace
- Available repositories
- Status reporting
- Status expectations
- Blocking rules
- Handoff
- Git rules
- Completion checklist

### 9.6 Generate Repo-Local `AGENTS.md`

For each selected repo, generate:

```text
~/agent-work/<slug>/<repo>/AGENTS.md
```

Content:

```markdown
# Agent Instructions

This repository is part of the agent workspace:

`~/agent-work/<slug>`

Read the session-level instructions at:

`../AGENTS.md`

Additional rule:

- Work only inside this generated worktree.
- Do not modify canonical repositories under `~/projects`.
```

### 9.7 Generate `.agent/HANDOFF.md`

Initial content:

```markdown
# Handoff

## Goal

TBD

## Current Status

Starting.

## Repositories

- backend
- frontend

## Files Changed

TBD

## Commands Run

TBD

## Test Results

TBD

## Open Questions

TBD

## Next Steps

TBD

## Risks / Follow-ups

TBD
```

### 9.8 Generate `.agent/prompt.md`

Initial content:

```markdown
# Agent Start Prompt

Read `AGENTS.md` first.

Workspace:

`~/agent-work/<slug>`

Repositories:

- `backend`
- `frontend`

Before starting, run:

```bash
agent-status <slug> WORKING "Starting task"
```

Task:

<Tell the agent the task here>
```

### 9.9 Create Tmux Window

Window name:

```text
<slug>
```

Working directory:

```text
~/agent-work/<slug>
```

Initial layout:

```text
<slug>
├── left: agent shell
└── right: workspace status/watch pane
```

Right pane command:

```bash
watch -n 3 'cat .agent/status 2>/dev/null; echo; for repo in */.git; do d=${repo%/.git}; echo "== $d =="; git -C "$d" status -sb; echo; done'
```

Because worktree `.git` may be a file rather than directory, use a more robust version:

```bash
watch -n 3 'cat .agent/status 2>/dev/null; echo; for d in */; do if git -C "$d" rev-parse --is-inside-work-tree >/dev/null 2>&1; then echo "== ${d%/} =="; git -C "$d" status -sb; echo; fi; done'
```

Left pane should show:

```bash
cat .agent/prompt.md
```

Then leave the shell ready for the user.

Acceptance criteria:

- Window is created and selected.
- Workspace opens in the correct directory.
- Prompt is visible.
- Status/watch pane is useful but not required for correctness.

## 10. Phase 1.7: Jumping Between Agents

### 10.1 Implement `agent-jump`

Command:

```bash
agent-jump <slug|blocked|feedback>
```

Behavior:

- If a slug is provided, find metadata/status and switch tmux to that window.
- If `blocked`, find status files with `STATE=BLOCKED` and jump to one.
- If `feedback`, find `STATE=NEEDS_FEEDBACK` or `STATE=BLOCKED`.

For v1, if multiple matches exist:

- print the list and ask user to choose, or
- jump to the oldest updated one

Acceptance criteria:

- Works from inside tmux.
- Works from outside tmux by attaching/switching if possible.
- Gives clear error if no matching agent exists.

## 11. Phase 2: Quality and Lifecycle Commands

Goal: make day-to-day operations smoother.

### 11.1 `agent-list`

Show all workspaces and states.

```bash
agent-list
```

Output:

```text
permissions-refactor  BLOCKED         Need decision: 403 or 404
notification-bug      WORKING         Reproducing failing test
access-cleanup        READY           Ready for review
```

### 11.2 `agent-close`

Mark a workspace as inactive/done and optionally close the tmux window.

```bash
agent-close <slug>
```

Behavior:

- update status to `DONE` or `PAUSED`
- optionally kill tmux window after confirmation
- do not delete worktrees

### 11.3 `agent-clean`

Remove a workspace and git worktrees after explicit confirmation.

```bash
agent-clean <slug>
```

Behavior:

- show workspace path
- show git status for each repo
- refuse cleanup if uncommitted changes exist unless `--force`
- remove worktrees using `git worktree remove`
- archive or remove status files

Acceptance criteria:

- Never deletes dirty work accidentally.
- Requires confirmation.
- Provides clear manual cleanup instructions on failure.

## 12. Phase 3: Improved UX

### 12.1 Add `fzf` Selection

Use `fzf` if installed for:

- repository selection
- blocked-agent jump
- workspace open/close

Fallback to plain prompts when `fzf` is unavailable.

### 12.2 Add Staleness Detection

Enhance dashboard:

- flag `WORKING` agents with stale status updates
- default stale threshold: 30 minutes
- configurable with `AGENT_STALE_MINUTES`

### 12.3 Add Event Log

Each `agent-status` call appends to:

```text
~/.agent-control/logs/<slug>.log
```

Format:

```text
2026-05-23 15:45:20 WORKING Inspecting backend permission checks
2026-05-23 15:52:03 BLOCKED Need decision: 403 or 404
```

Cockpit can show recent events in a pane.

## 13. Phase 4: Optional Advanced Features

Only after the basic system works.

### 13.1 Task Argument Support

Allow:

```bash
agent-spawn permissions-refactor backend frontend --task "Refactor permission handling"
```

This writes the task into `.agent/prompt.md`.

### 13.2 Diff Export

Command:

```bash
agent-diff <slug>
```

Writes diffs for all selected repositories into:

```text
~/.agent-control/context/<slug>/<repo>.diff
```

### 13.3 Refresh Worktrees

Command:

```bash
agent-refresh <slug>
```

Fetches and rebases/merges only with explicit confirmation. This should be carefully designed and not rushed.

### 13.4 Pluggable Agent Commands

Allow per-workspace agent command selection:

```bash
agent-spawn --agent codex permissions-refactor backend frontend
agent-spawn --agent claude notification-bug backend
```

## 14. Suggested Script Skeletons

### 14.1 Common Library

Create:

```text
~/.local/lib/agent-control/common.sh
```

Responsibilities:

- load environment defaults
- create directories
- normalize slug
- load repo config
- print errors
- quote values
- parse status files

Basic structure:

```bash
#!/usr/bin/env bash

AGENT_CONTROL_HOME="${AGENT_CONTROL_HOME:-$HOME/.agent-control}"
AGENT_WORK_HOME="${AGENT_WORK_HOME:-$HOME/agent-work}"
AGENT_TMUX_SESSION="${AGENT_TMUX_SESSION:-agents}"
AGENT_BASE_BRANCH="${AGENT_BASE_BRANCH:-origin/main}"
AGENT_COMMAND="${AGENT_COMMAND:-codex}"

ensure_dirs() {
  mkdir -p "$AGENT_CONTROL_HOME/status" "$AGENT_CONTROL_HOME/logs" "$AGENT_CONTROL_HOME/config" "$AGENT_WORK_HOME"
}

normalize_slug() {
  printf '%s' "$1" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[[:space:]]+/-/g; s/[^a-z0-9_-]+/-/g; s/-+/-/g; s/^-//; s/-$//'
}
```

### 14.2 `agent-status` Skeleton

```bash
#!/usr/bin/env bash
set -euo pipefail

. "$HOME/.local/lib/agent-control/common.sh"
ensure_dirs

slug="${1:?slug required}"
state="${2:?state required}"
shift 2
summary="$*"

workspace="$AGENT_WORK_HOME/$slug"
status_file="$AGENT_CONTROL_HOME/status/$slug.status"
updated_at="$(date '+%Y-%m-%d %H:%M:%S')"

cat > "$status_file" <<STATUS
SLUG="$slug"
STATE="$state"
SUMMARY="$summary"
UPDATED_AT="$updated_at"
WORKSPACE="$workspace"
TMUX_SESSION="$AGENT_TMUX_SESSION"
TMUX_WINDOW="$slug"
STATUS

mkdir -p "$AGENT_CONTROL_HOME/logs"
printf '%s %s %s\n' "$updated_at" "$state" "$summary" >> "$AGENT_CONTROL_HOME/logs/$slug.log"
```

### 14.3 `agent-blocked` Skeleton

```bash
#!/usr/bin/env bash
set -euo pipefail

slug="${1:?slug required}"
shift
message="${*:-Blocked without message}"

agent-status "$slug" BLOCKED "$message"

tmux display-message "Agent blocked: $slug - $message" 2>/dev/null || true
printf '\a'
```

### 14.4 `agent-dashboard` Skeleton

```bash
#!/usr/bin/env bash
set -euo pipefail

AGENT_CONTROL_HOME="${AGENT_CONTROL_HOME:-$HOME/.agent-control}"
status_dir="$AGENT_CONTROL_HOME/status"

clear
printf 'Agent Cockpit\n'
printf '=============\n\n'

if ! ls "$status_dir"/*.status >/dev/null 2>&1; then
  echo "No agents yet."
  echo
  echo "Try: agent-spawn"
  exit 0
fi

print_group() {
  state="$1"
  title="$2"
  files="$(grep -l "^STATE=\"$state\"" "$status_dir"/*.status 2>/dev/null || true)"
  [ -z "$files" ] && return 0

  echo "$title"
  echo "----------------------------------------"

  for file in $files; do
    slug="$(grep '^SLUG=' "$file" | cut -d= -f2- | sed 's/^"//; s/"$//')"
    summary="$(grep '^SUMMARY=' "$file" | cut -d= -f2- | sed 's/^"//; s/"$//')"
    updated="$(grep '^UPDATED_AT=' "$file" | cut -d= -f2- | sed 's/^"//; s/"$//')"
    printf '[%s] %s\n' "$slug" "$summary"
    printf '  updated: %s\n' "$updated"
  done
  echo
}

print_group BLOCKED "BLOCKED"
print_group NEEDS_FEEDBACK "NEEDS FEEDBACK"
print_group FAILED "FAILED"
print_group READY "READY"
print_group WORKING "WORKING"
print_group STARTING "STARTING"
print_group PAUSED "PAUSED"
print_group DONE "DONE"
```

## 15. Quota Dashboard Rendering

The cockpit should render shared quota information in one compact pane with the 5-hour and 7-day windows next to each other.

### 15.1 MVP Terminal Rendering

The MVP may use progress bars instead of true circles because portable terminal ring charts are hard without a richer TUI.

Example:

```text
USAGE QUOTAS (Claude, shared)

5 HOUR QUOTA                         7 DAY QUOTA
usage   ███████░░░░░░░░░░░ 36%       usage   ██████████████░░░░ 69%
elapsed █████░░░░░░░░░░░░░ 24%       elapsed ██████░░░░░░░░░░░░ 31%
risk    +12 ahead of time            risk    +38 high risk
reset   in 3h 47m                    reset   in 4d 18h
```

### 15.2 Ring Chart Semantics

When a richer TUI is added, use two concentric rings for each quota window:

```text
outer ring = quota usage percentage
inner ring = time elapsed percentage
```

Interpretation:

```text
outer ring more complete than inner ring  = usage is ahead of time
outer ring equal/less complete            = usage is on track
```

### 15.3 Computation Rules

For each window:

```text
elapsed_percentage = (now - window_started_at) / (window_resets_at - window_started_at) * 100
burn_delta = used_percentage - elapsed_percentage
```

If `window_started_at` is missing:

```text
5h window start = window_resets_at - 5 hours
7d window start = window_resets_at - 7 days
```

Risk labels:

```text
burn_delta <= 0       on track
0 < burn_delta <= 10  slightly ahead
10 < burn_delta <= 25 risk
burn_delta > 25       high risk
```

### 15.4 Split Dashboard Commands

Support both combined and split dashboard rendering:

```bash
agent-dashboard          # agents + quota summary
agent-dashboard-agents   # only agent table/statuses
agent-dashboard-quotas   # only shared Claude quota pane
```

The default cockpit layout can use the combined dashboard first. A later layout can split the right side into an agents pane and a quota pane.

## 16. Testing Plan

### 16.1 Unit-Style Shell Tests

Test functions manually or with a small shell test runner later.

Cases:

- slug normalization
- status file creation
- blocked status update
- config loading
- missing repo handling
- duplicate slug handling

### 16.2 Manual End-to-End Test

1. Create or configure repo presets.
2. Run `agent-cockpit`.
3. Run `agent-spawn test-agent backend frontend`.
4. Verify worktrees exist.
5. Verify branches exist.
6. Verify tmux window exists.
7. Run `agent-status test-agent WORKING "hello"`.
8. Verify dashboard updates.
9. Run `agent-blocked test-agent "need input"`.
10. Verify dashboard highlights blocked state.
11. Run `agent-jump test-agent`.
12. Verify tmux switches to the workspace.

### 16.3 Safety Tests

- Spawn with existing slug.
- Spawn with invalid repo path.
- Spawn with existing branch.
- Clean workspace with dirty changes.
- Run dashboard with malformed status file.

## 17. Rollout Plan

### Step 1

Implement `agent-status`, `agent-blocked`, and the basic agent status part of `agent-dashboard`.

This gives immediate value even before workspace spawning is automated.

### Step 2

Implement `agent-quota-update` and `agent-dashboard-quotas` using mocked quota JSON.

This validates the shared quota model before connecting it to Claude.

### Step 3

Implement `agent-cockpit` with a simple tmux layout:

```text
left pane  = free shell
right pane = dashboard with agents and shared quotas
```

### Step 4

Implement non-interactive `agent-spawn <slug> <repo...>`.

This is easier than interactive selection and proves the worktree/tmux flow.

### Step 5

Add interactive `agent-spawn` with repository defaults.

### Step 6

Add `agent-jump`.

### Step 7

Add Claude statusline integration through `claude-statusline` once the local payload shape is verified.

### Step 8

Add lifecycle commands: `agent-list`, `agent-close`, `agent-clean`.

### Step 9

Add nicer UX: `fzf`, stale detection, event logs, better notifications, and richer ring visualization.

## 18. Definition of Done for MVP

The MVP is complete when:

- The user can start the cockpit with `agent-cockpit`.
- The user can spawn a workspace with a slug and selected repositories.
- Git worktrees are created under `~/agent-work/<slug>/`.
- `AGENTS.md` and `.agent/HANDOFF.md` are generated.
- A tmux window is created and selected.
- Agents can call `agent-status` and `agent-blocked`.
- The cockpit dashboard shows agent state grouped by urgency.
- The cockpit dashboard shows shared Claude 5-hour and 7-day quota state.
- The quota pane clearly distinguishes usage percentage from elapsed-time percentage.
- The dashboard still works when quota data is unavailable.
- The user can jump to an agent window by slug.

## 19. Future Design Notes

The tool may eventually evolve into a richer TUI or web dashboard, but only after the file-based model proves useful.

The most important invariant to preserve is:

```text
one slug = one workspace = one tmux window = one status entry
```

Selected repositories are children of the workspace. Agent purpose is not encoded in infrastructure. Purpose comes from the task prompt.


## 20. Quota Integration Design Notes

Claude usage quotas are global to the user, not owned by any single agent workspace. The dashboard must therefore avoid per-agent quota attribution unless a future provider exposes reliable per-session accounting.

For v1, quota tracking is observational:

```text
Claude session/statusline data -> agent-quota-update -> ~/.agent-control/quotas/claude.json -> dashboard
```

The cockpit should treat quota data as advisory. It should help the user answer questions such as:

- Are we burning 5-hour quota faster than the 5-hour window is progressing?
- Are we burning 7-day quota faster than the week is progressing?
- Is it safe to spawn another long-running agent session right now?
- Should some lower-priority agents be paused until reset?

Do not block agent spawning automatically in v1. If proactive protection is desired later, add an explicit warning prompt rather than a hard stop.
