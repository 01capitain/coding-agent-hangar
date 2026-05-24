"""CLI entrypoints registered as console scripts in pyproject.toml.

Phases 1+ replace stub bodies with real implementations; stubs for unimplemented
commands stay so ``--help`` works and callers see a clear "not implemented yet"
exit code rather than a stack trace.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from . import ansi as ansi_mod
from . import config
from . import dashboard as dashboard_mod
from . import init as init_mod
from . import quota as quota_mod
from . import repos as repos_mod
from . import spawn as spawn_mod
from . import status as status_mod
from . import teardown as teardown_mod
from . import tmux as tmux_mod
from . import workspace as workspace_mod

_NOT_IMPLEMENTED_EXIT = 1
_USER_ERROR_EXIT = 2

_STATE_CHOICES = status_mod.VALID_STATES


def _stub(name: str) -> None:
    print(f"{name}: not implemented yet", file=sys.stderr)
    sys.exit(_NOT_IMPLEMENTED_EXIT)


def init() -> None:
    parser = argparse.ArgumentParser(
        prog="hangar-setup",
        description="Create ~/.agent-control/ layout and seed repos.yaml.",
    )
    parser.parse_args()

    try:
        report = init_mod.run_init()
    except init_mod.InitError as exc:
        print(f"hangar-setup: {exc}", file=sys.stderr)
        sys.exit(_USER_ERROR_EXIT)

    print(f"Hangar root: {report['control_home']}")
    created = report["created_subdirs"]
    if created:
        print(f"Created {len(created)} subdir(s):")
        for path in created:
            print(f"  + {path}")
    else:
        print("All subdirs already in place.")

    status = report["repos_yaml_status"]
    repos_path = report["repos_yaml"]
    if status == "preserved-existing":
        print(f"repos.yaml: kept existing file at {repos_path}")
    else:
        print(f"repos.yaml: seeded {repos_path} with bundled hotelkit sample.")
    print("Done. Edit repos.yaml to match your real repositories before spawning.")


def spawn() -> None:
    parser = argparse.ArgumentParser(
        prog="agent-spawn",
        description=(
            "Create a workspace (tmux window, worktrees, AGENTS.md). "
            "Omit `slug` for interactive prompts."
        ),
    )
    parser.add_argument(
        "slug",
        nargs="?",
        help="Workspace slug. Omit for interactive mode.",
    )
    parser.add_argument(
        "repos",
        nargs="*",
        help="Zero or more repo keys from repos.yaml. Zero = planning workspace.",
    )
    parser.add_argument(
        "--branch",
        required=False,
        help=(
            "Branch name to create in each repo's worktree. Required when "
            "any repos are passed. Same name is used across all repos."
        ),
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the zero-repo confirmation prompt.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Reattach to an existing workspace for this slug instead of "
            "erroring. Cannot be combined with repos or --branch."
        ),
    )
    parser.add_argument(
        "--suffix",
        action="store_true",
        help=(
            "If a workspace at `slug` already exists, create the next free "
            "<slug>-N instead of erroring."
        ),
    )
    args = parser.parse_args()

    if not config.status_dir().is_dir():
        print(
            "agent-spawn: control directory missing. Run `hangar-setup` first.",
            file=sys.stderr,
        )
        sys.exit(_USER_ERROR_EXIT)

    if args.resume and args.suffix:
        print(
            "agent-spawn: --resume and --suffix are mutually exclusive.",
            file=sys.stderr,
        )
        sys.exit(_USER_ERROR_EXIT)

    if args.slug is None:
        if args.repos or args.branch or args.resume or args.suffix or args.yes:
            print(
                "agent-spawn: positional/--branch/--resume/--suffix/--yes "
                "require an explicit slug. Re-run with `agent-spawn <slug> ...` "
                "or `agent-spawn` alone for the interactive flow.",
                file=sys.stderr,
            )
            sys.exit(_USER_ERROR_EXIT)
        _spawn_interactive()
        return

    _spawn_non_interactive(args)


# ---------- non-interactive path ----------


def _spawn_non_interactive(args: argparse.Namespace) -> None:
    if args.resume and (args.repos or args.branch):
        print(
            "agent-spawn: --resume cannot be combined with repos or --branch.",
            file=sys.stderr,
        )
        sys.exit(_USER_ERROR_EXIT)

    slug = _normalize_with_warning(args.slug)

    layout = workspace_mod.layout_for(slug)
    if layout.workspace_dir.exists():
        if args.resume:
            _reattach_workspace(slug, layout)
            return
        if args.suffix:
            slug = workspace_mod.next_available_slug(slug)
            layout = workspace_mod.layout_for(slug)
            print(f"agent-spawn: existing workspace; using suffixed slug '{slug}'.")
        else:
            suggested = workspace_mod.next_available_slug(slug)
            print(
                f"agent-spawn: workspace already exists at {layout.workspace_dir}. "
                f"Pass --resume to reattach or --suffix to create '{suggested}'.",
                file=sys.stderr,
            )
            sys.exit(_USER_ERROR_EXIT)
    elif args.resume:
        print(
            f"agent-spawn: --resume given but no workspace exists at {layout.workspace_dir}.",
            file=sys.stderr,
        )
        sys.exit(_USER_ERROR_EXIT)

    selected_repos = _resolve_repos(args.repos)

    if selected_repos and not args.branch:
        print(
            "agent-spawn: --branch is required when one or more repos are passed.",
            file=sys.stderr,
        )
        sys.exit(_USER_ERROR_EXIT)

    if selected_repos:
        try:
            collisions = spawn_mod.check_branch_collisions(selected_repos, args.branch)
        except spawn_mod.SpawnError as exc:
            print(f"agent-spawn: {exc}", file=sys.stderr)
            sys.exit(_USER_ERROR_EXIT)
        if collisions:
            names = ", ".join(r.key for r in collisions)
            print(
                f"agent-spawn: branch {args.branch!r} already exists in {names}. "
                "Pick a different --branch or delete the existing ref first "
                "(interactive mode offers reuse).",
                file=sys.stderr,
            )
            sys.exit(_USER_ERROR_EXIT)

    if not selected_repos and not args.yes:
        confirmed = _confirm(
            f"Create zero-repo planning workspace for slug {slug!r}? [y/N] "
        )
        if not confirmed:
            print("agent-spawn: aborted by user.")
            sys.exit(0)

    _finalize_spawn(slug, selected_repos, branch=args.branch, reuse_in=frozenset())


# ---------- interactive path ----------


def _spawn_interactive() -> None:
    try:
        all_repos = repos_mod.load_repos()
    except repos_mod.RepoConfigError as exc:
        print(f"agent-spawn: {exc}", file=sys.stderr)
        sys.exit(_USER_ERROR_EXIT)

    slug = _prompt_for_slug()
    layout = workspace_mod.layout_for(slug)

    if layout.workspace_dir.exists():
        choice = _prompt_resume_suffix_abort(slug)
        if choice == "abort":
            print("agent-spawn: aborted by user.")
            sys.exit(0)
        if choice == "resume":
            _reattach_workspace(slug, layout)
            return
        if choice == "suffix":
            slug = workspace_mod.next_available_slug(slug)
            print(f"agent-spawn: using suffixed slug '{slug}'.")

    selected_repos = _prompt_for_repos(all_repos)

    branch: str | None = None
    reuse_in: set[str] = set()
    if selected_repos:
        branch = _prompt_for_branch()
        try:
            collisions = spawn_mod.check_branch_collisions(selected_repos, branch)
        except spawn_mod.SpawnError as exc:
            print(f"agent-spawn: {exc}", file=sys.stderr)
            sys.exit(_USER_ERROR_EXIT)
        for repo in collisions:
            reuse = _confirm(
                f"Branch {branch!r} already exists in {repo.key}. "
                "Reuse the existing branch (no new branch created)? [y/N] "
            )
            if not reuse:
                print(
                    f"agent-spawn: aborted — branch {branch!r} exists in {repo.key} "
                    "and reuse was declined.",
                    file=sys.stderr,
                )
                sys.exit(_USER_ERROR_EXIT)
            reuse_in.add(repo.key)
    else:
        confirmed = _confirm(
            f"Create zero-repo planning workspace for slug {slug!r}? [y/N] "
        )
        if not confirmed:
            print("agent-spawn: aborted by user.")
            sys.exit(0)

    _finalize_spawn(
        slug, selected_repos, branch=branch, reuse_in=frozenset(reuse_in)
    )


def _prompt_for_slug() -> str:
    raw = _input_required("Workspace slug: ", missing_message="slug is required")
    try:
        return _normalize_with_warning(raw)
    except SystemExit:
        raise
    except workspace_mod.WorkspaceError as exc:
        print(f"agent-spawn: {exc}", file=sys.stderr)
        sys.exit(_USER_ERROR_EXIT)


def _prompt_resume_suffix_abort(slug: str) -> str:
    layout = workspace_mod.layout_for(slug)
    suggested_suffix = workspace_mod.next_available_slug(slug)
    print(
        f"Workspace for {slug!r} already exists at {layout.workspace_dir}."
    )
    while True:
        try:
            answer = input(
                f"  [r]esume / [s]uffix as {suggested_suffix!r} / [a]bort: "
            ).strip().lower()
        except EOFError:
            return "abort"
        if answer in {"r", "resume"}:
            return "resume"
        if answer in {"s", "suffix"}:
            return "suffix"
        if answer in {"", "a", "abort"}:
            return "abort"
        print("  (expected r / s / a)")


def _prompt_for_repos(all_repos: list[repos_mod.Repo]) -> list[repos_mod.Repo]:
    if not all_repos:
        print("agent-spawn: repos.yaml has no entries — creating a zero-repo workspace.")
        return []
    ordered = sorted(all_repos, key=lambda r: (not r.default, r.key))
    print("Repos (nothing pre-selected; * = default hint):")
    for i, repo in enumerate(ordered, start=1):
        marker = "*" if repo.default else " "
        print(f"  {marker} {i:>2}. {repo.key:<24} {repo.name}")
    while True:
        try:
            raw = input(
                "Select by number (comma-separated, blank or 'none' for zero-repo): "
            ).strip()
        except EOFError:
            return []
        if raw == "" or raw.lower() == "none":
            return []
        picks: list[repos_mod.Repo] = []
        try:
            for token in raw.split(","):
                token = token.strip()
                if not token:
                    continue
                idx = int(token)
                if idx < 1 or idx > len(ordered):
                    raise ValueError(f"out of range: {idx}")
                repo = ordered[idx - 1]
                if repo not in picks:
                    picks.append(repo)
        except ValueError as exc:
            print(f"  (invalid selection: {exc} — try again)")
            continue
        return picks


def _prompt_for_branch() -> str:
    return _input_required(
        "Branch name (same across every repo): ",
        missing_message="branch is required when repos are selected",
    )


def _input_required(prompt: str, *, missing_message: str) -> str:
    try:
        value = input(prompt).strip()
    except EOFError:
        print(f"agent-spawn: {missing_message}", file=sys.stderr)
        sys.exit(_USER_ERROR_EXIT)
    if not value:
        print(f"agent-spawn: {missing_message}", file=sys.stderr)
        sys.exit(_USER_ERROR_EXIT)
    return value


# ---------- shared helpers ----------


def _finalize_spawn(
    slug: str,
    selected_repos: list,
    *,
    branch: str | None,
    reuse_in: frozenset[str],
) -> None:
    try:
        layout = workspace_mod.prepare_skeleton(
            slug,
            repos=[r.name for r in selected_repos],
            branch=branch,
        )
    except workspace_mod.WorkspaceError as exc:
        print(f"agent-spawn: {exc}", file=sys.stderr)
        sys.exit(_USER_ERROR_EXIT)

    try:
        if selected_repos:
            spawn_mod.create_worktrees(
                layout, selected_repos, branch=branch, reuse_in=reuse_in
            )
            spawn_mod.run_bootstraps(layout, selected_repos)
    except spawn_mod.SpawnError as exc:
        print(f"agent-spawn: {exc}", file=sys.stderr)
        sys.exit(_USER_ERROR_EXIT)

    try:
        status_mod.write_status(
            slug, "STARTING", "workspace created; bootstrap running"
        )
    except status_mod.StatusError as exc:
        print(f"agent-spawn: {exc}", file=sys.stderr)
        sys.exit(_USER_ERROR_EXIT)

    # Print success BEFORE the tmux call: when ``focus()`` runs from
    # outside an existing tmux client it ``os.execvp``-replaces this
    # process with ``tmux attach`` — anything printed after that point
    # is lost (and the new tmux session covers the screen anyway).
    print(f"[{slug}] STARTING at {layout.workspace_dir}")

    try:
        tmux_summary = tmux_mod.open_workspace_window(
            slug, cwd=str(layout.workspace_dir)
        )
        print(f"agent-spawn: {tmux_summary}")
    except tmux_mod.TmuxError as exc:
        print(f"agent-spawn: tmux step skipped ({exc})", file=sys.stderr)


def _reattach_workspace(slug: str, layout) -> None:
    print(f"[{slug}] resuming workspace at {layout.workspace_dir}")
    try:
        tmux_summary = tmux_mod.open_workspace_window(
            slug, cwd=str(layout.workspace_dir)
        )
        print(f"agent-spawn: {tmux_summary}")
    except tmux_mod.TmuxError as exc:
        print(f"agent-spawn: tmux step skipped ({exc})", file=sys.stderr)


def _normalize_with_warning(raw: str, *, prog: str = "agent-spawn") -> str:
    try:
        normalized = workspace_mod.normalize_slug(raw)
    except workspace_mod.WorkspaceError as exc:
        print(f"{prog}: {exc}", file=sys.stderr)
        sys.exit(_USER_ERROR_EXIT)
    if normalized != raw:
        print(
            f"{prog}: slug normalized to '{normalized}' (from {raw!r}).",
            file=sys.stderr,
        )
    return normalized


def _resolve_repos(repo_keys: list[str]) -> list:
    if not repo_keys:
        return []
    try:
        all_repos = repos_mod.load_repos()
    except repos_mod.RepoConfigError as exc:
        print(f"agent-spawn: {exc}", file=sys.stderr)
        sys.exit(_USER_ERROR_EXIT)
    resolved = []
    for key in repo_keys:
        try:
            resolved.append(repos_mod.lookup(all_repos, key))
        except repos_mod.RepoConfigError as exc:
            print(f"agent-spawn: {exc}", file=sys.stderr)
            sys.exit(_USER_ERROR_EXIT)
    return resolved


def _confirm(prompt: str) -> bool:
    try:
        answer = input(prompt).strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}


def status() -> None:
    parser = argparse.ArgumentParser(
        prog="agent-status",
        description="Atomic write of ~/.agent-control/status/<slug>.status.",
    )
    parser.add_argument("slug")
    parser.add_argument("state", choices=_STATE_CHOICES, help="Workspace state.")
    parser.add_argument("summary", help="One-line status summary.")
    args = parser.parse_args()

    try:
        record = status_mod.write_status(args.slug, args.state, args.summary)
    except status_mod.StatusError as exc:
        print(f"agent-status: {exc}", file=sys.stderr)
        sys.exit(_USER_ERROR_EXIT)

    print(f"[{record.slug}] {record.state}: {record.summary}")


def blocked() -> None:
    parser = argparse.ArgumentParser(
        prog="agent-mark-as-blocked",
        description="Set state to BLOCKED, run tmux display-message, ring the bell.",
    )
    parser.add_argument("slug")
    parser.add_argument("message", help="What is blocking the agent.")
    args = parser.parse_args()

    try:
        record = status_mod.write_status(args.slug, "BLOCKED", args.message)
    except status_mod.StatusError as exc:
        print(f"agent-mark-as-blocked: {exc}", file=sys.stderr)
        sys.exit(_USER_ERROR_EXIT)

    _notify_tmux(record.slug, record.summary)
    # ASCII bell — rings the terminal even outside tmux.
    sys.stderr.write("\a")
    sys.stderr.flush()
    print(f"[{record.slug}] BLOCKED: {record.summary}")


def _notify_tmux(slug: str, message: str) -> None:
    if shutil.which("tmux") is None:
        return
    try:
        subprocess.run(
            ["tmux", "display-message", f"[{slug}] BLOCKED: {message}"],
            check=False,
            capture_output=True,
            timeout=2,
        )
    except (subprocess.SubprocessError, OSError):
        # A missing tmux server is fine; we still wrote the status file.
        pass


def dashboard() -> None:
    parser = argparse.ArgumentParser(
        prog="hangar-watch",
        description=(
            "Render grouped statuses + quota pane. The rich rendering that "
            "`hangar-checkin` runs under `watch -n 2`."
        ),
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI colors even when stdout is a TTY.",
    )
    args = parser.parse_args()

    if not config.status_dir().is_dir():
        print(
            "hangar-watch: control directory missing. Run `hangar-setup` first.",
            file=sys.stderr,
        )
        sys.exit(_USER_ERROR_EXIT)

    use_color = ansi_mod.should_use_color() and not args.no_color
    print(dashboard_mod.render_dashboard(use_color=use_color))


def tmux_status() -> None:
    parser = argparse.ArgumentParser(
        prog="hangar-statusline",
        description=(
            "Emit the compact one-line summary for use in tmux's `status-right`."
        ),
    )
    parser.parse_args()

    if not config.status_dir().is_dir():
        # Don't yell from inside tmux's status loop — print nothing, exit 0.
        return

    print(dashboard_mod.render_statusline())


def quota_update() -> None:
    parser = argparse.ArgumentParser(
        prog="hangar-quota-update",
        description=(
            "Read Claude statusline JSON from stdin, normalize it, "
            "write ~/.agent-control/quotas/claude.json."
        ),
    )
    parser.parse_args()

    raw = sys.stdin.read()
    if not raw.strip():
        # Empty stdin is the common no-op case (statusline misconfigured or
        # piped from /dev/null during testing). Exit clean — the wrapper still
        # has to render the user's existing statusline.
        return

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"hangar-quota-update: invalid JSON on stdin ({exc})", file=sys.stderr)
        sys.exit(_USER_ERROR_EXIT)

    if not isinstance(payload, dict):
        print("hangar-quota-update: expected a JSON object on stdin", file=sys.stderr)
        sys.exit(_USER_ERROR_EXIT)

    normalized = quota_mod.normalize_payload(payload)
    try:
        quota_mod.write_snapshot(normalized)
    except OSError as exc:
        print(f"hangar-quota-update: {exc}", file=sys.stderr)
        sys.exit(_USER_ERROR_EXIT)


def cockpit() -> None:
    parser = argparse.ArgumentParser(
        prog="hangar-checkin",
        description=(
            "Open the cockpit tmux window: create or attach the `agents` session, "
            "create or reuse the `cockpit` window with the watched dashboard."
        ),
    )
    parser.parse_args()

    if not config.status_dir().is_dir():
        print(
            "hangar-checkin: control directory missing. Run `hangar-setup` first.",
            file=sys.stderr,
        )
        sys.exit(_USER_ERROR_EXIT)

    try:
        summary = tmux_mod.open_checkin()
    except tmux_mod.TmuxError as exc:
        print(f"hangar-checkin: {exc}", file=sys.stderr)
        sys.exit(_USER_ERROR_EXIT)

    # If open_checkin attached, we never get here. If we got here, we were
    # inside tmux and the active window has switched to the cockpit.
    print(f"hangar-checkin: {summary}")


_JUMP_CATEGORIES: dict[str, str] = {
    "blocked": "BLOCKED",
    "feedback": "NEEDS_FEEDBACK",
}


def jump() -> None:
    parser = argparse.ArgumentParser(
        prog="agent-jump",
        description=(
            "Switch tmux to a workspace, or to one of the workspaces currently "
            "BLOCKED / NEEDS_FEEDBACK. From outside tmux this attaches to the "
            "`agents` session and selects the target window."
        ),
    )
    parser.add_argument("target", help="A slug, or one of: blocked, feedback.")
    args = parser.parse_args()

    if not config.status_dir().is_dir():
        print(
            "agent-jump: control directory missing. Run `hangar-setup` first.",
            file=sys.stderr,
        )
        sys.exit(_USER_ERROR_EXIT)

    state = _JUMP_CATEGORIES.get(args.target.lower())
    if state is not None:
        _jump_to_category(args.target.lower(), state)
        return

    _jump_to_slug(args.target)


def _jump_to_slug(raw: str) -> None:
    slug = _normalize_with_warning(raw, prog="agent-jump")
    layout = workspace_mod.layout_for(slug)
    if not layout.workspace_dir.exists():
        print(
            f"agent-jump: no workspace matches {slug!r} (looked at {layout.workspace_dir}).",
            file=sys.stderr,
        )
        sys.exit(_USER_ERROR_EXIT)
    _focus_workspace(slug, layout)


def _jump_to_category(label: str, state: str) -> None:
    records = [r for r in status_mod.list_records() if r.state == state]
    if not records:
        print(f"agent-jump: no {state} workspaces.", file=sys.stderr)
        sys.exit(_USER_ERROR_EXIT)

    # Most-recent-first within the (single-state) group — matches the
    # hangar-watch dashboard ordering so the operator sees the same shape.
    records.sort(key=lambda r: -r.updated_at.timestamp())

    if len(records) == 1:
        target = records[0]
    else:
        target = _pick_record(label, state, records)
        if target is None:
            print("agent-jump: aborted by user.")
            sys.exit(0)

    layout = workspace_mod.layout_for(target.slug)
    if not layout.workspace_dir.exists():
        print(
            f"agent-jump: status file points at {target.slug!r} but workspace dir "
            f"is missing at {layout.workspace_dir}.",
            file=sys.stderr,
        )
        sys.exit(_USER_ERROR_EXIT)
    _focus_workspace(target.slug, layout)


def _pick_record(
    label: str, state: str, records: list[status_mod.StatusRecord]
) -> status_mod.StatusRecord | None:
    print(f"Multiple {state} workspaces. Pick one to jump to:")
    for i, record in enumerate(records, start=1):
        age = status_mod.relative_age(record.updated_at)
        print(f"  {i:>2}. {record.slug:<28} {age:<10} {record.summary}")
    while True:
        try:
            raw = input("Choice (number, or 'a' to abort): ").strip().lower()
        except EOFError:
            return None
        if raw in {"", "a", "abort"}:
            return None
        try:
            idx = int(raw)
        except ValueError:
            print("  (expected a number or 'a')")
            continue
        if idx < 1 or idx > len(records):
            print(f"  (out of range: pick 1..{len(records)})")
            continue
        return records[idx - 1]


def _focus_workspace(slug: str, layout) -> None:
    # Print BEFORE the tmux call: focus() may execvp into `tmux attach`
    # from outside a tmux client, which replaces this process.
    print(f"agent-jump: focusing {slug} at {layout.workspace_dir}")
    try:
        summary = tmux_mod.open_workspace_window(slug, cwd=str(layout.workspace_dir))
        print(f"agent-jump: {summary}")
    except tmux_mod.TmuxError as exc:
        print(f"agent-jump: tmux step skipped ({exc})", file=sys.stderr)


def list_workspaces() -> None:
    parser = argparse.ArgumentParser(
        prog="agent-list",
        description="List all workspaces and their states.",
    )
    parser.parse_args()

    if not config.status_dir().is_dir():
        print(
            "agent-list: control directory missing. Run `hangar-setup` first.",
            file=sys.stderr,
        )
        sys.exit(_USER_ERROR_EXIT)

    records = status_mod.list_records()
    if not records:
        print("(no workspaces yet)")
        return

    records.sort(key=lambda r: (r.priority(), -r.updated_at.timestamp()))
    _render_table(records)


def _render_table(records: list[status_mod.StatusRecord]) -> None:
    headers = ("SLUG", "STATE", "UPDATED", "SUMMARY")
    rows = [
        (
            r.slug,
            r.state,
            status_mod.relative_age(r.updated_at),
            r.summary,
        )
        for r in records
    ]
    widths = [
        max(len(headers[i]), max(len(row[i]) for row in rows))
        for i in range(len(headers))
    ]
    header_line = "  ".join(headers[i].ljust(widths[i]) for i in range(len(headers)))
    sep_line = "  ".join("-" * widths[i] for i in range(len(headers)))
    print(header_line.rstrip())
    print(sep_line)
    for row in rows:
        print("  ".join(row[i].ljust(widths[i]) for i in range(len(row))).rstrip())


def mark_done() -> None:
    parser = argparse.ArgumentParser(
        prog="agent-mark-done",
        description=(
            "Set state to DONE, run tmux display-message, ring the bell. "
            "Mirror of agent-mark-as-blocked. Does NOT touch worktrees, "
            "branches, or the tmux window — use agent-teardown for that."
        ),
    )
    parser.add_argument("slug")
    parser.add_argument("summary", help="One-line summary of what was done.")
    args = parser.parse_args()

    try:
        record = status_mod.write_status(args.slug, "DONE", args.summary)
    except status_mod.StatusError as exc:
        print(f"agent-mark-done: {exc}", file=sys.stderr)
        sys.exit(_USER_ERROR_EXIT)

    _notify_tmux_done(record.slug, record.summary)
    # ASCII bell — rings the terminal even outside tmux.
    sys.stderr.write("\a")
    sys.stderr.flush()
    print(f"[{record.slug}] DONE: {record.summary}")


def _notify_tmux_done(slug: str, message: str) -> None:
    if shutil.which("tmux") is None:
        return
    try:
        subprocess.run(
            ["tmux", "display-message", f"[{slug}] DONE: {message}"],
            check=False,
            capture_output=True,
            timeout=2,
        )
    except (subprocess.SubprocessError, OSError):
        pass


def teardown() -> None:
    parser = argparse.ArgumentParser(
        prog="agent-teardown",
        description=(
            "Guided interactive teardown of an agent's workspace: remove worktrees, "
            "delete branches, archive the status file, remove the workspace dir. "
            "Irreversible. Refuses uncommitted work without --force."
        ),
    )
    parser.add_argument("slug")
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Allow teardown of workspaces with uncommitted changes, and "
            "force-delete branches that haven't been merged."
        ),
    )
    args = parser.parse_args()

    if not config.status_dir().is_dir():
        print(
            "agent-teardown: control directory missing. Run `hangar-setup` first.",
            file=sys.stderr,
        )
        sys.exit(_USER_ERROR_EXIT)

    slug = _normalize_with_warning(args.slug, prog="agent-teardown")
    layout = workspace_mod.layout_for(slug)
    if not layout.workspace_dir.exists():
        print(
            f"agent-teardown: no workspace at {layout.workspace_dir}",
            file=sys.stderr,
        )
        sys.exit(_USER_ERROR_EXIT)

    metadata = teardown_mod.read_metadata(layout)
    branch = metadata.get("BRANCH", "")
    base_branch = config.base_branch()

    worktrees = teardown_mod.find_worktree_dirs(layout)

    print(f"Workspace: {layout.workspace_dir}")
    if branch:
        print(f"Branch:    {branch}")
    if not worktrees:
        print("Worktrees: (none — zero-repo workspace)")
    else:
        print(f"Worktrees ({len(worktrees)}):")

    statuses: list[teardown_mod.WorktreeStatus] = []
    for worktree in worktrees:
        try:
            ws = teardown_mod.probe_worktree(worktree, base_branch)
        except teardown_mod.TeardownError as exc:
            print(f"agent-teardown: {exc}", file=sys.stderr)
            sys.exit(_USER_ERROR_EXIT)
        statuses.append(ws)
        merged_label = {
            True: f"merged into {base_branch}",
            False: f"NOT merged into {base_branch}",
            None: f"merge check unavailable ({base_branch} not found?)",
        }[ws.merged_into_base]
        dirty_label = "DIRTY" if ws.uncommitted else "clean"
        print(f"  - {worktree.name}  branch={ws.branch}  {dirty_label}  {merged_label}")
        if ws.short_status:
            for line in ws.short_status.splitlines():
                print(f"      {line}")

    dirty = [s for s in statuses if s.uncommitted]
    if dirty and not args.force:
        names = ", ".join(s.path.name for s in dirty)
        print(
            f"agent-teardown: uncommitted changes in {names}. "
            "Re-run with --force to tear down anyway.",
            file=sys.stderr,
        )
        sys.exit(_USER_ERROR_EXIT)

    # Info-only prompts (no gating); user's answers are discarded.
    _confirm("PR opened? [y/N] ")
    _confirm("PR merged? [y/N] ")

    # Resolve each worktree's canonical BEFORE removing it — once the
    # worktree dir is gone, `git -C <path>` can't tell us which canonical
    # it belonged to.
    canonicals: dict[Path, Path] = {}
    for ws in statuses:
        try:
            canonicals[ws.path] = teardown_mod.canonical_for(ws.path)
        except teardown_mod.TeardownError as exc:
            print(f"agent-teardown: {exc}", file=sys.stderr)
            sys.exit(_USER_ERROR_EXIT)

    removed_worktrees: set[Path] = set()
    for ws in statuses:
        if not _confirm(f"OK to remove worktree at {ws.path}? [y/N] "):
            print(f"  skipped: {ws.path}")
            continue
        try:
            teardown_mod.remove_worktree(ws.path, force=args.force)
            removed_worktrees.add(ws.path)
            print(f"  removed worktree: {ws.path}")
        except teardown_mod.TeardownError as exc:
            print(f"agent-teardown: {exc}", file=sys.stderr)
            sys.exit(_USER_ERROR_EXIT)

        if not ws.branch or ws.branch == "HEAD":
            continue
        if not _confirm(f"Delete branch '{ws.branch}' in {ws.path.name}? [y/N] "):
            print(f"  kept branch: {ws.branch}")
            continue
        try:
            teardown_mod.delete_branch(
                canonicals[ws.path], ws.branch, force=args.force
            )
            print(f"  deleted branch: {ws.branch}")
        except teardown_mod.TeardownError as exc:
            print(f"agent-teardown: {exc}", file=sys.stderr)

    archive_path = teardown_mod.archive_status_file(slug)
    if archive_path is not None:
        print(f"archived status: {archive_path}")

    if not statuses or removed_worktrees == {s.path for s in statuses}:
        teardown_mod.remove_workspace_dir(layout)
        print(f"removed workspace dir: {layout.workspace_dir}")
    else:
        kept = [s.path for s in statuses if s.path not in removed_worktrees]
        print(
            f"workspace dir kept ({layout.workspace_dir}); "
            f"{len(kept)} worktree(s) still inside."
        )
