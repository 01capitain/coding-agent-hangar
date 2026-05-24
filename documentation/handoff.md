# Session handoff

Read this first when picking up work after a break. The two authoritative
docs are still `README.md` (user-facing) and `documentation/grilled-decisions.md`
(design decisions). This file is the **per-session bridge**: where we left
off, what was decided that day, and what NOT to redo.

Last updated: 2026-05-24

---

## Status at a glance

- **Phases 0, 1, 2, 3, 4 complete.** Phases 5–7 ahead.
- **136 tests passing**, ruff clean. Working tree had multiple Phase-3 /
  Phase-4 commits at end of session — push status is whatever git says
  when you read this.
- Local validation done end-to-end:
  - Phases 1–2 against hand-written status files (`hangar-setup` →
    `agent-status` / `agent-mark-as-blocked` → `hangar-watch` /
    `agent-list` / `hangar-statusline`).
  - Phase 3 against a temp `AGENT_CONTROL_HOME` smoke run: piped a fake
    Claude statusline JSON through `hangar-quota-update`, saw the rendered
    `hangar-watch` pane (5h + 7d bars, reset countdown, context line) and
    the compact `5h:U%/E% 7d:U%/E%` in `hangar-statusline`. Also exercised
    `scripts/claude-statusline` with and without `HANGAR_STATUSLINE_RENDERER`.
  - Phase 4 against a tmp git canonical + tmp control + tmp work home:
    `agent-spawn "Real Feature" demo --branch feature/x` produces the
    workspace (`real-feature`), worktree on `feature/x`, AGENTS.md with
    the branch baked in, metadata.env with `BRANCH="feature/x"`, status
    `STARTING`, dashboard renders. The tmux step bails outside a real
    tmux session (expected: `os.execvp("tmux attach")` needs a tty);
    success message prints before the tmux call so the user always sees
    spawn confirmed.

## How to pick up cold

```bash
cd /Users/stephan/Documents/Projects/coding-agent-hangar
source .venv/bin/activate     # or `pipx install -e .` for global commands
ruff check src tests
pytest
```

All three should be silent-on-success. Then look at:

