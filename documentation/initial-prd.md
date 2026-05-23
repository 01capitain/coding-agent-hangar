# PRD: Agent Cockpit

## 1. Summary

Agent Cockpit is a local command-line and tmux-based control plane for managing multiple parallel AI agent sessions. It lets the user spawn isolated workspaces, select which repositories should be included, automatically create git worktrees, open a dedicated tmux window for the agent, and collect status updates back into a central dashboard.

The tool is intentionally lightweight. It should use shell scripts, git worktrees, tmux, markdown instruction files, and status files. It should not require a daemon, database, web server, or cloud service for the initial version.

## 2. Problem Statement

The user runs multiple parallel AI agent sessions across backend and frontend repositories. These agents are effective but frequently become blocked because they need quick user validation, access approval, or clarification. The user often does not notice these requests quickly enough, making them the bottleneck.

A second issue is repository state contamination. When several agents operate in or around the same repositories, refinement or planning agents can become confused by dirty working trees or files that are actively being changed by other agents.

The current workflow requires too much manual setup per session:

- creating or choosing worktrees
- opening tmux panes/windows
- remembering agent operating rules
- reminding agents how to report status
- checking which agents are blocked
- switching between terminals manually

Agent Cockpit should make this workflow repeatable, visible, and safe.

## 3. Goals

### 3.1 Primary Goals

- Spawn a new isolated agent workspace from a single command.
- Ask for a human-readable slug/name for the workspace.
- Ask which repositories to include from a preset list, with sensible defaults.
- Create one git worktree per selected repository.
- Create a dedicated tmux window for the workspace and switch to it.
- Generate an `AGENTS.md` file containing operating rules, status reporting rules, blocking rules, and handoff expectations.
- Prepare the command/context for starting a new agent session.
- Let agents report status back to a central dashboard.
- Show shared Claude quota/token usage in the cockpit so the user can decide whether enough budget remains for ongoing agents.
- Let the user live primarily in a dashboard/cockpit panel and jump to agents that need attention.

### 3.2 Non-Goals for Initial Version

- No separate agent roles such as development, refinement, review, architect, or coder.
- No web UI.
- No long-running daemon.
- No database.
- No remote orchestration.
- No automatic task assignment.
- No automatic merging, rebasing, or force-pushing.
- No automatic dependency installation.
- No agent-to-agent protocol beyond shared files and status.
- No attempt to enforce Claude usage limits automatically in v1; the dashboard is informational only.
- No hard dependency on Claude-specific quota data being available; unsupported environments must degrade gracefully.

## 4. Core Concept

The core unit is an agent workspace.

One workspace has:

- one slug
- one tmux window
- one status entry
- one generated `AGENTS.md`
- one `.agent/` metadata directory
- zero or more repository worktrees, usually one or more

Example:

```text
~/agent-work/permissions-refactor/
├── AGENTS.md
├── .agent/
│   ├── metadata.env
│   ├── status -> ~/.agent-control/status/permissions-refactor.status
│   ├── HANDOFF.md
│   └── prompt.md
├── backend/
└── frontend/
```

The infrastructure does not decide whether the agent is doing implementation, refinement, or review. The user gives the task once the workspace is opened.

## 5. User Personas

### 5.1 Primary User

A technical product/development lead who coordinates several AI agent sessions in parallel across multiple repositories and wants to reduce their own bottleneck in the feedback loop.

### 5.2 Agent Session

An AI coding or reasoning session running in a terminal, such as Codex, Claude Code, Cursor Agent, or another CLI-based agent. The specific agent backend should be configurable and not hardcoded.

## 6. Key User Stories

### 6.1 Spawn a New Agent Workspace

As the user, I want to run `agent-spawn`, provide a slug, choose repositories, and have the tool create an isolated workspace and tmux window so I can immediately give an agent its task.

Acceptance criteria:

