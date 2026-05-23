"""Integration tests for the Phase 2 commands wired through cli.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_hangar import cli


def _run(monkeypatch: pytest.MonkeyPatch, func, argv: list[str]) -> int:
    monkeypatch.setattr("sys.argv", argv)
    try:
        func()
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    return 0


def test_hangar_watch_reads_status_files_and_prints(
    initialized_hangar: Path,
    write_status_with_age,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_status_with_age("alpha", "BLOCKED", "needs decision", age_minutes=5)
    write_status_with_age("beta", "WORKING", "investigating", age_minutes=2)

    rc = _run(monkeypatch, cli.dashboard, ["hangar-watch", "--no-color"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "BLOCKED (1)" in out
    assert "alpha" in out
    assert "WORKING (1)" in out
    assert "beta" in out


def test_hangar_watch_without_setup_errors_clearly(
    hangar_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = _run(monkeypatch, cli.dashboard, ["hangar-watch"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "hangar-setup" in err


def test_hangar_statusline_reads_status_files(
    initialized_hangar: Path,
    write_status_with_age,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_status_with_age("alpha", "BLOCKED", "x")
    write_status_with_age("beta", "WORKING", "y")

    rc = _run(monkeypatch, cli.tmux_status, ["hangar-statusline"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert out == "[B:1] [F:0] [R:0] [W:1]"


def test_hangar_statusline_silent_without_setup(
    hangar_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # No setup yet — statusline must exit 0 with empty output so tmux's
    # status-right loop doesn't spam errors.
    rc = _run(monkeypatch, cli.tmux_status, ["hangar-statusline"])
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_hangar_checkin_without_tmux_errors_clearly(
    initialized_hangar: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "agent_hangar.tmux.shutil.which", lambda _name: None
    )
    rc = _run(monkeypatch, cli.cockpit, ["hangar-checkin"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "tmux is not on PATH" in err


def test_hangar_checkin_without_setup_errors_clearly(
    hangar_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = _run(monkeypatch, cli.cockpit, ["hangar-checkin"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "hangar-setup" in err
