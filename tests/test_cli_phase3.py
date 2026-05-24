"""Integration tests for the Phase 3 command wired through cli.py."""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_hangar import cli, config, quota


def _run(monkeypatch: pytest.MonkeyPatch, func, argv: list[str]) -> int:
    monkeypatch.setattr("sys.argv", argv)
    try:
        func()
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    return 0


def _pipe_stdin(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(text))


def test_quota_update_writes_normalized_snapshot(
    initialized_hangar: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    five_resets = datetime(2026, 5, 24, 15, 0, 0, tzinfo=timezone.utc)
    payload = {
        "rate_limits": {
            "five_hour": {
                "used_percentage": 36.0,
                "resets_at": int(five_resets.timestamp()),
            }
        },
        "context_window": {"used_percentage": 42.5},
    }
    _pipe_stdin(monkeypatch, json.dumps(payload))

    rc = _run(monkeypatch, cli.quota_update, ["hangar-quota-update"])
    assert rc == 0

    target = config.quota_dir() / "claude.json"
    assert target.is_file()
    written = json.loads(target.read_text(encoding="utf-8"))
    assert written["five_hour"]["resets_at"] == "2026-05-24T15:00:00Z"
    assert written["five_hour"]["used_percentage"] == 36.0
    assert written["context_window"]["used_percentage"] == 42.5
    # No leftover .tmp files.
    assert [p.name for p in config.quota_dir().iterdir()] == ["claude.json"]


def test_quota_update_empty_stdin_is_no_op(
    initialized_hangar: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pipe_stdin(monkeypatch, "")
    rc = _run(monkeypatch, cli.quota_update, ["hangar-quota-update"])
    assert rc == 0
    assert not (config.quota_dir() / "claude.json").exists()


def test_quota_update_invalid_json_errors(
    initialized_hangar: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _pipe_stdin(monkeypatch, "{not valid json")
    rc = _run(monkeypatch, cli.quota_update, ["hangar-quota-update"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "invalid JSON" in err


def test_quota_update_non_object_errors(
    initialized_hangar: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _pipe_stdin(monkeypatch, json.dumps([1, 2, 3]))
    rc = _run(monkeypatch, cli.quota_update, ["hangar-quota-update"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "JSON object" in err


def test_quota_update_tolerates_missing_fields(
    initialized_hangar: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Only context_window populated; rate limits absent. Snapshot should
    # still be written (no exception, no error exit).
    _pipe_stdin(monkeypatch, json.dumps({"context_window": {"used_percentage": 7.0}}))
    rc = _run(monkeypatch, cli.quota_update, ["hangar-quota-update"])
    assert rc == 0

    snap = quota.load_snapshot()
    assert snap is not None
    assert snap.context_used_percentage == 7.0
    assert snap.five_hour is None
    assert snap.seven_day is None


def test_quota_update_round_trip_into_statusline(
    initialized_hangar: Path,
    write_status_with_age,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Write a status file + populate the quota snapshot, then verify
    # ``hangar-statusline`` includes both pieces in its compact line.
    write_status_with_age("alpha", "WORKING", "x")
    five_resets = datetime.now(timezone.utc).replace(microsecond=0)
    # Push reset 1 hour ahead so elapsed = 4h of 5h ≈ 80%.
    from datetime import timedelta as _td

    payload = {
        "rate_limits": {
            "five_hour": {
                "used_percentage": 50.0,
                "resets_at": int((five_resets + _td(hours=1)).timestamp()),
            }
        }
    }
    _pipe_stdin(monkeypatch, json.dumps(payload))
    rc = _run(monkeypatch, cli.quota_update, ["hangar-quota-update"])
    assert rc == 0

    rc = _run(monkeypatch, cli.tmux_status, ["hangar-statusline"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert "[W:1]" in out
    assert "5h:50%" in out
