"""Additive contracts for episodic residents, separate from WorkRelease state."""
from __future__ import annotations

import re

from .contracts import ContractError, check_id


OUTCOMES = ("done", "stopped", "failed", "interrupted", "unknown", "not_started")
WORKER_STOPS = (
    "completed", "idle", "waiting_for_worker", "budget_exhausted", "context_unavailable",
    "execution_uncertain", "repeated_failure", "model_unavailable", "outside_scope",
)
RUNNER_STOPS = (
    "execution_disabled", "coordinator_busy", "timeout", "stale_generation", "output_limit",
    "invalid_result", "process_failed", "launch_failed", "recovered", "cancelled",
)


def sha256(value, name):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ContractError(f"{name} must be a lowercase SHA-256 digest")
    return value


def generation(value):
    if type(value) is not int or value < 1:
        raise ContractError("resident generation must be a positive integer")
    return value


def validate_resident_event(etype, data, item_id):
    """Called by the protected event envelope contract for every resident event."""
    if item_id is not None:
        raise ContractError("resident events cannot advance a WorkRelease item")
    check_id("resident_id", data.get("resident_id"))
    generation(data.get("generation"))
    if etype == "resident.initialized":
        for key in ("workspace", "state_dir"):
            if not isinstance(data.get(key), str) or not data[key].startswith("/"):
                raise ContractError(f"resident {key} must be absolute")
    elif etype == "resident.wake":
        check_id("wake_id", data.get("wake_id"))
        if data.get("episode_id") is not None:
            check_id("episode_id", data["episode_id"])
        for key in ("context_sha256", "profile_sha256"):
            sha256(data.get(key), key)
        if data.get("status") not in ("admitted", "duplicate", "busy", "refused"):
            raise ContractError("invalid resident wake status")
    elif etype == "resident.episode.started":
        for key in ("episode_id", "wake_id"):
            check_id(key, data.get(key))
        for key in ("context_sha256", "profile_sha256"):
            sha256(data.get(key), key)
        if not isinstance(data.get("runner_process"), dict):
            raise ContractError("resident runner birth identity is required")
        if not isinstance(data.get("child_process"), dict):
            raise ContractError("resident child birth identity is required")
    elif etype == "resident.episode.finished":
        check_id("episode_id", data.get("episode_id"))
        if data.get("outcome") not in OUTCOMES:
            raise ContractError("invalid resident outcome")
        if data.get("stop_reason") not in WORKER_STOPS + RUNNER_STOPS:
            raise ContractError("invalid resident stop reason")
        sha256(data.get("checkpoint_sha256"), "checkpoint_sha256")
        if data["outcome"] == "done" and data["stop_reason"] != "completed":
            raise ContractError("done requires an explicit completed result")
    elif etype == "resident.generation.fenced":
        previous = generation(data.get("previous_generation"))
        if data["generation"] != previous + 1:
            raise ContractError("resident fencing advances exactly one generation")
        if not isinstance(data.get("reason"), str) or not data["reason"].strip():
            raise ContractError("resident fencing requires a reason")
    else:
        raise ContractError(f"unknown resident event {etype!r}")
