"""Claude quota snapshot reader and quota rendering helpers.

The normalized snapshot lives at ``<control_home>/quotas/claude.json`` and is
refreshed by ``hangar-quota-update`` (see ``cli.quota_update``). Layout::

    {
      "updated_at": "2026-05-24T11:30:00Z",
      "context_window": { "used_percentage": 42.0 },
      "five_hour": {
        "used_percentage": 36.0,
        "resets_at": "2026-05-24T15:17:00Z"
      },
      "seven_day": {
        "used_percentage": 69.0,
        "resets_at": "2026-05-28T05:00:00Z"
      }
    }

Any of the three top-level data keys may be missing — Claude omits a window
key when the matching field isn't in the statusline JSON yet. Rendering
degrades gracefully: missing context_window hides nothing visible; a missing
window shows ``unavailable`` for that window only. Missing file entirely →
``render_pane`` shows the bootstrap hint, ``render_compact`` returns ``""``.

Per ``grilled-decisions.md`` §11 the window start (``elapsed`` bar) is
inferred from ``resets_at - window_duration``. Burn-delta = used − elapsed,
colored green ≤0, yellow ≤10, orange ≤25, red >25.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import ansi, config

FIVE_HOUR = timedelta(hours=5)
SEVEN_DAY = timedelta(days=7)

_BAR_WIDTH = 18
_BAR_FILLED = "█"
_BAR_EMPTY = "░"


@dataclass(frozen=True)
class QuotaWindow:
    """One rate-limit window (5h or 7d)."""

    label: str
    used_percentage: float
    resets_at: datetime
    duration: timedelta

    def window_started_at(self) -> datetime:
        return self.resets_at - self.duration

    def elapsed_percentage(self, *, now: datetime) -> float:
        total = self.duration.total_seconds()
        elapsed = (now - self.window_started_at()).total_seconds()
        if total <= 0:
            return 0.0
        return max(0.0, min(100.0, elapsed / total * 100.0))

    def burn_delta(self, *, now: datetime) -> float:
        return self.used_percentage - self.elapsed_percentage(now=now)


@dataclass(frozen=True)
class QuotaSnapshot:
    updated_at: datetime | None
    context_used_percentage: float | None
    five_hour: QuotaWindow | None
    seven_day: QuotaWindow | None

    def windows(self) -> list[QuotaWindow]:
        return [w for w in (self.five_hour, self.seven_day) if w is not None]


# ---------- IO ----------


def load_snapshot() -> QuotaSnapshot | None:
    """Read the normalized claude.json snapshot. Returns None if missing/unreadable."""
    path = config.quota_dir() / "claude.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(raw, dict):
        return None
    return _parse_snapshot(raw)


def _parse_snapshot(raw: dict) -> QuotaSnapshot:
    updated_at = _parse_iso(raw.get("updated_at"))
    ctx = raw.get("context_window")
    ctx_used = None
    if isinstance(ctx, dict):
        ctx_used = _coerce_percentage(ctx.get("used_percentage"))
    return QuotaSnapshot(
        updated_at=updated_at,
        context_used_percentage=ctx_used,
        five_hour=_parse_window("5 HOUR", raw.get("five_hour"), FIVE_HOUR),
        seven_day=_parse_window("7 DAY", raw.get("seven_day"), SEVEN_DAY),
    )


def _parse_window(
    label: str, raw: object, duration: timedelta
) -> QuotaWindow | None:
    if not isinstance(raw, dict):
        return None
    used = _coerce_percentage(raw.get("used_percentage"))
    resets_at = _parse_iso(raw.get("resets_at"))
    if used is None or resets_at is None:
        return None
    return QuotaWindow(
        label=label,
        used_percentage=used,
        resets_at=resets_at,
        duration=duration,
    )


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    raw = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _coerce_percentage(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------- rendering: pane ----------


def render_pane(
    snapshot: QuotaSnapshot | None = None,
    *,
    now: datetime | None = None,
    use_color: bool = True,
) -> str:
    """Multi-line quota block shown at the bottom of ``hangar-watch``."""
    if snapshot is None:
        snapshot = load_snapshot()
    if now is None:
        now = datetime.now(timezone.utc)

    header = ansi.style("USAGE QUOTAS (Claude, shared)", ansi.BOLD, use_color=use_color)
    rule = "─" * 40

    if snapshot is None or not snapshot.windows():
        body = _unavailable_body(use_color=use_color)
        return "\n".join((header, rule, body))

    lines: list[str] = [header, rule]
    for window in snapshot.windows():
        lines.append("")
        lines.extend(_render_window(window, now=now, use_color=use_color))

    if snapshot.context_used_percentage is not None:
        lines.append("")
        lines.append(_render_context_line(snapshot.context_used_percentage, use_color))
    return "\n".join(lines)


def _unavailable_body(*, use_color: bool) -> str:
    label = "Claude:"
    value = ansi.style("unavailable", ansi.DIM, use_color=use_color)
    hint = ansi.style(
        " (run `hangar-quota-update` to populate)",
        ansi.DIM,
        use_color=use_color,
    )
    return f"{label}  {value}{hint}"


def _render_window(
    window: QuotaWindow, *, now: datetime, use_color: bool
) -> list[str]:
    elapsed = window.elapsed_percentage(now=now)
    delta = window.used_percentage - elapsed
    used_color = _burn_color(delta)

    header = ansi.style(window.label, ansi.BOLD, use_color=use_color)
    used_bar = _bar(window.used_percentage)
    elapsed_bar = _bar(elapsed)
    reset = _format_reset(window.resets_at, now=now)

    used_line = (
        f"used    {ansi.style(used_bar, used_color, use_color=use_color)} "
        f"{ansi.style(f'{window.used_percentage:.0f}%', used_color, use_color=use_color)}"
    )
    # Pad based on the ansi-free width so the reset countdown column is stable.
    used_visible = len(f"used    {used_bar} {window.used_percentage:.0f}%")
    pad = max(1, 44 - used_visible)
    used_line += " " * pad + ansi.style(
        f"reset in {reset}", ansi.DIM, use_color=use_color
    )

    elapsed_line = (
        f"elapsed {ansi.style(elapsed_bar, ansi.DIM, use_color=use_color)} "
        f"{ansi.style(f'{elapsed:.0f}%', ansi.DIM, use_color=use_color)}"
    )
    return [header, used_line, elapsed_line]


def _render_context_line(used_percentage: float, use_color: bool) -> str:
    label = ansi.style("context", ansi.BOLD, use_color=use_color)
    value = ansi.style(f"{used_percentage:.0f}%", ansi.DIM, use_color=use_color)
    return f"{label} {value}"


def _bar(percent: float) -> str:
    clamped = max(0.0, min(100.0, percent))
    filled = int(round(clamped / 100.0 * _BAR_WIDTH))
    filled = max(0, min(_BAR_WIDTH, filled))
    return _BAR_FILLED * filled + _BAR_EMPTY * (_BAR_WIDTH - filled)


def _burn_color(delta: float) -> str:
    if delta <= 0:
        return ansi.GREEN
    if delta <= 10:
        return ansi.YELLOW
    if delta <= 25:
        return ansi.ORANGE
    return ansi.RED


def _format_reset(resets_at: datetime, *, now: datetime) -> str:
    delta = resets_at - now
    if delta.total_seconds() <= 0:
        return "now"
    seconds = int(delta.total_seconds())
    days = seconds // 86_400
    hours = (seconds % 86_400) // 3600
    minutes = (seconds % 3600) // 60
    if days >= 1:
        return f"{days}d {hours}h"
    if hours >= 1:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


# ---------- rendering: compact statusline ----------


def render_compact(
    snapshot: QuotaSnapshot | None = None,
    *,
    now: datetime | None = None,
) -> str:
    """Compact quota fragment for the tmux statusline. Plain text, no ANSI.

    Format: ``5h:U%/E% 7d:U%/E%``. Returns ``""`` when no snapshot is
    available so ``render_statusline`` can omit the separator.
    """
    if snapshot is None:
        snapshot = load_snapshot()
    if snapshot is None:
        return ""
    if now is None:
        now = datetime.now(timezone.utc)

    parts: list[str] = []
    if snapshot.five_hour:
        parts.append(_compact_segment("5h", snapshot.five_hour, now=now))
    if snapshot.seven_day:
        parts.append(_compact_segment("7d", snapshot.seven_day, now=now))
    return " ".join(parts)


def _compact_segment(prefix: str, window: QuotaWindow, *, now: datetime) -> str:
    elapsed = window.elapsed_percentage(now=now)
    return f"{prefix}:{window.used_percentage:.0f}%/{elapsed:.0f}%"


# ---------- normalize Claude statusline JSON → on-disk snapshot ----------


def normalize_payload(payload: dict, *, now: datetime | None = None) -> dict:
    """Turn raw Claude statusline JSON into the on-disk snapshot shape.

    Tolerant of missing fields: only writes keys it could parse. The Unix
    ``resets_at`` integer is converted to ISO 8601 here per
    ``grilled-decisions.md`` §4.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    out: dict = {"updated_at": _iso(now)}

    ctx = payload.get("context_window")
    if isinstance(ctx, dict):
        used = _coerce_percentage(ctx.get("used_percentage"))
        if used is not None:
            out["context_window"] = {"used_percentage": used}

    limits = payload.get("rate_limits")
    if isinstance(limits, dict):
        five = _normalize_window(limits.get("five_hour"))
        if five is not None:
            out["five_hour"] = five
        seven = _normalize_window(limits.get("seven_day"))
        if seven is not None:
            out["seven_day"] = seven
    return out


