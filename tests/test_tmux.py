"""Tests for the tmux orchestration layer.

Subprocess calls are captured via a recorder so tests never actually invoke
the tmux binary. The recorder also lets each test stage per-command return
values, so we can simulate "session missing" / "window present" cases.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pytest

from agent_hangar import tmux as tmux_mod


@dataclass
class _Recorded:
    args: list[str]


@pytest.fixture
def tmux_recorder(monkeypatch: pytest.MonkeyPatch):
    calls: list[_Recorded] = []
    behaviors: dict[tuple, Callable[[list[str]], tmux_mod.TmuxResult]] = {}

    def fake_run(args, *, check=False):
        calls.append(_Recorded(list(args)))
        key = tuple(args[:2])
        handler = behaviors.get(key)
        if handler is None:
            result = tmux_mod.TmuxResult(0, "", "")
        else:
            result = handler(args)
        if check and result.returncode != 0:
            raise tmux_mod.TmuxError(f"fake tmux {args} failed")
        return result

    monkeypatch.setattr(tmux_mod, "_run", fake_run)
    return calls, behaviors


def test_open_checkin_creates_session_and_window(
    monkeypatch: pytest.MonkeyPatch, tmux_recorder
) -> None:
    calls, behaviors = tmux_recorder
    # Stage: session missing → has-session returns 1; window list returns empty.
    behaviors[("has-session", "-t")] = lambda _args: tmux_mod.TmuxResult(1, "", "")
    behaviors[("list-windows", "-t")] = lambda _args: tmux_mod.TmuxResult(0, "", "")
    monkeypatch.setenv("TMUX", "/fake/tmux-socket,123,0")

    summary = tmux_mod.open_checkin()

    cmds = [c.args[0] for c in calls]
    assert "new-session" in cmds
    assert "new-window" in cmds
    assert "split-window" in cmds
    assert "send-keys" in cmds
    assert "select-window" in cmds
    # send-keys carries the watch command.
    send = next(c for c in calls if c.args[0] == "send-keys")
    assert tmux_mod.WATCH_COMMAND in send.args
    assert "created" in summary


def test_open_checkin_reuses_existing_session_and_window(
    monkeypatch: pytest.MonkeyPatch, tmux_recorder
) -> None:
    calls, behaviors = tmux_recorder
    behaviors[("has-session", "-t")] = lambda _args: tmux_mod.TmuxResult(0, "", "")
    behaviors[("list-windows", "-t")] = lambda _args: tmux_mod.TmuxResult(
        0, f"{tmux_mod.COCKPIT_WINDOW}\n", ""
    )
    monkeypatch.setenv("TMUX", "/fake/tmux-socket,123,0")

    summary = tmux_mod.open_checkin()

    cmds = [c.args[0] for c in calls]
    assert "new-session" not in cmds
    assert "new-window" not in cmds
    assert "select-window" in cmds
    assert "reused" in summary


def test_run_raises_when_tmux_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tmux_mod.shutil, "which", lambda _name: None)
    with pytest.raises(tmux_mod.TmuxError, match="tmux is not on PATH"):
        tmux_mod._run(["has-session", "-t", "x"])


def test_has_session_returns_false_on_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmux_recorder
) -> None:
    _, behaviors = tmux_recorder
    behaviors[("has-session", "-t")] = lambda _args: tmux_mod.TmuxResult(1, "", "")
    assert tmux_mod.has_session("agents") is False


def test_open_workspace_window_creates_window_and_pretypes_command(
    monkeypatch: pytest.MonkeyPatch, tmux_recorder
) -> None:
    calls, behaviors = tmux_recorder
    # Session exists, window does not.
    behaviors[("has-session", "-t")] = lambda _args: tmux_mod.TmuxResult(0, "", "")
    behaviors[("list-windows", "-t")] = lambda _args: tmux_mod.TmuxResult(0, "", "")
    monkeypatch.setenv("TMUX", "/fake/tmux-socket,123,0")
    monkeypatch.setenv("AGENT_COMMAND", "claude")

    summary = tmux_mod.open_workspace_window("perms-refactor", cwd="/tmp/perms")

    new_window = next(c for c in calls if c.args[0] == "new-window")
    assert "-n" in new_window.args
    assert "perms-refactor" in new_window.args
    assert "-c" in new_window.args
    assert "/tmp/perms" in new_window.args

    send = next(c for c in calls if c.args[0] == "send-keys")
    assert "claude" in send.args
    # CRITICAL: no trailing "Enter" — the operator hits Enter when ready.
    assert "Enter" not in send.args

    assert "created" in summary


def test_open_workspace_window_reuses_existing(
    monkeypatch: pytest.MonkeyPatch, tmux_recorder
) -> None:
    calls, behaviors = tmux_recorder
    behaviors[("has-session", "-t")] = lambda _args: tmux_mod.TmuxResult(0, "", "")
    behaviors[("list-windows", "-t")] = lambda _args: tmux_mod.TmuxResult(
        0, "perms-refactor\n", ""
    )
    monkeypatch.setenv("TMUX", "/fake/tmux-socket,123,0")

    summary = tmux_mod.open_workspace_window("perms-refactor", cwd="/tmp/perms")

    cmds = [c.args[0] for c in calls]
    assert "new-window" not in cmds
    assert "send-keys" not in cmds
    assert "select-window" in cmds
    assert "reused" in summary
