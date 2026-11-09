"""Rules evaluator: predict the integrator's ruling on a gate-accepted attempt.

The rules live in planner-owned ``governance/evaluator.toml``.  The evaluator is a
pure projection over the attempt (features from the lane diff, then the first
matching rule) plus the append-only ``evaluation.recorded`` event that freezes the
prediction.  ``agreement`` compares those predictions with the integrator's actual
ruling per task class, which is the evidence needed before rule-based acceptance
can replace manual review.
"""
from __future__ import annotations

import operator
import subprocess
import tomllib
from pathlib import Path

from . import decisions
from .config import home, load_lane, load_releases, load_repos, match

#: Rule operators accepted by ``evaluate``.  Only these six are policy language.
_OPS = {">": operator.gt, ">=": operator.ge, "<": operator.lt,
        "<=": operator.le, "==": operator.eq}

_RULES_REL = ("governance", "evaluator.toml")


def load_rules(path=None) -> dict:
    """Load ``governance/evaluator.toml`` (or an explicit path)."""
    target = Path(path) if path is not None else home().joinpath(*_RULES_REL)
    raw = tomllib.loads(target.read_text())
    return {"revision": int(raw.get("revision", 0)),
            "default": raw.get("default", "accept"),
            "rules": [dict(rule) for rule in raw.get("rules", ())]}


def _git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()}")
    return p.stdout


def features(repo_path, seed_sha: str, head_sha: str, size_budget, test_globs) -> dict:
    """Measure a lane diff ``seed_sha..head_sha`` for the evaluator rules."""
    repo = Path(repo_path)
    changed_lines = 0
    files_touched = 0
    for line in _git(repo, "diff", "--numstat", seed_sha, head_sha).splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added, deleted = parts[0], parts[1]
        if added.isdigit():
            changed_lines += int(added)
        if deleted.isdigit():
            changed_lines += int(deleted)
        files_touched += 1
    new_test_files = 0
    for line in _git(repo, "diff", "--name-status", "--diff-filter=A",
                     seed_sha, head_sha).splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and match(parts[-1], test_globs):
            new_test_files += 1
    ratio = changed_lines / size_budget if size_budget else 0.0
    return {"changed_lines": changed_lines, "changed_lines_ratio": ratio,
            "new_test_files": new_test_files, "files_touched": files_touched}


def evaluate(features: dict, rules: dict) -> tuple[str, list[str]]:
    """First matching rule's verdict and name, else the rule set's default."""
    for rule in rules.get("rules", ()):
        feature = rule.get("feature")
        if feature not in features:
            continue
        op = _OPS.get(rule.get("op"))
        if op is None:
            raise ValueError(f"unknown evaluator operator {rule.get('op')!r}")
        if op(features[feature], rule.get("value")):
            return rule["verdict"], [rule["name"]]
    return rules.get("default", "accept"), []


def _existing_evaluation(events: list[dict], attempt_id: str) -> dict | None:
    found = None
    for ev in events:
        if ev["type"] == "evaluation.recorded" and ev["data"].get("attempt_id") == attempt_id:
            found = ev["data"]
    return found


def _attempt_context(events: list[dict], attempt_id: str) -> dict | None:
    """Resolve the repository, lane and diff SHAs of a recorded attempt."""
    claimed = finished = experiment = None
    item_id = None
    for ev in events:
        data = ev["data"]
        if data.get("attempt_id") != attempt_id:
            continue
        if ev["type"] == "item.claimed":
            claimed = data
            item_id = item_id or ev.get("item_id")
        elif ev["type"] == "attempt.finished":
            finished = data
            item_id = item_id or ev.get("item_id")
        elif ev["type"] == "experiment.recorded":
            experiment = data
            item_id = item_id or ev.get("item_id")
    if finished is None or not finished.get("head_sha"):
        return None

    release = None
    try:
        releases = {r.id: r for r in load_releases()}
        release = releases.get(item_id)
    except (OSError, KeyError, ValueError):
        releases = {}

    seed_sha = (finished.get("seed_sha")
                or (claimed or {}).get("base_sha")
                or (release.base_sha if release else None))
    if not seed_sha:
        return None

    lane = None
    lane_name = (claimed or {}).get("lane") or (release.eligible_lanes[0] if release else "implement")
    try:
        lane = load_lane(lane_name)
    except (OSError, KeyError, ValueError):
        lane = None

    repos = {}
    try:
        repos = load_repos()
    except (OSError, KeyError, ValueError):
        pass
    repo_path = None
    if release is not None and release.repo in repos:
        repo_path = repos[release.repo].path
    if repo_path is None:            # no release metadata: find the repo holding the commit
        for spec in repos.values():
            p = subprocess.run(["git", "-C", str(spec.path), "cat-file", "-e",
                                f"{finished['head_sha']}^{{commit}}"], capture_output=True)
            if p.returncode == 0:
                repo_path = spec.path
                break
    if repo_path is None:
        return None

    size = (experiment or {}).get("size") or (release.size if release else "M")
    return {"item_id": item_id, "repo_path": repo_path,
            "seed_sha": seed_sha, "head_sha": finished["head_sha"],
            "size_budget": (lane.size_budget_lines.get(size, 0) if lane else 0),
            "test_globs": (lane.test_globs if lane else ())}


