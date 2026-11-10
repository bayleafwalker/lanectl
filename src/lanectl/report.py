"""Precision and cost report over the event log.

The report is a pure projection: experiments give the population (one record
per attempt), gate decisions say which attempts the gates accepted, and the
judgment plane (landing / integrator rejection) says which accepted attempts
were ruled on.  Precision is the share of ruled attempts that landed with no
integrator fix at all.  Model precision is narrower: only fixes classed
``model-error`` count against the model, so spec gaps (the planner's) and gate
gaps (the gates') still leave an attempt clean for the model.
"""
from __future__ import annotations

import importlib
import pkgutil

from .events import EventLog

# How many decimals precision and mean elapsed time are reported with.
_DIGITS = 3

#: Section registry: name -> ``(build, fmt)``.  Stage features add a section by
#: exposing a module-level ``report_section()`` instead of editing this module.
_SECTIONS: dict[str, tuple] = {}


def register_section(name: str, build, fmt=None) -> None:
    """Register a report section.

    ``build(events)`` produces the section value and ``fmt(value)`` renders it
    as report lines; ``fmt`` may be ``None`` for a JSON-only section.
    """
    _SECTIONS[name] = (build, fmt)


def _discover_sections() -> None:
    """Import every lanectl submodule and register its ``report_section()``."""
    package = importlib.import_module(__package__)
    for info in sorted(pkgutil.iter_modules(package.__path__, package.__name__ + "."),
                       key=lambda info: info.name):
        module = importlib.import_module(info.name)
        section = getattr(module, "report_section", None)
        if callable(section):
            register_section(*section())


# Fix classes by owner.  Only model-error counts against the model; the
# planner owns spec gaps and the gates own gate gaps.
_MODEL_FIX_CLASSES = {"model-error"}
_PLANNER_FIX_CLASSES = {"spec-gap"}
_GATE_FIX_CLASSES = {"gate-gap"}


def _empty_group() -> dict:
    return {"attempts": 0, "gate_accepted": 0, "ruled": 0, "landed_clean": 0,
            "precision": None, "model_precision": None, "below_bar": False,
            "mean_elapsed_s": 0.0, "usage": {}, "fix_classes": {}}


def _add_units(target: dict, units: dict) -> None:
    for k, v in units.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            target[k] = target.get(k, 0) + v
        else:                                   # only numeric units are summed
            target[k] = v


def _below_bar(precision: float | None, ruled: int, bar: float, min_ruled: int) -> bool:
    return ruled >= min_ruled and precision is not None and precision < bar


def attribution(events: list[dict]) -> dict:
    """Attempt-level fix attribution shared by the report and status metrics.

    Gate acceptance is a gates ``candidate`` decision, or the integrator's
    approval of an attempt the gates parked as review-required (the integrator
    is the judgment plane, so its approval makes protected-path work gate
    accepted too).  ``clean`` is a landing with no fix commits at all;
    ``model_clean`` treats every fix class except ``model-error`` as not the
    model's fault, so spec gaps are the planner's and gate gaps the gates'.
    """
    gate_ok: set[str] = set()
    integrator_rejected: set[str] = set()
    landed: dict[str, list] = {}             # attempt_id -> fix_commits
    fixes: dict[str, dict[str, int]] = {}    # attempt_id -> {fix_class: count}
    fix_classes: dict[str, int] = {}

    for ev in events:
        t, d = ev["type"], ev["data"]
        if t == "decision.recorded":
            if d.get("decision") == "candidate" and d.get("by") in ("gates", "integrator"):
                gate_ok.add(d["attempt_id"])   # integrator approvals count too
            elif d.get("by") == "integrator" and d.get("decision") != "candidate":
                integrator_rejected.add(d["attempt_id"])   # approvals are not rejections
        elif t == "item.landed":
            landed[d["attempt_id"]] = list(d.get("fix_commits") or [])
        elif t == "integrator.fix":
            aid, cls = d["attempt_id"], d["fix_class"]
            per_attempt = fixes.setdefault(aid, {})
            per_attempt[cls] = per_attempt.get(cls, 0) + 1
            fix_classes[cls] = fix_classes.get(cls, 0) + 1

    ruled = gate_ok & (set(landed) | integrator_rejected)
    clean = {aid for aid, commits in landed.items()
             if not commits and not fixes.get(aid)}

    def _model_clean(aid: str) -> bool:
        """Landed, and no integrator fix was classed ``model-error``."""
        if aid not in landed:
            return False
        return not any(cls in _MODEL_FIX_CLASSES for cls in fixes.get(aid, {}))

    model_clean = {aid for aid in landed if _model_clean(aid)}
    return {"gate_ok": gate_ok, "landed": landed, "fixes": fixes,
            "fix_classes": fix_classes, "ruled": ruled, "clean": clean,
            "model_clean": model_clean}


