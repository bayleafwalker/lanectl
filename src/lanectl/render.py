"""Terminal rendering helpers shared by the CLI: state words, tables, ages, errors, confirms.

Stdlib only. Colour is added on a TTY and never carries meaning alone: every state
keeps its symbol and word.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from .vocab import SYMBOLS, classify

# The estate-wide state vocabulary (operator-interface contract, section 3) lives in vocab.py.
NEEDS, FAILED, RUNNING, OK, IDLE, UNKNOWN = (SYMBOLS[k] for k in
                                             ("needs", "failed", "running", "ok", "idle", "unknown"))
_COLORS = {NEEDS: "33", FAILED: "31", RUNNING: "36", OK: "32", IDLE: "2", UNKNOWN: "2"}


class CliError(Exception):
    """A user-facing failure: what happened, why, and the exact fix (contract section 4)."""

    def __init__(self, message: str, *, why: str = "", fix: str = "", code: int = 1,
                 slug: str = "failed"):
        super().__init__(message)
        self.message, self.why, self.fix, self.code, self.slug = message, why, fix, code, slug

    def as_dict(self) -> dict:
        return {"schema": "lanectl.error/v1",
                "error": {"code": self.slug, "message": self.message, "fix": self.fix}}


def use_color(stream=None) -> bool:
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return False
    return bool(os.environ.get("FORCE_COLOR")) or stream.isatty()


def sym(symbol: str, stream=None) -> str:
    """The state symbol, coloured on a TTY."""
    return f"\x1b[{_COLORS[symbol]}m{symbol}\x1b[0m" if use_color(stream) else symbol


def state(word: str, stream=None) -> str:
    """A state word with its vocab symbol: ``▲ candidate``."""
    return f"{sym(SYMBOLS[classify(word)], stream)} {word}"


def clip(text: str, width: int) -> str:
    """One line, cut at ``width`` with an ellipsis; the full text lives under ``show``."""
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[: max(width - 1, 0)].rstrip() + "…"


def table(rows: list[list[str]], headers: list[str] | None = None, indent: str = "") -> list[str]:
    """Left-aligned columns padded to the widest cell; the last column is not padded."""
    grid = ([headers] if headers else []) + [[str(c) for c in r] for r in rows]
    widths = [max(len(r[i]) for r in grid) for i in range(len(grid[0]))] if grid else []
    return [indent + "  ".join(c if i == len(r) - 1 else c.ljust(widths[i])
                               for i, c in enumerate(r)).rstrip() for r in grid]


def ago(ts: str | None, now: datetime | None = None) -> str:
    """Relative age of an ISO-8601 timestamp (``3m ago``); ``-`` when unparseable."""
    try:
        then = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return "-"
    seconds = int(((now or datetime.now(timezone.utc)) - then).total_seconds())
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size}{unit} ago"
    return "just now"


def money(value: float) -> str:
    return f"${value:,.2f}"


def count(value: float) -> str:
    """Rounded for reading: 940, 12k, 2.7M."""
    n = abs(value)
    for limit, suffix in ((1e9, "G"), (1e6, "M"), (1e3, "k")):
        if n >= limit:
            scaled = value / limit
            return f"{scaled:.1f}".rstrip("0").rstrip(".") + suffix if abs(scaled) < 10 \
                else f"{scaled:.0f}{suffix}"
    return f"{value:.0f}" if float(value).is_integer() else f"{value:.2f}"


def confirm(prompt: str, *, yes: bool = False) -> bool:
    """Ask on a TTY; proceed silently off a TTY (unattended callers) or with ``--yes``."""
    if yes or not (sys.stdin.isatty() and sys.stdout.isatty()):
        return True
    try:
        return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False
