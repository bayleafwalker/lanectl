"""Seed tests for contracts, projection, diff policy and decision rules (protected)."""
import pytest

from lanectl.contracts import Acceptance, ContractError, LaneRevision, WorkRelease, make_event
from lanectl.events import project_items
from lanectl.gates import decision
from lanectl.gates.diffpolicy import FileChange, evaluate

LANE = LaneRevision(
    lane="implement", revision=1, size_max="M", routing={"m": 1.0}, max_attempts=2,
    retry="different_model", caps={}, size_budget_lines={"S": 50, "M": 200},
    protected_paths=("governance/**", "src/pkg/gates/**"),
    dependency_manifests=("**/pyproject.toml",), test_globs=("tests/**/test_*.py",),
    forbidden_added_patterns=(r"pytest\.mark\.(skip|xfail)",), external_models=("m",))


def rel(**kw):
    base = dict(id="item-1", repo="r", base_sha="0" * 40, title="t", outcome="o", task_class="glue",
                size="S", data_class="public", scope_paths=("src/pkg/**", "tests/**"),
                acceptance=Acceptance(exec=("true",), files=("tests/acc/test_acc.py",)))
    base.update(kw)
    return WorkRelease(**base)


def test_event_contract_rejects_unknown_and_incomplete():
    with pytest.raises(ContractError):
        make_event("nope", {})
    with pytest.raises(ContractError):
        make_event("item.claimed", {"attempt_id": "a"}, item_id="item-1")
    with pytest.raises(ContractError):
        make_event("decision.recorded", {"attempt_id": "a", "decision": "maybe", "reasons": [],
                                         "rules_revision": "x"})
    ev = make_event("usage.recorded", {"provider": "p", "source": "s", "units": {"tokens_in": 3}})
    assert ev["schema"] == "lanectl.event/v1"


def test_release_validates_classes():
    with pytest.raises(ContractError):
        rel(size="XL")
    with pytest.raises(ContractError):
        rel(data_class="secret")
    with pytest.raises(ContractError):
        rel(id="Bad ID")


def test_clean_change_passes():
    ch = [FileChange("M", "src/pkg/a.py", 10, 2, ["x = 1"]), FileChange("A", "tests/test_a.py", 20, 0, ["def test(): ..."])]
    assert evaluate(ch, rel(), LANE, ("tests/acc/test_acc.py",)) == []


def test_red_team_editing_acceptance_or_gates_is_protected():
    ch = [FileChange("M", "tests/acc/test_acc.py", 1, 1, ["assert True"])]
    v = evaluate(ch, rel(), LANE, ("tests/acc/test_acc.py",))
    assert v and v[0].startswith("protected-path:")
    v = evaluate([FileChange("M", "src/pkg/gates/x.py", 1, 0, ["pass"])], rel(), LANE)
    assert v[0].startswith("protected-path:")
    dec, _, follow = decision.decide({"diff-policy": v}, "done", 1, 2)
    assert (dec, follow) == ("parked", "park")


def test_scope_size_deps_test_edits_and_skips():
    ch = [FileChange("M", "docs/x.md", 1, 0, ["x"]),
          FileChange("M", "src/pkg/pyproject.toml", 1, 0, ["dep"]),
          FileChange("M", "tests/test_old.py", 1, 3, ["@pytest.mark.skip"]),
          FileChange("A", "src/pkg/big.py", 300, 0, [])]
    v = evaluate(ch, rel(), LANE)
    kinds = {x.split(":")[0] for x in v}
    assert kinds == {"out-of-scope", "dependency-change", "existing-test-modified",
                     "forbidden-pattern", "size-budget"}
    assert evaluate(ch[1:3], rel(allow_deps=True, allow_test_edits=True), LANE) == \
        ["forbidden-pattern: tests/test_old.py: /pytest\\.mark\\.(skip|xfail)/"]


def test_decision_rules():
    assert decision.decide({"a": []}, "done", 1, 2)[0] == "candidate"
    assert decision.decide({"a": ["x"]}, "done", 1, 2)[::2] == ("rejected", "requeue")
    assert decision.decide({"a": ["x"]}, "done", 2, 2)[::2] == ("rejected", "park")
    assert decision.decide({"a": []}, "escalated", 1, 2)[0] == "parked"
    assert decision.decide({"a": []}, "failed", 1, 2)[0] == "rejected"


def test_projection_lifecycle():
    ev = lambda t, d, i="item-1": make_event(t, d, item_id=i)
    log = [ev("release.published", {"release_id": "item-1", "revision": 1}),
           ev("item.claimed", {"attempt_id": "item-1-a1", "lane": "implement", "model": "m", "worker": "w"}),
           ev("attempt.finished", {"attempt_id": "item-1-a1", "outcome": "done", "exit_code": 0, "head_sha": "h"}),
           ev("decision.recorded", {"attempt_id": "item-1-a1", "decision": "rejected", "reasons": ["x"],
                                    "rules_revision": "v1"}),
           ev("item.requeued", {"reason": "x"})]
    assert project_items(log)["item-1"].state == "requeued"
    log += [ev("item.claimed", {"attempt_id": "item-1-a2", "lane": "implement", "model": "m", "worker": "w"}),
            ev("decision.recorded", {"attempt_id": "item-1-a2", "decision": "candidate", "reasons": [],
                                     "rules_revision": "v1"}),
            make_event("train.built", {"train_id": "t1", "base_sha": "b", "attempts": ["item-1-a2"], "passed": True})]
    v = project_items(log)["item-1"]
    assert v.state == "in-train" and len(v.attempts) == 2
    log.append(ev("item.landed", {"attempt_id": "item-1-a2", "train_id": "t1", "fix_commits": []}))
    assert project_items(log)["item-1"].state == "landed"
    log.append(ev("release.published", {"release_id": "item-1", "revision": 2}))
    assert project_items(log)["item-1"].state == "landed"   # landed items are not reopened
