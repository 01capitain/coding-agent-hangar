"""Phase 0 smoke test: package imports and every CLI ``--help`` works.

These tests do NOT rely on the console scripts being on ``PATH``. They drive
each CLI function directly with ``sys.argv`` monkeypatched, which is enough to
confirm that the argparse signatures are wired correctly.
"""

from __future__ import annotations

import pytest

from agent_hangar import cli

CLI_FUNCTIONS = [
    ("hangar-init", "init"),
    ("agent-spawn", "spawn"),
    ("agent-status", "status"),
    ("agent-blocked", "blocked"),
    ("agent-dashboard", "dashboard"),
    ("agent-tmux-status", "tmux_status"),
    ("agent-quota-update", "quota_update"),
    ("agent-cockpit", "cockpit"),
    ("agent-jump", "jump"),
    ("agent-list", "list_workspaces"),
    ("agent-close", "close"),
    ("agent-clean", "clean"),
]


def test_package_imports() -> None:
    import agent_hangar

    assert agent_hangar.__version__


@pytest.mark.parametrize(("prog", "func_name"), CLI_FUNCTIONS)
def test_help_exits_zero_and_mentions_prog(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    prog: str,
    func_name: str,
) -> None:
    monkeypatch.setattr("sys.argv", [prog, "--help"])
    func = getattr(cli, func_name)

    with pytest.raises(SystemExit) as excinfo:
        func()

    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert prog in captured.out
    assert "usage:" in captured.out
