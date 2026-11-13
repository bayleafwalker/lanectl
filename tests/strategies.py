"""Hypothesis strategies for the lanectl event contract.

The planner-owned properties in ``tests/stage1/test_acc_event_properties.py``
draw from two generators defined here:

``valid_events()``
    Any event accepted by :func:`lanectl.contracts.validate_event`: every event
    type in ``EVENT_TYPES``, every required payload key, optional extra keys,
    and an item id that is either ``None`` or a ``check_id``-valid identifier.

``event_logs()``
    Plausible but adversarial append-only histories for a handful of items:
    releases, claims, finishes, gates, decisions, trains, landings, requeues,
    parks, repeated events and deliberately out-of-order events.

Everything generated here is JSON round-trippable and every identifier-shaped
value satisfies :func:`lanectl.contracts.check_id`.
"""
from __future__ import annotations

import string

from hypothesis import strategies as st
from hypothesis.strategies import composite

from lanectl.contracts import (
    CAPACITY_BASES,
    DECISIONS,
    EVENT_TYPES,
    TEARDOWN_REASONS,
    FIX_CLASSES,
    LANE_DECISION_KINDS,
    LANE_DECISION_PHASES,
    RECONCILE_OUTCOMES,
    check_id,
    make_event,
)

# --------------------------------------------------------------------- scalars

_ID_HEAD = string.ascii_lowercase + string.digits
_ID_TAIL = _ID_HEAD + "._-"

#: Plausible values. All of them also happen to satisfy ``check_id`` so a
#: generated identifier is never accidentally rejected by the contract.
LANES = ("implement", "review")
MODELS = ("deepseek-v4.1-flash", "deepseek-v4.1-pro", "qwen3-coder")
WORKERS = ("opencode-go", "claude", "local")
OUTCOMES = ("succeeded", "failed", "escalated", "timeout")
GATES = ("diff-policy", "fail-on-base", "acceptance", "acceptance-on-base")
PROVIDERS = ("opencode-go", "claude", "local")
SOURCES = ("adapter", "gate", "manual")
WINDOWS = ("5h", "day", "week")
POLICY_KINDS = ("lane", "allocation")
UNIT_NAMES = ("tokens_in", "tokens_out", "cache_read", "cost_micros")
REASONS = (
    "gate: diff-policy violations",
    "gate: acceptance failed on base",
    "infra: adapter timeout",
    "infra: no changes produced",
    "ok: gates passed",
)


def ids(prefix: str = "id") -> st.SearchStrategy[str]:
    """A ``check_id``-valid identifier, optionally carrying a readable prefix."""
    return st.builds(
        lambda tail: f"{prefix}-{tail}",
        st.text(alphabet=_ID_TAIL, min_size=1, max_size=31),
    )


def shas() -> st.SearchStrategy[str]:
    return st.from_regex(r"[0-9a-f]{8,40}", fullmatch=True)


def timestamps() -> st.SearchStrategy[str]:
    return st.from_regex(
        r"20[2-9]\d-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])"
        r"T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\dZ",
        fullmatch=True,
    )


def _stamp(index: int) -> str:
    """A deterministic, monotonically increasing contract-shaped timestamp."""
    return f"2026-01-01T{index // 3600 % 24:02d}:{index // 60 % 60:02d}:{index % 60:02d}Z"


_NUMBERS = st.one_of(
    st.integers(min_value=-1_000, max_value=1_000_000),
    st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6),
)

_EXTRA_VALUES = st.one_of(
    st.none(),
    st.booleans(),
    _NUMBERS,
    st.text(max_size=40),
    st.lists(st.one_of(_NUMBERS, st.text(max_size=20)), max_size=3),
    st.dictionaries(st.sampled_from(("a", "b", "c")), _NUMBERS, max_size=2),
)

