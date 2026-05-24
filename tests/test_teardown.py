"""Tests for the teardown module's git probes + destructive primitives.

The orchestrator (``cli.teardown``) is tested in test_cli_phase7.py;
this file isolates the building blocks against a real tmp canonical so
git command shapes are verified without stdin or output capture.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_hangar import config, spawn, teardown, workspace
from agent_hangar import repos as repos_mod


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )


@pytest.fixture
def work_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    work = tmp_path / "agent-work"
    monkeypatch.setenv("AGENT_WORK_HOME", str(work))
    return work


# ---------- read_metadata ----------


def test_read_metadata_parses_quoted_values(
    initialized_hangar: Path, work_home: Path
) -> None:
    layout = workspace.prepare_skeleton(
        "alpha", repos=["a"], branch="feature/x",
        now=datetime(2026, 5, 24, tzinfo=timezone.utc),
    )
    meta = teardown.read_metadata(layout)
    assert meta["SLUG"] == "alpha"
    assert meta["BRANCH"] == "feature/x"
    assert meta["REPOS"] == "a"


def test_read_metadata_missing_returns_empty(
    initialized_hangar: Path, work_home: Path
) -> None:
    layout = workspace.layout_for("ghost")
    assert teardown.read_metadata(layout) == {}


# ---------- find_worktree_dirs ----------


def test_find_worktree_dirs_returns_real_worktrees_only(
    initialized_hangar: Path,
    work_home: Path,
    tmp_canonical_repo: Path,
) -> None:
    repo = repos_mod.Repo(
        "backend", "backend", tmp_canonical_repo, False, "", "origin/main"
    )
    layout = workspace.prepare_skeleton(
        "alpha", repos=["backend"], branch="feature/x"
    )
    spawn.create_worktrees(layout, [repo], branch="feature/x")

    # Plant a non-worktree directory to verify it's ignored.
    (layout.workspace_dir / "notes").mkdir()
    (layout.workspace_dir / "notes" / "README.md").write_text("scratch\n")

    dirs = teardown.find_worktree_dirs(layout)
    assert [p.name for p in dirs] == ["backend"]


def test_find_worktree_dirs_empty_workspace(
    initialized_hangar: Path, work_home: Path
) -> None:
    layout = workspace.prepare_skeleton("planning")
    assert teardown.find_worktree_dirs(layout) == []


# ---------- probe_worktree ----------


def test_probe_worktree_detects_clean_and_merged(
    initialized_hangar: Path,
    work_home: Path,
    tmp_canonical_repo: Path,
) -> None:
    repo = repos_mod.Repo(
        "backend", "backend", tmp_canonical_repo, False, "", "origin/main"
    )
    layout = workspace.prepare_skeleton(
        "clean-merge", repos=["backend"], branch="feature/clean"
    )
    spawn.create_worktrees(layout, [repo], branch="feature/clean")
    worktree = layout.workspace_dir / "backend"

    ws = teardown.probe_worktree(worktree, base_branch="origin/main")
    assert ws.uncommitted is False
    assert ws.branch == "feature/clean"
    # The new branch is created off origin/main, so origin/main IS an
    # ancestor of feature/clean — merged_into_base is True.
    assert ws.merged_into_base is True


def test_probe_worktree_detects_uncommitted(
    initialized_hangar: Path,
    work_home: Path,
    tmp_canonical_repo: Path,
) -> None:
    repo = repos_mod.Repo(
        "backend", "backend", tmp_canonical_repo, False, "", "origin/main"
    )
    layout = workspace.prepare_skeleton(
        "dirty", repos=["backend"], branch="feature/dirty"
    )
    spawn.create_worktrees(layout, [repo], branch="feature/dirty")
    worktree = layout.workspace_dir / "backend"
    (worktree / "new-file.txt").write_text("hello\n")

    ws = teardown.probe_worktree(worktree, base_branch="origin/main")
    assert ws.uncommitted is True
    assert "new-file.txt" in ws.short_status


def test_probe_worktree_detects_not_merged_after_commit(
    initialized_hangar: Path,
    work_home: Path,
    tmp_canonical_repo: Path,
) -> None:
    repo = repos_mod.Repo(
        "backend", "backend", tmp_canonical_repo, False, "", "origin/main"
    )
    layout = workspace.prepare_skeleton(
        "diverged", repos=["backend"], branch="feature/diverged"
    )
    spawn.create_worktrees(layout, [repo], branch="feature/diverged")
    worktree = layout.workspace_dir / "backend"
    # Commit a change so feature/diverged is no longer an ancestor of
    # origin/main.
    (worktree / "feature.txt").write_text("hi\n")
    _git("add", "feature.txt", cwd=worktree)
    _git(
        "-c", "user.email=test@example.com",
        "-c", "user.name=Test",
        "commit", "-m", "diverge",
        cwd=worktree,
    )

    ws = teardown.probe_worktree(worktree, base_branch="origin/main")
    assert ws.merged_into_base is False


# ---------- canonical_for ----------


def test_canonical_for_resolves_back_to_canonical(
    initialized_hangar: Path,
    work_home: Path,
    tmp_canonical_repo: Path,
) -> None:
    repo = repos_mod.Repo(
        "backend", "backend", tmp_canonical_repo, False, "", "origin/main"
    )
    layout = workspace.prepare_skeleton(
        "alpha", repos=["backend"], branch="feature/x"
    )
    spawn.create_worktrees(layout, [repo], branch="feature/x")
    worktree = layout.workspace_dir / "backend"
    assert teardown.canonical_for(worktree) == tmp_canonical_repo


# ---------- destructive ----------


def test_remove_worktree_cleans_canonical_registration(
    initialized_hangar: Path,
    work_home: Path,
    tmp_canonical_repo: Path,
) -> None:
    repo = repos_mod.Repo(
        "backend", "backend", tmp_canonical_repo, False, "", "origin/main"
    )
    layout = workspace.prepare_skeleton(
        "alpha", repos=["backend"], branch="feature/x"
    )
    spawn.create_worktrees(layout, [repo], branch="feature/x")
    worktree = layout.workspace_dir / "backend"

    teardown.remove_worktree(worktree)
    assert not worktree.exists()
    # `git worktree list` no longer shows our worktree.
    listing = subprocess.run(
        ["git", "-C", str(tmp_canonical_repo), "worktree", "list"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert str(worktree) not in listing


def test_remove_worktree_force_handles_dirty(
    initialized_hangar: Path,
    work_home: Path,
    tmp_canonical_repo: Path,
) -> None:
    repo = repos_mod.Repo(
        "backend", "backend", tmp_canonical_repo, False, "", "origin/main"
    )
    layout = workspace.prepare_skeleton(
        "dirty-remove", repos=["backend"], branch="feature/x"
    )
    spawn.create_worktrees(layout, [repo], branch="feature/x")
    worktree = layout.workspace_dir / "backend"
    (worktree / "scratch.txt").write_text("scratch\n")

    with pytest.raises(teardown.TeardownError):
        teardown.remove_worktree(worktree)
    # With force, the same call succeeds.
    teardown.remove_worktree(worktree, force=True)
    assert not worktree.exists()


def test_delete_branch_safe_refuses_unmerged(
    initialized_hangar: Path,
    work_home: Path,
    tmp_canonical_repo: Path,
) -> None:
    repo = repos_mod.Repo(
        "backend", "backend", tmp_canonical_repo, False, "", "origin/main"
    )
    layout = workspace.prepare_skeleton(
        "branchtest", repos=["backend"], branch="feature/unmerged"
    )
    spawn.create_worktrees(layout, [repo], branch="feature/unmerged")
    worktree = layout.workspace_dir / "backend"
    (worktree / "x.txt").write_text("x\n")
    _git("add", "x.txt", cwd=worktree)
    _git(
        "-c", "user.email=test@example.com",
        "-c", "user.name=Test",
        "commit", "-m", "diverge", cwd=worktree,
    )
    teardown.remove_worktree(worktree)

    # `git branch -d` should refuse the unmerged branch.
    with pytest.raises(teardown.TeardownError):
        teardown.delete_branch(tmp_canonical_repo, "feature/unmerged")
    # With force, deletion succeeds.
    teardown.delete_branch(
        tmp_canonical_repo, "feature/unmerged", force=True
    )
    branches = subprocess.run(
        ["git", "-C", str(tmp_canonical_repo), "branch", "--list", "feature/unmerged"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert branches.strip() == ""


# ---------- archive_status_file ----------


def test_archive_status_file_moves_into_archive(
    initialized_hangar: Path, work_home: Path
) -> None:
    from agent_hangar import status

    status.write_status("alpha", "DONE", "all good")
    src = config.status_path("alpha")
    assert src.exists()

    now = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)
    archive = teardown.archive_status_file("alpha", now=now)
    assert archive is not None
    assert archive.name == "alpha-20260524T120000Z.status"
    assert archive.exists()
    assert not src.exists()


def test_archive_status_file_returns_none_when_missing(
    initialized_hangar: Path, work_home: Path
) -> None:
    assert teardown.archive_status_file("never-existed") is None


# ---------- remove_workspace_dir ----------


def test_remove_workspace_dir_recursive(
    initialized_hangar: Path, work_home: Path
) -> None:
    layout = workspace.prepare_skeleton("toremove")
    assert layout.workspace_dir.exists()
    teardown.remove_workspace_dir(layout)
    assert not layout.workspace_dir.exists()


def test_remove_workspace_dir_idempotent_when_missing(
    initialized_hangar: Path, work_home: Path
) -> None:
    layout = workspace.layout_for("never-there")
    # Should not raise.
    teardown.remove_workspace_dir(layout)
