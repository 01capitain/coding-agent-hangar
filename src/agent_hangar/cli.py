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

from . import ansi as ansi_mod
from . import config
from . import dashboard as dashboard_mod
from . import init as init_mod
from . import quota as quota_mod
from . import repos as repos_mod
from . import spawn as spawn_mod
from . import status as status_mod
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
            "Phase 4 ships the non-interactive form; resume/suffix/abort "
            "and interactive prompts arrive in Phase 5."
        ),
    )
    parser.add_argument("slug", help="Workspace slug. Required.")
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
    args = parser.parse_args()

    if not config.status_dir().is_dir():
        print(
            "agent-spawn: control directory missing. Run `hangar-setup` first.",
            file=sys.stderr,
        )
        sys.exit(_USER_ERROR_EXIT)

    try:
        slug = workspace_mod.normalize_slug(args.slug)
    except workspace_mod.WorkspaceError as exc:
        print(f"agent-spawn: {exc}", file=sys.stderr)
        sys.exit(_USER_ERROR_EXIT)

    selected_repos = _resolve_repos(args.repos)

    if selected_repos and not args.branch:
        print(
            "agent-spawn: --branch is required when one or more repos are passed.",
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

    try:
        layout = workspace_mod.prepare_skeleton(
            slug,
            repos=[r.name for r in selected_repos],
            branch=args.branch,
        )
    except workspace_mod.WorkspaceError as exc:
        print(f"agent-spawn: {exc}", file=sys.stderr)
        sys.exit(_USER_ERROR_EXIT)

    try:
        if selected_repos:
            spawn_mod.create_worktrees(layout, selected_repos, branch=args.branch)
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
        # The workspace is on disk and status is STARTING — the spawn
        # succeeded in every way except the tmux flourish. Print the
        # error but don't blow up the exit code, the user can open the
        # window manually.
        print(f"agent-spawn: tmux step skipped ({exc})", file=sys.stderr)


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


def jump() -> None:
    parser = argparse.ArgumentParser(
        prog="agent-jump",
        description="Switch tmux to a workspace, or to the next blocked/feedback workspace.",
    )
    parser.add_argument("target", help="A slug, or one of: blocked, feedback.")
    parser.parse_args()
    _stub("agent-jump")


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
    parser.parse_args()
    _stub("agent-mark-done")


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
        help="Allow teardown of workspaces with uncommitted changes.",
    )
    parser.parse_args()
    _stub("agent-teardown")
