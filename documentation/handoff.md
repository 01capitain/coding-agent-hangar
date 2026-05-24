# Session handoff

Read this first when picking up work after a break. The two authoritative
docs are still `README.md` (user-facing) and `documentation/grilled-decisions.md`
(design decisions). This file is the **per-session bridge**: where we left
off, what was decided that day, and what NOT to redo.

Last updated: 2026-05-24

---

## Status at a glance

- **Phases 0, 1, 2, 3 complete.** Phases 4–7 ahead.
- **90 tests passing**, ruff clean. Working tree had pending Phase 3 commits
  at end of session — push status is whatever git says when you read this.
- Local validation done end-to-end:
  - Phases 1–2 against hand-written status files (`hangar-setup` →
    `agent-status` / `agent-mark-as-blocked` → `hangar-watch` /
    `agent-list` / `hangar-statusline`).
  - Phase 3 against a temp `AGENT_CONTROL_HOME` smoke run: piped a fake
    Claude statusline JSON through `hangar-quota-update`, saw the rendered
    `hangar-watch` pane (5h + 7d bars, reset countdown, context line) and
    the compact `5h:U%/E% 7d:U%/E%` in `hangar-statusline`. Also exercised
    `scripts/claude-statusline` with and without `HANGAR_STATUSLINE_RENDERER`.

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
| 4 — `agent-spawn` non-interactive | ⏳ Next | worktrees, AGENTS.md, tmux window | — |
| 5 — `agent-spawn` interactive + resume | ⏳ | curated picker, resume/suffix/abort | — |
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

## Next: Phase 4 (`agent-spawn` non-interactive)

Spec lives in `ROADMAP.md` Phase 4 and `grilled-decisions.md` §3, §5, §6,
§7, §9. Subtasks:

1. **Slug validation / normalization.** Lowercase, hyphenate spaces,
   strip invalid chars, collapse runs, trim. Refuse empty slug.
2. **`workspace.py`** (already scaffolded, currently empty): compute the
   workspace path `${AGENT_WORK_HOME}/<slug>`, refuse if it exists, mkdir,
   prepare `.agent/` and the AGENTS.md/CLAUDE.md pair.
3. **`spawn.py` / `cli.spawn`**: orchestrate per-repo `git fetch` + 
   `git worktree add -b agent/<slug>/<repo> <workspace>/<repo> <base_branch>`.
   Status starts `STARTING`. Run `bootstrap` per repo in the background
   with stdout/stderr to `~/.agent-control/logs/<slug>-<repo>-bootstrap.log`.
4. **Templates** (`src/agent_hangar/templates/`): AGENTS.md, HANDOFF.md,
   prompt.md. Status-reporting rules, blocking rules, slug+workspace+repo
   paths baked in via simple `{slug}`-style substitution (avoid jinja for
   one extra dep).
5. **Tmux window**: open a window named after the slug with the prompt
   shown. Reuse `tmux.py` patterns from `hangar-checkin`.
6. **Zero-repo case** (§9): workspace dir + tmux window + AGENTS.md, no
   worktrees, no bootstrap. CLI-level confirmation for the foot-gun.
7. **Tests**: heavy `subprocess.run` mocking (or a tmp git repo fixture
   for the worktree paths). Keep the test footprint as integration-y as
   we can without depending on a real network or a real tmux.

`agent-list` and `hangar-watch` already do the right thing once `agent-spawn`
populates status files, so no dashboard work for Phase 4.

**Exit criterion (from ROADMAP):**
`agent-spawn permissions-refactor backend frontend` creates the workspace,
worktrees materialize, tmux window opens, prompt is visible, bootstrap
finishes in the background, status transitions from `STARTING` onward.

## Design decisions to keep in mind (NOT re-litigate)

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
