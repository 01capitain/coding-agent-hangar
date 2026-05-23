"""CLI entrypoints registered as console scripts in pyproject.toml.

Phases 1+ replace stub bodies with real implementations; stubs for unimplemented
commands stay so ``--help`` works and callers see a clear "not implemented yet"
exit code rather than a stack trace.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

from . import ansi as ansi_mod
from . import config
from . import dashboard as dashboard_mod
from . import init as init_mod
from . import status as status_mod
from . import tmux as tmux_mod

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
            "Interactive when args omitted; prompts resume/suffix/abort if slug exists."
        ),
    )
    parser.add_argument(
        "slug",
        nargs="?",
        help="Workspace slug. If omitted, prompt interactively.",
    )
    parser.add_argument(
        "repos",
        nargs="*",
        help="Zero or more repo keys from repos.yaml. Zero = planning workspace.",
    )
    parser.parse_args()
    _stub("agent-spawn")


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
    _stub("hangar-quota-update")


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
