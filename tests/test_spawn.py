"""Tests for the subprocess half of the spawn flow.

``create_worktrees`` is exercised against a real tmp git canonical so we
catch shape errors in the git command line. ``run_bootstraps`` is driven
through an injected spawner — we never actually run ``npm ci`` in tests.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_hangar import repos as repos_mod
from agent_hangar import spawn, workspace


def _fake_completed(
    rc: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=rc, stdout=stdout, stderr=stderr
    )


# ---------- create_worktrees ----------


def test_create_worktrees_against_real_git(
    initialized_hangar: Path,
    work_home: Path,
    tmp_canonical_repo: Path,
) -> None:
    repo = repos_mod.Repo(
        key="backend",
        name="backend-core-nestjs",
        path=tmp_canonical_repo,
        default=True,
        bootstrap="",
        base_branch="origin/main",
    )
    layout = workspace.prepare_skeleton(
        "real-test",
        repos=[repo.name],
        branch="feature/test",
    )
    worktrees = spawn.create_worktrees(layout, [repo], branch="feature/test")
    assert worktrees == [layout.workspace_dir / "backend-core-nestjs"]
    assert (layout.workspace_dir / "backend-core-nestjs" / "README.md").is_file()
    # Branch was created in the canonical's branch list.
    branches = subprocess.run(
        ["git", "-C", str(tmp_canonical_repo), "branch", "--list", "feature/test"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "feature/test" in branches


def test_create_worktrees_rejects_empty_branch(
    initialized_hangar: Path,
    work_home: Path,
    tmp_canonical_repo: Path,
) -> None:
    repo = repos_mod.Repo("a", "a", tmp_canonical_repo, False, "", "origin/main")
    layout = workspace.prepare_skeleton("alpha", repos=["a"])
    with pytest.raises(spawn.SpawnError, match="branch name is required"):
        spawn.create_worktrees(layout, [repo], branch="")


def test_create_worktrees_errors_when_canonical_missing(
    initialized_hangar: Path, work_home: Path, tmp_path: Path
) -> None:
    repo = repos_mod.Repo(
        "ghost", "ghost", tmp_path / "no-such-repo", False, "", "origin/main"
    )
    layout = workspace.prepare_skeleton("alpha", repos=["ghost"], branch="b")
    with pytest.raises(spawn.SpawnError, match="canonical repo path missing"):
        spawn.create_worktrees(layout, [repo], branch="b")


def test_create_worktrees_propagates_git_failure(
    initialized_hangar: Path,
    work_home: Path,
    tmp_canonical_repo: Path,
) -> None:
    repo = repos_mod.Repo("a", "a", tmp_canonical_repo, False, "", "origin/main")
    layout = workspace.prepare_skeleton("alpha", repos=["a"], branch="b")
    calls: list[list[str]] = []

    def runner(args):
        calls.append(list(args))
        if "fetch" in args:
            return _fake_completed(rc=0)
        return _fake_completed(rc=1, stderr="boom")

    with pytest.raises(spawn.SpawnError, match="git worktree add failed"):
        spawn.create_worktrees(layout, [repo], branch="b", runner=runner)
    # Fetch was attempted before worktree-add — order matters for the user
    # to know that we did the safe step first.
    assert calls[0][:3] == ["git", "-C", str(tmp_canonical_repo)]


# ---------- branch existence ----------


def test_branch_exists_in_canonical_true_after_creation(
    initialized_hangar: Path,
    work_home: Path,
    tmp_canonical_repo: Path,
) -> None:
    repo = repos_mod.Repo(
        "backend", "backend", tmp_canonical_repo, False, "", "origin/main"
    )
    assert spawn.branch_exists_in_canonical(repo, "main") is True
    assert spawn.branch_exists_in_canonical(repo, "no-such-branch") is False


def test_check_branch_collisions_lists_only_colliders(
    initialized_hangar: Path,
    work_home: Path,
    tmp_canonical_repo: Path,
) -> None:
    repo = repos_mod.Repo(
        "backend", "backend", tmp_canonical_repo, False, "", "origin/main"
    )
    colliders = spawn.check_branch_collisions([repo], "main")
    assert [r.key for r in colliders] == ["backend"]
    assert spawn.check_branch_collisions([repo], "feature/never-used") == []


def test_branch_exists_errors_on_missing_canonical(
    tmp_path: Path,
) -> None:
    repo = repos_mod.Repo(
        "ghost", "ghost", tmp_path / "no-such", False, "", "origin/main"
    )
    with pytest.raises(spawn.SpawnError, match="canonical repo path missing"):
        spawn.branch_exists_in_canonical(repo, "main")


def test_create_worktrees_reuse_existing_branch(
    initialized_hangar: Path,
    work_home: Path,
    tmp_canonical_repo: Path,
) -> None:
    # Pre-create the branch in the canonical so we can ask create_worktrees
    # to reuse it.
    subprocess.run(
        ["git", "-C", str(tmp_canonical_repo), "branch", "preexisting"],
        check=True, capture_output=True, text=True,
    )
    repo = repos_mod.Repo(
        "backend", "backend-core-nestjs", tmp_canonical_repo, False, "", "origin/main"
    )
    layout = workspace.prepare_skeleton(
        "reuse-test", repos=[repo.name], branch="preexisting"
    )

    captured: list[list[str]] = []

    def runner(args):
        captured.append(list(args))
        return _fake_completed(rc=0)

    spawn.create_worktrees(
        layout, [repo], branch="preexisting",
        reuse_in={"backend"}, runner=runner,
    )
    # The worktree-add call must NOT use -b when reusing.
    worktree_calls = [c for c in captured if "worktree" in c]
    assert len(worktree_calls) == 1
    assert "-b" not in worktree_calls[0]
    assert "preexisting" in worktree_calls[0]


# ---------- cleanup_failed_spawn ----------


def test_cleanup_failed_spawn_removes_workspace_and_worktrees(
    initialized_hangar: Path,
    work_home: Path,
    tmp_canonical_repo: Path,
) -> None:
    # Spawn one worktree successfully, then simulate a failure for a second
    # repo and confirm cleanup removes both the workspace dir and the first
    # worktree's registration in the canonical.
    repo = repos_mod.Repo(
        key="backend",
        name="backend-core-nestjs",
        path=tmp_canonical_repo,
        default=True,
        bootstrap="",
        base_branch="origin/main",
    )
    layout = workspace.prepare_skeleton(
        "rollback-test", repos=[repo.name], branch="feature/rollback"
    )
    spawn.create_worktrees(layout, [repo], branch="feature/rollback")
    assert (layout.workspace_dir / "backend-core-nestjs").is_dir()

    spawn.cleanup_failed_spawn(layout, [repo])

    assert not layout.workspace_dir.exists()
    # The canonical no longer lists the removed worktree.
    listing = subprocess.run(
        ["git", "-C", str(tmp_canonical_repo), "worktree", "list", "--porcelain"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert str(layout.workspace_dir / "backend-core-nestjs") not in listing


def test_cleanup_failed_spawn_is_idempotent_with_no_worktrees(
    initialized_hangar: Path,
    work_home: Path,
    tmp_path: Path,
) -> None:
    # Skeleton-only workspace (no worktree subdirs created yet) is the
    # case the breakfast-backend incident hit: create_worktrees failed
    # before any add ran, leaving only the workspace dir behind.
    layout = workspace.prepare_skeleton("alpha", repos=["a"], branch="b")
    repo = repos_mod.Repo(
        "a", "a", tmp_path / "no-canonical", False, "", "origin/main"
    )
    assert layout.workspace_dir.is_dir()

    spawn.cleanup_failed_spawn(layout, [repo])

    assert not layout.workspace_dir.exists()


def test_cleanup_failed_spawn_swallows_git_errors(
    initialized_hangar: Path,
    work_home: Path,
    tmp_canonical_repo: Path,
) -> None:
    # If `git worktree remove` fails (e.g. corrupted state), cleanup must
    # still remove the workspace dir — the original SpawnError is what the
    # operator needs to see, not a noisy secondary failure.
    repo = repos_mod.Repo(
        key="backend",
        name="backend-core-nestjs",
        path=tmp_canonical_repo,
        default=True,
        bootstrap="",
        base_branch="origin/main",
    )
    layout = workspace.prepare_skeleton(
        "noisy-cleanup", repos=[repo.name], branch="feature/cleanup"
    )
    # Create the subdir + a .git marker so cleanup tries the git path.
    worktree_dir = layout.workspace_dir / "backend-core-nestjs"
    worktree_dir.mkdir()
    (worktree_dir / ".git").write_text("gitdir: /nowhere\n", encoding="utf-8")

    def runner(args):
        return _fake_completed(rc=1, stderr="boom")

    spawn.cleanup_failed_spawn(layout, [repo], runner=runner)
    assert not layout.workspace_dir.exists()


# ---------- run_bootstraps ----------


def test_run_bootstraps_skips_empty_bootstrap(
    initialized_hangar: Path,
    work_home: Path,
) -> None:
    repo = repos_mod.Repo("a", "a", Path("/dev/null"), False, "", "origin/main")
    layout = workspace.prepare_skeleton("alpha", repos=["a"], branch="b")

    spawned: list[list[str]] = []

    def spawner(args):
        spawned.append(list(args))
        return _DummyProcess(pid=42)

    handles = spawn.run_bootstraps(layout, [repo], spawner=spawner)
    assert handles == []
    assert spawned == []


def test_run_bootstraps_builds_correct_shell(
    initialized_hangar: Path,
    work_home: Path,
) -> None:
    repo = repos_mod.Repo(
        "backend",
        "backend-core-nestjs",
        Path("/var/www/backend-core-nestjs"),
        False,
        "npm ci",
        "origin/main",
    )
    layout = workspace.prepare_skeleton(
        "perms",
        repos=["backend-core-nestjs"],
        branch="feature/perms",
    )

    captured: list[list[str]] = []

    def spawner(args):
        captured.append(list(args))
        return _DummyProcess(pid=12345)

    handles = spawn.run_bootstraps(layout, [repo], spawner=spawner)

    assert len(handles) == 1
    assert handles[0].repo is repo
    assert handles[0].pid == 12345
    assert handles[0].log_path.name == "perms-backend-bootstrap.log"

    assert len(captured) == 1
    assert captured[0][:2] == ["sh", "-c"]
    script = captured[0][2]
    assert f"cd {layout.workspace_dir / 'backend-core-nestjs'}" in script
    assert "npm ci" in script
    assert "STARTING_FAILED" in script  # failure branch present
    assert "agent-status perms" in script
    assert "perms-backend-bootstrap.log" in script
    # The cd + bootstrap is wrapped so log captures both — see the
    # spawn._bootstrap_shell comment for why this matters.
    assert script.startswith("{ cd ")


def test_run_bootstraps_creates_log_dir(
    initialized_hangar: Path,
    work_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Point logs at a tmp subdir that doesn't exist yet; run_bootstraps must
    # mkdir it.
    monkeypatch.setenv("AGENT_CONTROL_HOME", str(tmp_path / "control-fresh"))
    # Recreate the status dir so prepare_skeleton's status symlink target
    # is in a valid hangar root.
    from agent_hangar import config
    config.status_dir().mkdir(parents=True, exist_ok=True)
    layout = workspace.prepare_skeleton("alpha", repos=["a"], branch="b")
    repo = repos_mod.Repo("a", "a", Path("/dev/null"), False, "true", "origin/main")
    spawn.run_bootstraps(layout, [repo], spawner=lambda args: _DummyProcess(pid=1))
    assert config.log_dir().is_dir()


# ---------- support ----------


class _DummyProcess:
    """Stand-in for ``subprocess.Popen`` — we only need ``.pid``."""

    def __init__(self, pid: int) -> None:
        self.pid = pid


@pytest.fixture
def work_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Local copy of the work_home fixture from test_workspace.py."""
    work = tmp_path / "agent-hangar"
    monkeypatch.setenv("AGENT_WORK_HOME", str(work))
    return work
