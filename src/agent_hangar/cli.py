"""CLI entrypoints registered as console scripts in pyproject.toml.

Phase 0 status: every command parses its documented arguments (so ``--help`` works)
and exits with a "not implemented yet" message. Phases 1+ replace the stub bodies
with real behavior; the argparse signatures here are the contract.
"""

from __future__ import annotations

import argparse
import sys

_NOT_IMPLEMENTED_EXIT = 1

_STATE_CHOICES = (
    "STARTING",
    "WORKING",
    "NEEDS_FEEDBACK",
    "BLOCKED",
    "READY",
    "DONE",
    "FAILED",
    "PAUSED",
    "STARTING_FAILED",
)


def _stub(name: str) -> None:
    print(f"{name}: not implemented yet", file=sys.stderr)
    sys.exit(_NOT_IMPLEMENTED_EXIT)


def init() -> None:
    parser = argparse.ArgumentParser(
        prog="agent-init",
        description="Create ~/.agent-control/ layout and a sample repos.yaml.",
    )
    parser.parse_args()
    _stub("agent-init")


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
    parser.parse_args()
    _stub("agent-status")


def blocked() -> None:
    parser = argparse.ArgumentParser(
        prog="agent-blocked",
        description="Set state to BLOCKED, run tmux display-message, ring the bell.",
    )
    parser.add_argument("slug")
    parser.add_argument("message", help="What is blocking the agent.")
    parser.parse_args()
    _stub("agent-blocked")


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
    _stub("agent-list")


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
