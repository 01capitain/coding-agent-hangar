"""Unit tests for the status read/write layer."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_hangar import config, status


def _seed_control_dir(hangar_home: Path) -> None:
    config.status_dir().mkdir(parents=True, exist_ok=True)
    config.log_dir().mkdir(parents=True, exist_ok=True)


def test_write_then_read_roundtrip(hangar_home: Path) -> None:
    _seed_control_dir(hangar_home)

    record = status.write_status("alpha", "WORKING", "investigating thing")
    again = status.read_status("alpha")

    assert again is not None
    assert again.slug == "alpha"
    assert again.state == "WORKING"
    assert again.summary == "investigating thing"
    assert again.started_at == record.started_at
    assert again.updated_at == record.updated_at


def test_started_at_preserved_across_writes(hangar_home: Path) -> None:
    _seed_control_dir(hangar_home)

    first = status.write_status("beta", "STARTING", "boot")
    time.sleep(0.01)
    second = status.write_status("beta", "WORKING", "now working")

    assert second.started_at == first.started_at
    assert second.updated_at > first.updated_at


def test_write_rejects_unknown_state(hangar_home: Path) -> None:
    _seed_control_dir(hangar_home)
    with pytest.raises(status.StatusError):
        status.write_status("gamma", "ON_FIRE", "nope")


def test_write_refuses_without_control_dir(hangar_home: Path) -> None:
    # Note: do NOT create the control dir; write should refuse.
    with pytest.raises(status.StatusError, match="hangar-setup"):
        status.write_status("delta", "WORKING", "no home")


def test_log_file_appended_on_each_write(hangar_home: Path) -> None:
    _seed_control_dir(hangar_home)

    status.write_status("eps", "STARTING", "boot")
    status.write_status("eps", "WORKING", "investigating")
    status.write_status("eps", "READY", "done thinking")

    log_text = config.log_path("eps").read_text(encoding="utf-8")
    lines = [line for line in log_text.splitlines() if line.strip()]
    assert len(lines) == 3
    assert "STARTING" in lines[0]
    assert "WORKING" in lines[1]
    assert "READY" in lines[2]


def test_summary_with_quotes_and_backslashes_roundtrip(hangar_home: Path) -> None:
    _seed_control_dir(hangar_home)

    tricky = 'agent said "hello" and used a \\ backslash'
    status.write_status("zeta", "WORKING", tricky)

    again = status.read_status("zeta")
    assert again is not None
    assert again.summary == tricky


def test_list_records_skips_archive_dir(hangar_home: Path) -> None:
    _seed_control_dir(hangar_home)
    config.status_archive_dir().mkdir(parents=True, exist_ok=True)
    # An archived status file should not appear in the live listing.
    (config.status_archive_dir() / "old.status").write_text(
        'SLUG="old"\nSTATE="DONE"\nSUMMARY="archived"\n'
        'UPDATED_AT="2024-01-01T00:00:00Z"\nSTARTED_AT="2024-01-01T00:00:00Z"\n',
        encoding="utf-8",
    )

    status.write_status("live", "WORKING", "current")
    records = status.list_records()
    assert [r.slug for r in records] == ["live"]


def test_list_records_skips_malformed_files(hangar_home: Path) -> None:
    _seed_control_dir(hangar_home)
    (config.status_dir() / "broken.status").write_text(
        "this is not a status file\n", encoding="utf-8"
    )
    status.write_status("good", "WORKING", "fine")

    records = status.list_records()
    assert [r.slug for r in records] == ["good"]


def test_priority_orders_blocked_before_working() -> None:
    blocked = status.StatusRecord(
        slug="a", state="BLOCKED", summary="",
        updated_at=datetime.now(timezone.utc),
        started_at=datetime.now(timezone.utc),
    )
    working = status.StatusRecord(
        slug="b", state="WORKING", summary="",
        updated_at=datetime.now(timezone.utc),
        started_at=datetime.now(timezone.utc),
    )
    assert blocked.priority() < working.priority()


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(seconds=5), "just now"),
        (timedelta(minutes=3), "3m ago"),
        (timedelta(hours=2), "2h ago"),
        (timedelta(days=4), "4d ago"),
    ],
)
def test_relative_age(delta: timedelta, expected: str) -> None:
    now = datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc)
    assert status.relative_age(now - delta, now=now) == expected


def test_atomic_write_leaves_no_partial_file_on_failure(
    hangar_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_control_dir(hangar_home)
    status.write_status("eta", "WORKING", "good content")

    original = status._atomic_write_status

    def boom(record: status.StatusRecord) -> None:
        raise RuntimeError("disk gremlin")

    monkeypatch.setattr(status, "_atomic_write_status", boom)
    with pytest.raises(RuntimeError):
        status.write_status("eta", "READY", "this write fails")
    monkeypatch.setattr(status, "_atomic_write_status", original)

    # Previous content survives; no stray tmp file lingering.
    final = status.read_status("eta")
    assert final is not None
    assert final.state == "WORKING"
    assert final.summary == "good content"
    leftovers = list(config.status_dir().glob("eta.status.tmp.*"))
    assert leftovers == []
