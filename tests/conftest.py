"""Pytest fixtures shared across the test suite.

Test status files live under ``tmp_path``; the ``hangar_home`` fixture
points ``AGENT_CONTROL_HOME`` at it. The user's real ``~/.agent-control/``
is never read or written during tests.
"""

from __future__ import annotations

import dataclasses
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