#: Keys that are plausible on several payloads but never collide with the
#: required keys of the event they are attached to (see ``_extras``).
_PLAIN_EXTRA_KEYS = (
    "lane", "lane_revision", "release_revision", "model", "worker", "repo",
    "branch", "gate", "passed", "violations", "reasons", "outcome",
    "exit_code", "elapsed_s", "size", "task_class", "by", "source", "note",
    "fix_commits", "units", "observed", "reason",
)
#: Extra keys whose values are identifiers, so they must satisfy check_id.
_ID_EXTRA_KEYS = ("attempt_id", "item_id", "train_id", "release_id")
_SHA_EXTRA_KEYS = ("commit", "base_sha", "head_sha", "seed_sha")


def _extras(required: tuple[str, ...]) -> st.SearchStrategy[dict]:
    plain = tuple(k for k in _PLAIN_EXTRA_KEYS if k not in required)
    ident = tuple(k for k in _ID_EXTRA_KEYS if k not in required)
    shas_ = tuple(k for k in _SHA_EXTRA_KEYS if k not in required)
    return st.builds(
        lambda a, b, c: {**a, **b, **c},
        st.dictionaries(st.sampled_from(plain), _EXTRA_VALUES, max_size=3),
        st.dictionaries(st.sampled_from(ident), ids("extra"), max_size=2),
        st.dictionaries(st.sampled_from(shas_), shas(), max_size=2),
    )


def _reasons() -> st.SearchStrategy[list[str]]:
    return st.lists(
        st.one_of(st.sampled_from(REASONS), st.text(max_size=30)),
        min_size=0,
        max_size=4,
    )


def _units() -> st.SearchStrategy[dict]:
    return st.dictionaries(
        st.sampled_from(UNIT_NAMES),
        st.one_of(
            st.integers(min_value=0, max_value=10**9),
            st.floats(allow_nan=False, allow_infinity=False, min_value=0, max_value=1e9),
        ),
        max_size=4,
    )


# ---------------------------------------------------------------- event payloads

