"""tmux orchestration for ``hangar-checkin`` and per-agent window switches.

Every shell-out goes through :func:`_run` so tests can monkeypatch one place
to capture or simulate tmux behavior.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass

from . import config

COCKPIT_WINDOW = "cockpit"
WATCH_COMMAND = "watch -c -n 2 hangar-watch"
TMUX_BINARY = "tmux"


class TmuxError(Exception):
    """Raised when tmux can't be invoked or returns a non-zero we care about."""


@dataclass(frozen=True)
class TmuxResult:
    returncode: int
    stdout: str
    stderr: str


def _run(args: list[str], *, check: bool = False) -> TmuxResult:
    if shutil.which(TMUX_BINARY) is None:
        raise TmuxError(
            "tmux is not on PATH. Install tmux to use `hangar-checkin`."
        )
    result = subprocess.run(
        [TMUX_BINARY, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise TmuxError(
            f"tmux {' '.join(args)} failed (rc={result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return TmuxResult(result.returncode, result.stdout, result.stderr)


def has_session(name: str) -> bool:
    return _run(["has-session", "-t", name]).returncode == 0


def has_window(session: str, window: str) -> bool:
    result = _run(["list-windows", "-t", session, "-F", "#W"])
    if result.returncode != 0:
        return False
    return window in result.stdout.splitlines()


def ensure_session(name: str) -> None:
    if has_session(name):
        return
    _run(["new-session", "-d", "-s", name], check=True)


def ensure_cockpit_window(session: str, window: str = COCKPIT_WINDOW) -> None:
    """Create the cockpit window if missing.

    Layout: main pane runs ``watch -c -n 2 hangar-watch``; a shell pane sits
    next to it for ad-hoc commands. Idempotent — a second call detects the
    existing window and does nothing.
    """
    if has_window(session, window):
        return
    target = f"{session}:"
    # Create the window with a shell first, then split + send the watch command
    # into the new pane. Keeps the shell available for ad-hoc commands.
    _run(["new-window", "-t", target, "-n", window], check=True)
    _run(["split-window", "-h", "-t", f"{session}:{window}"], check=True)
    _run(
        [
            "send-keys",
            "-t",
            f"{session}:{window}.0",
            WATCH_COMMAND,
            "Enter",
        ],
        check=True,
    )


def focus(session: str, window: str = COCKPIT_WINDOW) -> None:
    """Switch the current tmux client to ``session:window``.

    If we're not inside tmux, attach instead.
    """
    target = f"{session}:{window}"
    if os.environ.get("TMUX"):
        _run(["select-window", "-t", target], check=True)
    else:
        # Attach replaces the current process with the tmux client.
        os.execvp(TMUX_BINARY, [TMUX_BINARY, "attach", "-t", session])


def open_checkin() -> str:
    """High-level entry point used by ``cli.cockpit``.

    Returns a short summary string describing what happened (created / reused),
    useful for tests and the user-visible output.
    """
    session = config.tmux_session()
    created_session = not has_session(session)
    ensure_session(session)
    created_window = not has_window(session, COCKPIT_WINDOW)
    ensure_cockpit_window(session)
    focus(session)  # may not return if we attach
    parts = []
    parts.append(
        f"session `{session}` "
        + ("created" if created_session else "reused")
    )
    parts.append(
        f"window `{COCKPIT_WINDOW}` "
        + ("created" if created_window else "reused")
    )
    return "; ".join(parts)
