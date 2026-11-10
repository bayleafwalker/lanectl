"""Learning projection: replace hand-set routing weights with evidence.

The posterior groups ruled attempts by ``(model, task_class)``.  A ruled
attempt is one the gates accepted and the judgment plane settled (landed or
integrator-rejected); it is *clean* when the model was not at fault, meaning no
integrator fix was classed ``model-error``.  The Beta posterior over that
count is the evidence a routing weight should follow.

``suggest`` turns posteriors into weights bounded by the planner-owned limits
in ``governance/routing.toml``: models with too few ruled attempts stay at the
prior, the best mean is scaled to ``max_weight``, and every eligible model
keeps at least ``min_weight`` so exploration never stops.  Suggestions are
advice only; changing a lane's routing remains a reviewed LaneRevision.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from .config import home, load_lane
from .events import EventLog
from .report import attribution

# Decimals for posterior means and suggested weights.
_DIGITS = 3


def _prior(limits: dict) -> tuple[float, float]:
    raw = limits["prior"]
    return float(raw[0]), float(raw[1])


def _attempt_classes(events: list[dict]) -> dict[str, tuple[str, str]]:
    """Map attempt id to ``(model, task_class)`` from experiment records."""
    seen: dict[str, tuple[str, str]] = {}
    for ev in events:
        if not isinstance(ev, dict) or ev.get("type") != "experiment.recorded":
            continue
        data = ev.get("data")
        if not isinstance(data, dict):
            continue
        aid = data.get("attempt_id")
        model = data.get("model")
        task_class = data.get("task_class")
        if not isinstance(aid, str) or aid in seen:
            continue
        if not isinstance(model, str) or not isinstance(task_class, str):
            continue
        seen[aid] = (model, task_class)
    return seen


def _counts(events: list[dict]) -> dict[tuple[str, str], dict[str, int]]:
    """Count ruled and model-clean ruled attempts per ``(model, task_class)``."""
    attributed = attribution(events)
    ruled = attributed["ruled"]
    model_clean = attributed["model_clean"]
    groups: dict[tuple[str, str], dict[str, int]] = {}
    for aid, key in _attempt_classes(events).items():
        if aid not in ruled:
            continue
        group = groups.setdefault(key, {"ruled": 0, "clean": 0})
        group["ruled"] += 1
        if aid in model_clean:
            group["clean"] += 1
    return groups


def _mean(clean: int, ruled: int, alpha: float, beta: float) -> float:
    return (alpha + clean) / (alpha + beta + ruled)


def posterior(events: list[dict], limits: dict) -> dict[tuple[str, str], dict]:
    """Beta posterior mean of model-clean landings per model and task class."""
    alpha, beta = _prior(limits)
    out: dict[tuple[str, str], dict] = {}
    for key, group in _counts(events).items():
        out[key] = {
            "ruled": group["ruled"],
            "clean": group["clean"],
            "mean": round(_mean(group["clean"], group["ruled"], alpha, beta), _DIGITS),
        }
    return out


def suggest(events: list[dict], limits: dict, models, task_class: str) -> dict[str, float]:
    """Suggested weights for eligible *models* in *task_class*.

    Models below ``min_evidence`` ruled attempts use the prior mean.  Weights
    are proportional to the mean and scaled so the largest is ``max_weight``,
    then clamped to at least ``min_weight`` and rounded to three decimals.
    """
    alpha, beta = _prior(limits)
    min_evidence = int(limits.get("min_evidence", 0))
    prior_mean = alpha / (alpha + beta)
    counts = _counts(events)

    means: dict[str, float] = {}
    for model in models:
        group = counts.get((model, task_class))
        if group is None or group["ruled"] < min_evidence:
            means[model] = prior_mean
        else:
            means[model] = _mean(group["clean"], group["ruled"], alpha, beta)
    if not means:
        return {}

    peak = max(means.values())
    max_weight = float(limits["max_weight"])
    min_weight = float(limits["min_weight"])
    if peak <= 0:
        return {model: round(min_weight, _DIGITS) for model in means}

    weights: dict[str, float] = {}
    for model, mean in means.items():
        weight = mean / peak * max_weight
        weights[model] = round(max(weight, min_weight), _DIGITS)
    return weights


def load_limits(path: Path | str | None = None) -> dict:
    """Load the planner-owned routing limits (``governance/routing.toml``)."""
    target = Path(path) if path is not None else Path(home()) / "governance" / "routing.toml"
    raw = tomllib.loads(target.read_text())
    classes = raw.get("adaptive_classes", [])
    if not isinstance(classes, list) or any(not isinstance(c, str) or not c for c in classes):
        raise ValueError("adaptive_classes must be a list of task class names")
    result = {
        "revision": int(raw.get("revision", 0)),
        "min_weight": float(raw["min_weight"]),
        "max_weight": float(raw["max_weight"]),
        "min_evidence": int(raw["min_evidence"]),
        "prior": [float(raw["prior"][0]), float(raw["prior"][1])],
    }
    if "adaptive_classes" in raw:
        result["adaptive_classes"] = classes
    if "max_relative_change" in raw:
        result["max_relative_change"] = float(raw["max_relative_change"])
    return result


def format_learning(posterior_view: dict[tuple[str, str], dict],
                    suggestions: dict[str, dict[str, float]],
                    lane_name: str, lane_revision: int,
                    current: dict[str, float]) -> str:
    """Render the posterior table and per-class suggested weights."""
    lines = [f"{'MODEL':16} {'TASK_CLASS':16} {'RULED':>6} {'CLEAN':>6} {'MEAN':>6}"]
    for (model, task_class) in sorted(posterior_view):
        row = posterior_view[(model, task_class)]
        lines.append(f"{model[:16]:16} {task_class[:16]:16} {row['ruled']:>6} "
                     f"{row['clean']:>6} {row['mean']:>6.3f}")
    for task_class in sorted(suggestions):
        lines.append("")
        lines.append(f"suggested routing for task_class {task_class} "
                     f"(lane {lane_name} r{lane_revision}):")
        for model in sorted(suggestions[task_class]):
            lines.append(f"  {model:40} current={current.get(model, 0.0):.3f} "
                         f"suggested={suggestions[task_class][model]:.3f}")
    return "\n".join(lines)


def register(sub) -> dict:
    p = sub.add_parser("learn", help="posterior evidence and suggested routing weights")
    p.add_argument("--lane", default="implement")
    return {"learn": _cmd}


def _cmd(args, log: EventLog) -> int:
    limits = load_limits()
    events = log.read()
    view = posterior(events, limits)
    lane = load_lane(args.lane)
    models = sorted(lane.routing)
    suggestions = {task_class: suggest(events, limits, models, task_class)
                   for task_class in sorted({cls for _, cls in view})}
    print(format_learning(view, suggestions, lane.lane, lane.revision, lane.routing))
    return 0
