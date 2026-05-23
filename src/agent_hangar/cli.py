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

from . import config
from . import init as init_mod
from . import status as status_mod

_NOT_IMPLEMENTED_EXIT = 1
_USER_ERROR_EXIT = 2

_STATE_CHOICES = status_mod.VALID_STATES


def _stub(name: str) -> None:
    print(f"{name}: not implemented yet", file=sys.stderr)
    sys.exit(_NOT_IMPLEMENTED_EXIT)


def init() -> None:
    parser = argparse.ArgumentParser(
        prog="hangar-init",
        description="Create ~/.agent-control/ layout and seed repos.yaml.",
    )
    parser.parse_args()

    try:
        report = init_mod.run_init()
    except init_mod.InitError as exc:
        print(f"hangar-init: {exc}", file=sys.stderr)
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
    elif status == "seeded-with-sync-repos":
        n = report["sync_repos_count"]
        print(
            f"repos.yaml: seeded {repos_path} with bundled hotelkit sample "
            f"+ {n} entr{'y' if n == 1 else 'ies'} from `sync-repos list`."
        )
    else:
        print(
            f"repos.yaml: seeded {repos_path} with bundled hotelkit sample "
            "(sync-repos not on PATH)."
        )
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
        prog="agent-blocked",
        description="Set state to BLOCKED, run tmux display-message, ring the bell.",
    )
    parser.add_argument("slug")
    parser.add_argument("message", help="What is blocking the agent.")
    args = parser.parse_args()

    try:
        record = status_mod.write_status(args.slug, "BLOCKED", args.message)
    except status_mod.StatusError as exc:
        print(f"agent-blocked: {exc}", file=sys.stderr)
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
        prog="agent-dashboard",
        description="Render grouped statuses + quota pane. Use under `watch -n 2`.",
    )
    parser.parse_args()
    _stub("agent-dashboard")


def tmux_status() -> None:
    parser = argparse.ArgumentParser(
        prog="agent-tmux-status",
        description="Emit the compact one-line status summary for tmux status-right.",
    )
    parser.parse_args()
    _stub("agent-tmux-status")


def quota_update() -> None:
    parser = argparse.ArgumentParser(
        prog="agent-quota-update",
        description=(
            "Read Claude statusline JSON from stdin, normalize it, "
            "write ~/.agent-control/quotas/claude.json."
        ),
    )
    parser.parse_args()
    _stub("agent-quota-update")


def cockpit() -> None:
    parser = argparse.ArgumentParser(
        prog="agent-cockpit",
        description="Create or attach the `agents` tmux session and open the cockpit window.",
    )
    parser.parse_args()
    _stub("agent-cockpit")


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
            "agent-list: control directory missing. Run `hangar-init` first.",
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


def close() -> None:
    parser = argparse.ArgumentParser(
        prog="agent-close",
        description=(
            "Mark workspace DONE or PAUSED; optionally kill its tmux window. "
            "Does NOT remove worktrees — use agent-clean for that."
        ),
    )
    parser.add_argument("slug")
    parser.parse_args()
    _stub("agent-close")


def clean() -> None:
    parser = argparse.ArgumentParser(
        prog="agent-clean",
        description="Guided interactive cleanup of a workspace.",
    )
    parser.add_argument("slug")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow cleanup of workspaces with uncommitted changes.",
    )
    parser.parse_args()
    _stub("agent-clean")