def build_report(events: list[dict], precision_bar: float = 0.5,
                 min_ruled: int = 20) -> dict:
    """Build the per-task-class / per-model precision and cost report."""
    attributed = attribution(events)
    gate_ok = attributed["gate_ok"]
    landed = attributed["landed"]
    fixes = attributed["fixes"]
    fix_classes = attributed["fix_classes"]
    ruled_ids = attributed["ruled"]
    clean_ids = attributed["clean"]
    model_clean_ids = attributed["model_clean"]
    usage_events: list[dict] = []
    experiments: list[dict] = []

    for ev in events:
        t, d = ev["type"], ev["data"]
        if t == "experiment.recorded":
            experiments.append({"attempt_id": d["attempt_id"], "model": d["model"],
                                "task_class": d["task_class"],
                                "elapsed_s": d.get("elapsed_s", 0.0)})
        elif t == "usage.recorded" and d.get("attempt_id") and d.get("model"):
            usage_events.append({"attempt_id": d["attempt_id"], "model": d["model"],
                                 "units": d.get("units") or {}})

    # Both groupings start from the experiment records; an attempt appears
    # once under its class and once under its model.
    def _new_group() -> dict:
        return {"_ids": [], "_elapsed": 0.0, **_empty_group()}

    by_class: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
    attempt_model: dict[str, str] = {}
    attempt_class: dict[str, str] = {}
    for x in experiments:
        aid = x["attempt_id"]
        attempt_model[aid] = x["model"]
        attempt_class[aid] = x["task_class"]
        for groups, key in ((by_class, x["task_class"]), (by_model, x["model"])):
            g = groups.setdefault(key, _new_group())
            g["_ids"].append(aid)
            g["_elapsed"] += x.get("elapsed_s", 0.0)

    # Usage belongs to the model recorded on the event (falling back to the
    # model of the attempt), and to that attempt's task class when known.
    for u in usage_events:
        aid = u["attempt_id"]
        model = u["model"] or attempt_model.get(aid)
        if model in by_model:
            _add_units(by_model[model]["usage"], u["units"])
        cls = attempt_class.get(aid)
        if cls in by_class:
            _add_units(by_class[cls]["usage"], u["units"])

    def _populate(g: dict) -> None:
        ids = g["_ids"]
        g["attempts"] = len(ids)
        g["gate_accepted"] = sum(1 for aid in ids if aid in gate_ok)
        g["ruled"] = sum(1 for aid in ids if aid in ruled_ids)
        g["landed_clean"] = sum(1 for aid in ids if aid in clean_ids)
        clean_ruled = sum(1 for aid in ids if aid in clean_ids and aid in ruled_ids)
        if g["ruled"]:
            g["precision"] = round(clean_ruled / g["ruled"], _DIGITS)
        model_clean_ruled = sum(1 for aid in ids
                                if aid in model_clean_ids and aid in ruled_ids)
        if g["ruled"]:
            g["model_precision"] = round(model_clean_ruled / g["ruled"], _DIGITS)
        g["below_bar"] = _below_bar(g["model_precision"], g["ruled"],
                                    precision_bar, min_ruled)
        g["mean_elapsed_s"] = (round(g["_elapsed"] / len(ids), _DIGITS)
                               if ids else 0.0)
        for aid in ids:
            for cls, n in fixes.get(aid, {}).items():
                g["fix_classes"][cls] = g["fix_classes"].get(cls, 0) + n
        del g["_ids"], g["_elapsed"]

    for group in by_class.values():
        _populate(group)
    for group in by_model.values():
        _populate(group)

    stop_conditions = []
    planner_flags = []
    gate_flags = []
    for cls in sorted(by_class):
        g = by_class[cls]
        if g["below_bar"]:
            stop_conditions.append(
                f"task_class {cls}: precision {g['model_precision']:.3f} < "
                f"{precision_bar:g} over {g['ruled']} ruled items")
        spec_gap_ruled = sum(
            1 for aid, c in attempt_class.items()
            if c == cls and aid in ruled_ids
            and any(k in _PLANNER_FIX_CLASSES for k in fixes.get(aid, {})))
        if spec_gap_ruled:
            planner_flags.append(
                f"task_class {cls}: {spec_gap_ruled} of {g['ruled']} ruled "
                f"items needed spec-gap fixes")
        gate_gap_ruled = sum(
            1 for aid, c in attempt_class.items()
            if c == cls and aid in ruled_ids
            and any(k in _GATE_FIX_CLASSES for k in fixes.get(aid, {})))
        if gate_gap_ruled:
            gate_flags.append(
                f"task_class {cls}: {gate_gap_ruled} of {g['ruled']} ruled "
                f"items needed gate-gap fixes")

    report = {"by_class": by_class, "by_model": by_model,
              "fix_classes": fix_classes, "stop_conditions": stop_conditions,
              "planner_flags": planner_flags, "gate_flags": gate_flags,
              "precision_bar": precision_bar, "min_ruled": min_ruled}
    _discover_sections()
    for name, (build, _fmt) in _SECTIONS.items():
        report[name] = build(events)
    return report


