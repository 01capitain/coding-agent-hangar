"""Pytest fixtures shared across the test suite."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def hangar_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the hangar's control plane at a tmp dir for the duration of the test."""
    control = tmp_path / "agent-control"
    monkeypatch.setenv("AGENT_CONTROL_HOME", str(control))
    return control
