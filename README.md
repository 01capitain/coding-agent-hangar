# Agent Hangar

> Status: pre-alpha; nothing is implemented yet — this is the planning + skeleton phase.

Agent Hangar is a local control plane for running parallel AI coding agents in tmux. It spawns isolated workspaces with git worktrees, generates the agent instructions, and surfaces every agent's status — including shared Claude usage quota — so you can see at a glance which agents need attention without flipping between terminal windows.

The hangar metaphor: each agent gets its own bay (a workspace), prepared the same way every time, and a control tower (the cockpit) shows what's where. You stay in the tower; you walk to a bay only when something needs you.

## Why this exists

When you run several AI agents in parallel across multiple repositories, two things break down:

1. **You become the bottleneck.** Agents block on validation, clarification, or access requests. You don't notice fast enough because you're heads-down in your own work. The dashboard surfaces those moments in your peripheral vision.
2. **Repository state contaminates.** Refinement, planning, and review agents get confused by dirty working trees that other agents are actively changing. Per-agent git worktrees fix this.

Agent Hangar solves both with shell-light, file-based primitives: status files on disk, git worktrees per agent, tmux windows for switching, and a Python orchestration layer that ties it together.

## Core concept

One **slug** identifies one **workspace**. A workspace has:

- one tmux window (named after the slug)
- one status entry under `~/.agent-control/status/<slug>.status`
- one generated `AGENTS.md` (Claude reads it as `CLAUDE.md` via a symlink)
- one `.agent/` metadata directory
- zero or more git worktrees under the workspace directory

