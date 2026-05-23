"""Tests for the dashboard renderer.

Every test drives input through real ``.status`` files written under the
``hangar_home`` fixture's tmp_path. The user's real ``~/.agent-control/``
is never touched.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from agent_hangar import dashboard, status


def test_empty_hangar_renders_placeholder(
    initialized_hangar: Path, fixed_now: datetime
) -> None:
    out = dashboard.render_dashboard(now=fixed_now, use_color=False)
    assert "no agents yet" in out
    assert "AGENT HANGAR" in out
    assert "USAGE QUOTAS" in out


def test_header_includes_refresh_timestamp(
    initialized_hangar: Path, fixed_now: datetime
) -> None:
    out = dashboard.render_dashboard(now=fixed_now, use_color=False)
    assert "2026-05-23 19:00:00 UTC" in out


def test_groups_in_priority_order(
    initialized_hangar: Path,
    write_status_with_age,
    fixed_now: datetime,
) -> None:
    # Write status files reflecting a realistic mid-day mix.
    write_status_with_age("done-one", "DONE", "yesterday's task", age_minutes=240)
    write_status_with_age("working-one", "WORKING", "still going", age_minutes=2)
    write_status_with_age("blocked-one", "BLOCKED", "needs 403/404 call", age_minutes=12)
    write_status_with_age("ready-one", "READY", "PR up", age_minutes=30)

    out = dashboard.render_dashboard(now=fixed_now, use_color=False)
    blocked_idx = out.index("BLOCKED")
    ready_idx = out.index("READY")
    working_idx = out.index("WORKING")
    done_idx = out.index("DONE")
    assert blocked_idx < ready_idx < working_idx < done_idx


def test_empty_groups_are_skipped(
    initialized_hangar: Path,
    write_status_with_age,
    fixed_now: datetime,
) -> None:
    # Only WORKING records — no other group headers should appear.
    write_status_with_age("a", "WORKING", "doing things", age_minutes=1)
    out = dashboard.render_dashboard(now=fixed_now, use_color=False)
    assert "WORKING (1)" in out
    assert "BLOCKED" not in out
    assert "READY" not in out


def test_stale_tag_renders_for_old_working(
    initialized_hangar: Path,
    write_status_with_age,
    fixed_now: datetime,
) -> None:
    write_status_with_age("fresh", "WORKING", "moving along", age_minutes=5)
    write_status_with_age("dusty", "WORKING", "long-running", age_minutes=45)

    out = dashboard.render_dashboard(
        now=fixed_now, stale_minutes=30, use_color=False
    )
    fresh_line = next(line for line in out.splitlines() if "fresh" in line)
    dusty_line = next(line for line in out.splitlines() if "dusty" in line)
    assert "[stale]" not in fresh_line
    assert "[stale]" in dusty_line


def test_stale_tag_only_for_working_state(
    initialized_hangar: Path,
    write_status_with_age,
    fixed_now: datetime,
) -> None:
    # A BLOCKED row with old UPDATED_AT is NOT stale — only WORKING gets the tag.
    write_status_with_age("waiting", "BLOCKED", "old block", age_minutes=120)
    out = dashboard.render_dashboard(
        now=fixed_now, stale_minutes=30, use_color=False
    )
    assert "[stale]" not in out


def test_within_group_oldest_first(
    initialized_hangar: Path,
    write_status_with_age,
    fixed_now: datetime,
) -> None:
    write_status_with_age("new-block", "BLOCKED", "just blocked", age_minutes=1)
    write_status_with_age("old-block", "BLOCKED", "waiting a while", age_minutes=60)
    write_status_with_age("middle", "BLOCKED", "in between", age_minutes=15)

    out = dashboard.render_dashboard(now=fixed_now, use_color=False)
    body_lines = [
        line
        for line in out.splitlines()
        if any(slug in line for slug in ("old-block", "middle", "new-block"))
    ]
    slugs_in_order = [
        next(s for s in ("old-block", "middle", "new-block") if s in line)
        for line in body_lines
    ]
    assert slugs_in_order == ["old-block", "middle", "new-block"]


def test_render_with_color_includes_ansi_escape(
    initialized_hangar: Path,
    write_status_with_age,
    fixed_now: datetime,
) -> None:
    write_status_with_age("alpha", "BLOCKED", "needs decision", age_minutes=5)
    colored = dashboard.render_dashboard(now=fixed_now, use_color=True)
    assert "\033[" in colored

    plain = dashboard.render_dashboard(now=fixed_now, use_color=False)
    assert "\033[" not in plain


def test_long_summary_truncated_with_ellipsis(
    initialized_hangar: Path,
    write_status_with_age,
    fixed_now: datetime,
) -> None:
    huge = "x" * 500
    write_status_with_age("alpha", "WORKING", huge, age_minutes=1)
    out = dashboard.render_dashboard(
        now=fixed_now,
        use_color=False,
        terminal_width=80,
    )
    line = next(line for line in out.splitlines() if "alpha" in line)
    assert "…" in line


def test_records_argument_overrides_disk_read(fixed_now: datetime) -> None:
    """When ``records`` is passed, no disk read happens — useful as a unit test escape hatch."""
    synthetic = [
        status.StatusRecord(
            slug="alpha",
            state="BLOCKED",
            summary="needs ans",
            updated_at=fixed_now - timedelta(minutes=3),
            started_at=fixed_now - timedelta(minutes=10),
        )
    ]
    out = dashboard.render_dashboard(
        records=synthetic, now=fixed_now, use_color=False
    )
    assert "alpha" in out
    assert "BLOCKED (1)" in out