def evaluate_attempt(log, attempt_id: str, rules: dict | None = None) -> dict | None:
    """Record ``evaluation.recorded`` for *attempt_id* once, returning its data."""
    events = log.read()
    existing = _existing_evaluation(events, attempt_id)
    if existing is not None:
        return existing
    # One preliminary acceptance proposal per attempt: a proposal recorded
    # earlier (a default freeze before any policy existed) is kept as the basis.
    proposed = decisions.latest_acceptance_proposal(events, attempt_id)
    try:
        rules = rules or load_rules()
    except (OSError, tomllib.TOMLDecodeError):
        return None                 # no planner policy: nothing to predict with
    ctx = _attempt_context(events, attempt_id)
    if ctx is None:
        return None
    try:
        measured = features(ctx["repo_path"], ctx["seed_sha"], ctx["head_sha"],
                            ctx["size_budget"], ctx["test_globs"])
    except (OSError, RuntimeError):
        return None                 # lane commits are gone; caller reports the skip
    verdict, reasons = evaluate(measured, rules)
    data = {"attempt_id": attempt_id, "evaluator": "rules", "verdict": verdict,
            "rules_revision": f"evaluator/v{rules['revision']}",
            "features": measured, "reasons": reasons}
    log.append("evaluation.recorded", data, item_id=ctx["item_id"])
    if proposed is None:
        # Preliminary: the gates and the integrator decide what actually lands.
        decisions.acceptance_proposed(
            log, item_id=ctx["item_id"], attempt_id=attempt_id, chosen=verdict,
            policy_revision=data["rules_revision"], reasons=reasons)
    return data


def agreement(events: list[dict]) -> dict[str, dict]:
    """Per task class: how often the evaluator's verdict matched the ruling.

    The integrator accepts an attempt that landed with no ``model-error`` fix;
    it rejects an attempt it rejected, or one that landed only after such a fix.
    Only evaluated attempts the integrator has ruled on enter the denominator.
    """
    task_class: dict[str, str] = {}
    landed: set[str] = set()
    rejected: set[str] = set()
    model_error: set[str] = set()
    verdicts: dict[str, str] = {}
    for ev in events:
        t, d = ev["type"], ev["data"]
        if t == "experiment.recorded":
            task_class[d["attempt_id"]] = d.get("task_class")
        elif t == "item.landed":
            landed.add(d["attempt_id"])
        elif t == "decision.recorded" and d.get("by") == "integrator" \
                and d.get("decision") != "candidate":
            rejected.add(d["attempt_id"])
        elif t == "integrator.fix" and d.get("fix_class") == "model-error":
            model_error.add(d["attempt_id"])
        elif t == "evaluation.recorded":
            verdicts[d["attempt_id"]] = d.get("verdict")

    groups: dict[str, dict] = {}
    for aid, verdict in verdicts.items():
        cls = task_class.get(aid)
        if cls is None or (aid not in landed and aid not in rejected):
            continue
        accepted = aid in landed and aid not in rejected and aid not in model_error
        group = groups.setdefault(cls, {"evaluated_ruled": 0, "agreed": 0, "agreement": 0.0})
        group["evaluated_ruled"] += 1
        if verdict == ("accept" if accepted else "reject"):
            group["agreed"] += 1
    for group in groups.values():
        group["agreement"] = round(group["agreed"] / group["evaluated_ruled"], 3)
    return groups


def _fmt_agreement(groups: dict[str, dict]) -> list[str]:
    lines = ["evaluator:"]
    for cls in sorted(groups or {}):
        g = groups[cls]
        lines.append(f"  {cls}: evaluated_ruled={g['evaluated_ruled']} "
                     f"agreed={g['agreed']} agreement={g['agreement']:.3f}")
    return lines


def report_section():
    """Report section: evaluator agreement per task class."""
    return "evaluator", agreement, _fmt_agreement


def _gate_accepted(events: list[dict]) -> set[str]:
    accepted = {ev["data"]["attempt_id"] for ev in events
                if ev["type"] == "decision.recorded"
                and ev["data"].get("decision") == "candidate"
                and ev["data"].get("by") in ("gates", "integrator")}
    accepted |= {ev["data"]["attempt_id"] for ev in events
                 if ev["type"] == "experiment.recorded"
                 and ev["data"].get("decision") == "candidate"}
    return accepted


def _branch_exists(repo_path: Path, branch: str) -> bool:
    p = subprocess.run(["git", "-C", str(repo_path), "rev-parse", "--verify", "--quiet",
                        f"refs/heads/{branch}"], capture_output=True)
    return p.returncode == 0


def backfill(log) -> list[str]:
    """Evaluate gate-accepted attempts that have no evaluation yet."""
    events = log.read()
    evaluated = {ev["data"].get("attempt_id") for ev in events
                 if ev["type"] == "evaluation.recorded"}
    messages = []
    rules = None
    try:
        rules = load_rules()
    except (OSError, tomllib.TOMLDecodeError):
        return ["no governance/evaluator.toml; nothing to evaluate"]
    for aid in sorted(_gate_accepted(events) - evaluated):
        ctx = _attempt_context(events, aid)
        if ctx is None:
            messages.append(f"{aid}: skipped (no attempt diff to evaluate)")
            continue
        branch = f"lane/{aid}"
        if not _branch_exists(ctx["repo_path"], branch):
            messages.append(f"{aid}: skipped (lane branch {branch} missing)")
            continue
        data = evaluate_attempt(log, aid, rules)
        if data is None:
            messages.append(f"{aid}: skipped (could not evaluate)")
        else:
            why = ", ".join(data["reasons"]) or "default"
            messages.append(f"{aid}: {data['verdict']} ({why})")
    return messages


def register(sub) -> dict:
    p = sub.add_parser("evaluate", help="rules-evaluate gate-accepted attempts")
    p.add_argument("--backfill", action="store_true",
                   help="evaluate gate-accepted attempts that have no evaluation yet")
    return {"evaluate": _cmd}


def _cmd(args, log) -> int:
    if not args.backfill:
        print("nothing to do (use --backfill)")
        return 0
    for message in backfill(log):
        print(message)
    return 0
