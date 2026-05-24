"""Load and validate ``~/.agent-control/config/repos.yaml``.

The YAML schema is documented in ``grilled-decisions.md`` §7 and the bundled
sample at ``src/agent_hangar/templates/repos.sample.yaml``. Each entry maps to
a :class:`Repo`. Required fields: ``key``, ``name``, ``path``. Optional:
``default`` (sort hint, default ``False``), ``bootstrap`` (shell command,
default ``""``), ``base_branch`` (default :data:`agent_hangar.config.DEFAULT_BASE_BRANCH`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import config


class RepoConfigError(Exception):
    """Raised when ``repos.yaml`` is missing, unparseable, or fails validation."""


@dataclass(frozen=True)
class Repo:
    key: str
    name: str
    path: Path
    default: bool
    bootstrap: str
    base_branch: str


def load_repos() -> list[Repo]:
    """Return the parsed repo list. Raises :class:`RepoConfigError` on any problem."""
    repos_path = config.repos_yaml_path()
    if not repos_path.exists():
        raise RepoConfigError(
            f"repos.yaml not found at {repos_path}. Run `hangar-setup` first."
        )
    try:
        import yaml
    except ImportError as exc:
        raise RepoConfigError(
            "PyYAML is required to read repos.yaml. Install with `pip install pyyaml`."
        ) from exc

    try:
        raw = yaml.safe_load(repos_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RepoConfigError(f"repos.yaml is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict) or "repos" not in raw:
        raise RepoConfigError("repos.yaml must contain a top-level `repos:` list.")
    items = raw["repos"]
    if not isinstance(items, list):
        raise RepoConfigError("`repos:` must be a list.")

    repos: list[Repo] = []
    seen_keys: set[str] = set()
    for index, item in enumerate(items):
        repo = _parse_entry(item, index=index)
        if repo.key in seen_keys:
            raise RepoConfigError(f"duplicate repo key {repo.key!r} in repos.yaml")
        seen_keys.add(repo.key)
        repos.append(repo)
    return repos


def lookup(repos: list[Repo], key: str) -> Repo:
    for repo in repos:
        if repo.key == key:
            return repo
    raise RepoConfigError(
        f"unknown repo key {key!r}. Known keys: {', '.join(r.key for r in repos)}"
    )


def _parse_entry(item: object, *, index: int) -> Repo:
    if not isinstance(item, dict):
        raise RepoConfigError(f"repos[{index}] must be a mapping, got {type(item).__name__}")
    for required in ("key", "name", "path"):
        if required not in item or not isinstance(item[required], str) or not item[required]:
            raise RepoConfigError(f"repos[{index}] missing required field `{required}`")
    base_branch = item.get("base_branch") or config.DEFAULT_BASE_BRANCH
    return Repo(
        key=item["key"],
        name=item["name"],
        path=Path(item["path"]).expanduser(),
        default=bool(item.get("default", False)),
        bootstrap=str(item.get("bootstrap", "") or ""),
        base_branch=str(base_branch),
    )
