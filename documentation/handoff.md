# Session handoff

Read this first when picking up work after a break. The two authoritative
docs are still `README.md` (user-facing) and `documentation/grilled-decisions.md`
(design decisions). This file is the **per-session bridge**: where we left
off, what was decided that day, and what NOT to redo.

Last updated: 2026-05-23

---

## Status at a glance

- **Phases 0, 1, 2 complete.** Phases 3–7 ahead.
- **7 commits ahead of `origin/master`.** Working tree clean. Unpushed by
  user choice — not because anything is broken.
- **61 tests passing**, ruff clean.
- Local validation done end-to-end against hand-written status files
  (`hangar-setup` → `agent-status` / `agent-mark-as-blocked` → `hangar-watch`
  / `agent-list` / `hangar-statusline`).

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
| 3 — Quota | ⏳ Next | `hangar-quota-update` (real impl), quota pane fills in | — |
| 4 — `agent-spawn` non-interactive | ⏳ | worktrees, AGENTS.md, tmux window | — |
| 5 — `agent-spawn` interactive + resume | ⏳ | curated picker, resume/suffix/abort | — |
| 6 — `agent-jump` | ⏳ | `<slug>`/`blocked`/`feedback` | — |
| 7 — Done signal + teardown | ⏳ | `agent-mark-done`, `agent-teardown` | — |

`agent-mark-done` is a stub but its shape is fully decided: it mirrors
`agent-mark-as-blocked` (state + bell + tmux display-message). Implementation
is essentially copy-paste in Phase 7.

## Next: Phase 3 (Quota integration)

Spec is already nailed in `grilled-decisions.md` §4 and §11; just plumbing
to wire it up.

1. `src/agent_hangar/quota.py`: replace the Phase-2 stubs (`render_pane` /
   `render_compact`) with real readers of `~/.agent-control/quotas/claude.json`.
   Compute burn-delta = `used_percentage - elapsed_percentage`. Color by
   threshold (green ≤0, yellow ≤10, orange ≤25, red >25). Render the
   two-line-per-window layout from §11.
2. `cli.quota_update()`: read JSON from stdin, extract `rate_limits.five_hour`,
   `rate_limits.seven_day`, `context_window.used_percentage`. Convert Unix
   timestamp `resets_at` to ISO 8601 on write (§4 explicit correction:
   field is `resets_at`, value is Unix int). Atomic-write
   `~/.agent-control/quotas/claude.json`. Graceful on missing fields.
3. `scripts/claude-statusline`: bash wrapper to drop into
   `~/.claude/settings.json` `statusLine.command`. Pipes JSON to
   `hangar-quota-update`, then renders the user's existing statusline
   output unchanged.
4. `dashboard.render_statusline()`: include the compact `5h:U%/E% 7d:U%/E%`
   fragment once `quota.render_compact()` returns non-empty.
5. Tests: mocked quota fixtures in `tests/fixtures/quota/` (the user's
   real `~/.agent-control/` is never touched per existing convention).

**Exit criterion (from ROADMAP):** Cockpit's quota pane updates whenever
Claude Code is used; removing the statusline wrapper degrades the pane to
`unavailable` without breaking the rest.

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

1. **7 unpushed commits.** User chose not to push yet. Push when ready
   with `git push -u origin master`.
2. **Cockpit `watch` dependency** is documented but not enforced; if
   `hangar-checkin` runs on a fresh macOS without `watch`, the cockpit
   window opens but its main pane errors out. Acceptable for now (the
   error is obvious); revisit if it becomes friction.
3. **PRD and initial-implementation-plan** still reference old command
   names (`agent-init`, `agent-dashboard`, etc.). By design, per the
   README's "grilled-decisions wins where it disagrees with PRD/plan."