def _data_for(etype: str) -> st.SearchStrategy[dict]:
    """A complete required payload for ``etype`` (extras are added by callers)."""
    if etype == "release.published":
        return st.fixed_dictionaries({
            "release_id": ids("release"),
            "revision": st.integers(min_value=1, max_value=10),
        })
    if etype == "release.publication.invalidated":
        return st.fixed_dictionaries({"release_id": ids("release"), "revision": st.integers(1, 10),
            "target_event_sha256": st.just("a" * 64), "reason": st.just("incorrect"),
            "evidence_ref": st.just("git:" + "a" * 40 + ":proof")})
    if etype == "item.claimed":
        return st.fixed_dictionaries({
            "attempt_id": ids("attempt"),
            "lane": st.sampled_from(LANES),
            "model": st.sampled_from(MODELS),
            "worker": st.sampled_from(WORKERS),
        })
    if etype == "attempt.finished":
        return st.fixed_dictionaries({
            "attempt_id": ids("attempt"),
            "outcome": st.sampled_from(OUTCOMES),
            "exit_code": st.integers(min_value=-1, max_value=3),
            "head_sha": shas(),
        })
    if etype == "gate.result":
        return st.fixed_dictionaries({
            "attempt_id": ids("attempt"),
            "gate": st.sampled_from(GATES),
            "passed": st.booleans(),
            "violations": st.lists(st.text(max_size=40), max_size=3),
        })
    if etype == "decision.recorded":
        return st.fixed_dictionaries({
            "attempt_id": ids("attempt"),
            "decision": st.sampled_from(DECISIONS),
            "reasons": _reasons(),
            "rules_revision": st.one_of(
                st.integers(min_value=1, max_value=10), st.sampled_from(("integrator",))
            ),
        })
    if etype == "experiment.recorded":
        return st.fixed_dictionaries({
            "attempt_id": ids("attempt"),
            "model": st.sampled_from(MODELS),
            "worker": st.sampled_from(WORKERS),
            "task_class": st.sampled_from(("test-generators", "glue", "bugfix", "refactor")),
            "decision": st.sampled_from(DECISIONS),
            "elapsed_s": st.floats(allow_nan=False, allow_infinity=False,
                                   min_value=0, max_value=3600),
        })
    if etype == "usage.recorded":
        return st.fixed_dictionaries({
            "provider": st.sampled_from(PROVIDERS),
            "source": st.sampled_from(SOURCES),
            "units": _units(),
        })
    if etype == "window.observed":
        return st.fixed_dictionaries({
            "provider": st.sampled_from(PROVIDERS),
            "window": st.sampled_from(WINDOWS),
            "observed": st.one_of(
                st.integers(min_value=0, max_value=10**6),
                st.floats(allow_nan=False, allow_infinity=False, min_value=0, max_value=1e6),
            ),
        })
    if etype == "policy.revised":
        return st.fixed_dictionaries({
            "kind": st.sampled_from(POLICY_KINDS),
            "revision": st.integers(min_value=1, max_value=10),
            "digest": shas(),
        })
    if etype == "train.built":
        return st.fixed_dictionaries({
            "train_id": ids("train"),
            "base_sha": shas(),
            "attempts": st.lists(ids("attempt"), max_size=4),
            "passed": st.booleans(),
        })
    if etype == "item.landed":
        return st.fixed_dictionaries({
            "attempt_id": ids("attempt"),
            "train_id": ids("train"),
            "fix_commits": st.lists(shas(), max_size=3),
        })
    if etype == "item.parked":
        return st.fixed_dictionaries({"reason": st.text(min_size=1, max_size=200)})
    if etype == "item.requeued":
        return st.fixed_dictionaries({"reason": st.text(min_size=1, max_size=200)})
    if etype == "integrator.fix":
        return st.fixed_dictionaries({
            "attempt_id": ids("attempt"),
            "commit": shas(),
            "fix_class": st.sampled_from(FIX_CLASSES),
        })
    # v1 additive extension (planner, 2026-11-08): shapes the stage 2-5 lanes build to.
    if etype == "admission.shadow":
        return st.fixed_dictionaries({
            "static": st.sampled_from(("admit", "block")),
            "capacity": st.sampled_from(("admit", "block")),
            "agree": st.booleans(),
            "reasons": _reasons(),
        })
    if etype == "evaluation.recorded":
        return st.fixed_dictionaries({
            "attempt_id": ids("attempt"),
            "evaluator": st.sampled_from(("rules", "model")),
            "verdict": st.sampled_from(("accept", "reject", "abstain")),
            "rules_revision": st.text(min_size=1, max_size=40),
        })
    if etype == "landing.planned":
        return st.fixed_dictionaries({
            "train_id": ids("train"),
            "plan": st.lists(st.fixed_dictionaries({
                "attempt_id": ids("attempt"),
                "action": st.sampled_from(("land", "hold", "reject"))}), max_size=4),
            "by": st.sampled_from(("operator", "integrator-shadow")),
        })
    if etype == "triage.proposed":
        return st.fixed_dictionaries({
            "source": st.sampled_from(("check", "train", "reap")),
            "fingerprint": shas(),
            "summary": st.text(min_size=1, max_size=200),
        })
    if etype == "burn.planned":
        return st.fixed_dictionaries({
            "provider": st.sampled_from(PROVIDERS),
            "window": st.sampled_from(WINDOWS),
            "burnable": st.integers(min_value=0, max_value=10**7),
            "items": st.lists(ids("item"), max_size=6),
        })
    if etype == "lane.decision":
        return st.fixed_dictionaries({
            "decision_id": ids("dec"),
            "kind": st.sampled_from(LANE_DECISION_KINDS),
            "phase": st.sampled_from(LANE_DECISION_PHASES),
            "chosen": st.one_of(st.none(), ids("choice")),
            "mechanism": st.sampled_from(("weighted-hash/v1", "static-caps/v1", "burn-plan/v1", "gates")),
            "policy_revision": st.text(min_size=1, max_size=40),
        })
    if etype == "capacity.observed":
        return st.fixed_dictionaries({
            "provider": st.sampled_from(PROVIDERS),
            "pool": st.sampled_from(("opencode-go:default", "anthropic:default")),
            "source": st.sampled_from(("probe", "adapter", "window-detector")),
            "unit": st.sampled_from(("output_tokens", "requests")),
            "basis": st.sampled_from(CAPACITY_BASES),
            "observed_at": timestamps(),
        })
    if etype == "capacity.reserved":
        return st.fixed_dictionaries({
            "reservation_id": ids("res"),
            "provider": st.sampled_from(PROVIDERS),
            "pool": st.sampled_from(("opencode-go:default", "anthropic:default")),
            "unit": st.sampled_from(("output_tokens", "requests")),
            "amount": st.integers(min_value=0, max_value=10**7),
            "attempt_id": ids("attempt"),
        })
    if etype == "capacity.reconciled":
        return st.fixed_dictionaries({
            "reservation_id": ids("res"),
            "actual": st.one_of(st.none(), st.integers(min_value=0, max_value=10**7)),
            "outcome": st.sampled_from(RECONCILE_OUTCOMES),
        })
    if etype == "train.deployed":
        return st.fixed_dictionaries({
            "train_id": ids("train"),
            "repo": st.sampled_from(("lanectl", "homelab-analytics")),
            "namespace": ids("lane-dev"),
            "passed": st.booleans(),
            "expires_at": timestamps(),
        })
    if etype == "train.torn_down":
        return st.fixed_dictionaries({
            "train_id": ids("train"),
            "namespace": ids("lane-dev"),
            "reason": st.sampled_from(TEARDOWN_REASONS),
            "passed": st.booleans(),
        })
    if etype == "work.synced":
        return st.fixed_dictionaries({
            "work": st.sampled_from(["lanectl#1", "homelab-analytics#1553"]),
            "train_id": ids("train"),
            "closed": st.booleans(),
            "ok": st.booleans(),
        })
    raise AssertionError(f"no payload strategy for {etype!r}")