- The command asks for a slug if none is provided.
- The command asks which repositories to include.
- Default repositories are preselected.
- The user can confirm before filesystem or git changes are made.
- Worktrees are created under `~/agent-work/<slug>/<repo>`.
- A tmux window named after the slug is created.
- The user is switched to the new tmux window.
- The window shows the workspace path, selected repositories, generated instructions, and the prepared agent start command.

### 6.2 Report Agent Status

As an agent, I want to update my status with a simple command so the user can see what I am doing without switching to my window.

Acceptance criteria:

- `agent-status <slug> <state> <summary>` writes a status file.
- The status file includes slug, state, summary, timestamp, workspace, and tmux target where available.
- Status updates are reflected in the dashboard.

### 6.3 Report Blocked State

As an agent, I want to call `agent-blocked <slug> <message>` when I need user input so the dashboard highlights me and the user can jump to me quickly.

Acceptance criteria:

- `agent-blocked` sets state to `BLOCKED` or `NEEDS_FEEDBACK`.
- The message is visible in the dashboard.
- A tmux display message or terminal bell is triggered.
- On WSL, the initial implementation does not depend on Windows toast notifications.

### 6.4 Monitor All Agents

As the user, I want a cockpit dashboard that groups agent workspaces by state so I can see which agents are working, blocked, ready, done, or failed.

Acceptance criteria:

- `agent-dashboard` reads status files from `~/.agent-control/status/`.
- It groups entries by state.
- It shows slug, summary, updated timestamp, and optionally workspace.
- It works well with `watch -n 2 agent-dashboard` inside tmux.

### 6.5 Jump to an Agent

As the user, I want to jump from the cockpit to a specific agent workspace or to the next blocked agent.

Acceptance criteria:

- `agent-jump <slug>` switches tmux to the workspace window.
- `agent-jump blocked` jumps to a blocked or feedback-needed workspace.
- If multiple workspaces match, the initial version may choose the oldest blocked one or list options.

### 6.6 Keep Agent Instructions Consistent

As the user, I want every workspace to contain an `AGENTS.md` file with status reporting and handoff rules so I do not need to repeat those instructions manually.

Acceptance criteria:

- `AGENTS.md` is generated during spawn.
- It includes the workspace slug, workspace path, selected repositories, status commands, blocking rules, git rules, and handoff expectations.
- Each repository worktree can contain a short repo-local `AGENTS.md` that points back to the workspace-level `../AGENTS.md`.

### 6.7 Monitor Shared Claude Quota and Token Usage

As the user, I want the cockpit to show shared Claude usage windows so I can decide whether the current quota is sufficient for the agents that are running.

Claude quota is user-bound, not agent-bound. All active agent sessions contribute to the same quota windows, and every agent session may be able to observe or report the same quota data. The cockpit must therefore display Claude quota once as shared global state, not once per agent.

Acceptance criteria:

- The dashboard has a shared `USAGE QUOTAS` pane.
- The pane shows a 5-hour quota view and a 7-day quota view side by side.
- Each quota view uses two progress indicators:
  - outer ring or outer progress indicator: quota used
  - inner ring or inner progress indicator: time elapsed in the quota window
- The dashboard clearly indicates whether usage is on track:
  - if usage percentage is greater than elapsed-time percentage, usage is ahead of time and may not last until reset
  - if usage percentage is less than or equal to elapsed-time percentage, usage is on track
- The pane shows reset time or time remaining when available.
- If Claude quota data is unavailable, the pane shows `unavailable` instead of failing.
- The quota pane is compact and avoids long descriptions; detailed explanation belongs in documentation, not in the cockpit UI.

## 7. Functional Requirements

### 7.1 Configuration

The tool must support a repository preset file.

Recommended path:

```text
~/.agent-control/config/repos.env
```

Initial format:

```bash
REPO_BACKEND_NAME="backend"
REPO_BACKEND_PATH="$HOME/projects/backend"
REPO_BACKEND_DEFAULT="true"

REPO_FRONTEND_NAME="frontend"
REPO_FRONTEND_PATH="$HOME/projects/frontend"
REPO_FRONTEND_DEFAULT="true"

REPO_DOCS_NAME="docs"
REPO_DOCS_PATH="$HOME/projects/docs"
REPO_DOCS_DEFAULT="false"
```

