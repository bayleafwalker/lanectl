"""Acceptance: restricted work runs only in a lane that allows it (planner-owned).

The tick timer runs the implement lane unattended; restricted work routes to first-party
(Claude) models, whose allowance is shared with interactive sessions, so it must never be
admitted there (operator direction 2026-11-10).
"""
import dataclasses

from lanectl.config import RepoSpec, load_lane
from lanectl.contracts import Acceptance, WorkRelease
from lanectl.ready import readiness


def _rel(data_class="public"):
    return WorkRelease(id="it", repo="r", base_sha="a" * 40, revision=1, title="t", outcome="o",
                       task_class="glue", size="S", data_class=data_class, scope_paths=("src/**",),
                       acceptance=Acceptance(exec=("true",), files=()), release_dir="/nonexistent")


def _repos(floor):
    return {"r": RepoSpec(name="r", path="/nonexistent", main="main", test_cmd="true",
                          check_cmd="true", worktree_root="/nonexistent", data_class_floor=floor,
                          routing={"claude-sonnet-5-5": 1.0})}


def _blocked(reasons):
    return any("allow_restricted" in r for r in reasons)


def test_implement_lane_refuses_restricted_work():
    lane = load_lane("implement")
    assert lane.allow_restricted is False
    assert _blocked(readiness(_rel(), lane, _repos("restricted")))
    assert _blocked(readiness(_rel("restricted"), lane, _repos("public")))


def test_public_work_is_not_affected():
    assert not _blocked(readiness(_rel(), load_lane("implement"), _repos("public")))


def test_a_lane_that_allows_restricted_work_admits_it():
    lane = dataclasses.replace(load_lane("implement"), allow_restricted=True)
    assert not _blocked(readiness(_rel(), lane, _repos("restricted")))


def test_restricted_lane_governance():
    lane = load_lane("restricted")
    assert lane.allow_restricted is True
    assert set(lane.routing) and all(m.startswith("claude-") for m in lane.routing)
    assert lane.caps["concurrency"] == 1 and lane.caps["items_per_day"] <= 2
