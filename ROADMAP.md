# Agent Hangar — Roadmap

This roadmap orders the work from "nothing exists" to "v1 MVP" to "post-MVP polish" to "speculative." It supersedes the phasing in `documentation/initial-implementation-plan.md` where they disagree.

The MVP exists to answer one question: **does the dashboard surface blocked / feedback-needed agents fast enough that the user stops being the bottleneck?** Everything in v1 supports that answer. Anything that doesn't is deferred.

---

## Phase 0 — Skeleton (in progress)

Lay down the project so contributors (human or agent) can start building.

- [x] `documentation/initial-prd.md`
- [x] `documentation/initial-implementation-plan.md`
- [x] `documentation/grilled-decisions.md` — authoritative decisions
- [x] `README.md`
- [x] `ROADMAP.md` (this file)
- [x] `pyproject.toml` with all `agent-*` entry points (stubs OK)
- [x] `src/agent_hangar/` package skeleton with empty modules
- [x] `tests/` skeleton (pytest config, smoke test that imports run)
- [x] CI config (lint + tests on push) — single workflow, nothing fancy

**Exit criterion:** `pipx install .` succeeds; every `agent-*` command exists and prints a "not implemented yet" stub with `--help` working. ✓

---

## Phase 1 — Status reporting (the smallest useful loop)

The dashboard is worthless until something writes to it. Start here.

- [x] `hangar-setup` — create `~/.agent-control/{config,status,status/archive,logs,quotas,templates}` and seed `repos.yaml` from the bundled hotelkit-shaped sample. Idempotent: refuses to clobber an existing `repos.yaml`. Validate PyYAML is importable; print an install hint if not.
- [x] `agent-status <slug> <state> <summary>` — atomic write of `~/.agent-control/status/<slug>.status` in the PRD's `KEY="value"` format. Append to `~/.agent-control/logs/<slug>.log`.
- [x] `agent-mark-as-blocked <slug> <message>` — wrapper that calls `agent-status … BLOCKED …`, runs `tmux display-message` if tmux is reachable, prints `\a`.
- [x] `agent-list` — table of all workspaces from status files. Useful for debugging before the dashboard exists.

**Exit criterion:** You can write a status file by hand or via `agent-status`, and `agent-list` shows it. ✓

---

## Phase 2 — Dashboard and cockpit

Make the status visible.

- [ ] `hangar-watch` — render grouped statuses in priority order: BLOCKED → NEEDS_FEEDBACK → FAILED → STARTING_FAILED → READY → WORKING → STARTING → PAUSED → DONE. Compute "minutes since `UPDATED_AT`"; flag `WORKING` rows older than `AGENT_STALE_MINUTES` (default 30) as `[stale]`. Handle missing/partial status files gracefully.
- [ ] `hangar-checkin` — create / attach the `agents` tmux session; create / reuse the `cockpit` window with a layout that runs `watch -n 2 hangar-watch` in the main pane and a shell in a side pane.
- [ ] `hangar-statusline` — print the compact one-liner `[B:n] [F:n] [R:n] [W:n] | 5h:U%/E% 7d:U%/E%` with ANSI color codes. Document the `set -g status-right` snippet in README.
- [ ] Bell-on-transition: `agent-mark-as-blocked` (and any state transition into BLOCKED) triggers `tmux display-message` + `\a`. Steady-state silence.

**Exit criterion:** You can manually write a few status files, run `hangar-checkin`, see them grouped, and the tmux status line updates from any window.

---

## Phase 3 — Quota integration

Verify the shared Claude quota half of the dashboard.

- [ ] `hangar-quota-update` — read JSON from stdin, extract `rate_limits.{five_hour,seven_day}.{used_percentage,resets_at}` and `context_window.used_percentage`. Convert Unix timestamps to ISO 8601. Write normalized `~/.agent-control/quotas/claude.json`. Crash-resistant on missing fields. Keep a `raw_available` summary for debugging.
- [ ] Dashboard quota pane — two-line per window layout (used bar + elapsed bar + reset countdown). Color the used bar by burn-delta (green ≤0, yellow ≤10, orange ≤25, red >25). Show `unavailable` when the quota file is missing or stale beyond a threshold.
- [ ] `scripts/claude-statusline` — bash wrapper for `~/.claude/settings.json` `statusLine.command`. Pipes the JSON into `hangar-quota-update`, then renders the user's existing statusline output unchanged.
- [ ] Mocked quota fixtures in `tests/` to exercise the renderer without a live Claude session.

**Exit criterion:** With the statusline wrapper installed, the cockpit's quota pane updates whenever you use Claude Code. Removing the wrapper degrades the pane to `unavailable` without breaking the rest.

---