The implementation may later move to YAML or TOML, but shell-readable config is acceptable for v1.

### 7.2 Workspace Creation

For each selected repository, `agent-spawn` must create a git worktree.

Branch naming:

```text
agent/<slug>/<repo>
```

Worktree path:

```text
~/agent-work/<slug>/<repo>
```

Base branch:

- default: `origin/main`
- configurable globally or per repo in a later version

### 7.3 Shared Claude Quota Tracking

The tool should maintain shared Claude quota state separately from individual agent state.

Recommended path:

```text
~/.agent-control/quotas/claude.json
```

Example structure:

```json
{
  "source": "claude-statusline",
  "updated_at": "2026-05-23T10:42:15+02:00",
  "five_hour": {
    "window_started_at": "2026-05-23T09:30:00+02:00",
    "window_resets_at": "2026-05-23T14:30:00+02:00",
    "elapsed_percentage": 24,
    "used_percentage": 36,
    "remaining_percentage": 64
  },
  "seven_day": {
    "window_started_at": "2026-05-16T00:00:00+02:00",
    "window_resets_at": "2026-05-23T00:00:00+02:00",
    "elapsed_percentage": 31,
    "used_percentage": 69,
    "remaining_percentage": 31
  }
}
```

The dashboard must treat this as global state. It must not attach quota usage to a specific agent workspace.

If `window_started_at` is missing but `window_resets_at` is present, the dashboard may infer:

```text
5h start = reset - 5 hours
7d start = reset - 7 days
```

The dashboard should compute:

```text
burn_delta = used_percentage - elapsed_percentage
```

Suggested display semantics:

```text
burn_delta <= 0       on track
0 < burn_delta <= 10  slightly ahead
10 < burn_delta <= 25 risk
burn_delta > 25       high risk
```

### 7.4 Quota Data Collection

The tool should include a best-effort quota update command:

```bash
agent-quota-update
```

The command should accept JSON from stdin when used as a Claude statusline hook or equivalent integration. It should extract known quota fields when available, write `~/.agent-control/quotas/claude.json`, and ignore missing fields without failing.

The implementation must support unknown or changing Claude payload shapes by:

- storing only normalized fields needed by the dashboard
- preserving enough raw metadata to debug availability
- showing `unavailable` when usage data cannot be found
- not blocking agent status updates when quota update fails

### 7.5 Cockpit Quota Visualization

The cockpit should place the 5-hour and 7-day quota indicators in one compact pane next to each other.

Preferred layout:

```text
USAGE QUOTAS (Claude, shared)
┌──────────────────────────────┬──────────────────────────────┐
│ 5 HOUR                       │ 7 DAY                        │
│ outer: usage                 │ outer: usage                 │
│ inner: elapsed               │ inner: elapsed               │
│ used 36% / elapsed 24%       │ used 69% / elapsed 31%       │
│ reset 14:30                  │ reset May 23                 │
└──────────────────────────────┴──────────────────────────────┘
```

In the terminal MVP, the visual may be rendered as compact progress bars. A later TUI can render true ring charts.

### 7.6 Slug Validation

Slugs should be safe for paths, branch names, and tmux windows.

Allowed characters:

```text
a-z 0-9 - _
```

Recommended normalization:

- lowercase input
- replace spaces with hyphens
- remove unsupported characters
- collapse repeated hyphens
- trim leading/trailing hyphens

If the resulting slug is empty, ask again.

### 7.4 Existing Workspace Handling

If `~/agent-work/<slug>` already exists, `agent-spawn` must not overwrite it automatically.

The user should be offered options:

1. open existing workspace
2. create a suffixed workspace, such as `<slug>-2`
3. abort

For v1, it is acceptable to abort with a clear message and require the user to choose a different slug.

### 7.5 Status States

Supported states for v1:

```text
STARTING
WORKING
NEEDS_FEEDBACK
BLOCKED
READY
DONE
FAILED
PAUSED
```

State meanings:

- `STARTING`: workspace created and agent session is being prepared
- `WORKING`: agent is actively working
- `NEEDS_FEEDBACK`: agent needs a user decision but may not be fully blocked
- `BLOCKED`: agent cannot proceed without user input or access
- `READY`: agent believes the task is ready for user review
- `DONE`: agent finished the task
- `FAILED`: agent hit an unrecoverable issue
- `PAUSED`: workspace intentionally paused

### 7.6 Status File Format

Status files should be shell-compatible key-value files.

Path:

```text
~/.agent-control/status/<slug>.status
```

Example:

```bash
SLUG="permissions-refactor"
STATE="NEEDS_FEEDBACK"
SUMMARY="Need decision: should missing access return 403 or 404?"
UPDATED_AT="2026-05-23 15:45:20"
WORKSPACE="$HOME/agent-work/permissions-refactor"
TMUX_SESSION="agents"
TMUX_WINDOW="permissions-refactor"
```

### 7.7 Metadata File Format

Each workspace should have:

```text
~/agent-work/<slug>/.agent/metadata.env
```

Example:

```bash
SLUG="permissions-refactor"
WORKSPACE="$HOME/agent-work/permissions-refactor"
REPOS="backend frontend"
TMUX_SESSION="agents"
TMUX_WINDOW="permissions-refactor"
STATUS_FILE="$HOME/.agent-control/status/permissions-refactor.status"
CREATED_AT="2026-05-23 15:40:00"
```

### 7.8 Handoff File

Each workspace should have:

```text
~/agent-work/<slug>/.agent/HANDOFF.md
```

The generated file should include headings for:

- Goal
- Current Status
- Repositories
- Files Changed
- Commands Run
- Test Results
- Open Questions
- Next Steps
- Risks / Follow-ups

### 7.9 Prompt File

Each workspace should have:

```text
~/agent-work/<slug>/.agent/prompt.md
```

This file should contain the initial prompt scaffold shown to the user when the workspace window opens.

### 7.10 Tmux Integration

The tool should use one persistent tmux session.

Default session name:

```text
agents
```

Cockpit window:

```text
cockpit
```

Workspace window:

```text
<slug>
```

`agent-cockpit` should create or attach to the session.

`agent-spawn` should create a new tmux window for the workspace and switch to it.

### 7.11 Agent Start Command

The agent backend command should be configurable.

Examples:

```bash
AGENT_COMMAND="codex"
AGENT_COMMAND="claude"
AGENT_COMMAND="cursor-agent"
```

For v1, the spawn window should prepare the command and show the prompt rather than automatically starting a task. Automatic task passing can be added later.

## 8. Non-Functional Requirements

### 8.1 Portability

The initial target environment is WSL/Linux with tmux, bash, git, and standard Unix tools.

The tool should avoid macOS-only dependencies such as `osascript`.

### 8.2 Safety

The tool must not modify canonical repositories directly except to create worktrees from them.

The tool must not delete worktrees without an explicit cleanup command and confirmation.

The tool must not force-push, rebase, or merge automatically.

### 8.3 Simplicity

The initial implementation should remain understandable as shell scripts.

No daemon, database, TUI framework, or web server should be introduced until the file-based version proves useful.

### 8.4 Observability

All agent status should be inspectable from files.

No state should exist only inside tmux.

## 9. Command Overview

### Required for v1

```bash
agent-cockpit
agent-spawn
agent-status <slug> <state> <summary>
agent-blocked <slug> <message>
agent-dashboard
agent-jump <slug|blocked|feedback>
```

### Optional for v1.1

```bash
agent-list
agent-close <slug>
agent-clean <slug>
agent-open <slug>
```

## 10. Example Workflow

The user starts the cockpit:

```bash
agent-cockpit
```

The user spawns a workspace:

```bash
agent-spawn
```

Prompts:

```text
Slug: permissions-refactor
Repositories:
[x] backend
[x] frontend
[ ] docs
Create workspace? [Y/n]
```

The tool creates:

```text
~/agent-work/permissions-refactor/backend
~/agent-work/permissions-refactor/frontend
~/agent-work/permissions-refactor/AGENTS.md
~/agent-work/permissions-refactor/.agent/
```

The tool opens tmux window:

```text
permissions-refactor
```

The user starts the agent using the prepared prompt.

The agent reports:

```bash
agent-status permissions-refactor WORKING "Inspecting backend permission checks"
```

Later:

```bash
agent-blocked permissions-refactor "Should missing access return 403 or 404?"
```

The dashboard shows:

```text
NEEDS FEEDBACK / BLOCKED
permissions-refactor — Should missing access return 403 or 404?
```

The user jumps:

```bash
agent-jump permissions-refactor
```

The user answers and returns to the cockpit.

## 11. Risks and Mitigations

### 11.1 Agents Ignore Status Rules

Risk: Agents may forget to call `agent-status` or `agent-blocked`.

Mitigation:

- Put explicit rules in `AGENTS.md`.
- Show the status command examples prominently in the generated prompt.
- Add a visible per-workspace side pane that shows when the status was last updated.

### 11.2 Worktree Confusion

Risk: Agents may navigate into canonical repositories or sibling workspaces.

Mitigation:

- `AGENTS.md` explicitly says to work only inside the workspace.
- Repo-local `AGENTS.md` points to the workspace-level instructions.
- The prompt includes absolute workspace paths.

### 11.3 Slug/Branch Conflicts

Risk: Two workspaces try to use the same slug or branch.

Mitigation:

- Validate slug uniqueness.
- Abort on existing worktree path.
- Check for existing branch before creating worktree.

### 11.4 Dashboard Becomes Too Noisy

Risk: Many finished agents clutter the dashboard.

Mitigation:

- Group `DONE` last.
- Add `agent-close` later to archive inactive status files.

### 11.5 Claude Quota Data Is Missing or Inaccurate

Risk: Claude quota fields may be unavailable, version-dependent, login-method-dependent, or differently named than expected.

Mitigation:

- Treat quota integration as best effort.
- Make `agent-quota-update` tolerant of missing fields.
- Show `unavailable` in the dashboard instead of failing.
- Keep quota state global and informational, not authoritative for automation.
- Allow manual or mocked quota JSON for testing the dashboard.

### 11.6 Quota Visualization Is Misread

Risk: Users may confuse time elapsed, quota used, and remaining quota.

Mitigation:

- Keep the rule consistent: outer indicator is usage, inner indicator is elapsed time.
- Show small labels such as `used`, `elapsed`, and `reset`.
- Highlight only the outcome: `on track`, `risk`, or `high risk`.
- Put detailed explanations in documentation, not the compact cockpit pane.

## 12. Open Questions

- Which agent CLI should be the default command: Codex, Claude, Cursor, or configurable only?
- Should `agent-blocked` map to `BLOCKED` or `NEEDS_FEEDBACK` by default?
- Should the dashboard show stale `WORKING` agents whose status has not updated for a configurable time?
- Should repo presets live in shell env, YAML, or TOML after v1?
- Should `agent-spawn` support a non-interactive `--repos backend,frontend` mode in v1?
- Which Claude statusline payload fields are reliably available for 5-hour and 7-day quota data in the user's environment?
- Should the cockpit warn proactively when usage is ahead of elapsed time, or only show the visual risk state?
- Should quota history be retained for trend analysis, or should v1 only keep the latest normalized snapshot?

## 13. Success Metrics

- User can spawn a new workspace in under one minute.
- User can see all blocked or feedback-needed agents from the cockpit.
- No two active agents need to share a dirty worktree.
- The user spends less time manually checking terminal windows.
- Agents consistently produce useful handoff and status information.
- The user can see shared Claude 5-hour and 7-day usage state without visiting individual agent sessions.
- The cockpit helps the user spot when quota usage is ahead of elapsed time.