A workspace can have **zero** worktrees (useful for planning or PRD agents that don't need code), **one** worktree (single-repo tasks — the common case), or **many** (cross-repo features). Repository selection is per-spawn, deliberately not pre-checked.

```text
~/agent-work/permissions-refactor/
├── AGENTS.md
├── CLAUDE.md -> AGENTS.md
├── .agent/
│   ├── metadata.env
│   ├── status -> ~/.agent-control/status/permissions-refactor.status
│   ├── HANDOFF.md
│   └── prompt.md
├── backend-core-nestjs/    # git worktree on branch agent/permissions-refactor/backend-core-nestjs
└── frontend-hotelkit-web/  # git worktree on branch agent/permissions-refactor/frontend-hotelkit-web
```

## Requirements

- Linux or WSL (the v1 target). macOS-only tools (e.g., `osascript`) are not used.
- `git`, `tmux`, `bash` (any modern shell user; bash is used for thin glue).
- Python 3.11+.
- `PyYAML` for repo config parsing (`apt install python3-yaml` or `pip install pyyaml`).
- A Claude Code installation if you want shared usage quota in the dashboard (otherwise the quota pane shows `unavailable` and everything else still works).

## Install

```bash
git clone <repo-url> coding-agent-dashboard
cd coding-agent-dashboard
pipx install .            # preferred — isolates dependencies
# OR
pip install --user -e .   # editable install for development
```

The `pyproject.toml` registers `hangar-*` (control-plane commands) and `agent-*` (per-agent commands) console scripts; ensure `~/.local/bin/` is on your `PATH`.

```bash
hangar-init
```

Creates `~/.agent-control/` and seeds `~/.agent-control/config/repos.yaml` from the bundled hotelkit-shaped sample. Edit the file to match your actual repositories — delete what doesn't apply and add what does. Re-running `hangar-init` is idempotent: it adds any missing subdirs and never clobbers an existing `repos.yaml`.

## Configuration

### `~/.agent-control/config/repos.yaml`

```yaml
repos:
  - key: backend
    name: backend-core-nestjs
    path: /var/www/backend-core-nestjs
    default: true # sort hint only; NOT pre-checked
    bootstrap: npm ci
    base_branch: origin/main

  - key: frontend
    name: frontend-hotelkit-web
    path: /var/www/frontend-hotelkit-web
    default: true
    bootstrap: npm ci

  - key: mobile
    name: hotelkit-react-native
    path: /var/www/hotelkit-react-native
    bootstrap: npm ci

  - key: e2e
    name: playwright-e2e-tests
    path: /var/www/playwright-e2e-tests
    bootstrap: npm ci
```

`bootstrap` is the command run in the worktree immediately after creation, in the background, while the workspace is in `STARTING` state. Stdout/stderr go to `~/.agent-control/logs/<slug>-<repo>-bootstrap.log`.

### Environment variables (all optional)

```bash
AGENT_CONTROL_HOME="$HOME/.agent-control"
AGENT_WORK_HOME="$HOME/agent-work"
AGENT_TMUX_SESSION="agents"
AGENT_BASE_BRANCH="origin/main"
AGENT_COMMAND="claude"
AGENT_STALE_MINUTES="30"
```

If you want workspaces under `/var/www/agent-work/` (for nginx wildcard vhosts), set `AGENT_WORK_HOME=/var/www/agent-work`.

## Quick start

```bash
hangar-cockpit                                      # opens the agents tmux session and cockpit window
agent-spawn permissions-refactor backend frontend   # creates workspace, worktrees, tmux window
# inside the new tmux window: start your agent, give it the task in .agent/prompt.md
```

From inside the agent session:

```bash
agent-status permissions-refactor WORKING "Inspecting permission checks in backend"
agent-blocked permissions-refactor "Should missing access return 403 or 404?"
```

From the cockpit (or anywhere):

```bash
agent-jump permissions-refactor       # switch tmux to that workspace
agent-jump blocked                    # jump to the next blocked agent
hangar-dashboard                      # one-shot dashboard render (cockpit uses watch on this)
```

When the task is done:

```bash
agent-clean permissions-refactor      # guided interactive cleanup checklist
```

## Commands

Commands split by scope. `hangar-*` commands operate on the whole control plane (all agents, the cockpit, the shared quota). `agent-*` commands target a single workspace by slug.

**Hangar-level (global)**

| Command                | Purpose                                                                                                                |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `hangar-init`          | Create `~/.agent-control/` layout and seed `repos.yaml` from the bundled hotelkit sample.                              |
| `hangar-cockpit`       | Create or attach the `agents` tmux session and open the cockpit window with the watched dashboard.                     |
| `hangar-dashboard`     | One-shot render of the grouped status dashboard + quota pane. Run under `watch -n 2` in the cockpit window.            |
| `hangar-list`          | Plain ASCII table of every workspace and its state. The simpler, scriptable view used outside the cockpit.             |
| `hangar-tmux-status`   | Emit the compact `[B:n] [F:n] [R:n] [W:n] | 5h:U%/E% 7d:U%/E%` line consumed by `set -g status-right` in `~/.tmux.conf`. |
| `hangar-quota-update`  | Read Claude statusline JSON from stdin, normalize, write `~/.agent-control/quotas/claude.json`.                        |

**Per-agent (slug-bound)**

| Command                                 | Purpose                                                                                                                                  |
| --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `agent-spawn [slug] [repo...]`          | Create a workspace. Interactive when args omitted; prompts resume/suffix/abort if slug exists. Pass zero repos for a planning workspace. |
| `agent-status <slug> <state> <summary>` | Update the workspace's status file. Atomic write.                                                                                        |
| `agent-blocked <slug> <message>`        | Set state to `BLOCKED`, send tmux display-message, ring the bell.                                                                        |
| `agent-jump <slug\|blocked\|feedback>`  | Switch tmux to a workspace; with `blocked`/`feedback` picks the next match.                                                              |
| `agent-close <slug>`                    | Mark workspace `DONE` or `PAUSED`; optionally kill its tmux window. Does **not** remove worktrees.                                       |
| `agent-clean <slug>`                    | Guided interactive cleanup. Refuses uncommitted work without `--force`.                                                                  |

## Status states

```text
STARTING         workspace created, bootstrap running
WORKING          agent is actively working
NEEDS_FEEDBACK   agent needs a decision but is not fully blocked
BLOCKED          agent cannot proceed without input/access
READY            agent believes the task is ready for review
DONE             agent finished
FAILED           agent hit an unrecoverable issue
PAUSED           workspace intentionally paused
STARTING_FAILED  bootstrap (e.g., npm ci) failed; see log
```

`WORKING` rows that haven't updated in `AGENT_STALE_MINUTES` minutes (default 30) render with a `[stale]` tag in the dashboard.

## Tmux status line integration

Agent Hangar shines when the compact status summary is visible from every tmux window, not just the cockpit. Add to `~/.tmux.conf`:

```tmux
set -g status-interval 15
set -g status-right '#(hangar-tmux-status) #{status-right}'
```

The output looks roughly like:

```text
[B:1] [F:0] [R:2] [W:3]  |  5h:36%/24%  7d:69%/31%
```

`B` = blocked, `F` = needs feedback, `R` = ready, `W` = working. Colors shift to red/yellow when something demands attention. The bell rings on a transition (`B` count increases), not on steady-state.

## Claude Code statusline integration (for quota)

Claude Code's statusline emits a JSON payload that contains `rate_limits.five_hour.used_percentage`, `rate_limits.five_hour.resets_at`, `rate_limits.seven_day.*`, and `context_window.used_percentage`. Pipe it into `hangar-quota-update`:

`~/.local/bin/claude-statusline-hangar` (or fold this into your existing statusline script):

```bash
#!/usr/bin/env bash
set -euo pipefail

payload="$(cat)"
printf '%s' "$payload" | hangar-quota-update >/dev/null 2>&1 || true

# Keep emitting your normal statusline output.
printf '%s' "$payload" | your-existing-statusline-renderer
```

In `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "bash ~/.local/bin/claude-statusline-hangar"
  }
}
```

Every Claude Code session refreshes the shared quota file. The cockpit picks up the latest snapshot. Quota integration is best-effort: if Claude's payload shape changes, the cockpit shows `unavailable` for missing fields and nothing else breaks.

## What ships in v1

See `ROADMAP.md`. The MVP focuses on: spawn, status reporting, dashboard (with quota), cockpit, jump, guided cleanup. Push notifications, Claude Code hook integration, fzf, event-log panes, and richer TUI rendering are deferred until the file-based core proves itself.

## Project structure

```text
coding-agent-dashboard/
├── README.md              # this file
├── ROADMAP.md             # phased build order
├── LICENSE
├── pyproject.toml         # entry points for agent-* commands
├── src/agent_hangar/      # Python implementation
│   ├── cli.py             # argparse dispatch
│   ├── spawn.py
│   ├── status.py
│   ├── dashboard.py
│   ├── quota.py
│   ├── tmux.py
│   ├── repos.py
│   ├── workspace.py
│   ├── clean.py
│   └── templates/         # AGENTS.md, HANDOFF.md, prompt.md templates
├── scripts/
│   └── claude-statusline  # bash wrapper that pipes JSON to hangar-quota-update
├── tests/
└── documentation/
    ├── initial-prd.md
    ├── initial-implementation-plan.md
    └── grilled-decisions.md   # the design decisions that supersede the PRD where they disagree
```

## Design references

- `documentation/initial-prd.md` — the original product requirements.
- `documentation/initial-implementation-plan.md` — the original implementation plan.
- `documentation/grilled-decisions.md` — **authoritative** when it disagrees with the PRD/plan. Read this first if you're contributing.

## Prior art

- [manaflow-ai/cmux](https://github.com/manaflow-ai/cmux) — native macOS app for managing parallel coding agents through panes/tabs/sidebar, with cross-backend resume hooks for ~13 agents (Claude Code, Codex, Cursor CLI, Gemini, etc.). Different platform and surface than Agent Hangar (GUI vs. tmux + filesystem), no quota tracking, no worktree isolation. Useful as a feature-idea source: per-pane PR status, listening-port surfacing, OSC notification ingestion, browser-pane scripting for agents. See `ROADMAP.md` Post-MVP entries and `documentation/grilled-decisions.md` §15 for which of those have been queued and which are open questions.

## License

See `LICENSE`.