#: One strategy per event type. Built eagerly so the coverage is obvious and
#: ``valid_events`` can sample the type first.
_DATA_BY_TYPE = {etype: _data_for(etype) for etype in EVENT_TYPES}
_EVENT_TYPES = tuple(EVENT_TYPES)


# -------------------------------------------------------------- valid events

@composite
def valid_events(draw) -> dict:
    """Any event the contract accepts, including optional extra keys.

    ``item_id`` is drawn from ``None`` or a check_id-valid id so both the
    envelope-without-item and the normal case are exercised.
    """
    etype = draw(st.sampled_from(_EVENT_TYPES))
    data = dict(draw(_DATA_BY_TYPE[etype]))
    data.update(draw(_extras(EVENT_TYPES[etype])))
    item_id = draw(st.one_of(st.none(), ids("item")))
    if etype == "release.publication.invalidated":
        item_id = data["release_id"]
    if item_id is not None:
        check_id("item_id", item_id)
    return make_event(etype, data, item_id=item_id, ts=draw(timestamps()))


# ---------------------------------------------------------------- event logs

def _claim(item_id: str, attempt_id: str, revision: int, index: int) -> dict:
    return make_event("item.claimed", {
        "attempt_id": attempt_id,
        "lane": "implement",
        "lane_revision": 1,
        "model": MODELS[0],
        "worker": WORKERS[0],
        "release_revision": revision,
        "base_sha": "0" * 40,
        "branch": f"lane/{attempt_id}",
    }, item_id=item_id, ts=_stamp(index))


def _finished(item_id: str, attempt_id: str, outcome: str, index: int) -> dict:
    return make_event("attempt.finished", {
        "attempt_id": attempt_id,
        "outcome": outcome,
        "exit_code": 0 if outcome == "succeeded" else 1,
        "head_sha": "1" * 40,
        "elapsed_s": 12.5,
    }, item_id=item_id, ts=_stamp(index))


def _gate(item_id: str, attempt_id: str, gate: str, passed: bool, index: int) -> dict:
    return make_event("gate.result", {
        "attempt_id": attempt_id,
        "gate": gate,
        "passed": passed,
        "violations": [] if passed else [f"{gate}: violation"],
    }, item_id=item_id, ts=_stamp(index))


