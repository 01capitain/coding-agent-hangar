"""Integration tests for the Phase-6 ``agent-jump`` command.

Phase 6 wires the cockpit-to-workspace shortcut:

- ``agent-jump <slug>`` focuses the workspace's tmux window.
- ``agent-jump blocked`` / ``agent-jump feedback`` filter the status
  records by state. Zero matches → error; one match → auto-jump;
  many matches → interactive numbered picker.

The tmux helper is stubbed so we don't need a real tmux server. Status
files are seeded via :func:`status.write_status`.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from agent_hangar import cli, status, tmux, workspace


def _run(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> int:
    monkeypatch.setattr("sys.argv", argv)
    try:
        cli.jump()
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    return 0


@pytest.fixture
def work_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    work = tmp_path / "agent-hangar"
    monkeypatch.setenv("AGENT_WORK_HOME", str(work))
    return work


@pytest.fixture
def stub_tmux(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    recorded: list[str] = []

    def fake(slug: str, *, cwd: str) -> str:
        recorded.append(f"{slug}|{cwd}")
        return f"window `{slug}` reused"

    monkeypatch.setattr(tmux, "open_workspace_window", fake)
    return recorded


def _seed_workspace(work_home: Path, slug: str) -> None:
    """Create a minimal on-disk workspace dir so the slug-jump path finds it."""
    (work_home / slug).mkdir(parents=True, exist_ok=True)


# ---------- slug path ----------


def test_jump_to_slug_focuses_workspace(
    work_home: Path,
    initialized_hangar: Path,
    stub_tmux: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_workspace(work_home, "alpha")
    rc = _run(monkeypatch, ["agent-jump", "alpha"])
    assert rc == 0
    assert stub_tmux == [f"alpha|{work_home / 'alpha'}"]
    out = capsys.readouterr().out
    assert "focusing alpha" in out


def test_jump_to_slug_normalizes_with_warning(
    work_home: Path,
    initialized_hangar: Path,
    stub_tmux: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_workspace(work_home, "permissions-refactor")
    rc = _run(monkeypatch, ["agent-jump", "Permissions Refactor"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "normalized to 'permissions-refactor'" in captured.err
    assert stub_tmux == [f"permissions-refactor|{work_home / 'permissions-refactor'}"]


def test_jump_to_missing_slug_errors(
    work_home: Path,
    initialized_hangar: Path,
    stub_tmux: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = _run(monkeypatch, ["agent-jump", "ghost"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "no workspace matches 'ghost'" in err
    assert stub_tmux == []


# ---------- category: blocked ----------


def test_jump_blocked_zero_matches_errors(
    work_home: Path,
    initialized_hangar: Path,
    stub_tmux: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = _run(monkeypatch, ["agent-jump", "blocked"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "no BLOCKED workspaces" in err
    assert stub_tmux == []


def test_jump_blocked_one_match_auto_jumps(
    work_home: Path,
    initialized_hangar: Path,
    stub_tmux: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_workspace(work_home, "alpha")
    status.write_status("alpha", "BLOCKED", "waiting on API spec")
    # A non-blocked workspace should be ignored.
    _seed_workspace(work_home, "beta")
    status.write_status("beta", "WORKING", "humming along")

    rc = _run(monkeypatch, ["agent-jump", "blocked"])
    assert rc == 0
    assert stub_tmux == [f"alpha|{work_home / 'alpha'}"]


def test_jump_blocked_many_picker_happy(
    work_home: Path,
    initialized_hangar: Path,
    stub_tmux: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for slug in ("alpha", "billing-fix"):
        _seed_workspace(work_home, slug)
        status.write_status(slug, "BLOCKED", f"{slug} reason")

    # Pick the second entry.
    monkeypatch.setattr("sys.stdin", io.StringIO("2\n"))
    rc = _run(monkeypatch, ["agent-jump", "blocked"])
    assert rc == 0
    assert len(stub_tmux) == 1
    # We don't lock to a specific order — both blocked were written in the
    # same second so timestamps are equal. Just verify the chosen one is
    # one of the two seeded slugs.
    chosen = stub_tmux[0].split("|", 1)[0]
    assert chosen in {"alpha", "billing-fix"}


def test_jump_blocked_picker_aborts_on_a(
    work_home: Path,
    initialized_hangar: Path,
    stub_tmux: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for slug in ("alpha", "beta"):
        _seed_workspace(work_home, slug)
        status.write_status(slug, "BLOCKED", "reason")

    monkeypatch.setattr("sys.stdin", io.StringIO("a\n"))
    rc = _run(monkeypatch, ["agent-jump", "blocked"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "aborted by user" in out
    assert stub_tmux == []


def test_jump_blocked_picker_reprompts_on_bad_input(
    work_home: Path,
    initialized_hangar: Path,
    stub_tmux: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for slug in ("alpha", "beta"):
        _seed_workspace(work_home, slug)
        status.write_status(slug, "BLOCKED", "reason")

    # Out-of-range, then non-numeric, then valid.
    monkeypatch.setattr("sys.stdin", io.StringIO("99\nnope\n1\n"))
    rc = _run(monkeypatch, ["agent-jump", "blocked"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "out of range" in out
    assert "expected a number" in out
    assert len(stub_tmux) == 1


# ---------- category: feedback ----------


def test_jump_feedback_one_match(
    work_home: Path,
    initialized_hangar: Path,
    stub_tmux: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_workspace(work_home, "review-me")
    status.write_status("review-me", "NEEDS_FEEDBACK", "PR review please")
    rc = _run(monkeypatch, ["agent-jump", "feedback"])
    assert rc == 0
    assert stub_tmux == [f"review-me|{work_home / 'review-me'}"]


def test_jump_feedback_zero_matches_errors(
    work_home: Path,
    initialized_hangar: Path,
    stub_tmux: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_workspace(work_home, "alpha")
    status.write_status("alpha", "BLOCKED", "wrong state")
    rc = _run(monkeypatch, ["agent-jump", "feedback"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "no NEEDS_FEEDBACK workspaces" in err


# ---------- category target is case-insensitive ----------


def test_jump_category_label_is_case_insensitive(
    work_home: Path,
    initialized_hangar: Path,
    stub_tmux: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_workspace(work_home, "alpha")
    status.write_status("alpha", "BLOCKED", "reason")
    rc = _run(monkeypatch, ["agent-jump", "BLOCKED"])
    assert rc == 0
    assert stub_tmux == [f"alpha|{work_home / 'alpha'}"]


# ---------- missing control dir ----------


def test_jump_errors_without_setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("AGENT_CONTROL_HOME", str(tmp_path / "no-hangar"))
    monkeypatch.setenv("AGENT_WORK_HOME", str(tmp_path / "work"))
    rc = _run(monkeypatch, ["agent-jump", "alpha"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "hangar-setup" in err


# ---------- stale-status guard ----------


def test_jump_blocked_skips_when_workspace_dir_missing(
    work_home: Path,
    initialized_hangar: Path,
    stub_tmux: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Write a BLOCKED status but never create the workspace dir.
    status.write_status("orphan", "BLOCKED", "reason")
    # Make sure the workspace dir really doesn't exist.
    assert not workspace.layout_for("orphan").workspace_dir.exists()

    rc = _run(monkeypatch, ["agent-jump", "blocked"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "workspace dir is missing" in err
