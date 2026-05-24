"""Integration tests for the Phase-5 additions to ``agent-spawn``.

What Phase 5 adds on top of Phase 4:

- Slug normalization warning when the raw slug differs from the normalized.
- ``--resume`` / ``--suffix`` flags for non-interactive existing-slug
  handling (replacing the blanket "already exists" hard error).
- Interactive flow when ``agent-spawn`` runs with no positional slug:
  prompts for slug → resume/suffix/abort if it exists → numbered
  multi-select repo picker → branch prompt → per-repo branch-reuse
  confirm on collision.
- Branch existence pre-check before ``git worktree add``: non-interactive
  errors hard; interactive offers reuse.

Tests follow the Phase-4 pattern: real tmp git canonical, tmux + bootstrap
stubbed, stdin driven via ``io.StringIO``.
"""

from __future__ import annotations

import io
import subprocess
from pathlib import Path

import pytest

from agent_hangar import cli, config, spawn, status, tmux, workspace


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )


def _make_canonical(root: Path, name: str) -> Path:
    canonical = root / name
    canonical.mkdir()
    _git("init", "-b", "main", cwd=canonical)
    _git("config", "user.email", "test@example.com", cwd=canonical)
    _git("config", "user.name", "Test", cwd=canonical)
    (canonical / "README.md").write_text(f"{name}\n", encoding="utf-8")
    _git("add", "README.md", cwd=canonical)
    _git("commit", "-m", "seed", cwd=canonical)
    main_sha = subprocess.run(
        ["git", "rev-parse", "main"],
        cwd=canonical, capture_output=True, text=True, check=True,
    ).stdout.strip()
    _git("update-ref", "refs/remotes/origin/main", main_sha, cwd=canonical)
    return canonical


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
def two_canonicals(tmp_path: Path) -> tuple[Path, Path]:
    """Two independent tmp canonicals so per-repo branches don't cross-contaminate.

    Returns (backend, frontend) so collision tests can pre-create branches
    in one without affecting the other.
    """
    root = tmp_path / "canonicals"
    root.mkdir()
    backend = _make_canonical(root, "backend-canonical")
    frontend = _make_canonical(root, "frontend-canonical")
    return backend, frontend


@pytest.fixture
def two_repo_yaml(
    initialized_hangar: Path, two_canonicals: tuple[Path, Path]
) -> tuple[Path, Path]:
    """A repos.yaml with two entries pointing at independent canonicals."""
    backend, frontend = two_canonicals
    path = config.repos_yaml_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""
repos:
  - key: backend
    name: backend-core-nestjs
    path: {backend}
    default: true
    bootstrap: 'true'
    base_branch: origin/main
  - key: frontend
    name: frontend-web
    path: {frontend}
    default: false
    bootstrap: 'true'
    base_branch: origin/main