def _decision(item_id: str, attempt_id: str, decision: str, reasons: list[str], index: int) -> dict:
    return make_event("decision.recorded", {
        "attempt_id": attempt_id,
        "decision": decision,
        "reasons": reasons,
        "rules_revision": 3,
        "by": "gates",
    }, item_id=item_id, ts=_stamp(index))


def _experiment(item_id: str, attempt_id: str, decision: str, elapsed_s: float, index: int) -> dict:
    return make_event("experiment.recorded", {
        "attempt_id": attempt_id,
        "model": MODELS[0],
        "worker": WORKERS[0],
        "task_class": "test-generators",
        "decision": decision,
        "elapsed_s": elapsed_s,
    }, item_id=item_id, ts=_stamp(index))


@composite
def _landed_arc(draw, item_id: str) -> list[dict]:
    """A full, plausible arc: reject/requeue, then retry, train and land."""
    revision = draw(st.integers(min_value=1, max_value=3))
    first, second = f"{item_id}-a1", f"{item_id}-a2"
    train_id = draw(ids("train"))
    fix_class = draw(st.sampled_from(FIX_CLASSES))
    elapsed = draw(st.floats(allow_nan=False, allow_infinity=False, min_value=0, max_value=600))
    fix = draw(st.booleans())
    events = [
        make_event("release.published", {"release_id": item_id, "revision": revision},
                   item_id=item_id, ts=_stamp(0)),
        _claim(item_id, first, revision, 1),
        _finished(item_id, first, "failed", 2),
        _gate(item_id, first, "diff-policy", False, 3),
        _decision(item_id, first, "rejected", ["gate: diff-policy violations"], 4),
        _experiment(item_id, first, "rejected", elapsed, 5),
        make_event("item.requeued", {"reason": "gate: diff-policy violations"},
                   item_id=item_id, ts=_stamp(6)),
        _claim(item_id, second, revision, 7),
        _finished(item_id, second, "succeeded", 8),
        _gate(item_id, second, "diff-policy", True, 9),
        _gate(item_id, second, "acceptance", True, 10),
        _decision(item_id, second, "candidate", ["ok: gates passed"], 11),
        _experiment(item_id, second, "candidate", elapsed, 12),
        make_event("train.built", {
            "train_id": train_id,
            "repo": "lanectl",
            "base_sha": "0" * 40,
            "attempts": [second],
            "excluded": [],
            "passed": True,
        }, ts=_stamp(13)),
    ]
    if fix:
        events.append(make_event("integrator.fix", {
            "attempt_id": second,
            "commit": "2" * 40,
            "fix_class": fix_class,
            "train_id": train_id,
        }, ts=_stamp(14)))
    events.append(make_event("item.landed", {
        "attempt_id": second,
        "train_id": train_id,
        "fix_commits": ["2" * 40] if fix else [],
    }, item_id=item_id, ts=_stamp(15)))
    return events


@composite
def _parked_arc(draw, item_id: str) -> list[dict]:
    """A parked item: claim, escalation, decision, park."""
    revision = draw(st.integers(min_value=1, max_value=3))
    attempt_id = f"{item_id}-a1"
    reason = draw(st.sampled_from(REASONS))
    return [
        make_event("release.published", {"release_id": item_id, "revision": revision},
                   item_id=item_id, ts=_stamp(0)),
        _claim(item_id, attempt_id, revision, 1),
        _finished(item_id, attempt_id, "escalated", 2),
        _gate(item_id, attempt_id, "diff-policy", draw(st.booleans()), 3),
        _decision(item_id, attempt_id, "parked", [reason], 4),
        make_event("item.parked", {"reason": reason}, item_id=item_id, ts=_stamp(5)),
    ]


