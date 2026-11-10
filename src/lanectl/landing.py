"""Shadow landing plans and their agreement with what the operator landed.

Stage 4 runs the integrator in shadow: ``plan_landing`` turns one ``train.built``
into per-attempt ``land`` / ``hold`` / ``reject`` advice, and ``plan_match``
compares recorded advice with the landings that followed.  The shadow never
lands anything; ``lanectl land`` remains the operator's judgment call.

Authority lives in the planner-owned ``governance/integrator.toml``:
``fix_budget_lines`` bounds how large an integrator fix may be before the
attempt should be requeued instead, and ``allowed_fix_classes`` says which fix
classes the integrator may apply itself.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from .config import home

SHADOW = "integrator-shadow"
DEFAULT_AUTHORITY = "governance/integrator.toml"


def load_authority(path: str | Path | None = None) -> dict:
    """Read the integrator authority (revision, autonomous classes, fix budget).

    ``path`` may name the file directly; otherwise it is
    ``<LANECTL_HOME>/governance/integrator.toml``.
    """
    target = Path(path) if path is not None else home() / DEFAULT_AUTHORITY
    raw = tomllib.loads(target.read_text())
    result = {
        "revision": int(raw.get("revision", 0)),
        "autonomous_classes": list(raw.get("autonomous_classes", ())),
        "fix_budget_lines": int(raw.get("fix_budget_lines", 0)),
        "allowed_fix_classes": list(raw.get("allowed_fix_classes", ())),
    }
    if "integrator_host" in raw:
        if not isinstance(raw["integrator_host"], str) or not raw["integrator_host"]:
            raise ValueError("integrator_host must be a nonempty hostname")
        result["integrator_host"] = raw["integrator_host"]
    return result


def _latest_evaluations(events: list[dict]) -> dict[str, str]:
    """attempt_id -> the verdict of its latest ``evaluation.recorded``."""
    verdicts: dict[str, str] = {}
    for ev in events:
        if isinstance(ev, dict) and ev.get("type") == "evaluation.recorded":
            data = ev.get("data") or {}
            if "attempt_id" in data and "verdict" in data:
                verdicts[data["attempt_id"]] = data["verdict"]
    return verdicts


def _latest_train(events: list[dict], train_id: str) -> dict | None:
    """The most recent ``train.built`` for *train_id* (rebuilds supersede)."""
    found = None
    for ev in events:
        if (isinstance(ev, dict) and ev.get("type") == "train.built"
                and (ev.get("data") or {}).get("train_id") == train_id):
            found = ev
    return found


def _attempt_id(entry: object) -> str | None:
    """Excluded entries are ``{attempt_id, reason}`` tables (or bare ids)."""
    if isinstance(entry, dict):
        return entry.get("attempt_id")
    if isinstance(entry, str):
        return entry
    return None


def plan_landing(events: list[dict], train_id: str, authority: dict) -> list[dict]:
    """Plan one train: included attempts in train order, then excluded ones.

    Excluded attempts are always ``reject``.  Included attempts are ``hold`` on
    a failed train; on a passed train they ``land`` only when the attempt's
    latest evaluation verdict is ``accept`` (no evaluation means ``hold``).
    ``authority`` is accepted for the planner's future promotion policy; in
    shadow mode every plan is advisory, so it does not change the actions.
    """
    train = _latest_train(events, train_id)
    if train is None:
        return []
    data = train["data"]
    verdicts = _latest_evaluations(events)
    passed = bool(data.get("passed"))
    plan = []
    for aid in data.get("attempts") or ():
        action = "hold"
        if passed and verdicts.get(aid) == "accept":
            action = "land"
        plan.append({"attempt_id": aid, "action": action})
    for entry in data.get("excluded") or ():
        aid = _attempt_id(entry)
        if aid is not None:
            plan.append({"attempt_id": aid, "action": "reject"})
    return plan


def _shadow_plans(events: list[dict]) -> dict[str, dict]:
    """train_id -> latest shadow plan record, ignoring operator plans."""
    plans: dict[str, dict] = {}
    for ev in events:
        if not isinstance(ev, dict) or ev.get("type") != "landing.planned":
            continue
        data = ev.get("data") or {}
        if data.get("by") == SHADOW and data.get("train_id") is not None:
            plans[data["train_id"]] = data
    return plans


def plan_match(events: list[dict]) -> dict:
    """Agreement between recorded shadow plans and the landings that followed.

    Only trains with a shadow plan and at least one landing are decided.  A
    plan matches when every planned ``land`` attempt landed with no
    ``model-error`` fix and no other planned attempt landed.  ``agreement`` is
    ``matched / trains`` rounded to three decimals, or ``None`` with no
    decided trains.
    """
    plans = _shadow_plans(events)
    landed: dict[str, set[str]] = {}
    model_error: set[str] = set()
    for ev in events:
        if not isinstance(ev, dict):
            continue
        data = ev.get("data") or {}
        if ev.get("type") == "item.landed":
            train_id = data.get("train_id")
            if train_id is not None and "attempt_id" in data:
                landed.setdefault(train_id, set()).add(data["attempt_id"])
        elif ev.get("type") == "integrator.fix" and data.get("fix_class") == "model-error":
            if "attempt_id" in data:
                model_error.add(data["attempt_id"])

    trains = matched = 0
    for train_id, data in plans.items():
        landing = landed.get(train_id)
        if not landing:                     # the train has not been decided yet
            continue
        trains += 1
        plan = data.get("plan") or []
        to_land = {p.get("attempt_id") for p in plan if p.get("action") == "land"}
        other = {p.get("attempt_id") for p in plan if p.get("action") != "land"}
        ok = (to_land <= landing
              and not (to_land & model_error)
              and not (other & landing))
        matched += 1 if ok else 0
    return {"trains": trains, "matched": matched,
            "agreement": round(matched / trains, 3) if trains else None}


def _fmt_plan_match(value: dict) -> list[str]:
    agreement = value.get("agreement")
    rendered = "-" if agreement is None else f"{agreement:.3f}"
    return ["", f"landing_shadow: trains={value.get('trains', 0)} "
                f"matched={value.get('matched', 0)} agreement={rendered}"]


def report_section():
    """Report section: shadow landing plan agreement."""
    return "landing_shadow", plan_match, _fmt_plan_match


def fix_budget(events: list[dict], authority: dict, fix_lines: dict) -> list[str]:
    """Warn about integrator fixes outside the authority's class or size budget."""
    allowed = set(authority.get("allowed_fix_classes") or ())
    budget = authority.get("fix_budget_lines")
    warnings = []
    for ev in events:
        if not isinstance(ev, dict) or ev.get("type") != "integrator.fix":
            continue
        data = ev.get("data") or {}
        aid, commit, cls = data.get("attempt_id"), data.get("commit"), data.get("fix_class")
        if cls not in allowed:
            warnings.append(
                f"{aid}: fix {commit} class {cls!r} is not allowed "
                f"(allowed: {', '.join(sorted(allowed)) or 'none'})")
            continue
        lines = (fix_lines or {}).get(commit)
        if (isinstance(lines, (int, float)) and not isinstance(lines, bool)
                and budget is not None and lines > budget):
            warnings.append(
                f"{aid}: fix {commit} touches {lines} lines, over the "
                f"{budget}-line budget")
    return warnings


def register(sub) -> dict:
    p = sub.add_parser("plan-landing",
                       help="shadow integrator: plan the landing of one built train")
    p.add_argument("train_id")
    p.add_argument("--record", action="store_true",
                   help="record the plan as a landing.planned event")
    return {"plan-landing": _cmd}


def _cmd(args, log) -> int:
    events = log.read()
    plan = plan_landing(events, args.train_id, load_authority())
    if not plan:
        print(f"{args.train_id}: no landing plan (unknown or empty train)")
        return 0
    for item in plan:
        print(f"{item['attempt_id']} {item['action']}")
    if args.record:
        log.append("landing.planned", {"train_id": args.train_id, "plan": plan,
                                       "by": SHADOW})
    return 0
