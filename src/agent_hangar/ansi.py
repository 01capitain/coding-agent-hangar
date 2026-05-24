"""ANSI escape-code helpers used by the dashboard.

Kept dependency-free on purpose. See grilled-decisions §13: pure ANSI is fine
for v1; revisit ``rich`` only if the rendering actually needs it.
"""

from __future__ import annotations

import sys

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
# 256-color orange — sits between yellow and red in the quota burn-delta scale.
ORANGE = "\033[38;5;208m"


def style(text: str, code: str, *, use_color: bool = True) -> str:
    if not use_color or not code:
        return text
    return f"{code}{text}{RESET}"


def should_use_color(*, isatty: bool | None = None, no_color_env: str | None = None) -> bool:
    """Decide whether to emit ANSI escapes.

    Defaults follow conventional CLI rules: enabled when stdout is a TTY and
    ``NO_COLOR`` is not set. The kwargs exist so tests can pin behavior.
    """
    if no_color_env is None:
        import os

        no_color_env = os.environ.get("NO_COLOR")
    if no_color_env:
        return False
    if isatty is None:
        isatty = sys.stdout.isatty()
    return bool(isatty)
