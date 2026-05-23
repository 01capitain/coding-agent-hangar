# Agent Hangar — Grilled Decisions

Working name for the project: **Agent Hangar** (repo stays `coding-agent-dashboard`).

This document captures the decisions made while stress-testing the original `initial-prd.md` and `initial-implementation-plan.md` documents. It is the bridge between the PRD/plan and the upcoming `README.md` + `ROADMAP.md`. Where this document disagrees with the original PRD/plan, **this document wins**.

The grilling walked the design tree top-down: problem framing → invariants → feature shape → implementation choices. Each section below records the decision, the reasoning, and the concrete consequence.

---

## 1. Problem framing — dashboard-first, not push-first

**Decision.** The dashboard is the primary surface in v1. Push notifications (toast / `notify-send` / sound beyond the terminal bell) are explicitly deferred.

**Why.** The user's stated bottleneck is *"I am actively working but don't recognize the need to switch tabs"* — not "I am AFK." That is a glanceability problem, not a paging problem. Build the dashboard, prove it adds value, then layer push on once the value is established. Inverting that order builds a notification system whose value can't be measured against a baseline.

**Consequence.** The dashboard must be visible from peripheral vision in any tmux window, not just the cockpit. See §8.

---

## 2. Status reporting reliability — instructions + heartbeat

**Decision.** v1 ships with instruction-based status reporting (rules in `AGENTS.md` and the generated prompt) **plus** a heartbeat / staleness check. Backend-specific hooks (Claude Code `SessionStart` / `Stop`) and output-scraping wrappers are deferred.

**Why.** The dashboard is worthless if agents don't update status. Risk 11.1 in the PRD acknowledged this but mitigated only with hope. Instructions catch the common path; the heartbeat catches the abandonment case (`WORKING` with no update for N minutes → visually flagged as `STALE`). This is cheap, backend-agnostic, and lets us measure how often instructions actually fail before investing in hooks.

**Consequence.**
- The PRD's "stale detection" is promoted from v1.1 into v1 MVP.
- `UPDATED_AT` must be machine-parseable (it already is in the PRD format).
- Dashboard computes `minutes since UPDATED_AT` for any `WORKING` row.
- Default stale threshold: 30 minutes, configurable via `AGENT_STALE_MINUTES`.
- Stale rows render with a yellow `[stale]` tag, not promoted to BLOCKED — they're a hint, not a state.

---

## 3. Agent backend — Claude-first, pluggable-ready

**Decision.** v1 supports Claude Code as the only documented backend. `$AGENT_COMMAND` stays configurable (default `claude`) so swapping is a one-line edit, but no Codex/Cursor-specific code paths are added until they are actually used. Workspace instructions live in **`AGENTS.md`** as the file, with **`CLAUDE.md`** as a symlink pointing to it.

**Why.** Several pillars of the design (quota tracking via statusline, future hook-based reliability) are de facto Claude-only. Truly pluggable from day one means paying abstraction cost for one user with one primary backend. But hard-coding `claude` everywhere makes swapping painful later. Claude-first with light scaffolding is the honest middle path.

**Consequence.**
- `~/agent-work/<slug>/AGENTS.md` is the real file.
- `~/agent-work/<slug>/CLAUDE.md` is a symlink to `AGENTS.md` so Claude Code's recursive lookup picks it up.
- Quota integration is documented as a Claude-only feature; the pane shows `unavailable` gracefully on other backends.
- The PRD's open question §12 ("which agent CLI should be the default") is resolved: `claude`.

---

## 4. Quota tracking is real, not aspirational

**Verified.** Claude Code's statusline JSON does expose:

- `rate_limits.five_hour.used_percentage` and `rate_limits.five_hour.resets_at`
- `rate_limits.seven_day.used_percentage` and `rate_limits.seven_day.resets_at`
- `context_window.used_percentage`

The user's existing `~/.claude/statusline-command.sh` already reads them. The PRD's design is viable, with two corrections to bake in:

- Field is `resets_at` (not `reset_at`).
- Value is a **Unix timestamp**, not an ISO 8601 string. Normalize to ISO on write.

**Source.** `~/.claude/statusline-command.sh` is wired as the Claude Code statusline. `hangar-quota-update` will be invoked from a wrapper that the user adds to that script (or replaces it with). The wrapper pipes the JSON to `hangar-quota-update` and continues to render the user's existing statusline output.

---

## 5. Worktree bootstrap — per-repo command, runs in background during STARTING

**Decision.** The repos config declares a `bootstrap` command per repo (e.g., `npm ci`, `pnpm install --frozen-lockfile`). `agent-spawn` runs it in the background after creating each worktree. Workspace status stays `STARTING` until all bootstraps complete; transitions to `READY_TO_START` (or directly hands off to the user) afterward.

**Why.** Worktrees share `.git` but not `node_modules`, build caches, or `.env` files. Without bootstrap, every spawn loses 2-5 minutes of agent time to `npm install`. The PRD's "no automatic dependency installation" non-goal didn't solve this — it punted. A declarative per-repo command is the cheapest fix that doesn't pollute canonical repos.

**Consequence.**
- Bootstrap stdout/stderr captured to `~/.agent-control/logs/<slug>-<repo>-bootstrap.log` so failures are not silent.
- Bootstrap failure: the workspace transitions to `STARTING_FAILED` (visible in dashboard, not blocking). The user investigates the log.
- Status semantics: while any bootstrap is running, `STATE=STARTING`. Cleared by `agent-spawn` once all complete; the agent then takes over.
- No automatic `.env` file copy in v1 — document it as a manual step. Re-evaluate if it becomes a constant friction point.

---

## 6. Workspace location — configurable, default `~/agent-work`

**Decision.** `AGENT_WORK_HOME` stays as the PRD says, default `~/agent-work/`. The pattern of using `/var/www/agent-work/` (so nginx vhosts can be wired up later) is documented in the README as an opt-in for users who need it.

**Why.** Most agent work is "edit code + run unit tests + open PR." Integration testing through nginx / Docker is the user's job. Co-locating workspaces under `/var/www/` adds setup complexity that's only worth it for users who actually need wildcard vhosts. Keep the default clean, document the opt-in.

**Consequence.**
- Canonical repo paths in `repos.yaml` are absolute (e.g., `/var/www/backend-core-nestjs`) and the user controls them.
- The README's setup section explains both layouts.
- Bootstrap commands run with `cwd` = the worktree path; absolute path references in the user's project configs (logs, uploads) are their own problem.

---

## 7. Repo config — manually curated YAML

**Decision.** Repo presets live in `~/.agent-control/config/repos.yaml`, a manually curated YAML file. Schema is a list of repos with key, name, path, default-hint, bootstrap, base-branch.

**Example.**

```yaml
# ~/.agent-control/config/repos.yaml
repos:
  - key: backend
    name: backend-core-nestjs
    path: /var/www/backend-core-nestjs
    default: true        # sort hint, NOT a pre-check
    bootstrap: npm ci
    base_branch: origin/main

  - key: frontend
    name: frontend-hotelkit-web
    path: /var/www/frontend-hotelkit-web
    default: true
    bootstrap: npm ci

  - key: nxmono
    name: nx-monorepo
    path: /var/www/nx-monorepo
    bootstrap: pnpm install --frozen-lockfile

  - key: mobile
    name: hotelkit-react-native
    path: /var/www/hotelkit-react-native
    bootstrap: npm ci

  - key: e2e
    name: playwright-e2e-tests
    path: /var/www/playwright-e2e-tests
    bootstrap: npm ci
```

**Why.** Flat env vars (`REPO_X_NAME`, `REPO_X_PATH`, etc.) get cramped at 9+ repos. YAML is more readable; manual curation keeps it explicit (no surprise auto-discovery of random `.git` directories).

