"""Pytest fixtures shared across the test suite.

Test status files live under ``tmp_path``; the ``hangar_home`` fixture
points ``AGENT_CONTROL_HOME`` at it. The user's real ``~/.agent-control/``
is never read or written during tests.
"""

from __future__ import annotations

import dataclasses
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_hangar import config, status


@pytest.fixture
def hangar_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the hangar's control plane at a tmp dir for the duration of the test."""
    control = tmp_path / "agent-control"
    monkeypatch.setenv("AGENT_CONTROL_HOME", str(control))
    return control


@pytest.fixture
def initialized_hangar(hangar_home: Path) -> Path:
    """A hangar with its control subdirs in place but no status files yet."""
    config.status_dir().mkdir(parents=True, exist_ok=True)
    config.log_dir().mkdir(parents=True, exist_ok=True)
    return hangar_home


@pytest.fixture
def write_status_with_age(fixed_now: datetime):
    """Write a status file with UPDATED_AT pinned relative to ``fixed_now``.

    Returns a callable ``(slug, state, summary, *, age_minutes=0)`` that
    leaves a real ``.status`` file on disk. The timestamp is computed from
    ``fixed_now`` (not real wall-clock time), so tests that also pass
    ``now=fixed_now`` into the renderer see deterministic ages independent
    of when the test runs.
    """

    def _write(
        slug: str,
        state: str,
        summary: str,
        *,
        age_minutes: float = 0.0,
    ) -> status.StatusRecord:
        record = status.write_status(slug, state, summary)
        pinned = fixed_now - timedelta(minutes=age_minutes)
        aged = dataclasses.replace(
            record, updated_at=pinned, started_at=pinned
        )
        status._atomic_write_status(aged)
        return aged

    return _write


@pytest.fixture
def fixed_now() -> datetime:
    """A deterministic 'now' so age-rendering tests don't flap."""
    return datetime(2026, 5, 23, 19, 0, 0, tzinfo=timezone.utc)


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def tmp_canonical_repo(tmp_path: Path) -> Path:
    """A working git repo that worktrees can be carved out of.

    Initializes ``tmp_path/canonical`` with one commit on ``main``, and
    aliases ``origin/main`` to the local main so ``git worktree add ...
    origin/main`` resolves. Returns the canonical path.
    """
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    _git("init", "-b", "main", cwd=canonical)
    _git("config", "user.email", "test@example.com", cwd=canonical)
    _git("config", "user.name", "Test", cwd=canonical)
    (canonical / "README.md").write_text("seed\n", encoding="utf-8")
    _git("add", "README.md", cwd=canonical)
    _git("commit", "-m", "seed", cwd=canonical)
    # Fake an ``origin/main`` ref by aliasing it to the local main commit,
    # so ``worktree add ... origin/main`` works without a real remote.
    main_sha = subprocess.run(
        ["git", "rev-parse", "main"],
        cwd=canonical, capture_output=True, text=True, check=True,
    ).stdout.strip()
    _git("update-ref", "refs/remotes/origin/main", main_sha, cwd=canonical)
    return canonical
