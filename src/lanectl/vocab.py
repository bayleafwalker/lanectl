"""Operator state vocabulary shared by the TUI and generated HTML.

Six kinds with symbols that carry meaning without colour (operator-interface
contract, section 3).  ``classify`` maps any lane, owner or fact state word to a
kind; unrecognised words are ``unknown`` rather than guessed.
"""
from __future__ import annotations

SYMBOLS = {"needs": "▲", "failed": "✗", "running": "◐", "ok": "●", "idle": "○", "unknown": "◌"}
LABELS = {"needs": "needs you", "failed": "failed", "running": "running",
          "ok": "ok/done", "idle": "idle/queued", "unknown": "unknown/stale"}

_KINDS = {
    "needs": ("parked", "blocked", "missing", "pending-verification", "awaiting-verification",
              "review-required", "needs-you", "below"),
    "failed": ("failed", "rejected", "error", "offline", "expired", "revoked"),
    "running": ("active", "running", "claimed", "implemented", "gated", "in-train",
                "in-progress", "heartbeating"),
    "ok": ("ok", "done", "observed", "accepted", "landed", "fresh", "passed", "allowed"),
    "idle": ("ready", "queued", "candidate", "requeued", "new", "idle", "local", "draft"),
}
_BY_WORD = {word: kind for kind, words in _KINDS.items() for word in words}


def classify(state) -> str:
    return _BY_WORD.get(str(state).strip().lower(), "unknown")


def mark(state) -> str:
    """The state word prefixed by its kind's symbol: ``◐ active``."""
    return f"{SYMBOLS[classify(state)]} {state}"