**Consequence.**
- New dependency: `PyYAML`. `hangar-init` checks for it and prints the install command if missing (`apt install python3-yaml` on Debian/Ubuntu, or `pip install pyyaml`).
- A Python helper (used internally by the spawn flow) loads the YAML and emits shell-evaluable values for any bash glue that needs them.
- `default: true` is a **sort hint** only — repos with `default: true` sort to the top of the spawn list, but **nothing is pre-checked**. See §9.

---

## 8. Dashboard visibility — cockpit window + tmux status line summary

**Decision.** Two surfaces, both first-class in v1:

1. **Cockpit tmux window** — the full dashboard (PRD-as-written): grouped statuses, quota pane, recent log lines. Reached via `hangar-cockpit` (creates/attaches the `agents` session and the `cockpit` window).
2. **Tmux status line snippet** — a compact summary visible from EVERY tmux window. Format roughly:

   ```text
   [B:1] [F:0] [R:2] [W:3]  |  5h:36%/24%  7d:69%/31%
   ```

   B = BLOCKED, F = NEEDS_FEEDBACK, R = READY, W = WORKING. Colors:
   - red for non-zero B or F
   - yellow for R or for quota burn-delta in the "risk" band (10–25)
   - green when nothing demands attention
   - red for quota burn-delta in the "high risk" band (>25)

**Why.** The user explicitly said "I am actively working but don't recognize the need to switch tabs." A cockpit-window-only design fails that test — you have to *choose* to look. A status-line summary catches peripheral vision in every window without requiring a context switch. The cockpit window stays as the rich detail view when something interesting happens.

**Consequence.**
- A new command, `hangar-tmux-status`, prints the formatted status line; users paste a snippet into their `~/.tmux.conf`:

  ```tmux
  set -g status-interval 15
  set -g status-right '#(hangar-tmux-status) '
  ```

  This composes with existing status-right content rather than replacing it. The README documents the snippet.
- The tmux bell (`tmux display-message` + `\a`) fires only when the **blocked count increases** from one refresh to the next (transition, not steady-state). Otherwise the dashboard is silent.
- The cockpit window remains the rich view; the status line is the trigger.

---

## 9. Workspace shape — mix of multi-repo, single-repo, and zero-repo

**Decision.** Workspace identity is tied to the **slug**, not to any specific set of repos. A workspace can have 0, 1, or N repos. `agent-spawn` presents the curated repo list with **none pre-selected**; the user makes a deliberate choice every time. `default: true` in the YAML is a sort hint (those repos appear at the top), not a pre-check.

**Why.** Real tasks don't cluster cleanly into "always backend + frontend." Single-repo bug fixes are common, multi-repo features happen, and *planning* / *PRD* / *refinement* agents may want a workspace with no worktrees at all (just a tmux window + AGENTS.md for the agent to think in). The PRD's example pre-checking backend + frontend is mis-tuned.

**Consequence.**
- Zero-repo workspaces are supported: workspace dir is created, `AGENTS.md` and `.agent/` generated, tmux window opens at the workspace root, no worktree creation, no bootstrap. Status file follows the same lifecycle.
- The interactive spawn flow shows repos sorted: default-hint first, alphabetical within each group.
- Non-interactive form (`agent-spawn <slug> <repo>...`) stays as PRD-spec'd; passing zero repos creates a zero-repo workspace explicitly.
- `agent-spawn <slug>` with no repos and no `--no-repos` flag should confirm "create zero-repo workspace?" to avoid foot-guns.

---

## 10. Workspace lifecycle — prompt on resume, guided cleanup

**Decision (resume).** When `agent-spawn` is run with a slug whose workspace already exists, it prompts the user interactively:

1. **Resume** — switch to the existing tmux window (recreating it if killed), preserve all `.agent/` files (no clobbering of HANDOFF / prompt / AGENTS), do not re-run bootstrap. Status stays whatever it was.
2. **Suffix** — create `<slug>-2`, `<slug>-3`, etc.
3. **Abort.**

**Decision (cleanup).** `agent-clean <slug>` is a **guided interactive checklist**, not automation. It walks the user through cleanup, refusing dangerous moves:

