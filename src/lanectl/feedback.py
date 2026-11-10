"""Cost feedback: quota consumed versus work landed and repair burden.

The precision tables in :mod:`lanectl.report` say whether a model did good
work; this projection says what that work cost.  Tokens are attributed only
through the claim that created an attempt, so usage without an ``attempt_id``
is never guessed onto a model: it is reported separately for providers whose
usage the lane accounting controls.  ``tokens_per_landed`` is the directional
cost signal -- burning unused capacity is not itself success, and a model that
consumes quota without landing work has no defensible per-landed figure.
"""
from __future__ import annotations

#: Providers whose unattributed usage is surfaced.  Other providers' spend is
#: outside lane accounting or comes from a source we cannot qualify yet.
_UNATTRIBUTED_PROVIDERS = ("opencode",)

_MODEL_ERROR = "model-error"


def _output_tokens(units) -> float:
    """Numeric ``output_tokens`` from a usage record, or 0 when absent/bad."""
    value = (units or {}).get("output_tokens", 0) if isinstance(units, dict) else 0
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return 0


def _tidy(value: float) -> int | float:
    """Keep whole numbers integral in projections and JSON output."""
    return int(value) if float(value).is_integer() else value


def _new_row() -> dict:
    return {"attempts": 0, "infra_attempts": 0, "landed": 0, "output_tokens": 0,
            "tokens_per_landed": None, "fixes": 0, "model_error_fixes": 0}


def _infra_stopped(reasons) -> bool:
    """True when a decision's first reason marks an infrastructure stop."""
    return (isinstance(reasons, list) and bool(reasons)
            and str(reasons[0]).startswith("infra:"))


def cost_feedback(events: list[dict]) -> dict:
    """Per-model quota consumed, work landed and integrator repair burden.

    Rows are keyed by the model recorded on ``item.claimed``; usage is summed
    only when its ``attempt_id`` belongs to such a claim.  ``integrator.fix``
    events count against a model only for attempts that model landed.  The
    ``_unattributed`` key carries usage that cannot be attributed to a claim.

    ``attempts`` counts claims, while the report's ATT counts experiments;
    ``infra_attempts`` names the attempts a decision stopped for infrastructure
    (its first reason starts ``infra:``) and so never reached an experiment.
    """
    claim_model: dict[str, str] = {}         # attempt_id -> model
    rows: dict[str, dict] = {}               # model -> feedback row
    usage: list[tuple[str | None, str | None, float]] = []   # (attempt, provider, tokens)
    landed: set[str] = set()
    fixes: list[tuple[str, str]] = []        # (attempt_id, fix_class)
    infra: set[str] = set()                  # attempts a decision stopped for infra

    for ev in events:
        if not isinstance(ev, dict):
            continue
        t, d = ev.get("type"), ev.get("data")
        if not isinstance(d, dict):
            continue
        if t == "item.claimed":
            aid, model = d.get("attempt_id"), d.get("model")
            if not isinstance(aid, str) or not isinstance(model, str):
                continue
            claim_model.setdefault(aid, model)
            rows.setdefault(model, _new_row())["attempts"] += 1
        elif t == "usage.recorded":
            aid = d.get("attempt_id")
            usage.append((aid if isinstance(aid, str) else None,
                          d.get("provider"), _output_tokens(d.get("units"))))
        elif t == "decision.recorded":
            aid = d.get("attempt_id")
            if isinstance(aid, str) and _infra_stopped(d.get("reasons")):
                infra.add(aid)
        elif t == "item.landed":
            aid = d.get("attempt_id")
            if isinstance(aid, str) and aid in claim_model:
                landed.add(aid)
        elif t == "integrator.fix":
            aid, cls = d.get("attempt_id"), d.get("fix_class")
            if isinstance(aid, str) and isinstance(cls, str):
                fixes.append((aid, cls))

    unattributed = 0
    per_model_tokens: dict[str, float] = {}
    for aid, provider, tokens in usage:
        model = claim_model.get(aid) if aid is not None else None
        if model is None:
            if aid is None and provider in _UNATTRIBUTED_PROVIDERS:
                unattributed += tokens
            continue                          # unknown attempts are not attributed
        per_model_tokens[model] = per_model_tokens.get(model, 0) + tokens

    landed_by_model: dict[str, int] = {}
    for aid in landed:
        model = claim_model[aid]
        landed_by_model[model] = landed_by_model.get(model, 0) + 1

    for aid, cls in fixes:
        if aid not in landed:
            continue
        row = rows[claim_model[aid]]
        row["fixes"] += 1
        if cls == _MODEL_ERROR:
            row["model_error_fixes"] += 1

    for model, row in rows.items():
        tokens = per_model_tokens.get(model, 0)
        row["output_tokens"] = _tidy(tokens)
        row["landed"] = landed_by_model.get(model, 0)
        row["infra_attempts"] = sum(1 for aid in infra if claim_model.get(aid) == model)
        if row["landed"]:
            row["tokens_per_landed"] = round(tokens / row["landed"])

    return {**rows, "_unattributed": {"output_tokens": _tidy(unattributed)}}


def _fmt_cost_feedback(feedback: dict) -> list[str]:
    lines = ["", "cost_feedback:"]
    for model in sorted(m for m in feedback if m != "_unattributed"):
        row = feedback[model]
        per_landed = "-" if row["tokens_per_landed"] is None else row["tokens_per_landed"]
        # Attempts are claims, and ATT in the report is experiments: claims a
        # decision stopped for infra never reach an experiment, so label them.
        infra = f" infra={row['infra_attempts']}" if row["infra_attempts"] else ""
        lines.append(f"  {model}: attempts={row['attempts']}{infra} landed={row['landed']} "
                     f"output_tokens={row['output_tokens']} "
                     f"tokens_per_landed={per_landed} fixes={row['fixes']} "
                     f"model_error_fixes={row['model_error_fixes']}")
    unattributed = (feedback.get("_unattributed") or {}).get("output_tokens", 0)
    lines.append(f"  unattributed opencode output_tokens={unattributed}")
    return lines


def report_section():
    """Report section: cost feedback per model."""
    return "cost_feedback", cost_feedback, _fmt_cost_feedback
