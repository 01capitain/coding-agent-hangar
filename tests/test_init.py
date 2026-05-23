"""Tests for hangar-init."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_hangar import config, init


def test_run_init_creates_all_subdirs(hangar_home: Path) -> None:
    report = init.run_init()
    assert report["control_home"] == hangar_home
    for expected in (
        config.config_dir(),
        config.status_dir(),
        config.status_archive_dir(),
        config.log_dir(),
        config.quota_dir(),
        config.templates_dir(),
    ):
        assert expected.is_dir(), expected


def test_repos_yaml_seeded_with_hotelkit_template_when_no_sync_repos(
    hangar_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(init, "_sync_repos_paths", lambda: [])

    report = init.run_init()
    assert report["repos_yaml_status"] == "seeded-template-only"

    text = config.repos_yaml_path().read_text(encoding="utf-8")
    assert "backend-core-nestjs" in text
    assert "frontend-hotelkit-web" in text
    # The auto-discovery banner should not appear when sync-repos returned nothing.
    assert "auto-discovered from `sync-repos list`" not in text


def test_repos_yaml_appends_sync_repos_entries(
    hangar_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_paths = [
        Path("/Users/me/Documents/Projects/wealth-manager"),
        Path("/Users/me/Documents/Projects/jira-release-manager"),
    ]
    monkeypatch.setattr(init, "_sync_repos_paths", lambda: fake_paths)

    report = init.run_init()
    assert report["repos_yaml_status"] == "seeded-with-sync-repos"
    assert report["sync_repos_count"] == 2

    text = config.repos_yaml_path().read_text(encoding="utf-8")
    assert "auto-discovered from `sync-repos list`" in text
    assert "wealth-manager" in text
    assert "jira-release-manager" in text


def test_run_init_preserves_existing_repos_yaml(
    hangar_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(init, "_sync_repos_paths", lambda: [])
    init.run_init()

    custom = "repos:\n  - key: my-edit\n    name: my-edit\n    path: /tmp/x\n"
    config.repos_yaml_path().write_text(custom, encoding="utf-8")

    report = init.run_init()
    assert report["repos_yaml_status"] == "preserved-existing"
    assert config.repos_yaml_path().read_text(encoding="utf-8") == custom


def test_slug_collision_appends_suffix() -> None:
    taken: set[str] = set()
    assert init._slugify_key("backend", taken) == "backend"
    assert init._slugify_key("Backend", taken) == "backend-2"
    assert init._slugify_key("BACKEND", taken) == "backend-3"


def test_slugify_handles_spaces_and_special_chars() -> None:
    taken: set[str] = set()
    assert init._slugify_key("SLANG Capital documents", taken) == "slang-capital-documents"
    assert init._slugify_key("Personal Vault", taken) == "personal-vault"


def test_sync_repos_parses_only_absolute_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    sample_output = (
        "\U0001f4da Synced Repositories:\n"
        "/Users/me/Documents/Projects/repo-one\n"
        "/Users/me/Documents/Projects/repo-two/\n"
        "garbage line that is not a path\n"
        "\n"
    )

    class _FakeResult:
        stdout = sample_output

    monkeypatch.setattr(init.shutil, "which", lambda _cmd: "/usr/local/bin/sync-repos")
    monkeypatch.setattr(init.subprocess, "run", lambda *a, **k: _FakeResult())

    paths = init._sync_repos_paths()
    assert [str(p) for p in paths] == [
        "/Users/me/Documents/Projects/repo-one",
        "/Users/me/Documents/Projects/repo-two",
    ]


def test_sync_repos_silent_when_binary_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(init.SYNC_REPOS_LIST_ENV, raising=False)
    monkeypatch.setattr(init.shutil, "which", lambda _cmd: None)
    assert init._sync_repos_paths() == []


def test_sync_repos_reads_env_var_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    list_file = tmp_path / "repository-list.txt"
    list_file.write_text(
        "/Users/me/Documents/Projects/repo-one\n"
        "/Users/me/Documents/Projects/repo-two/\n"
        "not-a-path\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(init.SYNC_REPOS_LIST_ENV, str(list_file))

    paths = init._sync_repos_paths()
    assert [str(p) for p in paths] == [
        "/Users/me/Documents/Projects/repo-one",
        "/Users/me/Documents/Projects/repo-two",
    ]


def test_sync_repos_env_var_takes_precedence_over_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    list_file = tmp_path / "list.txt"
    list_file.write_text("/from/env\n", encoding="utf-8")
    monkeypatch.setenv(init.SYNC_REPOS_LIST_ENV, str(list_file))
    # Even if a binary is "available", the env var wins.
    monkeypatch.setattr(init.shutil, "which", lambda _cmd: "/usr/local/bin/sync-repos")

    def should_not_run(*a, **k):
        raise AssertionError("subprocess should not be invoked when env var is set")

    monkeypatch.setattr(init.subprocess, "run", should_not_run)
    paths = init._sync_repos_paths()
    assert [str(p) for p in paths] == ["/from/env"]


def test_sync_repos_env_var_missing_file_is_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(init.SYNC_REPOS_LIST_ENV, str(tmp_path / "does-not-exist"))
    assert init._sync_repos_paths() == []


def test_run_init_raises_when_pyyaml_missing(
    hangar_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom() -> None:
        raise init.InitError("PyYAML not installed")

    monkeypatch.setattr(init, "_ensure_pyyaml", boom)
    with pytest.raises(init.InitError):
        init.run_init()