1. Show workspace path, list of worktrees, current statuses (`git status -sb` per worktree).
2. Show whether the agent branch was merged into base branch on origin.
3. Show uncommitted changes (refuse to proceed without `--force` if any).
4. Walk the user through prompts: "PR opened? [y/N]", "PR merged? [y/N]", "OK to remove worktree at X? [y/N]", "OK to delete agent branch agent/<slug>/<repo>? [y/N]".
5. On confirmation, run `git worktree remove`, delete branches, archive the status file to `~/.agent-control/status/archive/<slug>-<timestamp>.status`, remove the workspace dir.

No auto-cleanup based on age or status in v1. The principle is: **collect evidence of the real cleanup steps before committing to automation.**

**Why.** Worktrees aren't supposed to outlive the work they hold. But automating cleanup before you know the real workflow risks deleting unmerged work or losing context. A guided checklist captures the human-in-the-loop reality and produces the evidence base for later automation.

**Consequence.**
- `agent-close <slug>` (PRD §11.2) becomes a lighter operation: set status to `DONE` or `PAUSED`, optionally kill the tmux window. Does NOT remove worktrees. Use `agent-clean` for that.
- Slug uniqueness scope: **active only**. A cleaned-up slug is available for reuse (archived status file lives in `archive/` so no name collision).
- Atomic status writes (temp file + rename) prevent partial writes during concurrent updates.

---

## 11. Quota rendering — two lines per window, reset on right

**Decision.** Cockpit quota pane uses two lines per window: usage bar on top, elapsed bar below, with reset countdown right-aligned on the usage line.

```text
USAGE QUOTAS (Claude, shared)

5 HOUR
used    ███████░░░░░░░░░░░ 36%             reset in 3h 47m
elapsed █████░░░░░░░░░░░░░ 24%

7 DAY
used    ██████████████░░░░ 69%             reset in 4d 18h
elapsed ██████░░░░░░░░░░░░ 31%
```

Color encodes risk:
- usage bar **green** when burn-delta (used − elapsed) ≤ 0
- **yellow** when 0 < delta ≤ 10
- **orange** when 10 < delta ≤ 25
- **red** when delta > 25

No separate "risk: high risk" text label — the color carries it. The two-bar comparison communicates ahead/behind visually.

**Why.** The user wants the layered view (used vs elapsed) so the comparison is explicit, and prefers to defer fancier rendering (rings, TUI) until the integration proves itself useful. Tmux status line compresses the same data into `5h:36%/24% 7d:69%/31%` because space is tight there.

**Consequence.**
- The dashboard renderer (in Python — see §13) computes burn-delta and picks the color per bar.
- Risk thresholds (≤0 / ≤10 / ≤25 / >25) are constants in the code; refactor to config only if they need to vary per environment.
- If `window_started_at` is missing, infer from `resets_at - 5h` / `resets_at - 7d` as the PRD says.

---

## 12. Project name — Agent Hangar

**Decision.** Product name throughout README/ROADMAP: **Agent Hangar**. Repo name stays `coding-agent-dashboard` for now. Commands split between `agent-*` (per-agent) and `hangar-*` (hangar-level) prefixes — see the amendment below. Filesystem root stays `~/.agent-control/`.

**Why.** "Cockpit" was the PRD's working name; "Hangar" reads better as a place where multiple craft (agents) live, prepare, and launch. The light inconsistency between product name and repo name lives only in the README intro; everything else uses straightforward language (workspace, spawn, dashboard, jump).

**Consequence.**
- README opens with: "Agent Hangar (repo: `coding-agent-dashboard`) is a local control plane for managing parallel AI coding agents…"
- The Hangar metaphor stays light. We do **not** rename `agent-spawn` to `agent-launch` or `workspace` to `bay`. Command names stay literal and discoverable.
- Renaming the git repo to `agent-hangar` is a cheap follow-up; not blocking on it.

**Amendment (CLI prefix split).** The command prefix is **not** a single `agent-*` family. It splits by scope:

- **`agent-*`** — operates on a single agent / workspace. The slug is the discriminator. Members: `agent-spawn`, `agent-status`, `agent-blocked`, `agent-jump`, `agent-close`, `agent-clean`.
- **`hangar-*`** — operates on the hangar itself, not on any one agent. Members: `hangar-init`, `hangar-dashboard`, `hangar-cockpit`, `hangar-list`, `hangar-tmux-status`, `hangar-quota-update`.

The trigger was `agent-init`: it reads as "initialize an agent" but actually initializes the control directory at `~/.agent-control/`. Once the principle was identified, the same audit applied to every meta command — anything operating on the whole control plane (the dashboard, the cockpit window, the aggregate list, the tmux status emitter, the shared quota writer) got the `hangar-` prefix. The split should make a command's scope obvious at first sight.

**Open ambiguity within `hangar-*`.** Several of the global commands have overlapping-sounding names (`hangar-dashboard` vs `hangar-cockpit` vs `hangar-list`) — these are *not* synonyms and the difference must be tightened by docstrings + the README's command table. Rough rule today: `hangar-cockpit` = the tmux window; `hangar-dashboard` = the rich content rendered inside that window (also runnable one-shot); `hangar-list` = the plain ASCII table for scripting / debug. Revisit names if real users keep picking wrong.

---

## 13. Implementation language — Python-first, bash glue only

**Decision.** Python is the primary implementation language. Bash is used only for thin glue (tmux invocations, the claude-statusline wrapper, perhaps an entrypoint shim if needed).

**Why.** Python-first makes the system easier to maintain, easier to extend, easier to grow into a richer TUI later (textual / rich / prompt_toolkit), and reduces the wheel-reinvention tax of JSON/YAML/timestamp/string-formatting in shell. The user accepted the trade-off against shell-first "inspect with cat" simplicity.

**Consequence.**
- Project layout:
  ```text
  /var/www/coding-agent-dashboard/
  ├── pyproject.toml
  ├── README.md
  ├── ROADMAP.md
  ├── LICENSE
  ├── src/
  │   └── agent_hangar/
  │       ├── __init__.py
  │       ├── cli.py            # argparse entrypoints
  │       ├── spawn.py
  │       ├── status.py
  │       ├── dashboard.py
  │       ├── quota.py
  │       ├── tmux.py
  │       ├── repos.py          # YAML loading
  │       ├── workspace.py      # path layout, metadata, AGENTS.md generation
  │       ├── templates/        # AGENTS.md, HANDOFF.md, prompt.md templates
  │       └── clean.py
  ├── scripts/
  │   └── claude-statusline     # bash wrapper that pipes JSON to hangar-quota-update
  ├── tests/
  └── documentation/
      ├── initial-prd.md
      ├── initial-implementation-plan.md
      └── grilled-decisions.md   # this file
  ```
- `pyproject.toml` declares console scripts:
  ```toml
  [project.scripts]
  hangar-init         = "agent_hangar.cli:init"
  hangar-dashboard    = "agent_hangar.cli:dashboard"
  hangar-cockpit      = "agent_hangar.cli:cockpit"
  hangar-list         = "agent_hangar.cli:list_workspaces"
  hangar-tmux-status  = "agent_hangar.cli:tmux_status"
  hangar-quota-update = "agent_hangar.cli:quota_update"
  agent-spawn         = "agent_hangar.cli:spawn"
  agent-status        = "agent_hangar.cli:status"
  agent-blocked       = "agent_hangar.cli:blocked"
  agent-jump          = "agent_hangar.cli:jump"
  agent-close         = "agent_hangar.cli:close"
  agent-clean         = "agent_hangar.cli:clean"
  ```
- Install via `pipx install .` (preferred — isolated) or `pip install --user -e .` (editable for development).
- Dependencies: `PyYAML`. Maybe `rich` for the dashboard renderer; evaluate once we have a v1 to look at — pure ANSI may be sufficient.
- Status files stay shell-source-compatible (`KEY="value"`). Atomic writes via temp file + `os.replace`.
- Tmux interactions use `subprocess.run(["tmux", ...], check=True)` rather than shelling out to a bash helper.

