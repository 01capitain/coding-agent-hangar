"""Workspace path layout, slug normalization, and ``.agent/`` scaffolding.

Phase 4 splits into two halves: this module owns the *local* side (paths,
the ``.agent/`` directory, AGENTS.md/CLAUDE.md, templated metadata files).
The repo-side half — ``git fetch`` / ``git worktree add`` / bootstrap
subprocesses — lives in :mod:`agent_hangar.spawn` because it sits on top of
this scaffolding.

The split matters because every function here is testable with only
``tmp_path``: no real git repos, no tmux, no network. Tests for
``agent-spawn`` end-to-end will mock the subprocess calls in ``spawn.py``
and let this module do its work for real.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path

from . import config

_SLUG_ALLOWED = re.compile(r"[^a-z0-9-]")
_SLUG_COLLAPSE_DASHES = re.compile(r"-+")
_TEMPLATE_PACKAGE = "agent_hangar.templates"


class WorkspaceError(Exception):
    """Raised for invalid slugs or workspace layout problems."""


@dataclass(frozen=True)
class WorkspaceLayout:
    """Resolved on-disk paths for one workspace.

    There is no ``prompt_md``: see ``project-no-prompt-md`` memory.
    Operator opens the agent CLI into an empty conversation and types
    the task in their first message.
    """

    slug: str
    workspace_dir: Path
    agent_dir: Path
    agents_md: Path
    claude_md: Path
    handoff_md: Path
    metadata_env: Path
    status_link: Path


# ---------- slug normalization ----------


def normalize_slug(raw: str) -> str:
    """Apply the PRD §7.3 normalization rules. Returns the normalized slug.

    Rules in order: lowercase, spaces → hyphen, drop unsupported chars,
    collapse runs of hyphens, trim leading/trailing hyphens. Raises
    :class:`WorkspaceError` if the result is empty (e.g. the input was
    ``"   "`` or ``"!!!"`` — there's nothing to make a slug out of).
    """
    if not isinstance(raw, str):
        raise WorkspaceError(f"slug must be a string, got {type(raw).__name__}")
    lowered = raw.strip().lower()
    spaced = lowered.replace(" ", "-")
    filtered = _SLUG_ALLOWED.sub("", spaced)
    collapsed = _SLUG_COLLAPSE_DASHES.sub("-", filtered)
    trimmed = collapsed.strip("-")
    if not trimmed:
        raise WorkspaceError(
            f"slug normalized to empty string from {raw!r} — "
            "use letters, digits, or hyphens."
        )
    return trimmed


# ---------- path layout ----------


def layout_for(slug: str) -> WorkspaceLayout:
    """Resolve every path a workspace needs. Pure — no FS side effects."""
    workspace_dir = config.work_home() / slug
    agent_dir = workspace_dir / ".agent"
    return WorkspaceLayout(
        slug=slug,
        workspace_dir=workspace_dir,
        agent_dir=agent_dir,
        agents_md=workspace_dir / "AGENTS.md",
        claude_md=workspace_dir / "CLAUDE.md",
        handoff_md=agent_dir / "HANDOFF.md",
        metadata_env=agent_dir / "metadata.env",
        status_link=agent_dir / "status",
    )


# ---------- skeleton creation ----------


def prepare_skeleton(
    slug: str,
    *,
    repos: list[str] | None = None,
    branch: str | None = None,
    now: datetime | None = None,
) -> WorkspaceLayout:
    """Create the workspace dir, ``.agent/``, and the templated metadata files.

    Does NOT create worktrees, does NOT open a tmux window, does NOT run
    bootstrap. Those live in :mod:`agent_hangar.spawn` and call this first.

    ``branch``, when provided, is recorded in ``metadata.env`` as
    ``BRANCH="..."``. It applies to every repo in the workspace — see the
    ``project-spawn-branch-policy`` memory. A zero-repo planning workspace
    needs no branch and can omit it.

    Refuses to clobber an existing workspace dir — the resume / suffix /
    abort flow is the caller's job (Phase 5). For Phase 4 the
    non-interactive ``agent-spawn`` simply errors when the dir exists.
    """
    if repos is None:
        repos = []
    if now is None:
        now = datetime.now(timezone.utc)

    layout = layout_for(slug)
    if layout.workspace_dir.exists():
        raise WorkspaceError(
            f"workspace directory already exists: {layout.workspace_dir}. "
            "Pick a different slug, or use the resume flow once it ships."
        )

    layout.workspace_dir.mkdir(parents=True, exist_ok=False)
    layout.agent_dir.mkdir(parents=True, exist_ok=False)

    layout.agents_md.write_text(
        _render_template("AGENTS.md.tmpl", slug=slug, repos=repos, branch=branch),
        encoding="utf-8",
    )
    _make_symlink(layout.claude_md, "AGENTS.md")

    layout.handoff_md.write_text(
        _render_template("HANDOFF.md.tmpl", slug=slug, repos=repos, branch=branch),
        encoding="utf-8",
    )
    layout.metadata_env.write_text(
        _render_metadata(
            slug=slug, repos=repos, branch=branch, now=now, layout=layout
        ),
        encoding="utf-8",
    )

    status_path = config.status_path(slug)
    # The status symlink may dangle until ``agent-status`` writes the real
    # file — that's intentional, the symlink target is stable from spawn time.
    _make_symlink(layout.status_link, str(status_path))

    return layout


# ---------- helpers ----------


def _render_template(
    template_name: str,
    *,
    slug: str,
    repos: list[str],
    branch: str | None,
) -> str:
    raw = files(_TEMPLATE_PACKAGE).joinpath(template_name).read_text(encoding="utf-8")
    return _substitute(raw, slug=slug, repos=repos, branch=branch)


def _substitute(
    text: str, *, slug: str, repos: list[str], branch: str | None
) -> str:
    workspace_path = str(config.work_home() / slug)
    repo_list = ", ".join(repos) if repos else "(no repos — planning workspace)"
    repo_bullets = "\n".join(f"- {r}" for r in repos) if repos else "_None — planning workspace._"
    replacements = {
        "{slug}": slug,
        "{workspace_path}": workspace_path,
        "{repos_inline}": repo_list,
        "{repos_bullets}": repo_bullets,
        "{branch}": branch or "(not set — zero-repo workspace)",
        "{tmux_session}": config.tmux_session(),
        "{tmux_window}": slug,
        "{agent_command}": config.agent_command(),
        "{status_path}": str(config.status_path(slug)),
    }
    for key, value in replacements.items():
        text = text.replace(key, value)
    return text


def _render_metadata(
    *,
    slug: str,
    repos: list[str],
    branch: str | None,
    now: datetime,
    layout: WorkspaceLayout,
) -> str:
    repos_str = " ".join(repos)
    created = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    lines = [
        f'SLUG="{slug}"',
        f'WORKSPACE="{layout.workspace_dir}"',
        f'REPOS="{repos_str}"',
        f'BRANCH="{branch or ""}"',
        f'TMUX_SESSION="{config.tmux_session()}"',
        f'TMUX_WINDOW="{slug}"',
        f'STATUS_FILE="{config.status_path(slug)}"',
        f'CREATED_AT="{created}"',
        "",
    ]
    return "\n".join(lines)


def _make_symlink(link: Path, target: str) -> None:
    """Create a symlink, replacing any existing one. Target is a string so the
    on-disk link is stable even if the resolved Path representation differs.
    """
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(target)