1. `documentation/grilled-decisions.md` — authoritative when it disagrees
   with PRD/plan. **§12 is the canonical CLI prefix decision** (see "Recent
   renames" below for what changed in the last session).
2. `ROADMAP.md` — checkboxes show what's done; unchecked items are work.
3. This file's "Next: Phase 3" section.

## What's done

| Phase | Status | Commands shipped | Tests |
|---|---|---|---|
| 0 — Skeleton | ✅ | (none — `pyproject`, package, tests/, CI) | 13 |
| 1 — Status reporting | ✅ | `hangar-setup`, `agent-status`, `agent-mark-as-blocked`, `agent-list` | 38 |
| 2 — Dashboard + cockpit | ✅ | `hangar-watch`, `hangar-checkin`, `hangar-statusline` | 61 |
| 3 — Quota | ✅ | `hangar-quota-update` (real), quota pane + compact fragment, `scripts/claude-statusline` | 90 |
| 4 — `agent-spawn` non-interactive | ✅ | `agent-spawn <slug> [repos...] --branch <name>` + scaffolding + worktree + background bootstrap + tmux window | 136 |
| 5 — `agent-spawn` interactive + resume | ⏳ Next | curated picker, resume/suffix/abort | — |
| 6 — `agent-jump` | ⏳ | `<slug>`/`blocked`/`feedback` | — |
| 7 — Done signal + teardown | ⏳ | `agent-mark-done`, `agent-teardown` | — |

`agent-mark-done` is a stub but its shape is fully decided: it mirrors
`agent-mark-as-blocked` (state + bell + tmux display-message). Implementation
is essentially copy-paste in Phase 7.

## What Phase 3 shipped

The plumbing landed roughly as planned — only one deviation from the
session-start spec, called out at the bottom.

- `src/agent_hangar/quota.py` now exports `QuotaSnapshot`, `QuotaWindow`,
  `load_snapshot`, `normalize_payload`, `write_snapshot`, `render_pane`,
  `render_compact`. Snapshot shape on disk:
  ```json
  {
    "updated_at": "...Z",
    "context_window": { "used_percentage": <float> },
    "five_hour": { "used_percentage": <float>, "resets_at": "...Z" },
    "seven_day": { "used_percentage": <float>, "resets_at": "...Z" }
  }
  ```
  Any of the three data keys may be absent; rendering degrades per-key.
- `cli.quota_update()` reads stdin, runs `normalize_payload`, atomic-writes
  via `quota.write_snapshot`. Empty stdin is a clean no-op. Invalid JSON
  or non-object payloads exit 2 with a one-line error.
- `scripts/claude-statusline` is the drop-in wrapper. Contract: read stdin
  once, forward a copy to `hangar-quota-update` (best-effort, errors
  swallowed), then call `$HANGAR_STATUSLINE_RENDERER` if set with the same
  stdin. With no renderer set the wrapper still updates the snapshot but
  prints nothing — Claude's statusline goes blank. Pointing
  `HANGAR_STATUSLINE_RENDERER` at the user's existing
  `~/.claude/statusline-command.sh` preserves their current statusline.
- `ansi.ORANGE` added (256-color, `38;5;208`) to support the new burn-delta
  scale. Burn thresholds match §11: green ≤0, yellow ≤10, orange ≤25, red >25.

### Deviation: env-var wrapper instead of in-place replacement

Original spec said the wrapper "renders the user's existing statusline
output unchanged." Two ways to do that: edit the user's
`~/.claude/statusline-command.sh` in place (personal-machine wiring; see
the no-personal-integrations memory), or compose by env-var pointer. We
went with the env-var (`HANGAR_STATUSLINE_RENDERER`) so the shipped wrapper
is generic and doesn't assume any particular renderer path. README still
needs the snippet that tells users to add that env var + repoint
`statusLine.command`; that's the only doc gap remaining for Phase 3.

### Deferred sub-items (from the original Phase 3 todo list)

- **"Stale beyond a threshold"** quota pane fallback: not built. The pane
  shows whatever is on disk. Re-evaluate if a stuck snapshot ever misleads
  more than it helps.
- **`raw_available` for debugging**: dropped. The normalized snapshot is
  small enough to read by eye; the raw payload would just double churn.

## Phase 4 — what shipped

Now complete. Foundation + subprocess half + integration.

### CLI surface

```
agent-spawn <slug> [repo1 repo2 ...] --branch <name>
agent-spawn <slug> --yes           # zero-repo planning workspace
```

Slug is normalized per PRD §7.3. ``--branch`` is required when any
repos are passed; same branch name applies across every repo. ``--yes``
skips the zero-repo confirmation prompt (otherwise stdin gets a y/N).

### Modules

- `workspace.py` — `normalize_slug`, `layout_for`, `prepare_skeleton`,
  `WorkspaceLayout`. Branch flows through as an optional kwarg; recorded
  in `metadata.env` as `BRANCH="..."` and substituted into AGENTS.md.
- `repos.py` — `load_repos()` parses `repos.yaml` into typed `Repo`
  dataclasses (key, name, path, default, bootstrap, base_branch).
  `lookup(repos, key)` for cli.spawn's repo resolution.
- `spawn.py` — `create_worktrees(layout, repos, branch)` is synchronous
  with `check`-style git error handling. `run_bootstraps(layout, repos)`
  fires one detached `sh -c` per repo; the shell script writes
  `STARTING_FAILED` via `agent-status` on non-zero exit so the dashboard
  reflects bootstrap failure without the parent polling.
- `tmux.py` — added `ensure_workspace_window` + `open_workspace_window`.
  New window named after the slug, `cwd` set to workspace dir,
  `$AGENT_COMMAND` pre-typed via `send-keys` without trailing `Enter`.
- `cli.spawn` — orchestrates: normalize_slug → resolve repos →
  zero-repo confirm → prepare_skeleton → create_worktrees → 
  run_bootstraps → STARTING status row → open_workspace_window. Prints
  the success line BEFORE the tmux call (because `focus()` `execvp`s
  outside an existing tmux session — anything after that exec is lost
  to the user).

### Templates

- `AGENTS.md.tmpl` — workspace context, status-reporting table,
  blocking vs NEEDS_FEEDBACK rules, git rules, branch line (`Branch:
  <name> — same name across every repo`).
- `HANDOFF.md.tmpl` — section scaffolds the agent maintains (Goal /
  Current status / Files changed / Commands run / Test results / Open
  questions / Next steps / Risks).
- **No `prompt.md`** — agent CLI opens to an empty conversation; the
  operator's first message IS the task.

### Tests

136 total. New in Phase 4:
- `tests/test_workspace.py` — slug normalization, layout, skeleton
  creation, BRANCH metadata, zero-repo planning case.
- `tests/test_repos.py` — happy-path load, missing file, duplicate
  keys, schema validation, `lookup`.
- `tests/test_spawn.py` — `create_worktrees` against a real tmp git
  canonical (via `tmp_canonical_repo` fixture in `conftest.py`);
  `run_bootstraps` driven through an injected spawner so the shell
  script is asserted without firing `npm ci`.
- `tests/test_tmux.py` — `open_workspace_window` send-keys command
  asserted, critically `"Enter" not in send.args`.
- `tests/test_cli_phase4.py` — end-to-end integration: slug normalize,
  branch threading, zero-repo confirm + abort, --yes, unknown repo
  key, existing workspace clobber refusal, no-setup error.

### Smoke (manual, 2026-05-24)

Built a tmp git canonical + tmp control + tmp work home; ran
`agent-spawn "Real Feature" demo --branch feature/x`. Result:

- Workspace at `<work>/real-feature` with AGENTS.md, CLAUDE.md → AGENTS.md
  symlink, `.agent/HANDOFF.md`, `.agent/metadata.env` (`BRANCH="feature/x"`).
- Git worktree at `<work>/real-feature/demo-repo` on branch `feature/x`.
- Status file at STARTING; `hangar-watch` renders it.
- Tmux step bailed (no tty in non-interactive shell, expected); cli
  prints the success message BEFORE the tmux call so users always see
  `[real-feature] STARTING at <path>` even if attach fails.

## Next: Phase 5 (interactive `agent-spawn` + resume)

Spec lives in `ROADMAP.md` Phase 5. Concrete subtasks:

1. **Interactive flow when args omitted.** `agent-spawn` (no args) should:
   prompt for slug, prompt for branch (required if any repos selected),
   show a multi-select repo picker sorted by `default: true` first, no
   pre-checks. Use `input()` and a simple text picker — fzf is Post-MVP
   (`grilled-decisions.md` §15 / ROADMAP).
2. **Resume / suffix / abort on existing slug.** Today the non-interactive
   path errors with "workspace directory already exists" (see
   `workspace.prepare_skeleton`). Replace that error with a prompt:
   resume (reuse existing dir + reopen tmux window + don't re-bootstrap)
   / suffix (`<slug>-2`, `<slug>-3`, …) / abort. Non-interactive
   `agent-spawn` keeps erroring unless `--resume` / `--suffix` is passed
   explicitly — interactive mode is when prompts make sense.
3. **Branch existence check** before `git worktree add` to give a clear
   error if the branch already exists in any selected canonical (would
   collide with `-b <branch>`). Bonus: offer to use existing branch
   without `-b` if the user confirms.
4. **Slug normalization warning.** When the user-supplied raw slug
   doesn't equal the normalized form, print "normalized to '<x>'" so
   they see what name will be used.

Tests follow the Phase-4 pattern: drive `input()` via `io.StringIO`,
keep the tmp-git-repo fixture for the worktree work.

All in `grilled-decisions.md`. Short version:

- **CLI prefix split by domain, not arity** (§12 amendment, revised):
  `agent-*` = about agents one or many (includes `agent-list`);
  `hangar-*` = hangar infrastructure (setup, monitoring stations, plumbing).
  This was rewritten mid-session — the earlier "by arity" framing is wrong.
- **Verb-clear names** for state transitions: `agent-mark-as-blocked` and
  `agent-mark-done` are siblings. PAUSED uses generic `agent-status`; no
  dedicated wrapper.
- **No `agent-close`.** It was redundant with `agent-status` + tmux nicety.
  Dropped, not renamed.
- **No `HANGAR_SYNC_REPOS_LIST` or sync-repos integration in code.**
  That was a personal-machine one-shot, not permanent.
- **`hangar-watch` is purely a reader.** No bell. No state side-files. No
  transition detection. Bell is `agent-mark-as-blocked`'s job, period.
- **ANSI only**, no `rich` dep (§13). Statusline is plain text — tmux's
  `status-right` doesn't pass ANSI through `#()`.
- **Push notifications stay Post-MVP** (§1). v1 attention model is bell +
  tmux statusline + cockpit window. Reconsider only when the empirical
  signal (bell + statusline insufficient) actually arrives.

## Open design questions (don't decide them speculatively)

In `grilled-decisions.md` §15:

- Port discovery → agent feedback loop (cmux-inspired). Lean: Shape C
  (agent reads its dev-server port from `.agent/`). Revisit when an agent
  first asks "what port is the backend on?"
- Agent session resume contract (`claude --resume <session_id>`).
  **Agent-scoped, not repo-scoped** — does not belong in `repos.yaml`.
  Natural home: `.agent/metadata.env`. Revisit on first lost conversation.

## Environment notes (outside the repo, easy to forget)

- **Ghostty bell config** lives at `~/.config/ghostty/config`. The hangar's
  bell wiring (`\a` on `agent-mark-as-blocked`) only rings if Ghostty's
  `bell-features` includes `system` or `audio`. Current setting:
  `bell-features = system,attention,title`. If you switch terminals,
  remember the bell wiring is at the terminal layer, not in our code.
- **`sync-repos`** is a personal zsh alias at
  `/Users/stephan/Documents/ZSH Aliases/sync-repos/`. The
  `repository-list.txt` next to it is the source-of-truth path list. We
  deliberately do NOT integrate with it from the codebase — if you ever
  need to re-seed `~/.agent-control/config/repos.yaml` from it, paste the
  paths manually.
- **`watch` command on macOS** is not installed by default. `hangar-checkin`
  runs `watch -c -n 2 hangar-watch` inside its cockpit pane; if `watch`
  is missing the pane will say "command not found." Fix: `brew install watch`.

## Recent renames (the trail through the session that landed us here)

Multiple naming rounds happened. Anything below is the **current** name;
the "was" column is what older docs / git history use.

| Was | Now |
|---|---|
| `agent-init` | `hangar-setup` |
| `agent-cockpit` | `hangar-checkin` |
| `agent-dashboard` | `hangar-watch` |
| `agent-tmux-status` | `hangar-statusline` |
| `agent-quota-update` | `hangar-quota-update` |
| `agent-blocked` | `agent-mark-as-blocked` |
| `agent-close` | `agent-mark-done` (semantics changed too — no longer touches tmux window) |
| `agent-clean` | `agent-teardown` |
| `agent-list` | `agent-list` (kept; was briefly `hangar-list`, reverted) |

If you find an old name lingering in code or docs, it's a stale reference.
The PRD (`documentation/initial-prd.md`) and the
implementation plan use old names by design — they're superseded by
grilled-decisions per the README. Don't update them.

## Side items unresolved

1. **README still references Phase-3 statusline wiring loosely.** The
   wrapper is shipped (`scripts/claude-statusline`) and the env-var
   contract (`HANGAR_STATUSLINE_RENDERER`) is documented in the wrapper's
   own header comment, but README doesn't yet have a paste-able snippet
   for `~/.claude/settings.json`. Add when touching README next.
2. **Cockpit `watch` dependency** is documented but not enforced; if
   `hangar-checkin` runs on a fresh macOS without `watch`, the cockpit
   window opens but its main pane errors out. Acceptable for now (the
   error is obvious); revisit if it becomes friction.
3. **PRD and initial-implementation-plan** still reference old command
   names (`agent-init`, `agent-dashboard`, etc.). By design, per the
   README's "grilled-decisions wins where it disagrees with PRD/plan."
