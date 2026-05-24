"""Integration tests for Phase-7 commands: agent-mark-done and agent-teardown.

``agent-mark-done`` mirrors ``agent-mark-as-blocked`` — state write, bell,
tmux display-message. ``agent-teardown`` drives a guided checklist
against a real tmp git canonical so the worktree-remove and branch-delete
paths exercise real git commands. Stdin is driven via :class:`io.StringIO`
to script the prompt sequence.
"""

from __future__ import annotations

import io
import subprocess
from pathlib import Path

import pytest

from agent_hangar import cli, config, spawn, status, workspace
from agent_hangar import repos as repos_mod


def _run(monkeypatch: pytest.MonkeyPatch, func, argv: list[str]) -> int:
    monkeypatch.setattr("sys.argv", argv)
    try:
        func()
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    return 0


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )


@pytest.fixture
def work_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    work = tmp_path / "agent-hangar"
    monkeypatch.setenv("AGENT_WORK_HOME", str(work))
    return work


# ============================================================
# agent-mark-done
# ============================================================


def test_mark_done_writes_status_and_rings_bell(
    initialized_hangar: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tmux_calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        tmux_calls.append(list(cmd))

        class _R:
            returncode = 0

        return _R()

    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    rc = _run(
        monkeypatch, cli.mark_done,
        ["agent-mark-done", "alpha", "shipped"],
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "\a" in captured.err
    assert "DONE" in captured.out

    record = status.read_status("alpha")
    assert record is not None
    assert record.state == "DONE"
    assert record.summary == "shipped"

    assert any("display-message" in c for c in tmux_calls[0])
    assert any("DONE" in part for part in tmux_calls[0])


def test_mark_done_survives_no_tmux(
    initialized_hangar: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.shutil, "which", lambda _name: None)
    rc = _run(
        monkeypatch, cli.mark_done,
        ["agent-mark-done", "beta", "no tmux"],
    )
    assert rc == 0


# ============================================================
# agent-teardown — setup helpers
# ============================================================


@pytest.fixture
def spawned_alpha(
    initialized_hangar: Path,
    work_home: Path,
    tmp_canonical_repo: Path,
) -> tuple[workspace.WorkspaceLayout, Path]:
    """Spawn 'alpha' with one worktree on feature/x — the common starting state."""
    repo = repos_mod.Repo(
        "backend", "backend-core-nestjs", tmp_canonical_repo,
        False, "", "origin/main",
    )
    layout = workspace.prepare_skeleton(
        "alpha", repos=[repo.name], branch="feature/x"
    )
    spawn.create_worktrees(layout, [repo], branch="feature/x")
    status.write_status("alpha", "WORKING", "going")
    return layout, tmp_canonical_repo


# ============================================================
# agent-teardown — error paths
# ============================================================


def test_teardown_errors_without_setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("AGENT_CONTROL_HOME", str(tmp_path / "no-hangar"))
    monkeypatch.setenv("AGENT_WORK_HOME", str(tmp_path / "work"))
    rc = _run(monkeypatch, cli.teardown, ["agent-teardown", "alpha"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "hangar-setup" in err


def test_teardown_errors_when_workspace_missing(
    initialized_hangar: Path,
    work_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = _run(monkeypatch, cli.teardown, ["agent-teardown", "ghost"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "no workspace at" in err


def test_teardown_refuses_dirty_without_force(
    spawned_alpha,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    layout, _canonical = spawned_alpha
    (layout.workspace_dir / "backend-core-nestjs" / "scratch.txt").write_text("x")

    rc = _run(monkeypatch, cli.teardown, ["agent-teardown", "alpha"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "uncommitted changes" in err
    assert "--force" in err
    # Worktree still exists — refusal must not destroy anything.
    assert (layout.workspace_dir / "backend-core-nestjs").exists()


# ============================================================
# agent-teardown — happy paths
# ============================================================


def test_teardown_full_yes_path_clears_everything(
    spawned_alpha,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    layout, canonical = spawned_alpha
    # Prompts in order: PR opened?, PR merged?, remove worktree?, delete branch?
    monkeypatch.setattr("sys.stdin", io.StringIO("y\ny\ny\ny\n"))

    rc = _run(monkeypatch, cli.teardown, ["agent-teardown", "alpha"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "removed worktree" in out
    assert "deleted branch" in out
    assert "archived status" in out
    assert "removed workspace dir" in out

    # Workspace gone.
    assert not layout.workspace_dir.exists()
    # Branch gone from canonical.
    branches = subprocess.run(
        ["git", "-C", str(canonical), "branch", "--list", "feature/x"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert branches.strip() == ""
    # Status archived: original gone, archive has one matching file.
    assert not config.status_path("alpha").exists()
    archived = list(config.status_archive_dir().glob("alpha-*.status"))
    assert len(archived) == 1


def test_teardown_zero_repo_workspace(
    initialized_hangar: Path,
    work_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    layout = workspace.prepare_skeleton("planning")
    status.write_status("planning", "DONE", "thinking is done")

    # Only PR-opened and PR-merged prompts fire (no worktree-level prompts).
    monkeypatch.setattr("sys.stdin", io.StringIO("n\nn\n"))
    rc = _run(monkeypatch, cli.teardown, ["agent-teardown", "planning"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "zero-repo workspace" in out
    assert "removed workspace dir" in out
    assert not layout.workspace_dir.exists()
    archived = list(config.status_archive_dir().glob("planning-*.status"))
    assert len(archived) == 1


# ============================================================
# agent-teardown — partial-no paths
# ============================================================


def test_teardown_keeps_worktree_when_user_says_no(
    spawned_alpha,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    layout, canonical = spawned_alpha
    # PR opened, PR merged, remove worktree=N (branch prompt is skipped).
    monkeypatch.setattr("sys.stdin", io.StringIO("y\ny\nn\n"))

    rc = _run(monkeypatch, cli.teardown, ["agent-teardown", "alpha"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "skipped" in out
    # Worktree + branch intact.
    assert (layout.workspace_dir / "backend-core-nestjs").exists()
    branches = subprocess.run(
        ["git", "-C", str(canonical), "branch", "--list", "feature/x"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "feature/x" in branches
    # Workspace dir NOT removed because a worktree remains inside.
    assert layout.workspace_dir.exists()
    assert "workspace dir kept" in out


def test_teardown_keeps_branch_when_user_says_no(
    spawned_alpha,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    layout, canonical = spawned_alpha
    # PR opened, PR merged, remove worktree=Y, delete branch=N.
    monkeypatch.setattr("sys.stdin", io.StringIO("y\ny\ny\nn\n"))

    rc = _run(monkeypatch, cli.teardown, ["agent-teardown", "alpha"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "removed worktree" in out
    assert "kept branch" in out
    # Worktree gone, branch still alive in canonical.
    assert not (layout.workspace_dir / "backend-core-nestjs").exists()
    branches = subprocess.run(
        ["git", "-C", str(canonical), "branch", "--list", "feature/x"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "feature/x" in branches
    # All worktrees removed → workspace dir removed.
    assert not layout.workspace_dir.exists()


def test_teardown_force_proceeds_through_dirty_and_unmerged(
    spawned_alpha,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    layout, canonical = spawned_alpha
    worktree = layout.workspace_dir / "backend-core-nestjs"
    # Dirty + diverged.
    (worktree / "feature.txt").write_text("hi\n")
    _git("add", "feature.txt", cwd=worktree)
    _git(
        "-c", "user.email=test@example.com",
        "-c", "user.name=Test",
        "commit", "-m", "diverge", cwd=worktree,
    )
    # And then dirty on top.
    (worktree / "scratch.txt").write_text("scratch\n")

    monkeypatch.setattr("sys.stdin", io.StringIO("y\ny\ny\ny\n"))
    rc = _run(
        monkeypatch, cli.teardown,
        ["agent-teardown", "alpha", "--force"],
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "removed worktree" in out
    assert "deleted branch" in out
    assert not layout.workspace_dir.exists()
    branches = subprocess.run(
        ["git", "-C", str(canonical), "branch", "--list", "feature/x"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert branches.strip() == ""


def test_teardown_normalizes_slug_with_warning(
    spawned_alpha,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # alpha is already on disk; passing "Alpha" should normalize+warn.
    monkeypatch.setattr("sys.stdin", io.StringIO("y\ny\ny\ny\n"))
    rc = _run(monkeypatch, cli.teardown, ["agent-teardown", "Alpha"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "normalized to 'alpha'" in err
