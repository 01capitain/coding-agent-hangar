"""Claude statusline JSON normalization and quota rendering helpers.

Phase 2 ships a stub: both render functions return "unavailable" placeholders.
Phase 3 fills in real logic (reading ~/.agent-control/quotas/claude.json,
computing burn-delta, picking colors per threshold) without changing this
module's external interface.
"""

from __future__ import annotations

from . import ansi


def render_pane(*, use_color: bool = True) -> str:
    """Multi-line quota block shown at the bottom of ``hangar-watch``."""
    header = ansi.style("USAGE QUOTAS", ansi.BOLD, use_color=use_color)
    rule = "─" * 40
    body_label = "Claude:"
    body_value = ansi.style("unavailable", ansi.DIM, use_color=use_color)
    body_hint = ansi.style(
        " (run `hangar-quota-update` to populate)",
        ansi.DIM,
        use_color=use_color,
    )
    return "\n".join((header, rule, f"{body_label}  {body_value}{body_hint}"))


def render_compact() -> str:
    """Compact quota fragment for the tmux statusline. Plain text, no ANSI."""
    return ""