## Phase 4 — Workspace spawn (non-interactive)

Prove the worktree + tmux + AGENTS.md flow before adding the interactive UI.

- [ ] `agent-spawn <slug> <repo>...` — non-interactive form.
  - Validate / normalize the slug.
  - Refuse if `~/agent-work/<slug>` already exists (interactive resume prompt comes in Phase 5).
  - For each repo: `git fetch --prune` in the canonical, `git worktree add -b agent/<slug>/<repo> <workspace>/<repo> <base_branch>`.
  - Generate `AGENTS.md` from template; create `CLAUDE.md` symlink.
  - Generate `.agent/metadata.env`, `.agent/HANDOFF.md`, `.agent/prompt.md`.
  - Symlink `.agent/status` → the status file path.
  - Per-repo `bootstrap` runs in background; logs to `~/.agent-control/logs/<slug>-<repo>-bootstrap.log`. Status starts at `STARTING`.
  - Create tmux window named after the slug with the prompt visible. Switch to it.
- [ ] Templates for `AGENTS.md`, `HANDOFF.md`, `prompt.md` covering status reporting rules, blocking rules, handoff expectations, slug + workspace + repo paths.
- [ ] Repo-local `AGENTS.md` in each worktree pointing back to the workspace-level `../AGENTS.md`.
- [ ] Zero-repo workspaces: `agent-spawn <slug>` with no repos creates a workspace dir + tmux window + AGENTS.md, no worktrees, no bootstrap. Confirms interactively to avoid accidents.

**Exit criterion:** End-to-end: `agent-spawn permissions-refactor backend frontend` creates the workspace, worktrees materialize, tmux window opens, the prompt is visible, bootstrap finishes in the background, status transitions from `STARTING` to ready-for-user.

---

## Phase 5 — Workspace spawn (interactive) and resume

Make spawning ergonomic.

- [ ] `agent-spawn` with no args — prompt for slug, show the curated repo list sorted by `default: true` hint with **nothing pre-checked**, accept multi-select input, confirm summary, then run the non-interactive path.
- [ ] Resume prompt when slug exists: **resume** (reattach window, preserve files, no bootstrap) / **suffix** (`<slug>-2`) / **abort**.
- [ ] Slug normalization (lowercase, hyphenate, strip invalid chars, collapse, trim).
- [ ] Branch existence check before `git worktree add`; clear error if it would collide.

**Exit criterion:** A new user can run `agent-spawn`, answer two prompts, and end up in a working workspace.

---

## Phase 6 — Jump

Closing the loop from dashboard back to a specific agent.

- [ ] `agent-jump <slug>` — switch tmux to the workspace's window. From outside tmux, attach to the `agents` session and select the window.
- [ ] `agent-jump blocked` / `agent-jump feedback` — find matching status files; if multiple, print an interactive list (`agent-list`-style) and let the user pick. (fzf integration deferred to post-MVP.)
- [ ] Clear error when no matching workspace exists.

**Exit criterion:** From the cockpit you can jump to any blocked agent in one command.

---

## Phase 7 — Done signal + guided teardown

Close the workspace lifecycle without destroying work.

- [ ] `agent-mark-done <slug> <summary>` — mirror of `agent-mark-as-blocked`: set state to `DONE`, append to the log, ring the bell, tmux display-message. Lightweight; the user typically reads the summary and either gives the next instruction in the same tmux window or moves on to `agent-teardown`. Does NOT touch worktrees, branches, or the tmux window. (For the rare `PAUSED` state, use the generic `agent-status` — no dedicated wrapper.)
- [ ] `agent-teardown <slug>` — guided interactive checklist:
  1. Show workspace path, list of worktrees, per-worktree `git status -sb`.
  2. Show whether `agent/<slug>/<repo>` is merged into base branch on origin.
  3. Show uncommitted changes; refuse to proceed without `--force` if any.
  4. Prompt: "PR opened? [y/N]", "PR merged? [y/N]", "Remove worktree at X? [y/N]", "Delete branch agent/<slug>/<repo>? [y/N]".
  5. On confirmation: `git worktree remove`, delete branches, archive status file to `~/.agent-control/status/archive/<slug>-<timestamp>.status`, remove workspace dir.

**Exit criterion:** An agent can mark itself done from inside its session; a merged feature can be torn down without surprises; uncommitted work blocks teardown; archived status files exist after teardown.

---

## v1 MVP — Definition of Done

The MVP is complete when all of the following work end-to-end:

1. `hangar-setup` sets up the control directory and validates dependencies.
2. `agent-spawn` (interactive and non-interactive) creates workspaces correctly, including zero-repo workspaces and resume-on-existing.
3. `agent-status` / `agent-mark-as-blocked` update status atomically and trigger the bell on BLOCKED transitions.
4. `hangar-watch` renders grouped statuses + quota pane and flags stale `WORKING` rows.
5. `hangar-statusline` produces a usable status-line one-liner consumed by the user's `~/.tmux.conf`.
6. `hangar-checkin` opens the cockpit window with the watched dashboard.
7. `agent-jump` works for `<slug>`, `blocked`, and `feedback`.
8. `hangar-quota-update` normalizes Claude statusline JSON and the dashboard degrades gracefully when quota data is missing.
9. `agent-list` lists all workspaces.
10. `agent-mark-done` signals completion (mirroring `agent-mark-as-blocked`); `agent-teardown` covers the irreversible cleanup path and refuses to nuke uncommitted work.
11. Documentation in `README.md` and `documentation/grilled-decisions.md` is current.

---

## Post-MVP — Reliability and ergonomics

After the MVP lands and gets a few weeks of real use, layer on the next set of improvements based on observed pain.

- **Push notifications.** WSL-friendly `notify-send` (via WSLg) or PowerShell BurntToast, plus a generic webhook hook. Triggered on the same transitions that ring the bell today.
- **`agent-notify` + OSC ingestion.** Generalize `agent-mark-as-blocked` into `agent-notify <slug> <severity> <message>` so any backend can yell with structured intent (info / feedback / blocked / ready). Wire a listener for OSC 9 / 99 / 777 terminal-notification sequences emitted from the agent shell, so backends that already speak that standard drive status without a bespoke wrapper. Becomes a third reliability channel alongside instructions and heartbeat (see `documentation/grilled-decisions.md` §2). Lays the groundwork for cross-backend pluggability without committing to it yet.
- **Claude Code hook integration.** `SessionStart` → `WORKING`, `Stop` → `READY` or `DONE`, hook into prompt submission to bump `UPDATED_AT`. Backend-specific; opt-in via config.
- **Event-log pane.** `agent-status` already appends to `~/.agent-control/logs/<slug>.log`; surface the last N lines per workspace in the cockpit.
- **fzf integration.** Use `fzf` when installed for repo selection in `agent-spawn`, blocked-agent picker in `agent-jump`, workspace selection in `agent-teardown`.
- **`agent-pr <slug>`.** Push the agent branch and open a PR per repo via `gh` or `git push -u`. Captures the harvest workflow once it's been done by hand enough times to know what's right.
- **PR status per workspace.** Surface each worktree's linked PR (open / draft / merged / changes-requested / failing-CI) in the dashboard, next to the branch. Source: `gh pr view --json state,number,reviewDecision,statusCheckRollup` per agent branch, cached with a short TTL so the watched dashboard render stays cheap; degrade to "no PR" when `gh` is missing or the branch is unpushed. Concrete payoff: a `READY` workspace whose PR is `MERGED` is the one-keystroke follow-up to `agent-teardown`; a `READY` workspace with `CHANGES_REQUESTED` is the obvious candidate to spawn a fixup agent against. Pairs naturally with `agent-pr <slug>` — that command writes the link, this one reads it back.
- **`agent-diff <slug>`.** Export diffs for every worktree to a known location for review.
- **`agent-refresh <slug>`.** Carefully designed fetch + rebase/merge with confirmation. Risky enough that it gets its own phase.
- **`.env` propagation.** Copy or template `.env` files from the canonical repo into the worktree if a per-repo rule says so.

---

## Speculative — Only if the file-based core proves itself

Don't build these until v1 + post-MVP have answered the dashboard-value question.

- **Rich TUI.** `textual` or `prompt_toolkit` migration with true ring charts for the quota pane, sortable status table, inline diff viewer.
- **Web dashboard.** A small HTTP frontend reading the same `~/.agent-control/` files. Only useful if you want to monitor agents from another device.
- **Cross-machine sync.** Push status files / quota snapshots to a shared store so the cockpit on machine A reflects agents running on machine B. Adds a daemon — explicitly excluded from v1.
- **Per-agent quota attribution.** Currently quota is global to the user; nothing tells you which agent burned the 5-hour window. If Claude exposes per-session usage later, attribute it.
- **Agent role abstractions.** Refinement vs. implementation vs. review distinctions. PRD §3.2 explicitly excluded these; reconsider only if the same role-shaped patterns keep recurring in practice.
- **Multi-user.** Currently single-user on a single box. Multi-user would require shared paths, locking, identity. Big enough to be its own product.

---

## Tracking

Day-to-day work breakdown lives in issues / tasks; this roadmap is the strategic shape. When in doubt about whether to build something now or later, ask: **does this help answer "is the dashboard surfacing blocked agents fast enough?"** If yes, it's in scope. If no, it waits.
