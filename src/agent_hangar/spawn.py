"""Worktree creation and background bootstrap orchestration for ``agent-spawn``.

This module is the subprocess half of the Phase 4 spawn flow. The local
half — workspace dir, ``.agent/``, AGENTS.md — lives in
:mod:`agent_hangar.workspace` and runs before anything here.

Design notes:

- ``create_worktrees`` is synchronous and uses ``check=True``. A failure
  here is a hard error for ``agent-spawn``: there's no worktree to bootstrap
  yet, so the spawn aborts and the caller surfaces a clear message.
- ``run_bootstraps`` fires one **detached** ``subprocess.Popen`` per repo
  that has a bootstrap command. Each spawned shell pipes stdout/stderr to
  ``~/.agent-control/logs/<slug>-<repo>-bootstrap.log`` and, on non-zero
  exit, invokes ``agent-status <slug> STARTING_FAILED ...`` so the
  dashboard reflects the failure (per ``grilled-decisions.md`` §5).
  Successful bootstraps leave the workspace at STARTING — the agent
  itself transitions to WORKING the moment it actually starts working.
- Subprocess calls are routed through injected callables (``runner`` for
  ``create_worktrees``, ``spawner`` for ``run_bootstraps``) so tests can
  capture commands without monkeypatching the global ``subprocess`` module.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from . import config
from .repos import Repo
from .workspace import WorkspaceLayout


class SpawnError(Exception):
    """Raised when worktree creation can't proceed (git failure, bad inputs)."""


@dataclass(frozen=True)
class BootstrapHandle:
    repo: Repo
    pid: int
    log_path: Path


# ---------- worktree creation ----------


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _default_runner(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), capture_output=True, text=True, check=False)


def create_worktrees(
    layout: WorkspaceLayout,
    repos: list[Repo],
    branch: str,
    *,
    runner: CommandRunner | None = None,
) -> list[Path]:
    """Fetch each canonical repo and create a worktree for it.

    Returns the list of worktree paths. ``branch`` is the user-supplied
    branch name (same across every repo per the spawn-branch policy).
    Raises :class:`SpawnError` on the first git failure — we don't try to
    half-spawn.
    """
    if not branch:
        raise SpawnError("branch name is required when creating worktrees")
    run = runner or _default_runner

    worktrees: list[Path] = []
    for repo in repos:
        if not repo.path.exists():
            raise SpawnError(
                f"canonical repo path missing for {repo.key!r}: {repo.path}"
            )

        fetch = run(["git", "-C", str(repo.path), "fetch", "--prune"])
        if fetch.returncode != 0:
            raise SpawnError(
                f"git fetch failed for {repo.key!r}: "
                f"{(fetch.stderr or fetch.stdout).strip()}"
            )

        worktree_dir = layout.workspace_dir / repo.name
        add = run([
            "git",
            "-C",
            str(repo.path),
            "worktree",
            "add",
            "-b",
            branch,
            str(worktree_dir),
            repo.base_branch,
        ])
        if add.returncode != 0:
            raise SpawnError(
                f"git worktree add failed for {repo.key!r}: "
                f"{(add.stderr or add.stdout).strip()}"
            )
        worktrees.append(worktree_dir)

    return worktrees


# ---------- background bootstraps ----------


ProcessSpawner = Callable[[list[str]], subprocess.Popen[bytes]]


def _default_spawner(args: list[str]) -> subprocess.Popen[bytes]:
    # ``start_new_session=True`` detaches the child from the spawner's
    # process group so killing ``agent-spawn`` (or the tmux pane that ran
    # it) doesn't take bootstrap with it.
    return subprocess.Popen(args, start_new_session=True)


def run_bootstraps(
    layout: WorkspaceLayout,
    repos: list[Repo],
    *,
    spawner: ProcessSpawner | None = None,
) -> list[BootstrapHandle]:
    """Fire a detached shell per repo bootstrap; return started handles.

    Repos with empty ``bootstrap`` are skipped silently. The shell script
    each child runs:

    1. ``cd`` into the freshly created worktree.
    2. Run the bootstrap command, appending stdout/stderr to the per-repo
       log under ``~/.agent-control/logs/``.
    3. On non-zero exit, invoke ``agent-status <slug> STARTING_FAILED
       "bootstrap failed for <repo>, see <log>"`` so the dashboard
       surfaces it without the parent process having to poll.

    Returns one :class:`BootstrapHandle` per repo that actually had a
    bootstrap command — useful for tests; production callers can ignore
    the return value.
    """
    spawn = spawner or _default_spawner
    log_dir = config.log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)

    handles: list[BootstrapHandle] = []
    for repo in repos:
        if not repo.bootstrap.strip():
            continue
        worktree_dir = layout.workspace_dir / repo.name
        log_path = log_dir / f"{layout.slug}-{repo.key}-bootstrap.log"
        script = _bootstrap_shell(
            worktree=worktree_dir,
            bootstrap=repo.bootstrap,
            log_path=log_path,
            slug=layout.slug,
            repo_key=repo.key,
        )
        process = spawn(["sh", "-c", script])
        handles.append(BootstrapHandle(repo=repo, pid=process.pid, log_path=log_path))
    return handles


def _bootstrap_shell(
    *,
    worktree: Path,
    bootstrap: str,
    log_path: Path,
    slug: str,
    repo_key: str,
) -> str:
    """Build the shell script that runs one bootstrap and reports failure."""
    q_worktree = shlex.quote(str(worktree))
    q_log = shlex.quote(str(log_path))
    q_slug = shlex.quote(slug)
    failure_msg = shlex.quote(
        f"bootstrap failed for {repo_key}, see {log_path}"
    )
    # The bootstrap command is intentionally NOT shell-quoted: it's a
    # shell snippet from repos.yaml (e.g. ``npm ci`` or
    # ``pnpm install --frozen-lockfile``) and is meant to be interpreted
    # by sh as-is. The braced group wraps both the cd and the bootstrap
    # so the log redirect captures cd errors too — otherwise a missing
    # worktree dir would silently print to the (detached) parent's stderr.
    return (
        f"{{ cd {q_worktree} && {bootstrap} ; }} >>{q_log} 2>&1; "
        f"rc=$?; "
        f"if [ $rc -ne 0 ]; then "
        f"agent-status {q_slug} STARTING_FAILED {failure_msg}; "
        f"fi"
    )
