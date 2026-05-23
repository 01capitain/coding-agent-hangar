"""Hangar initialization: create ~/.agent-control/ layout and seed repos.yaml.

Idempotent. Re-running on an existing hangar fills in any missing subdirs but
never clobbers an existing ``repos.yaml`` — the user's curated list wins.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from . import config

SAMPLE_TEMPLATE = "repos.sample.yaml"


class InitError(Exception):
    """Raised when initialization can't proceed (e.g., missing PyYAML)."""


def _ensure_pyyaml() -> None:
    try:
        import yaml  # noqa: F401
    except ImportError as exc:
        raise InitError(
            "PyYAML is required but not importable. Install it with one of:\n"
            "  apt install python3-yaml   # Debian/Ubuntu\n"
            "  pip install pyyaml"
        ) from exc


def _control_subdirs() -> list[Path]:
    return [
        config.config_dir(),
        config.status_dir(),
        config.status_archive_dir(),
        config.log_dir(),
        config.quota_dir(),
        config.templates_dir(),
    ]


def _load_template() -> str:
    return files("agent_hangar.templates").joinpath(SAMPLE_TEMPLATE).read_text(encoding="utf-8")


def run_init() -> dict[str, object]:
    """Materialize the control directory and seed ``repos.yaml``.

    Returns a small report dict for callers (and tests) that want to inspect
    what happened without parsing stdout.
    """
    _ensure_pyyaml()

    created: list[Path] = []
    for subdir in _control_subdirs():
        if not subdir.exists():
            subdir.mkdir(parents=True, exist_ok=True)
            created.append(subdir)
        elif not subdir.is_dir():
            raise InitError(f"expected directory at {subdir}, found a non-directory")

    repos_path = config.repos_yaml_path()
    if repos_path.exists():
        repos_yaml_status = "preserved-existing"
    else:
        repos_path.write_text(_load_template(), encoding="utf-8")
        repos_yaml_status = "seeded-template"

    return {
        "control_home": config.control_home(),
        "created_subdirs": created,
        "repos_yaml": repos_path,
        "repos_yaml_status": repos_yaml_status,
    }
