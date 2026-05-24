"""Tests for the quota snapshot reader, renderer, and payload normalizer.

The hangar's quota plumbing operates on a normalized on-disk snapshot at
``<control_home>/quotas/claude.json``. These tests build snapshots directly
(no real Claude statusline JSON required) so they pin the rendering
contract — burn-delta colors, the two-line-per-window layout, compact
``5h:U%/E% 7d:U%/E%`` fragment — separately from the JSON normalizer.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_hangar import ansi, config, quota


def _window(
    label: str,
    used: float,
    *,
    now: datetime,
    duration: timedelta,
    resets_in: timedelta | None = None,
) -> quota.QuotaWindow:
    if resets_in is None:
        # Default: halfway through the window so elapsed == 50%.
        resets_in = duration / 2
    return quota.QuotaWindow(
        label=label,
        used_percentage=used,
        resets_at=now + resets_in,
        duration=duration,
    )


def _snapshot(
    *,
    now: datetime,
    five_used: float | None = None,
    seven_used: float | None = None,
    context_used: float | None = None,
    five_resets_in: timedelta | None = None,
    seven_resets_in: timedelta | None = None,
) -> quota.QuotaSnapshot:
    return quota.QuotaSnapshot(
        updated_at=now,
        context_used_percentage=context_used,
        five_hour=(
            _window(
                "5 HOUR",
                five_used,
                now=now,
                duration=quota.FIVE_HOUR,
                resets_in=five_resets_in,
            )
            if five_used is not None
            else None
        ),
        seven_day=(
            _window(
                "7 DAY",
                seven_used,
                now=now,
                duration=quota.SEVEN_DAY,
                resets_in=seven_resets_in,
            )
            if seven_used is not None
            else None
        ),
    )


# ---------- elapsed/burn math ----------


def test_elapsed_percentage_at_midpoint(fixed_now: datetime) -> None:
    window = _window("5 HOUR", 50.0, now=fixed_now, duration=quota.FIVE_HOUR)
    assert window.elapsed_percentage(now=fixed_now) == pytest.approx(50.0)
    assert window.burn_delta(now=fixed_now) == pytest.approx(0.0)


def test_elapsed_percentage_clamps_after_reset(fixed_now: datetime) -> None:
    # ``resets_at`` already in the past — clamp to 100%, not >100.
    past = fixed_now - timedelta(hours=1)
    window = quota.QuotaWindow(
        label="5 HOUR",
        used_percentage=10.0,
        resets_at=past,
        duration=quota.FIVE_HOUR,
    )
    assert window.elapsed_percentage(now=fixed_now) == 100.0


# ---------- pane rendering ----------


def test_render_pane_unavailable_when_no_snapshot(initialized_hangar: Path) -> None:
    out = quota.render_pane(use_color=False)
    assert "USAGE QUOTAS" in out
    assert "unavailable" in out
    assert "hangar-quota-update" in out


def test_render_pane_shows_both_windows(fixed_now: datetime) -> None:
    snap = _snapshot(now=fixed_now, five_used=36.0, seven_used=69.0)
    out = quota.render_pane(snap, now=fixed_now, use_color=False)
    assert "5 HOUR" in out
    assert "7 DAY" in out
    assert "36%" in out
    assert "69%" in out
    # Elapsed bars rendered for each window (default fixture: midpoint = 50%).
    assert out.count("50%") == 2
    assert "reset in" in out


def test_render_pane_partial_snapshot_renders_only_present_window(
    fixed_now: datetime,
) -> None:
    snap = _snapshot(now=fixed_now, five_used=10.0)
    out = quota.render_pane(snap, now=fixed_now, use_color=False)
    assert "5 HOUR" in out
    assert "7 DAY" not in out
    assert "10%" in out


def test_render_pane_context_line_only_when_present(fixed_now: datetime) -> None:
    without = _snapshot(now=fixed_now, five_used=10.0)
    assert "context" not in quota.render_pane(without, now=fixed_now, use_color=False)

    with_ctx = _snapshot(now=fixed_now, five_used=10.0, context_used=42.0)
    out = quota.render_pane(with_ctx, now=fixed_now, use_color=False)
    assert "context" in out
    assert "42%" in out


@pytest.mark.parametrize(
    ("used", "elapsed_in", "expected_color"),
    [
        # Halfway through the 5h window; used vs elapsed = 50% baseline.
        (50.0, timedelta(hours=2, minutes=30), ansi.GREEN),  # delta 0 → green
        (55.0, timedelta(hours=2, minutes=30), ansi.YELLOW),  # delta 5 → yellow
        (70.0, timedelta(hours=2, minutes=30), ansi.ORANGE),  # delta 20 → orange
        (90.0, timedelta(hours=2, minutes=30), ansi.RED),  # delta 40 → red
    ],
)
def test_burn_color_thresholds(
    fixed_now: datetime,
    used: float,
    elapsed_in: timedelta,
    expected_color: str,
) -> None:
    # Place ``resets_at`` so the elapsed math is exactly ``elapsed_in``
    # past window_start: window_start = now − elapsed_in, resets_at = now + (5h − elapsed_in).
    snap = _snapshot(
        now=fixed_now,
        five_used=used,
        five_resets_in=quota.FIVE_HOUR - elapsed_in,
    )
    out = quota.render_pane(snap, now=fixed_now, use_color=True)
    assert expected_color in out


# ---------- compact statusline fragment ----------


def test_render_compact_format(fixed_now: datetime) -> None:
    snap = _snapshot(now=fixed_now, five_used=36.0, seven_used=69.0)
    out = quota.render_compact(snap, now=fixed_now)
    # Midpoint windows → elapsed = 50% on both.
    assert out == "5h:36%/50% 7d:69%/50%"


def test_render_compact_empty_when_no_snapshot(initialized_hangar: Path) -> None:
    assert quota.render_compact() == ""


def test_render_compact_skips_missing_window(fixed_now: datetime) -> None:
    snap = _snapshot(now=fixed_now, five_used=10.0)
    assert quota.render_compact(snap, now=fixed_now) == "5h:10%/50%"


# ---------- statusline integration ----------


def test_statusline_includes_quota_fragment(
    initialized_hangar: Path,
    write_status_with_age,
    fixed_now: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_status_with_age("alpha", "WORKING", "going")
    snap = _snapshot(now=fixed_now, five_used=12.0, seven_used=8.0)
    monkeypatch.setattr(quota, "load_snapshot", lambda: snap)
    # Pin ``render_compact``'s now so the elapsed math is deterministic.
    monkeypatch.setattr(
        quota, "render_compact", lambda *a, **kw: "5h:12%/50% 7d:8%/50%"
    )

    from agent_hangar import dashboard

    out = dashboard.render_statusline()
    assert "[W:1]" in out
    assert "|" in out
    assert "5h:12%/50%" in out


# ---------- normalize_payload (Claude statusline JSON → on-disk shape) ----------


_FROZEN = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)


def test_normalize_converts_unix_resets_at_to_iso() -> None:
    five_resets = datetime(2026, 5, 24, 15, 0, 0, tzinfo=timezone.utc)
    seven_resets = datetime(2026, 5, 28, 5, 0, 0, tzinfo=timezone.utc)
    payload = {
        "rate_limits": {
            "five_hour": {
                "used_percentage": 36.0,
                "resets_at": int(five_resets.timestamp()),
            },
            "seven_day": {
                "used_percentage": 69.0,
                "resets_at": int(seven_resets.timestamp()),
            },
        },
        "context_window": {"used_percentage": 42.0},
    }
    out = quota.normalize_payload(payload, now=_FROZEN)
    assert out["five_hour"]["resets_at"] == "2026-05-24T15:00:00Z"
    assert out["seven_day"]["resets_at"] == "2026-05-28T05:00:00Z"
    assert out["context_window"]["used_percentage"] == 42.0
    assert out["updated_at"] == "2026-05-24T12:00:00Z"


def test_normalize_drops_window_when_missing_required_field() -> None:
    payload = {
        "rate_limits": {
            # No ``resets_at`` → window is dropped (useless for rendering).
            "five_hour": {"used_percentage": 36.0},
            # Only resets_at, no percentage → also dropped.
            "seven_day": {"resets_at": 1780322400},
        }
    }
    out = quota.normalize_payload(payload, now=_FROZEN)
    assert "five_hour" not in out
    assert "seven_day" not in out


def test_normalize_is_graceful_on_empty_payload() -> None:
    out = quota.normalize_payload({}, now=_FROZEN)
    # ``updated_at`` is always written; nothing else.
    assert set(out.keys()) == {"updated_at"}


def test_normalize_tolerates_iso_string_resets_at() -> None:
    payload = {
        "rate_limits": {
            "five_hour": {
                "used_percentage": 12.5,
                "resets_at": "2026-05-24T15:00:00Z",
            }
        }
    }
    out = quota.normalize_payload(payload, now=_FROZEN)
    assert out["five_hour"]["resets_at"] == "2026-05-24T15:00:00Z"


def test_normalize_rejects_bool_resets_at() -> None:
    payload = {"rate_limits": {"five_hour": {"used_percentage": 1.0, "resets_at": True}}}
    out = quota.normalize_payload(payload, now=_FROZEN)
    assert "five_hour" not in out


# ---------- write_snapshot / load_snapshot round-trip ----------


def test_write_and_load_snapshot_round_trip(
    initialized_hangar: Path, fixed_now: datetime
) -> None:
    payload = {
        "updated_at": "2026-05-24T12:00:00Z",
        "context_window": {"used_percentage": 42.0},
        "five_hour": {
            "used_percentage": 36.0,
            "resets_at": "2026-05-24T15:00:00Z",
        },
        "seven_day": {
            "used_percentage": 69.0,
            "resets_at": "2026-05-28T12:00:00Z",
        },
    }
    config.quota_dir().mkdir(parents=True, exist_ok=True)
    quota.write_snapshot(payload)

    snap = quota.load_snapshot()
    assert snap is not None
    assert snap.context_used_percentage == 42.0
    assert snap.five_hour is not None
    assert snap.five_hour.used_percentage == 36.0
    assert snap.seven_day is not None
    assert snap.seven_day.used_percentage == 69.0
    # Disk file is the only artifact — no .tmp leftovers.
    files = list(config.quota_dir().iterdir())
    assert [f.name for f in files] == ["claude.json"]


def test_write_snapshot_creates_quota_dir_if_missing(
    initialized_hangar: Path,
) -> None:
    # quota_dir doesn't exist by default — write_snapshot must mkdir parents.
    assert not config.quota_dir().exists()
    quota.write_snapshot({"updated_at": "2026-05-24T12:00:00Z"})
    assert (config.quota_dir() / "claude.json").is_file()


def test_load_snapshot_returns_none_for_corrupt_file(
    initialized_hangar: Path,
) -> None:
    config.quota_dir().mkdir(parents=True, exist_ok=True)
    (config.quota_dir() / "claude.json").write_text("{not valid json", encoding="utf-8")
    assert quota.load_snapshot() is None


def test_load_snapshot_returns_none_when_missing(initialized_hangar: Path) -> None:
    assert quota.load_snapshot() is None