def _normalize_window(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    used = _coerce_percentage(raw.get("used_percentage"))
    resets_iso = _resets_at_to_iso(raw.get("resets_at"))
    if used is None and resets_iso is None:
        return None
    out: dict = {}
    if used is not None:
        out["used_percentage"] = used
    if resets_iso is not None:
        out["resets_at"] = resets_iso
    # Without both fields the window is useless for rendering; skip it.
    if "used_percentage" not in out or "resets_at" not in out:
        return None
    return out


def _resets_at_to_iso(value: object) -> str | None:
    """Accept Unix int/float seconds (Claude's shape) or an existing ISO string."""
    if value is None:
        return None
    if isinstance(value, bool):
        # bools are ints in Python — explicitly reject them.
        return None
    if isinstance(value, (int, float)):
        try:
            return _iso(datetime.fromtimestamp(value, tz=timezone.utc))
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        parsed = _parse_iso(value)
        if parsed is not None:
            return _iso(parsed)
        # Tolerate a stringified Unix timestamp.
        try:
            return _iso(datetime.fromtimestamp(float(value), tz=timezone.utc))
        except (ValueError, OverflowError, OSError):
            return None
    return None


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def write_snapshot(payload: dict) -> None:
    """Atomic write of the normalized snapshot to ``<quota_dir>/claude.json``."""
    target = config.quota_dir() / "claude.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, target)


__all__ = [
    "FIVE_HOUR",
    "SEVEN_DAY",
    "QuotaSnapshot",
    "QuotaWindow",
    "load_snapshot",
    "normalize_payload",
    "render_compact",
    "render_pane",
    "write_snapshot",
]