""",
        encoding="utf-8",
    )
    return backend, frontend


@pytest.fixture
def stub_tmux(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    recorded: list[str] = []

    def fake(slug: str, *, cwd: str) -> str:
        recorded.append(f"{slug}|{cwd}")
        return f"window `{slug}` created"

    monkeypatch.setattr(tmux, "open_workspace_window", fake)
    return recorded


@pytest.fixture
def stub_bootstrap(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    captured: list[list[str]] = []

    def fake(layout, repos):
        captured.append([r.key for r in repos])
        return []

    monkeypatch.setattr(spawn, "run_bootstraps", fake)
    return captured


# ---------- slug normalization warning ----------


def test_normalize_warning_when_raw_differs(
    work_home: Path,
    two_repo_yaml,
    stub_tmux,
    stub_bootstrap,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = _run(
        monkeypatch,
        ["agent-spawn", "Permissions Refactor", "backend", "--branch", "feature/x"],
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "normalized to 'permissions-refactor'" in captured.err


def test_no_normalize_warning_when_slug_already_clean(
    work_home: Path,
    two_repo_yaml,
    stub_tmux,
    stub_bootstrap,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = _run(
        monkeypatch,
        ["agent-spawn", "already-clean", "backend", "--branch", "feature/x"],
    )
    assert rc == 0
    err = capsys.readouterr().err
    assert "normalized to" not in err


# ---------- --resume ----------


def test_resume_flag_reattaches_existing_workspace(
    work_home: Path,
    two_repo_yaml,
    stub_tmux,
    stub_bootstrap,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # First, spawn alpha normally.
    rc = _run(monkeypatch, ["agent-spawn", "alpha", "backend", "--branch", "feature/x"])
    assert rc == 0
    capsys.readouterr()
    assert workspace.layout_for("alpha").workspace_dir.is_dir()

    # Snapshot the AGENTS.md so we can verify resume didn't rewrite it.
    agents_path = workspace.layout_for("alpha").agents_md
    original_mtime = agents_path.stat().st_mtime_ns

    # Resume.
    rc = _run(monkeypatch, ["agent-spawn", "alpha", "--resume"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "resuming workspace" in out

    # AGENTS.md untouched.
    assert agents_path.stat().st_mtime_ns == original_mtime
    # No second bootstrap fired.
    assert stub_bootstrap == [["backend"]]
    # tmux helper called twice (original + reattach), latest also pointing
    # at the alpha workspace dir.
    assert stub_tmux[-1].startswith("alpha|")


def test_resume_with_repos_is_rejected(
    work_home: Path,
    two_repo_yaml,
    stub_tmux,
    stub_bootstrap,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = _run(
        monkeypatch,
        ["agent-spawn", "alpha", "backend", "--branch", "x", "--resume"],
    )
    assert rc != 0
    err = capsys.readouterr().err
    assert "--resume cannot be combined" in err


def test_resume_without_existing_workspace_is_error(
    work_home: Path,
    two_repo_yaml,
    stub_tmux,
    stub_bootstrap,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = _run(monkeypatch, ["agent-spawn", "ghost", "--resume"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "no workspace exists" in err


# ---------- --suffix ----------


def test_suffix_flag_picks_next_available_slug(
    work_home: Path,
    two_repo_yaml,
    stub_tmux,
    stub_bootstrap,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = _run(monkeypatch, ["agent-spawn", "alpha", "backend", "--branch", "feature/x"])
    assert rc == 0
    capsys.readouterr()

    rc = _run(
        monkeypatch,
        ["agent-spawn", "alpha", "backend", "--branch", "feature/y", "--suffix"],
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "using suffixed slug 'alpha-2'" in out
    assert workspace.layout_for("alpha-2").workspace_dir.is_dir()


def test_suffix_with_no_collision_uses_base_slug(
    work_home: Path,
    two_repo_yaml,
    stub_tmux,
    stub_bootstrap,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # --suffix is a no-op when nothing collides — the user just gets the
    # base slug. The flag should not yell.
    rc = _run(
        monkeypatch,
        ["agent-spawn", "fresh", "backend", "--branch", "feature/x", "--suffix"],
    )
    assert rc == 0
    assert workspace.layout_for("fresh").workspace_dir.is_dir()


def test_resume_and_suffix_are_mutually_exclusive(
    work_home: Path,
    initialized_hangar: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = _run(monkeypatch, ["agent-spawn", "alpha", "--resume", "--suffix"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "mutually exclusive" in err


def test_existing_workspace_error_message_mentions_resume_and_suffix(
    work_home: Path,
    two_repo_yaml,
    stub_tmux,
    stub_bootstrap,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The Phase-4-style hard error remains the default; only the wording
    # changes — it now points at the new flags.
    _run(monkeypatch, ["agent-spawn", "alpha", "backend", "--branch", "feature/x"])
    capsys.readouterr()
    rc = _run(monkeypatch, ["agent-spawn", "alpha", "backend", "--branch", "feature/x"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "already exists" in err
    assert "--resume" in err
    assert "--suffix" in err


# ---------- branch collision (non-interactive) ----------


def test_branch_collision_non_interactive_errors(
    work_home: Path,
    two_repo_yaml: tuple[Path, Path],
    stub_tmux,
    stub_bootstrap,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    backend, _ = two_repo_yaml
    _git("branch", "stale-feature", cwd=backend)
    rc = _run(
        monkeypatch,
        ["agent-spawn", "alpha", "backend", "--branch", "stale-feature"],
    )
    assert rc != 0
    err = capsys.readouterr().err
    assert "branch 'stale-feature' already exists" in err
    assert "backend" in err


# ---------- interactive flow ----------


def test_interactive_full_happy_path(
    work_home: Path,
    two_repo_yaml,
    stub_tmux,
    stub_bootstrap,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Slug, then "1,2" (both repos), then branch.
    monkeypatch.setattr("sys.stdin", io.StringIO("Big Feature\n1,2\nfeature/big\n"))
    rc = _run(monkeypatch, ["agent-spawn"])
    assert rc == 0
    layout = workspace.layout_for("big-feature")
    assert layout.workspace_dir.is_dir()
    assert (layout.workspace_dir / "backend-core-nestjs").is_dir()
    assert (layout.workspace_dir / "frontend-web").is_dir()
    record = status.read_status("big-feature")
    assert record is not None
    assert record.state == "STARTING"
    # Both repos' bootstrap fired.
    assert stub_bootstrap == [["backend", "frontend"]]


def test_interactive_zero_repo_workspace(
    work_home: Path,
    two_repo_yaml,
    stub_tmux,
    stub_bootstrap,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Slug, then "none" for repos, then "y" to confirm zero-repo.
    monkeypatch.setattr("sys.stdin", io.StringIO("planning\nnone\ny\n"))
    rc = _run(monkeypatch, ["agent-spawn"])
    assert rc == 0
    assert workspace.layout_for("planning").workspace_dir.is_dir()
    assert stub_bootstrap == []


def test_interactive_picker_reprompts_on_bad_input(
    work_home: Path,
    two_repo_yaml,
    stub_tmux,
    stub_bootstrap,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Slug, then "9" (out of range), then "1", then branch.
    monkeypatch.setattr("sys.stdin", io.StringIO("alpha\n9\n1\nfeature/x\n"))
    rc = _run(monkeypatch, ["agent-spawn"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "invalid selection" in out
    assert workspace.layout_for("alpha").workspace_dir.is_dir()


def test_interactive_resume_on_existing_slug(
    work_home: Path,
    two_repo_yaml,
    stub_tmux,
    stub_bootstrap,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Seed alpha first.
    rc = _run(monkeypatch, ["agent-spawn", "alpha", "backend", "--branch", "feature/x"])
    assert rc == 0
    capsys.readouterr()

    # Interactive: type "alpha", then "r" for resume.
    monkeypatch.setattr("sys.stdin", io.StringIO("alpha\nr\n"))
    rc = _run(monkeypatch, ["agent-spawn"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "resuming workspace" in out


def test_interactive_suffix_on_existing_slug(
    work_home: Path,
    two_repo_yaml,
    stub_tmux,
    stub_bootstrap,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = _run(monkeypatch, ["agent-spawn", "alpha", "backend", "--branch", "feature/x"])
    assert rc == 0
    capsys.readouterr()

    # Slug "alpha", then "s" suffix, then "1" for repo backend, branch "feature/y".
    monkeypatch.setattr("sys.stdin", io.StringIO("alpha\ns\n1\nfeature/y\n"))
    rc = _run(monkeypatch, ["agent-spawn"])
    assert rc == 0
    assert workspace.layout_for("alpha-2").workspace_dir.is_dir()


def test_interactive_abort_on_existing_slug(
    work_home: Path,
    two_repo_yaml,
    stub_tmux,
    stub_bootstrap,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = _run(monkeypatch, ["agent-spawn", "alpha", "backend", "--branch", "feature/x"])
    assert rc == 0
    capsys.readouterr()

    monkeypatch.setattr("sys.stdin", io.StringIO("alpha\na\n"))
    rc = _run(monkeypatch, ["agent-spawn"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "aborted by user" in out


def test_interactive_branch_collision_reuse_yes(
    work_home: Path,
    two_repo_yaml: tuple[Path, Path],
    stub_tmux,
    stub_bootstrap,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    backend, _ = two_repo_yaml
    # Pre-create a non-checked-out branch in the backend canonical so the
    # collision check fires but `git worktree add` against the existing
    # branch can succeed.
    _git("branch", "stale-feature", cwd=backend)
    # Slug, pick repo 1 (backend), branch "stale-feature", then "y" to reuse.
    monkeypatch.setattr(
        "sys.stdin", io.StringIO("collide\n1\nstale-feature\ny\n")
    )
    rc = _run(monkeypatch, ["agent-spawn"])
    assert rc == 0
    layout = workspace.layout_for("collide")
    assert layout.workspace_dir.is_dir()
    assert (layout.workspace_dir / "backend-core-nestjs").is_dir()


def test_interactive_branch_collision_reuse_no_aborts(
    work_home: Path,
    two_repo_yaml: tuple[Path, Path],
    stub_tmux,
    stub_bootstrap,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    backend, _ = two_repo_yaml
    _git("branch", "stale-feature", cwd=backend)
    monkeypatch.setattr(
        "sys.stdin", io.StringIO("collide\n1\nstale-feature\nn\n")
    )
    rc = _run(monkeypatch, ["agent-spawn"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "reuse was declined" in err


def test_interactive_rejects_extra_args(
    work_home: Path,
    initialized_hangar: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # If the user passes --branch without a slug, they get a clear error.
    rc = _run(monkeypatch, ["agent-spawn", "--branch", "x"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "require an explicit slug" in err


# ---------- picker ordering ----------


def test_interactive_picker_sorts_default_first(
    work_home: Path,
    two_repo_yaml,
    stub_tmux,
    stub_bootstrap,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("ordertest\nnone\ny\n"))
    rc = _run(monkeypatch, ["agent-spawn"])
    assert rc == 0
    out = capsys.readouterr().out
    # 'backend' is default=true, 'frontend' is default=false → backend first.
    backend_pos = out.find("backend")
    frontend_pos = out.find("frontend")
    assert backend_pos != -1 and frontend_pos != -1
    assert backend_pos < frontend_pos
