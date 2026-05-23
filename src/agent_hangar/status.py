"""Status file read/write and the state model.

Status files live at ``<status_dir>/<slug>.status`` and use a shell-source-compatible
``KEY="value"`` format so they can be ``source``-d from bash glue. Writes are atomic
(temp file in the same directory + ``os.replace``) so concurrent updates can't leave
a partial file on disk.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from datetime import datetime, timezone

from . import config

VALID_STATES: tuple[str, ...] = (
    "STARTING",
    "WORKING",
    "NEEDS_FEEDBACK",
    "BLOCKED",
    "READY",
    "DONE",
    "FAILED",
    "PAUSED",
    "STARTING_FAILED",
)

# Order grouped statuses on the dashboard and in `agent-list`.
# Lower index = higher priority (rendered first).
STATE_PRIORITY: tuple[str, ...] = (
    "BLOCKED",
    "NEEDS_FEEDBACK",
    "FAILED",
    "STARTING_FAILED",
    "READY",
    "WORKING",
    "STARTING",
    "PAUSED",
    "DONE",
)


@dataclass(frozen=True)
class StatusRecord:
    slug: str
    state: str
    summary: str
    updated_at: datetime
    started_at: datetime

    def priority(self) -> int:
        try:
            return STATE_PRIORITY.index(self.state)
        except ValueError:
            return len(STATE_PRIORITY)


class StatusError(Exception):
    """Raised for malformed status files or invalid state transitions."""


_KEY_VALUE_LINE = re.compile(r'^([A-Z_][A-Z0-9_]*)="(.*)"\s*$')


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    # Always emit UTC with a trailing 'Z' to keep status files readable.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    raw = value.replace("Z", "+00:00")
    return datetime.fromisoformat(raw)


def parse_status_text(slug: str, text: str) -> StatusRecord:
    fields: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _KEY_VALUE_LINE.match(line)
        if not match:
            raise StatusError(f"malformed status line: {raw_line!r}")
        key, value = match.group(1), match.group(2)
        # Unescape just the two characters we ever produce when writing.
        value = value.replace('\\"', '"').replace("\\\\", "\\")
        fields[key] = value

    for required in ("SLUG", "STATE", "SUMMARY", "UPDATED_AT", "STARTED_AT"):
        if required not in fields:
            raise StatusError(f"status file for {slug} missing {required}")

    state = fields["STATE"]
    if state not in VALID_STATES:
        raise StatusError(f"unknown state {state!r} in status for {slug}")

    return StatusRecord(
        slug=fields["SLUG"],
        state=state,
        summary=fields["SUMMARY"],
        updated_at=_parse_iso(fields["UPDATED_AT"]),
        started_at=_parse_iso(fields["STARTED_AT"]),
    )


def read_status(slug: str) -> StatusRecord | None:
    path = config.status_path(slug)
    if not path.exists():
        return None
    return parse_status_text(slug, path.read_text(encoding="utf-8"))


def write_status(slug: str, state: str, summary: str) -> StatusRecord:
    if state not in VALID_STATES:
        raise StatusError(f"unknown state: {state!r}")

    status_dir = config.status_dir()
    if not status_dir.is_dir():
        raise StatusError(
            f"control directory missing at {config.control_home()}. "
            "Run `hangar-setup` first."
        )

    now = _now_utc()
    existing = read_status(slug)
    started_at = existing.started_at if existing else now

    record = StatusRecord(
        slug=slug,
        state=state,
        summary=summary,
        updated_at=now,
        started_at=started_at,
    )
    _atomic_write_status(record)
    _append_log(record)
    return record


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _render_status(record: StatusRecord) -> str:
    return "\n".join(
        (
            f'SLUG="{_escape(record.slug)}"',
            f'STATE="{_escape(record.state)}"',
            f'SUMMARY="{_escape(record.summary)}"',
            f'UPDATED_AT="{_iso(record.updated_at)}"',
            f'STARTED_AT="{_iso(record.started_at)}"',
            "",
        )
    )


def _atomic_write_status(record: StatusRecord) -> None:
    path = config.status_path(record.slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(_render_status(record), encoding="utf-8")
    os.replace(tmp, path)


def _append_log(record: StatusRecord) -> None:
    log_path = config.log_path(record.slug)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = (
        f"{_iso(record.updated_at)} {record.state} "
        f"{shlex.quote(record.summary)}\n"
    )
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(line)


def list_records() -> list[StatusRecord]:
    """Return every readable status record, skipping the archive dir."""
    status_dir = config.status_dir()
    if not status_dir.is_dir():
        return []
    records: list[StatusRecord] = []
    for path in sorted(status_dir.glob("*.status")):
        try:
            records.append(parse_status_text(path.stem, path.read_text(encoding="utf-8")))
        except StatusError:
            # Malformed files are skipped rather than blowing up the listing.
            continue
    return records


def relative_age(dt: datetime, *, now: datetime | None = None) -> str:
    """Human-friendly elapsed time, e.g. "just now", "3m ago", "2h ago", "4d ago"."""
    if now is None:
        now = _now_utc()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 30:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86_400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86_400}d ago"