def _fmt_precision(p: float | None) -> str:
    return "-" if p is None else f"{p:.3f}"


def _fmt_usage(units: dict) -> str:
    return ",".join(f"{k}={v}" for k, v in sorted(units.items())) or "-"


def _table(title: str, rows: dict) -> list[str]:
    # The name column fits the longest class or model name (never truncated);
    # the numeric columns keep their fixed widths, right aligned under the header.
    width = max([len(title), *(len(name) for name in rows)])
    out = [f"{title:{width}} {'ATT':>4} {'GATE':>5} {'RULED':>6} {'CLEAN':>6} "
           f"{'PREC':>6} {'MPREC':>6} {'FLAG':>6} {'MEAN_S':>8}  USAGE"]
    for name in sorted(rows):
        g = rows[name]
        flag = "below" if g["below_bar"] else "ok"
        out.append(f"{name:{width}} {g['attempts']:>4} {g['gate_accepted']:>5} "
                   f"{g['ruled']:>6} {g['landed_clean']:>6} "
                   f"{_fmt_precision(g['precision']):>6} "
                   f"{_fmt_precision(g['model_precision']):>6} {flag:>6} "
                   f"{g['mean_elapsed_s']:>8.1f}  {_fmt_usage(g['usage'])}")
    return out


def format_report(report: dict) -> str:
    """Render a report dict as a compact text table."""
    lines = _table("CLASS", report["by_class"])
    lines.append("")
    lines += _table("MODEL", report["by_model"])
    if report["fix_classes"]:
        lines.append("")
        lines.append("fix_classes: " + ", ".join(
            f"{k}={v}" for k, v in sorted(report["fix_classes"].items())))
    if report["stop_conditions"]:
        lines.append("stop_conditions:")
        lines += [f"  {s}" for s in report["stop_conditions"]]
    if report["planner_flags"]:
        lines.append("planner_flags:")
        lines += [f"  {s}" for s in report["planner_flags"]]
    if report["gate_flags"]:
        lines.append("gate_flags:")
        lines += [f"  {s}" for s in report["gate_flags"]]
    for name in sorted(_SECTIONS):
        _build, fmt = _SECTIONS[name]
        if fmt is not None and name in report:
            lines += fmt(report[name])
    return "\n".join(lines)


def register(sub) -> dict:
    p = sub.add_parser("report", help="precision, cost and stop conditions by task class and model")
    p.add_argument("--json", action="store_true", help="emit the report as JSON")
    p.add_argument("--precision-bar", type=float, default=0.5, metavar="P",
                   help="precision floor below which a task class is flagged (default 0.5)")
    p.add_argument("--min-ruled", type=int, default=20, metavar="N",
                   help="minimum ruled attempts before a class can be flagged (default 20)")
    return {"report": _cmd}


def _cmd(args, log: EventLog) -> int:
    import json
    report = build_report(log.read(), precision_bar=args.precision_bar,
                          min_ruled=args.min_ruled)
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(format_report(report))
    return 0
