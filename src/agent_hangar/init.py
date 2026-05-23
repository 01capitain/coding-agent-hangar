"""Hangar initialization: create ~/.agent-control/ layout and seed repos.yaml.

Idempotent. Re-running on an existing hangar fills in any missing subdirs but
never clobbers an existing ``repos.yaml`` — the user's curated list wins.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from importlib.resources import files
from pathlib import Path
from typing import Iterable

from . import config

SAMPLE_TEMPLATE = "repos.sample.yaml"
SYNC_REPOS_BINARY = "sync-repos"
SYNC_REPOS_LIST_ENV = "HANGAR_SYNC_REPOS_LIST"


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


def _parse_paths_from_text(text: str) -> list[Path]:
    paths: list[Path] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("/"):
            continue
        # Strip trailing slashes so the path normalizes cleanly.
        paths.append(Path(line.rstrip("/")))
    return paths


def _sync_repos_paths() -> list[Path]:
    """Return absolute paths the user's local repo registry reports.

    Resolution order, first hit wins:

    1. ``HANGAR_SYNC_REPOS_LIST`` env var: a file with one path per line. Use
       this when ``sync-repos`` is a shell alias (subprocess can't see aliases),
       or to point at any other curated path list.
    2. ``sync-repos`` resolvable via ``shutil.which``: invoke ``sync-repos list``
       and parse its stdout.

    Silent on every failure mode — a missing binary, unreadable env-pointed
    file, nonzero exit, garbled output should all just yield an empty list, not
    break ``hangar-init``.
    """
    env_path = os.environ.get(SYNC_REPOS_LIST_ENV)
    if env_path:
        list_path = Path(env_path).expanduser()
        try:
            return _parse_paths_from_text(list_path.read_text(encoding="utf-8"))
        except OSError:
            return []

    if shutil.which(SYNC_REPOS_BINARY) is None:
        return []
    try:
        result = subprocess.run(
            [SYNC_REPOS_BINARY, "list"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError):
        return []

    return _parse_paths_from_text(result.stdout)


_KEY_SANITIZE = re.compile(r"[^a-z0-9]+")


def _slugify_key(name: str, taken: set[str]) -> str:
    base = _KEY_SANITIZE.sub("-", name.lower()).strip("-") or "repo"
    key = base
    i = 2
    while key in taken:
        key = f"{base}-{i}"
        i += 1
    taken.add(key)
    return key


def _format_sync_repo_entry(path: Path, key: str) -> str:
    return (
        f"  - key: {key}\n"
        f"    name: {path.name}\n"
        f"    path: {path}\n"
        f'    # bootstrap: ""        # TODO: fill in (e.g., npm ci, pnpm install)\n'
        f"    # base_branch: origin/main\n"
    )


def _existing_keys_in_template(template_text: str) -> set[str]:
    return set(re.findall(r"^\s*- key:\s*([A-Za-z0-9_-]+)", template_text, re.MULTILINE))


def _build_repos_yaml(template_text: str, sync_paths: Iterable[Path]) -> str:
    paths = list(sync_paths)
    if not paths:
        return template_text

    taken = _existing_keys_in_template(template_text)
    body = template_text.rstrip() + "\n"
    body += (
        "\n  # === Local repositories (auto-discovered from `sync-repos list`) ===\n"
        "  # Edit, fill in bootstrap commands, and delete entries you don't want\n"
        "  # to register as agent worktree targets.\n"
    )
    for path in paths:
        key = _slugify_key(path.name, taken)
        body += "\n" + _format_sync_repo_entry(path, key)
    return body


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
    repos_yaml_status: str
    sync_paths: list[Path] = []
    if repos_path.exists():
        repos_yaml_status = "preserved-existing"
    else:
        template = _load_template()
        sync_paths = _sync_repos_paths()
        repos_path.write_text(_build_repos_yaml(template, sync_paths), encoding="utf-8")
        repos_yaml_status = "seeded-with-sync-repos" if sync_paths else "seeded-template-only"

    return {
        "control_home": config.control_home(),
        "created_subdirs": created,
        "repos_yaml": repos_path,
        "repos_yaml_status": repos_yaml_status,
        "sync_repos_count": len(sync_paths),
    }
