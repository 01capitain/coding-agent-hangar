"""Tests for the repos.yaml loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_hangar import config, repos


def _write_repos_yaml(text: str) -> None:
    path = config.repos_yaml_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_load_repos_happy_path(initialized_hangar: Path) -> None:
    _write_repos_yaml(
        """
        repos:
          - key: backend
            name: backend-core-nestjs
            path: /var/www/backend-core-nestjs
            default: true
            bootstrap: npm ci
            base_branch: origin/main
          - key: planning
            name: planning-repo
            path: /var/www/planning
        """
    )
    loaded = repos.load_repos()
    assert [r.key for r in loaded] == ["backend", "planning"]
    backend = loaded[0]
    assert backend.name == "backend-core-nestjs"
    assert backend.path == Path("/var/www/backend-core-nestjs")
    assert backend.default is True
    assert backend.bootstrap == "npm ci"
    assert backend.base_branch == "origin/main"

    planning = loaded[1]
    assert planning.default is False
    assert planning.bootstrap == ""
    assert planning.base_branch == "origin/main"  # default


def test_load_repos_errors_when_missing(initialized_hangar: Path) -> None:
    with pytest.raises(repos.RepoConfigError, match="not found"):
        repos.load_repos()


def test_load_repos_rejects_duplicate_keys(initialized_hangar: Path) -> None:
    _write_repos_yaml(
        """
        repos:
          - key: backend
            name: a
            path: /tmp/a
          - key: backend
            name: b
            path: /tmp/b
        """
    )
    with pytest.raises(repos.RepoConfigError, match="duplicate"):
        repos.load_repos()


def test_load_repos_requires_top_level_list(initialized_hangar: Path) -> None:
    _write_repos_yaml("repos: not-a-list")
    with pytest.raises(repos.RepoConfigError, match="must be a list"):
        repos.load_repos()


def test_load_repos_rejects_missing_required_field(initialized_hangar: Path) -> None:
    _write_repos_yaml(
        """
        repos:
          - key: missing-name
            path: /tmp/x
        """
    )
    with pytest.raises(repos.RepoConfigError, match="missing required field `name`"):
        repos.load_repos()


def test_lookup_finds_repo() -> None:
    sample = [
        repos.Repo("a", "a", Path("/x"), False, "", "origin/main"),
        repos.Repo("b", "b", Path("/y"), True, "npm ci", "origin/main"),
    ]
    assert repos.lookup(sample, "b").path == Path("/y")


def test_lookup_raises_on_unknown_key() -> None:
    with pytest.raises(repos.RepoConfigError, match="unknown repo key"):
        repos.lookup([], "anything")
