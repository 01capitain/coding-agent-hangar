"""Integration tests for the Phase-4 ``agent-spawn`` flow.

Strategy: drive ``cli.spawn`` end-to-end against a real tmp git canonical
(so ``git worktree add`` actually runs). Tmux and bootstrap subprocesses
are stubbed — we don't actually need a tmux server or ``npm`` to verify
the orchestration.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from agent_hangar import cli, config, spawn, status, tmux, workspace


def _run(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> int:
    monkeypatch.setattr("sys.argv", argv)
    try:
        cli.spawn()
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    return 0


@pytest.fixture
def work_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    work = tmp_path / "agent-hangar"
    monkeypatch.setenv("AGENT_WORK_HOME", str(work))
    return work


@pytest.fixture
def repos_yaml(initialized_hangar: Path, tmp_canonical_repo: Path) -> None:
    path = config.repos_yaml_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""
repos:
  - key: backend
    name: backend-core-nestjs
    path: {tmp_canonical_repo}
    default: true
    bootstrap: 'true'
    base_branch: origin/main
""",
        encoding="utf-8",
    )


@pytest.fixture
def stub_tmux(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace tmux.open_workspace_window with a recording stub."""
    recorded: list[str] = []

    def fake(slug: str, *, cwd: str) -> str:
        recorded.append(f"{slug}|{cwd}")
        return f"window `{slug}` created"

    monkeypatch.setattr(tmux, "open_workspace_window", fake)
    return recorded


@pytest.fixture
def stub_bootstrap(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Replace spawn.run_bootstraps with a recording stub that returns []."""
    captured: list[list[str]] = []

    def fake(layout, repos):
        captured.append([r.key for r in repos])
        return []

    monkeypatch.setattr(spawn, "run_bootstraps", fake)
    return captured


def test_spawn_with_one_repo_end_to_end(
    work_home: Path,
    repos_yaml,
    tmp_canonical_repo: Path,
    stub_tmux: list[str],
    stub_bootstrap: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = _run(
        monkeypatch,
        ["agent-spawn", "Permissions Refactor", "backend", "--branch", "feature/perms"],
    )
    assert rc == 0

    # Workspace exists with normalized slug.
    layout = workspace.layout_for("permissions-refactor")
    assert layout.workspace_dir.is_dir()
    assert layout.agents_md.is_file()
    assert (layout.workspace_dir / "backend-core-nestjs").is_dir()

    # Status file written: STARTING.
    record = status.read_status("permissions-refactor")
    assert record is not None
    assert record.state == "STARTING"

    # Bootstrap was invoked with the right repo.
    assert stub_bootstrap == [["backend"]]

    # Tmux helper was called with workspace dir as cwd.
    assert stub_tmux == [f"permissions-refactor|{layout.workspace_dir}"]

    out = capsys.readouterr().out
    assert "permissions-refactor" in out
    assert "STARTING" in out


def test_spawn_rejects_repos_without_branch(
    work_home: Path,
    repos_yaml,
    stub_tmux,
    stub_bootstrap,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = _run(monkeypatch, ["agent-spawn", "alpha", "backend"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "--branch is required" in err


def test_spawn_rejects_unknown_repo_key(
    work_home: Path,
    repos_yaml,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = _run(
        monkeypatch,
        ["agent-spawn", "alpha", "nonsense", "--branch", "b"],
    )
    assert rc != 0
    err = capsys.readouterr().err
    assert "unknown repo key" in err


def test_spawn_zero_repos_aborted_at_prompt(
    work_home: Path,
    initialized_hangar: Path,
    stub_tmux,
    stub_bootstrap,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("n\n"))
    rc = _run(monkeypatch, ["agent-spawn", "planning"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "aborted" in out
    # No workspace was created.
    assert not workspace.layout_for("planning").workspace_dir.exists()


def test_spawn_zero_repos_with_yes_flag_creates_workspace(
    work_home: Path,
    initialized_hangar: Path,
    stub_tmux,
    stub_bootstrap,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rc = _run(monkeypatch, ["agent-spawn", "planning", "--yes"])
    assert rc == 0
    layout = workspace.layout_for("planning")
    assert layout.workspace_dir.is_dir()
    assert layout.agents_md.is_file()
    # No worktrees, no bootstrap invocations.
    assert stub_bootstrap == []


def test_spawn_errors_when_workspace_exists(
    work_home: Path,
    repos_yaml,
    tmp_canonical_repo: Path,
    stub_tmux,
    stub_bootstrap,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run(
        monkeypatch,
        ["agent-spawn", "alpha", "backend", "--branch", "b"],
    )
    rc = _run(
        monkeypatch,
        ["agent-spawn", "alpha", "backend", "--branch", "b"],
    )
    assert rc != 0
    err = capsys.readouterr().err
    assert "already exists" in err


def test_spawn_cleans_up_workspace_dir_when_worktree_add_fails(
    work_home: Path,
    repos_yaml,
    tmp_canonical_repo: Path,
    stub_tmux,
    stub_bootstrap,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Reproduces the breakfast-backend incident: prepare_skeleton has
    # created the workspace dir, then create_worktrees blows up. The
    # workspace dir must be gone afterwards so the slug is free for retry.
    def boom(layout, repos, *, branch, reuse_in):
        raise spawn.SpawnError("git worktree add failed: branch already checked out")

    monkeypatch.setattr(spawn, "create_worktrees", boom)

    rc = _run(
        monkeypatch,
        ["agent-spawn", "breakfast-backend", "backend", "--branch", "feature/x"],
    )
    assert rc != 0
    err = capsys.readouterr().err
    assert "git worktree add failed" in err

    layout = workspace.layout_for("breakfast-backend")
    assert not layout.workspace_dir.exists()
    # No status file written either (write_status only runs on success).
    assert not config.status_path("breakfast-backend").exists()


def test_spawn_errors_without_setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("AGENT_CONTROL_HOME", str(tmp_path / "no-hangar"))
    monkeypatch.setenv("AGENT_WORK_HOME", str(tmp_path / "work"))
    rc = _run(monkeypatch, ["agent-spawn", "alpha", "--yes"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "hangar-setup" in err