@composite
def _random_item_arc(draw, item_id: str) -> list[dict]:
    """Claims/decisions plus a random chance of trains, landings and repeats."""
    revision = draw(st.integers(min_value=1, max_value=5))
    events = [
        make_event("release.published", {"release_id": item_id, "revision": revision},
                   item_id=item_id, ts=_stamp(0))
    ]
    index = 1
    for n in range(1, draw(st.integers(min_value=1, max_value=3)) + 1):
        attempt_id = f"{item_id}-a{n}"
        events.append(_claim(item_id, attempt_id, revision, index))
        index += 1
        if draw(st.booleans()):
            events.append(_finished(
                item_id, attempt_id, draw(st.sampled_from(OUTCOMES)), index))
            index += 1
        for gate in draw(st.sets(st.sampled_from(GATES), max_size=3)):
            events.append(_gate(item_id, attempt_id, gate, draw(st.booleans()), index))
            index += 1
        decision = draw(st.sampled_from(DECISIONS))
        events.append(_decision(item_id, attempt_id, decision, draw(_reasons()), index))
        index += 1
        events.append(_experiment(item_id, attempt_id, decision, 1.0, index))
        index += 1
        if decision == "candidate":
            train_id = draw(ids("train"))
            passed = draw(st.booleans())
            events.append(make_event("train.built", {
                "train_id": train_id,
                "base_sha": "0" * 40,
                "attempts": [attempt_id],
                "passed": passed,
            }, ts=_stamp(index)))
            index += 1
            if passed and draw(st.booleans()):
                events.append(make_event("item.landed", {
                    "attempt_id": attempt_id,
                    "train_id": train_id,
                    "fix_commits": draw(st.lists(shas(), max_size=2)),
                }, item_id=item_id, ts=_stamp(index)))
                index += 1
        elif decision == "parked":
            events.append(make_event("item.parked", {"reason": draw(st.sampled_from(REASONS))},
                                     item_id=item_id, ts=_stamp(index)))
            index += 1
        elif decision == "rejected":
            events.append(make_event("item.requeued", {"reason": draw(st.sampled_from(REASONS))},
                                     item_id=item_id, ts=_stamp(index)))
            index += 1
        if draw(st.booleans()):  # repeated event
            events.append(make_event("gate.result", {
                "attempt_id": attempt_id,
                "gate": draw(st.sampled_from(GATES)),
                "passed": draw(st.booleans()),
                "violations": [],
            }, item_id=item_id, ts=_stamp(index)))
            index += 1
    if draw(st.booleans()):  # a new release revision revives a parked/requeued item
        events.append(make_event("release.published",
                                 {"release_id": item_id, "revision": revision + 1},
                                 item_id=item_id, ts=_stamp(index)))
    return events


@composite
def _global_arc(draw) -> list[dict]:
    """Item-less capacity and policy events that still fold cleanly."""
    events = []
    for index in range(draw(st.integers(min_value=0, max_value=3))):
        etype = draw(st.sampled_from(
            ("usage.recorded", "window.observed", "policy.revised", "experiment.recorded")
        ))
        data = dict(draw(_DATA_BY_TYPE[etype]))
        data.update(draw(_extras(EVENT_TYPES[etype])))
        events.append(make_event(etype, data, item_id=None, ts=_stamp(100 + index)))
    return events


@composite
def event_logs(draw) -> list[dict]:
    """A handful of items with adversarial, sometimes out-of-order histories.

    Every claim carries an item id (so the projection can attribute its
    attempt), while repeated events and shuffled order exercise folds that
    tolerate duplicates and events arriving before the events they refer to.
    """
    item_ids = draw(st.lists(ids("item"), min_size=2, max_size=4, unique=True))
    events: list[dict] = []
    events.extend(draw(_landed_arc(item_ids[0])))
    events.extend(draw(_parked_arc(item_ids[1])))
    for item_id in item_ids[2:]:
        events.extend(draw(_random_item_arc(item_id)))
    events.extend(draw(_global_arc()))

    rng = draw(st.randoms(use_true_random=False))
    for _ in range(draw(st.integers(min_value=1, max_value=4))):
        events.append(rng.choice(events))  # repeated events

    # Guarantee at least one out-of-order event, not just a plausible append.
    if len(events) > 1:
        source = rng.randrange(len(events))
        event = events.pop(source)
        slots = [i for i in range(len(events) + 1) if i != source]
        events.insert(rng.choice(slots), event)
    if draw(st.booleans()):
        rng.shuffle(events)  # occasionally scramble the whole log
    return events
