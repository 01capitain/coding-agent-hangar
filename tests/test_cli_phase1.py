"""Integration tests for the Phase 1 commands wired through cli.py.

These drive each entrypoint via sys.argv monkeypatching and capture stdout/stderr
to assert end-to-end behavior with AGENT_CONTROL_HOME pointed at tmp_path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_hangar import cli, config
from agent_hangar import status as status_mod


def _run(monkeypatch: pytest.MonkeyPatch, func, argv: list[str]) -> int:
    monkeypatch.setattr("sys.argv", argv)
    try:
        func()
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    return 0


def test_hangar_setup_creates_dirs_and_repos_yaml(
    hangar_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = _run(monkeypatch, cli.init, ["hangar-setup"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Hangar root" in out
    assert "repos.yaml" in out
    assert config.repos_yaml_path().exists()


def test_agent_status_writes_and_agent_list_reads(
    hangar_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(monkeypatch, cli.init, ["hangar-setup"])
    capsys.readouterr()  # flush init output

    rc = _run(
        monkeypatch,
        cli.status,
        ["agent-status", "permissions-refactor", "WORKING", "looking at guards"],
    )
    assert rc == 0

    rc = _run(monkeypatch, cli.list_workspaces, ["agent-list"])
    assert rc == 0

    out = capsys.readouterr().out
    assert "permissions-refactor" in out
    assert "WORKING" in out
    assert "looking at guards" in out


def test_agent_list_without_setup_errors_clearly(
    hangar_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = _run(monkeypatch, cli.list_workspaces, ["agent-list"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "hangar-setup" in err


def test_agent_status_rejects_unknown_state(
    hangar_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(monkeypatch, cli.init, ["hangar-setup"])
    capsys.readouterr()

    # argparse rejects with exit code 2 before our code runs.
    rc = _run(monkeypatch, cli.status, ["agent-status", "foo", "ON_FIRE", "nope"])
    assert rc == 2


def test_agent_blocked_writes_status_rings_bell_and_calls_tmux(
    hangar_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(monkeypatch, cli.init, ["hangar-setup"])
    capsys.readouterr()

    tmux_calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        tmux_calls.append(list(cmd))

        class _R:
            returncode = 0

        return _R()

    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    rc = _run(monkeypatch, cli.blocked, ["agent-blocked", "alpha", "Need API token"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "\a" in captured.err
    assert "BLOCKED" in captured.out
    assert any("tmux" in c[0] for c in tmux_calls)
    assert any("display-message" in c for c in tmux_calls[0])
    assert any("Need API token" in part for part in tmux_calls[0])


def test_agent_blocked_does_not_fail_without_tmux(
    hangar_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(monkeypatch, cli.init, ["hangar-setup"])
    capsys.readouterr()

    monkeypatch.setattr(cli.shutil, "which", lambda _name: None)

    rc = _run(monkeypatch, cli.blocked, ["agent-blocked", "beta", "stuck"])
    assert rc == 0


def test_agent_list_orders_by_state_priority(
    hangar_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(monkeypatch, cli.init, ["hangar-setup"])
    capsys.readouterr()

    status_mod.write_status("done-one", "DONE", "finished a while ago")
    status_mod.write_status("working-one", "WORKING", "still going")
    status_mod.write_status("blocked-one", "BLOCKED", "needs a decision")

    rc = _run(monkeypatch, cli.list_workspaces, ["agent-list"])
    assert rc == 0
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    body = [line for line in lines if not line.startswith(("SLUG", "----"))]
    slugs_in_order = [line.split()[0] for line in body]
    assert slugs_in_order == ["blocked-one", "working-one", "done-one"]
