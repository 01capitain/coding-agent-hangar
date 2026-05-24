"""Guided cleanup of an agent workspace: data probes + destructive actions.

This module owns the **mechanics** of teardown — reading the workspace
metadata, asking git questions about each worktree, removing worktrees,
deleting branches, archiving the status file, and removing the workspace
directory. The **policy** half — when to prompt, how to render output,
whether to refuse uncommitted work — lives in :func:`cli.teardown`.

The split keeps the destructive primitives testable without driving them
through stdin. ``cli.teardown`` is the orchestrator; the heavy git work
sits here.

Subprocess calls are routed through an injected ``runner`` callable so
tests can capture commands without monkeypatching ``subprocess``.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from . import config
from .workspace import WorkspaceLayout


class TeardownError(Exception):
    """Raised on git failures, missing metadata, or invalid workspace state."""


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _default_runner(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), capture_output=True, text=True, check=False)


# ---------- metadata ----------


def read_metadata(layout: WorkspaceLayout) -> dict[str, str]:
    """Parse ``.agent/metadata.env`` into a dict.

    Lines look like ``KEY="value"`` per :mod:`workspace`'s renderer.
    Missing file → empty dict (teardown will fall back to scanning the
    workspace dir for worktree subdirs).
    """
    if not layout.metadata_env.exists():
        return {}
    result: dict[str, str] = {}
    for line in layout.metadata_env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, raw = line.partition("=")
        value = raw.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        result[key.strip()] = value
    return result


# ---------- worktree discovery ----------


def find_worktree_dirs(layout: WorkspaceLayout) -> list[Path]:
    """Return the worktree dirs in this workspace, in directory order.

    A worktree dir is any direct child of the workspace dir that contains
    a ``.git`` entry (file for worktrees, directory for the canonical —
    here we only see worktrees so the ``.git`` entry is a file).
    """
    if not layout.workspace_dir.is_dir():
        return []
    found: list[Path] = []
    for child in sorted(layout.workspace_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("."):
            continue  # skip .agent/, etc.
        if (child / ".git").exists():
            found.append(child)
    return found


# ---------- per-worktree probe ----------


@dataclass(frozen=True)
class WorktreeStatus:
    path: Path
    branch: str
    short_status: str  # `git status --short --branch` output, stripped
    uncommitted: bool
    merged_into_base: bool | None  # None when the check itself couldn't run
    base_branch: str


def probe_worktree(
    worktree: Path,
    base_branch: str,
    *,
    runner: CommandRunner | None = None,
) -> WorktreeStatus:
    """Run the read-only git probes against one worktree.

    Returns a :class:`WorktreeStatus`. Never raises for git non-zero —
    instead encodes the failure in the dataclass fields so the orchestrator
    can render a clean summary without a bunch of try/except.
    """
    run = runner or _default_runner

    porcelain = run(
        ["git", "-C", str(worktree), "status", "--porcelain"]
    )
    uncommitted = bool(porcelain.stdout.strip())

    short = run(
        ["git", "-C", str(worktree), "status", "--short", "--branch"]
    )
    short_status = short.stdout.strip()

    branch_proc = run(
        ["git", "-C", str(worktree), "rev-parse", "--abbrev-ref", "HEAD"]
    )
    branch = branch_proc.stdout.strip() if branch_proc.returncode == 0 else ""

    merged: bool | None
    if not branch or branch == "HEAD":
        merged = None
    else:
        # `git merge-base --is-ancestor <branch> <base>` exits 0 when
        # <branch> is fully contained in <base>'s history.
        check = run([
            "git", "-C", str(worktree),
            "merge-base", "--is-ancestor", branch, base_branch,
        ])
        if check.returncode == 0:
            merged = True
        elif check.returncode == 1:
            merged = False
        else:
            merged = None  # base branch unknown / other git failure

    return WorktreeStatus(
        path=worktree,
        branch=branch,
        short_status=short_status,
        uncommitted=uncommitted,
        merged_into_base=merged,
        base_branch=base_branch,
    )


# ---------- destructive actions ----------


def remove_worktree(
    worktree: Path,
    *,
    force: bool = False,
    runner: CommandRunner | None = None,
) -> None:
    """Run ``git worktree remove`` on ``worktree``.

    With ``force=True``, passes ``--force`` to git so worktrees with
    uncommitted changes can still be removed (the orchestrator should
    only enable this when the user passed ``--force``).
    """
    run = runner or _default_runner
    args = ["git", "-C", str(worktree), "worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(worktree))
    result = run(args)
    if result.returncode != 0:
        raise TeardownError(
            f"git worktree remove failed for {worktree}: "
            f"{(result.stderr or result.stdout).strip()}"
        )


def canonical_for(
    worktree: Path,
    *,
    runner: CommandRunner | None = None,
) -> Path:
    """Return the canonical repo path that hosts ``worktree``.

    Uses ``git rev-parse --path-format=absolute --git-common-dir`` which
    points at the canonical's ``.git`` directory; the canonical itself
    is its parent.
    """
    run = runner or _default_runner
    result = run([
        "git", "-C", str(worktree),
        "rev-parse", "--path-format=absolute", "--git-common-dir",
    ])
    if result.returncode != 0:
        raise TeardownError(
            f"could not resolve canonical for {worktree}: "
            f"{(result.stderr or result.stdout).strip()}"
        )
    common = Path(result.stdout.strip())
    return common.parent


def delete_branch(
    canonical: Path,
    branch: str,
    *,
    force: bool = False,
    runner: CommandRunner | None = None,
) -> None:
    """Delete ``branch`` in ``canonical``.

    Uses ``-d`` (safe, refuses unmerged) by default; with ``force=True``
    uses ``-D`` (unconditional). Surfaces the git stderr on failure so
    the orchestrator can pass it through unchanged.
    """
    run = runner or _default_runner
    flag = "-D" if force else "-d"
    result = run(["git", "-C", str(canonical), "branch", flag, branch])
    if result.returncode != 0:
        raise TeardownError(
            f"git branch {flag} {branch} failed in {canonical}: "
            f"{(result.stderr or result.stdout).strip()}"
        )


def archive_status_file(slug: str, *, now: datetime | None = None) -> Path | None:
    """Move ``status/<slug>.status`` to ``status/archive/<slug>-<ts>.status``.

    Returns the archive path. ``None`` if the source file didn't exist
    (e.g. spawn never wrote status). Creates the archive dir on demand.
    """
    src = config.status_path(slug)
    if not src.exists():
        return None
    archive_dir = config.status_archive_dir()
    archive_dir.mkdir(parents=True, exist_ok=True)
    ts = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    dst = archive_dir / f"{slug}-{ts}.status"
    src.replace(dst)
    return dst


def remove_workspace_dir(layout: WorkspaceLayout) -> None:
    """Remove the workspace dir entirely. Idempotent."""
    if not layout.workspace_dir.exists():
        return
    shutil.rmtree(layout.workspace_dir)
