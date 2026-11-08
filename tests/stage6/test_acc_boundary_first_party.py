"""Acceptance: restricted routing is a first-party allowlist (planner-owned)."""
import dataclasses

from lanectl.config import RepoSpec, load_lane
from lanectl.contracts import Acceptance, WorkRelease
from lanectl.ready import eligible_models


def _rel(data_class):
    return WorkRelease(id="it", repo="r", base_sha="a" * 40, revision=1, title="t", outcome="o",
                       task_class="glue", size="S", data_class=data_class, scope_paths=("src/**",),
                       acceptance=Acceptance(exec=("true",), files=()), release_dir="/nonexistent")


def _repo(floor, routing):
    return RepoSpec(name="r", path="/nonexistent", main="main", test_cmd="true", check_cmd="true",
                    worktree_root="/nonexistent", data_class_floor=floor, routing=routing)


ROUTING = {"claude-sonnet-5-5": 1.0, "gpt-5": 1.0, "opencode-go/other": 1.0, "mystery-model": 1.0}


def test_restricted_floor_keeps_only_first_party():
    lane = load_lane("implement")
    assert eligible_models(_rel("public"), lane, _repo("restricted", ROUTING)) == {"claude-sonnet-5-5": 1.0}


def test_restricted_release_keeps_only_first_party():
    lane = dataclasses.replace(load_lane("implement"), routing=dict(ROUTING))
    assert eligible_models(_rel("restricted"), lane) == {"claude-sonnet-5-5": 1.0}


def test_public_unchanged():
    lane = load_lane("implement")
    assert eligible_models(_rel("public"), lane, _repo("public", ROUTING)) == ROUTING
    assert eligible_models(_rel("public"), lane) == dict(lane.routing)
