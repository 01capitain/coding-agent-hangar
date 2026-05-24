"""Tests for slug normalization, workspace path layout, and skeleton creation.

This module owns the local half of the spawn flow: paths, the ``.agent/``
directory, templated metadata files. Git worktree subprocess work and the
tmux window lifecycle live in ``spawn.py`` (Phase 4 follow-up) and have
their own tests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_hangar import config, workspace

# ---------- normalize_slug ----------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("permissions-refactor", "permissions-refactor"),
        ("Permissions Refactor", "permissions-refactor"),
        ("  Spaces around  ", "spaces-around"),
        ("UPPER_CASE", "uppercase"),  # underscores stripped per PRD §7.3
        ("multi   space", "multi-space"),  # collapse repeated hyphens
        ("trailing---", "trailing"),
        ("---leading", "leading"),
        ("mixed!@#chars", "mixedchars"),
        ("with.dots/and/slashes", "withdotsandslashes"),
        ("digits-123", "digits-123"),
        ("π-emoji-✨", "emoji"),  # non-ASCII stripped; collapsed+trimmed
    ],
)
def test_normalize_slug_happy_paths(raw: str, expected: str) -> None:
    assert workspace.normalize_slug(raw) == expected


def test_normalize_slug_rejects_empty_result() -> None:
    with pytest.raises(workspace.WorkspaceError):
        workspace.normalize_slug("!!! ???")


def test_normalize_slug_rejects_blank_input() -> None:
    with pytest.raises(workspace.WorkspaceError):
        workspace.normalize_slug("   ")


def test_normalize_slug_rejects_non_string() -> None:
    with pytest.raises(workspace.WorkspaceError):
        workspace.normalize_slug(123)  # type: ignore[arg-type]


# ---------- layout_for ----------


def test_layout_resolves_paths_under_work_home(
    initialized_hangar: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    work = tmp_path / "agent-hangar"
    monkeypatch.setenv("AGENT_WORK_HOME", str(work))
    layout = workspace.layout_for("alpha")
    assert layout.workspace_dir == work / "alpha"
    assert layout.agent_dir == work / "alpha" / ".agent"
    assert layout.agents_md == work / "alpha" / "AGENTS.md"
    assert layout.claude_md == work / "alpha" / "CLAUDE.md"
    assert layout.handoff_md == work / "alpha" / ".agent" / "HANDOFF.md"
    assert layout.metadata_env == work / "alpha" / ".agent" / "metadata.env"
    assert layout.status_link == work / "alpha" / ".agent" / "status"
    assert not hasattr(layout, "prompt_md")  # no prompt.md by design


# ---------- prepare_skeleton ----------


@pytest.fixture
def work_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Redirect AGENT_WORK_HOME at a tmp dir so workspace creation is isolated."""
    work = tmp_path / "agent-hangar"
    monkeypatch.setenv("AGENT_WORK_HOME", str(work))
    return work


def test_prepare_skeleton_creates_workspace_with_repos(
    initialized_hangar: Path, work_home: Path
) -> None:
    layout = workspace.prepare_skeleton(
        "permissions-refactor",
        repos=["backend", "frontend"],
        now=datetime(2026, 5, 24, 10, 0, 0, tzinfo=timezone.utc),
    )

    assert layout.workspace_dir.is_dir()
    assert layout.agent_dir.is_dir()
    assert layout.agents_md.is_file()
    assert layout.handoff_md.is_file()
    assert layout.metadata_env.is_file()
    # By design: no prompt.md is created.
    assert not (layout.agent_dir / "prompt.md").exists()

    # CLAUDE.md symlinks to AGENTS.md.
    assert layout.claude_md.is_symlink()
    assert layout.claude_md.readlink() == Path("AGENTS.md")

    # Status link points at the real status path even though no file exists yet.
    assert layout.status_link.is_symlink()
    expected_target = config.status_path("permissions-refactor")
    assert Path(str(layout.status_link.readlink())) == expected_target


def test_prepare_skeleton_zero_repo_workspace(
    initialized_hangar: Path, work_home: Path
) -> None:
    layout = workspace.prepare_skeleton("planning")
    assert layout.workspace_dir.is_dir()
    contents = layout.agents_md.read_text(encoding="utf-8")
    # The planning-workspace marker shows up where the repo list would.
    assert "planning workspace" in contents.lower()


def test_prepare_skeleton_refuses_to_clobber(
    initialized_hangar: Path, work_home: Path
) -> None:
    workspace.prepare_skeleton("alpha")
    with pytest.raises(workspace.WorkspaceError, match="already exists"):
        workspace.prepare_skeleton("alpha")


def test_prepare_skeleton_substitutes_slug_in_templates(
    initialized_hangar: Path, work_home: Path
) -> None:
    layout = workspace.prepare_skeleton(
        "billing-fix", repos=["backend"], branch="feature/billing"
    )
    agents = layout.agents_md.read_text(encoding="utf-8")
    assert "billing-fix" in agents
    assert "agent-mark-as-blocked billing-fix" in agents
    assert "backend" in agents
    assert "feature/billing" in agents


def test_prepare_skeleton_substitutes_branch_placeholder_for_zero_repo(
    initialized_hangar: Path, work_home: Path
) -> None:
    layout = workspace.prepare_skeleton("planning")
    agents = layout.agents_md.read_text(encoding="utf-8")
    assert "zero-repo workspace" in agents


def test_prepare_skeleton_writes_metadata_env(
    initialized_hangar: Path, work_home: Path
) -> None:
    now = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)
    layout = workspace.prepare_skeleton(
        "auth-rewrite",
        repos=["backend", "frontend"],
        branch="feature/auth",
        now=now,
    )
    text = layout.metadata_env.read_text(encoding="utf-8")
    assert 'SLUG="auth-rewrite"' in text
    assert 'REPOS="backend frontend"' in text
    assert 'BRANCH="feature/auth"' in text
    assert 'TMUX_WINDOW="auth-rewrite"' in text
    assert 'CREATED_AT="2026-05-24T12:00:00Z"' in text


def test_prepare_skeleton_branch_omitted_renders_empty(
    initialized_hangar: Path, work_home: Path
) -> None:
    # Zero-repo / planning workspace: no branch supplied; field is empty.
    layout = workspace.prepare_skeleton("planning-only")
    text = layout.metadata_env.read_text(encoding="utf-8")
    assert 'BRANCH=""' in text


def test_prepare_skeleton_respects_tmux_session_override(
    initialized_hangar: Path,
    work_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_TMUX_SESSION", "my-agents")
    layout = workspace.prepare_skeleton("alpha")
    assert 'TMUX_SESSION="my-agents"' in layout.metadata_env.read_text(encoding="utf-8")


# ---------- next_available_slug ----------


def test_next_available_slug_when_first_suffix_is_free(work_home: Path) -> None:
    (work_home / "alpha").mkdir(parents=True)
    assert workspace.next_available_slug("alpha") == "alpha-2"


def test_next_available_slug_skips_taken_suffixes(work_home: Path) -> None:
    for name in ("alpha", "alpha-2", "alpha-3"):
        (work_home / name).mkdir(parents=True)
    assert workspace.next_available_slug("alpha") == "alpha-4"


def test_next_available_slug_when_only_base_exists(work_home: Path) -> None:
    # work_home itself doesn't need to exist for the helper to work — it
    # just probes paths under it. Create the base only.
    (work_home / "solo").mkdir(parents=True)
    assert workspace.next_available_slug("solo") == "solo-2"
