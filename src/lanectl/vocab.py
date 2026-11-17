"""Operator state vocabulary: the single table the CLI, TUI and HTML views share.

Six kinds with symbols that carry meaning without colour (operator-interface
contract, section 3).  ``classify`` maps any lane, owner or fact state word to a
kind; unrecognised words are ``unknown`` rather than guessed.

Class rule:
  needs   the next step is a judgment nothing automatic will take
  running an automatic process (runner, gate, evaluator) is working on it now
  idle    waiting on nothing, or on another item's automatic progress
  failed / ok / unknown   for anything else
"""
from __future__ import annotations

SYMBOLS = {"needs": "▲", "failed": "✗", "running": "◐", "ok": "●", "idle": "○", "unknown": "◌"}
LABELS = {"needs": "needs you", "failed": "failed", "running": "running",
          "ok": "ok/done", "idle": "idle/queued", "unknown": "unknown/stale"}

#: state word -> (kind, why).  Item states come from events.project_items; the rest are
#: owner statuses and fact states.
STATES = {
    # lane item states
    "ready": ("idle", "eligible; the next `run` or tick claims it"),
    "requeued": ("idle", "returned to the queue; the next `run` or tick claims it"),
    "claimed": ("running", "a runner holds the attempt and is executing it"),
    "implemented": ("running", "the runner is between worker output and the gates"),
    "gated": ("running", "gates passed or failed; the runner records the decision next"),
    "candidate": ("needs", "accepted by the gates; only a person (or opted-in integrator) trains and lands it"),
    "in-train": ("needs", "passed a train; land or reject it, nothing lands it automatically"),
    "parked": ("needs", "stopped after attempts or review; revise, approve or reject"),
    "rejected": ("failed", "the attempt was rejected and recorded"),
    "landed": ("ok", "fast-forwarded onto main"),
    "blocked": ("needs", "not ready or flagged blocked; a person must unblock it"),
    "draft": ("needs", "held draft; publish or revise it"),
    # owner statuses
    "pending": ("idle", "owner item queued behind other work"),
    "open": ("idle", "owner item open; waiting for its turn"),
    "in-progress": ("running", "owner item is being worked on"),
    "active": ("running", "owner reports it active"),
    "running": ("running", "owner reports it running"),
    "heartbeating": ("running", "a lease holder is heartbeating"),
    "done": ("ok", "owner item finished"),
    "accepted": ("ok", "owner accepted it"),
    "failed": ("failed", "the run or read failed"),
    "error": ("failed", "an error was reported"),
    "offline": ("failed", "the source is unreachable"),
    "expired": ("failed", "lease or evidence expired"),
    "revoked": ("failed", "authority was withdrawn"),
    # fact and check states
    "ok": ("ok", "check passed"),
    "observed": ("ok", "fact read from the owner"),
    "fresh": ("ok", "evidence is current"),
    "passed": ("ok", "check passed"),
    "allowed": ("ok", "policy allows it"),
    "missing": ("needs", "required evidence is absent"),
    "below": ("needs", "under the bar; a person decides"),
    "pending-verification": ("needs", "verification waits on a person"),
    "awaiting-verification": ("needs", "verification waits on a person"),
    "review-required": ("needs", "a person must review it"),
    "needs-you": ("needs", "explicitly waiting on a person"),
    "queued": ("idle", "queued for an automatic step"),
    "new": ("idle", "not started"),
    "idle": ("idle", "nothing in progress"),
    "local": ("idle", "local only; nothing pending"),
}


def classify(state) -> str:
    word = str(state).strip().lower().replace("_", "-")
    return STATES.get(word, ("unknown", ""))[0]


def mark(state) -> str:
    """The state word prefixed by its kind's symbol: ``◐ active``."""
    return f"{SYMBOLS[classify(state)]} {state}"
