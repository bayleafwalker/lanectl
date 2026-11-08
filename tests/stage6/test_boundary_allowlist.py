"""Restricted routing is a first-party allowlist, not an external-model denylist."""
import dataclasses

from lanectl.config import RepoSpec, load_lane
from lanectl.contracts import Acceptance, WorkRelease
from lanectl.ready import eligible_models, readiness

ROUTING = {
    "claude-sonnet-5-5": 1.0,
    "gpt-5": 1.0,
    "opencode-go/other": 1.0,
    "mystery-model": 1.0,
    "scripted/double": 1.0,
}


def _rel(data_class="public"):
    return WorkRelease(id="it", repo="r", base_sha="a" * 40, revision=1, title="t", outcome="o",
                       task_class="glue", size="S", data_class=data_class,
                       scope_paths=("src/**",),
                       acceptance=Acceptance(exec=("true",), files=()), release_dir="/nonexistent")


def _repo(floor, routing):
    return RepoSpec(name="r", path="/nonexistent", main="main", test_cmd="true",
                    check_cmd="true", worktree_root="/nonexistent",
                    data_class_floor=floor, routing=routing)


def test_floor_restricted_drops_non_claude_models_not_declared_external():
    lane = load_lane("implement")
    assert eligible_models(_rel("public"), lane, _repo("restricted", ROUTING)) == {
        "claude-sonnet-5-5": 1.0}


def test_release_restricted_drops_non_claude_models_not_declared_external():
    lane = dataclasses.replace(load_lane("implement"), routing=dict(ROUTING))
    assert eligible_models(_rel("restricted"), lane) == {"claude-sonnet-5-5": 1.0}


def test_external_claude_model_is_still_dropped():
    lane = dataclasses.replace(
        load_lane("implement"),
        routing={"claude-sonnet-5-5": 1.0, "claude-outsider": 1.0},
        external_models=("claude-outsider",))
    assert eligible_models(_rel("restricted"), lane) == {"claude-sonnet-5-5": 1.0}


def test_unmappable_model_is_dropped_not_routed():
    lane = dataclasses.replace(load_lane("implement"), routing={"mystery-model": 1.0})
    assert eligible_models(_rel("restricted"), lane) == {}


def test_public_routing_is_unchanged():
    lane = load_lane("implement")
    assert eligible_models(_rel("public"), lane) == dict(lane.routing)
    assert eligible_models(_rel("public"), lane, _repo("public", ROUTING)) == ROUTING


def test_restricted_without_first_party_weight_reports_no_eligible_model():
    lane = dataclasses.replace(load_lane("implement"),
                               routing={"gpt-5": 1.0, "mystery-model": 0.5})
    repo = _repo("restricted", {})
    rel = _rel("public")
    assert eligible_models(rel, lane, repo) == {}
    reasons = readiness(rel, lane, {"r": repo})
    assert any("no eligible model" in r for r in reasons)


def test_restricted_claude_zero_weight_still_reports_no_eligible_model():
    lane = dataclasses.replace(load_lane("implement"), routing={"claude-sonnet-5-5": 0.0})
    repo = _repo("restricted", {})
    rel = _rel("public")
    assert eligible_models(rel, lane, repo) == {"claude-sonnet-5-5": 0.0}
    assert any("no eligible model" in r for r in readiness(rel, lane, {"r": repo}))
