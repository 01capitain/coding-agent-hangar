"""Tests for the tmux ``status-right`` one-liner."""

from __future__ import annotations

from pathlib import Path

from agent_hangar import dashboard


def test_statusline_empty_hangar_shows_all_zeros(initialized_hangar: Path) -> None:
    out = dashboard.render_statusline()
    assert out == "[B:0] [F:0] [R:0] [W:0]"


def test_statusline_counts_each_bucket(
    initialized_hangar: Path, write_status_with_age
) -> None:
    write_status_with_age("a", "BLOCKED", "x")
    write_status_with_age("b", "BLOCKED", "y")
    write_status_with_age("c", "NEEDS_FEEDBACK", "z")
    write_status_with_age("d", "READY", "w")
    write_status_with_age("e", "WORKING", "v")
    write_status_with_age("f", "WORKING", "u")
    write_status_with_age("g", "WORKING", "t")
    # DONE rows do not count toward any visible bucket.
    write_status_with_age("h", "DONE", "old")

    out = dashboard.render_statusline()
    assert out == "[B:2] [F:1] [R:1] [W:3]"


def test_statusline_is_plain_text_no_ansi(
    initialized_hangar: Path, write_status_with_age
) -> None:
    write_status_with_age("a", "BLOCKED", "x")
    out = dashboard.render_statusline()
    assert "\033[" not in out
