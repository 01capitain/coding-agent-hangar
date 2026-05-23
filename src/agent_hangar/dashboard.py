"""Dashboard rendering for ``hangar-watch`` and ``hangar-statusline``.

Pure functions: ``render_dashboard()`` and ``render_statusline()`` produce
strings from inputs. No I/O side effects, no bell, no tmux calls — those are
the cli layer's job. The dashboard is a read-only view of the status files.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from . import ansi, config, quota, status

_STATE_COLOR = {
    "BLOCKED": ansi.RED,
    "NEEDS_FEEDBACK": ansi.YELLOW,
    "FAILED": ansi.RED,
    "STARTING_FAILED": ansi.RED,
    "READY": ansi.GREEN,
    "WORKING": ansi.CYAN,
    "STARTING": ansi.DIM,
    "PAUSED": ansi.DIM,
    "DONE": ansi.DIM,
}

_MIN_SLUG_WIDTH = 12
_MAX_SLUG_WIDTH = 36
_MIN_SUMMARY_WIDTH = 20
_DEFAULT_TERMINAL_WIDTH = 100


# ---------- full dashboard ----------


def render_dashboard(
    records: list[status.StatusRecord] | None = None,
    *,
    stale_minutes: int | None = None,
    now: datetime | None = None,
    use_color: bool = True,
    terminal_width: int = _DEFAULT_TERMINAL_WIDTH,
) -> str:
    """Render the full dashboard. Returns one string ready to print."""
    if records is None:
        records = status.list_records()
    if now is None:
        now = datetime.now(timezone.utc)
    if stale_minutes is None:
        stale_minutes = config.stale_minutes()

    lines: list[str] = []
    lines.append(_render_header(now, use_color))
    lines.append("")

    grouped = _group_by_state(records)
    rendered_any_group = False
    slug_w = _slug_width(records)
    summary_w = max(_MIN_SUMMARY_WIDTH, terminal_width - slug_w - 14)

    for state in status.STATE_PRIORITY:
        agents = grouped.get(state, [])
        if not agents:
            continue
        rendered_any_group = True
        lines.extend(
            _render_group(
                state,
                agents,
                now=now,
                stale_minutes=stale_minutes,
                use_color=use_color,
                slug_w=slug_w,
                summary_w=summary_w,
            )
        )
        lines.append("")

    if not rendered_any_group:
        lines.append(
            ansi.style(
                "(no agents yet — run `agent-spawn` to create one)",
                ansi.DIM,
                use_color=use_color,
            )
        )
        lines.append("")

    lines.append(quota.render_pane(use_color=use_color))
    return "\n".join(lines)


def _render_header(now: datetime, use_color: bool) -> str:
    timestamp = now.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return ansi.style(
        f"AGENT HANGAR  ·  refreshed {timestamp}",
        ansi.BOLD,
        use_color=use_color,
    )


def _group_by_state(
    records: Iterable[status.StatusRecord],
) -> dict[str, list[status.StatusRecord]]:
    by_state: dict[str, list[status.StatusRecord]] = {}
    for r in records:
        by_state.setdefault(r.state, []).append(r)
    # Within a state, oldest UPDATED_AT first so the longest-waiting agent is
    # at the top of its group — that's the one most likely to need attention.
    for state in by_state:
        by_state[state].sort(key=lambda r: r.updated_at)
    return by_state


def _render_group(
    state: str,
    agents: list[status.StatusRecord],
    *,
    now: datetime,
    stale_minutes: int,
    use_color: bool,
    slug_w: int,
    summary_w: int,
) -> list[str]:
    color = _STATE_COLOR.get(state, "")
    header_text = f"{state} ({len(agents)})"
    lines = [ansi.style(header_text, color + ansi.BOLD, use_color=use_color)]
    for record in agents:
        lines.append(
            _render_row(
                record,
                now=now,
                stale_minutes=stale_minutes,
                use_color=use_color,
                slug_w=slug_w,
                summary_w=summary_w,
            )
        )
    return lines


def _render_row(
    record: status.StatusRecord,
    *,
    now: datetime,
    stale_minutes: int,
    use_color: bool,
    slug_w: int,
    summary_w: int,
) -> str:
    age = status.relative_age(record.updated_at, now=now)
    summary = _truncate(record.summary, summary_w)
    slug = _truncate(record.slug, slug_w)
    base = f"  {slug.ljust(slug_w)}  {summary.ljust(summary_w)}  {age}"
    if _is_stale(record, now=now, stale_minutes=stale_minutes):
        base += "  " + ansi.style("[stale]", ansi.YELLOW, use_color=use_color)
    return base


def _is_stale(
    record: status.StatusRecord, *, now: datetime, stale_minutes: int
) -> bool:
    if record.state != "WORKING":
        return False
    return (now - record.updated_at) > timedelta(minutes=stale_minutes)


def _slug_width(records: Iterable[status.StatusRecord]) -> int:
    longest = max((len(r.slug) for r in records), default=_MIN_SLUG_WIDTH)
    return max(_MIN_SLUG_WIDTH, min(longest, _MAX_SLUG_WIDTH))


def _truncate(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[: width - 1] + "…"


# ---------- compact statusline ----------


_STATUSLINE_BUCKETS = (
    ("B", "BLOCKED"),
    ("F", "NEEDS_FEEDBACK"),
    ("R", "READY"),
    ("W", "WORKING"),
)


def render_statusline(records: list[status.StatusRecord] | None = None) -> str:
    """Return the tmux ``status-right`` one-liner.

    Plain text, no ANSI. tmux's ``status-right`` interpolation with ``#()``
    does not pass ANSI through; if colors are wanted later, switch to
    tmux's native ``#[fg=red]…#[default]`` syntax.
    """
    if records is None:
        records = status.list_records()

    counts = {state: 0 for _, state in _STATUSLINE_BUCKETS}
    for r in records:
        if r.state in counts:
            counts[r.state] += 1

    segments = [f"[{letter}:{counts[state]}]" for letter, state in _STATUSLINE_BUCKETS]
    quota_fragment = quota.render_compact()
    if quota_fragment:
        return " ".join(segments) + "  |  " + quota_fragment
    return " ".join(segments)
