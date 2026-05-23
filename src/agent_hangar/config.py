"""Environment-variable-resolved paths and tunables for the hangar.

Single source of truth: every module reads paths through these helpers rather
than hardcoding ``~/.agent-control``. Tests override ``AGENT_CONTROL_HOME`` via
monkeypatch to redirect the whole control plane at ``tmp_path``.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_TMUX_SESSION = "agents"
DEFAULT_BASE_BRANCH = "origin/main"
DEFAULT_AGENT_COMMAND = "claude"
DEFAULT_STALE_MINUTES = 30


def control_home() -> Path:
    """Root of the hangar's control plane. Defaults to ``~/.agent-control``."""
    env = os.environ.get("AGENT_CONTROL_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".agent-control"


def work_home() -> Path:
    """Root under which workspace directories are created."""
    env = os.environ.get("AGENT_WORK_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / "agent-work"


def config_dir() -> Path:
    return control_home() / "config"


def status_dir() -> Path:
    return control_home() / "status"


def status_archive_dir() -> Path:
    return status_dir() / "archive"


def log_dir() -> Path:
    return control_home() / "logs"


def quota_dir() -> Path:
    return control_home() / "quotas"


def templates_dir() -> Path:
    return control_home() / "templates"


def repos_yaml_path() -> Path:
    return config_dir() / "repos.yaml"


def status_path(slug: str) -> Path:
    return status_dir() / f"{slug}.status"


def log_path(slug: str) -> Path:
    return log_dir() / f"{slug}.log"


def tmux_session() -> str:
    return os.environ.get("AGENT_TMUX_SESSION", DEFAULT_TMUX_SESSION)


def base_branch() -> str:
    return os.environ.get("AGENT_BASE_BRANCH", DEFAULT_BASE_BRANCH)


def agent_command() -> str:
    return os.environ.get("AGENT_COMMAND", DEFAULT_AGENT_COMMAND)


def stale_minutes() -> int:
    raw = os.environ.get("AGENT_STALE_MINUTES")
    if not raw:
        return DEFAULT_STALE_MINUTES
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_STALE_MINUTES
