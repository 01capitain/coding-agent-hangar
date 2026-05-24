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

- [x] `hangar-watch` — render grouped statuses in priority order: BLOCKED → NEEDS_FEEDBACK → FAILED → STARTING_FAILED → READY → WORKING → STARTING → PAUSED → DONE. Compute "minutes since `UPDATED_AT`"; flag `WORKING` rows older than `AGENT_STALE_MINUTES` (default 30) as `[stale]`. Empty groups skipped. Pure read-only — no side effects, no bell. ANSI colors auto-disable on non-TTY or `--no-color`. Quota pane renders `unavailable` until Phase 3.
- [x] `hangar-checkin` — create / attach the `agents` tmux session; create / reuse the `cockpit` window with a layout that runs `watch -c -n 2 hangar-watch` in the main pane and a shell in a side pane. Idempotent.
- [x] `hangar-statusline` — print the compact one-liner `[B:n] [F:n] [R:n] [W:n]` (quota half appended once Phase 3 lands). Plain text — tmux `status-right` doesn't interpret ANSI through `#()`. Documented `set -g status-right` snippet in README.
- [x] Bell-on-transition decoupled from dashboard: `agent-mark-as-blocked` already rings on every call; `hangar-watch` stays purely a reader (no transition detection, no `last-render.json` side file).

**Exit criterion:** You can manually write a few status files, run `hangar-checkin`, see them grouped, and the tmux status line updates from any window. ✓

---

## Phase 3 — Quota integration

Verify the shared Claude quota half of the dashboard.

- [x] `hangar-quota-update` — read JSON from stdin, extract `rate_limits.{five_hour,seven_day}.{used_percentage,resets_at}` and `context_window.used_percentage`. Convert Unix timestamps to ISO 8601. Atomic write to `~/.agent-control/quotas/claude.json`. Tolerant of missing fields (only writes keys it could parse). Empty stdin is a no-op.
- [x] Dashboard quota pane — two-line per window layout (used bar + elapsed bar + reset countdown). Color the used bar by burn-delta (green ≤0, yellow ≤10, orange ≤25, red >25). Falls back to `unavailable` when the quota file is missing.
- [x] `scripts/claude-statusline` — bash wrapper for `~/.claude/settings.json` `statusLine.command`. Pipes the JSON into `hangar-quota-update`, then delegates to whatever script `HANGAR_STATUSLINE_RENDERER` points at (passthrough). Safe with no renderer configured.
- [x] Quota tests cover read/render/normalize without a live Claude session.

**Exit criterion:** With the statusline wrapper installed, the cockpit's quota pane updates whenever you use Claude Code. Removing the wrapper degrades the pane to `unavailable` without breaking the rest. ✓

Open items deferred from this phase:
- "Stale snapshot beyond a threshold" check: not implemented. ``load_snapshot`` returns whatever the on-disk file says; no max-age cliff. Decide once we have evidence that an old snapshot misleads more than it helps.
- Persisting `raw_available` for debugging: dropped. The normalized snapshot is small enough to interpret directly; keeping the raw payload doubles disk churn for no current consumer.

---

## Phase 4 — Workspace spawn (non-interactive)

Prove the worktree + tmux + AGENTS.md flow before adding the interactive UI.

- [x] `agent-spawn <slug> [repo...] --branch <name>` — non-interactive form.
  - Slug validated / normalized (`workspace.normalize_slug`, PRD §7.3).
  - Refuses if `~/agent-work/<slug>` already exists (interactive resume prompt comes in Phase 5).
  - For each repo: `git fetch --prune` in the canonical, then `git worktree add -b <branch> <workspace>/<repo> <base_branch>`. Branch name is **operator input**, same across every repo — see grilled-decisions §15 resolution.
  - Generates `AGENTS.md` from template; creates `CLAUDE.md` symlink.
  - Generates `.agent/metadata.env`, `.agent/HANDOFF.md`. No `prompt.md` — agent CLI opens to an empty conversation; operator's first message is the task.
  - Symlinks `.agent/status` → the status file path.
  - Per-repo `bootstrap` runs in background (detached `sh -c` with stdout/stderr to `~/.agent-control/logs/<slug>-<repo>-bootstrap.log`); the wrapper writes `STARTING_FAILED` if exit is non-zero. Status starts at `STARTING`.
  - Creates tmux window named after the slug with `$AGENT_COMMAND` pre-typed (no Enter). Switches to it.
- [x] Templates for `AGENTS.md` and `HANDOFF.md` covering status reporting rules, blocking rules, handoff expectations, slug + workspace + branch + repo paths.
- [x] Zero-repo workspaces: `agent-spawn <slug> [--yes]` creates a workspace dir + tmux window + AGENTS.md, no worktrees, no bootstrap. Confirms interactively when stdin is a tty; `--yes` skips the prompt.

**Exit criterion:** End-to-end: `agent-spawn permissions-refactor backend frontend --branch feature/perms` creates the workspace, worktrees materialize on the supplied branch, tmux window opens with the agent command pre-typed, bootstrap runs in background, status is `STARTING`. ✓ (Smoke-validated 2026-05-24.)

Deferred from this phase (live in Phase 5 / later):
- Repo-local `AGENTS.md` in each worktree pointing back to workspace-level — not yet built; can be added cheaply if Claude's per-worktree context lookup misses the workspace-level file.
- Resume / suffix / abort prompts on existing slug.

---

## Phase 5 — Workspace spawn (interactive) and resume

Make spawning ergonomic.

- [x] `agent-spawn` with no args — prompts for slug, shows the curated repo list sorted by `default: true` hint with **nothing pre-checked**, accepts comma-separated multi-select, then prompts for branch when any repo is selected. Re-prompts on invalid picker input.
- [x] Resume prompt when slug exists: **resume** (reattach window, preserve files, no bootstrap) / **suffix** (`<slug>-2`, `-3`, …) / **abort**. Non-interactive callers pick the same behavior with `--resume` / `--suffix`; bare collision keeps erroring with a message that points at both flags.
- [x] Slug normalization warning — when the raw slug doesn't equal the normalized form, print `slug normalized to '<x>'` on stderr so the operator sees the name that will be used.
- [x] Branch existence check before `git worktree add`. Non-interactive: hard error naming the colliding repo. Interactive: per-repo prompt offering reuse of the existing branch (no `-b`); declining aborts.

**Exit criterion:** A new user can run `agent-spawn`, answer two prompts, and end up in a working workspace. ✓ (163 tests passing; smoke-validated 2026-05-24.)

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
