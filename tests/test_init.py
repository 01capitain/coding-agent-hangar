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


def test_repos_yaml_seeded_with_hotelkit_template(hangar_home: Path) -> None:
    report = init.run_init()
    assert report["repos_yaml_status"] == "seeded-template"

    text = config.repos_yaml_path().read_text(encoding="utf-8")
    assert "backend-core-nestjs" in text
    assert "frontend-hotelkit-web" in text


def test_run_init_preserves_existing_repos_yaml(hangar_home: Path) -> None:
    init.run_init()

    custom = "repos:\n  - key: my-edit\n    name: my-edit\n    path: /tmp/x\n"
    config.repos_yaml_path().write_text(custom, encoding="utf-8")

    report = init.run_init()
    assert report["repos_yaml_status"] == "preserved-existing"
    assert config.repos_yaml_path().read_text(encoding="utf-8") == custom


def test_run_init_raises_when_pyyaml_missing(
    hangar_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom() -> None:
        raise init.InitError("PyYAML not installed")

    monkeypatch.setattr(init, "_ensure_pyyaml", boom)
    with pytest.raises(init.InitError):
        init.run_init()