---

## 14. v1 scope (Definition of Done)

The v1 MVP ships when the following all work end-to-end:

1. `hangar-init` creates `~/.agent-control/` and seeds `repos.yaml`, validates PyYAML is installed.
2. `agent-spawn <slug> <repo>...` creates a workspace, worktrees, `AGENTS.md` + `CLAUDE.md` symlink, `.agent/metadata.env`, `.agent/HANDOFF.md`, `.agent/prompt.md`, and the tmux window. Bootstrap runs in background.
3. `agent-spawn` interactive mode shows the curated repo list with nothing pre-selected, sorted by `default: true` hint.
4. `agent-spawn` with an existing slug prompts resume / suffix / abort.
5. `agent-status` and `agent-blocked` update the slug's status file atomically.
6. `hangar-dashboard` renders grouped statuses + quota pane in the cockpit window. Stale `WORKING` rows are flagged.
7. `hangar-tmux-status` emits the compact one-line summary for the tmux status bar.
8. `hangar-cockpit` creates / attaches the `agents` session and `cockpit` window with the dashboard running in `watch`.
9. `agent-jump <slug|blocked|feedback>` switches tmux. Multi-match: interactive list.
10. `hangar-quota-update` reads Claude statusline JSON from stdin and writes normalized `~/.agent-control/quotas/claude.json`. Graceful on missing fields.
11. The cockpit dashboard still renders when quota data is missing.
12. `agent-clean <slug>` walks the user through guided cleanup, refusing to remove uncommitted work without `--force`.

Explicitly **deferred** beyond v1:

- Push / desktop notifications.
- Claude Code hook integration for auto-status.
- Output-scraping wrappers.
- `agent-close` (light close, not destructive cleanup — easy add but lower priority than `agent-clean`).
- `fzf` integration for selection.
- Event-log pane.
- `agent-diff`, `agent-refresh`, `agent-pr`.
- True TUI / ring charts.
- Automatic dependency installation beyond the declared `bootstrap` command.
- Automatic `.env` file propagation.
- Auto-cleanup of stale workspaces.

---

## 15. Open items intentionally not decided

These are real questions deferred until v1 produces evidence:

- Exact stale threshold (30 min default — may need tuning per backend).
- Whether the cockpit quota pane should grow a sparkline of historical burn-delta.
- Whether the agent branch naming `agent/<slug>/<repo>` is PR-friendly enough or should be `agent/<slug>` (one branch per repo, but the slug is the discriminator).
- Whether to keep raw Claude statusline payloads for debugging in `~/.agent-control/quotas/raw/`.
- Whether `agent-spawn` should emit a task-description prompt the user fills in during interactive flow, or stay PRD-as-written (just open the workspace).
- **Port discovery → agent feedback loop.** Listening ports per worktree (cmux surfaces these passively in its sidebar) could be a dashboard-only column, but the higher-value shape is feeding the discovered port into the agent's context so it can validate its own work — run integration tests, smoke endpoints, hit the dev server it just modified. Postponed until we have direct experience of how agents coordinate frontend ↔ backend; revisit when an agent first has to ask "what port is the backend on?" Open sub-questions: where the agent reads the port from (file in `.agent/`, env var, prompt injection at spawn time, on-demand CLI), and when discovery runs (one-shot post-bootstrap vs. live polling).
- **Agent session resume contract.** `claude --resume <session_id>` (and per-backend equivalents) is the right escape hatch for the case tmux does NOT cover: the agent process is gone (crash, reboot, `Ctrl-D`) but the conversation lives in the backend's session store. The session ID is **agent-scoped, not repository-scoped** — it has nothing to do with `repos.yaml`. Natural home is per-slug, probably `.agent/metadata.env` (or a sibling `.agent/sessions.json` if multiple concurrent agents per workspace ever becomes a thing). Population would come from a backend hook; for Claude Code the session ID is already exposed via the statusline JSON, so the `hangar-quota-update` wrapper is one plausible entry point. Skip until the first lost conversation actually stings.
