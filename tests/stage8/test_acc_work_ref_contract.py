"""Acceptance: releases carry a tracker work reference (planner-owned contract, V1)."""
import pytest

from lanectl.contracts import EVENT_TYPES, Acceptance, ContractError, WorkRelease


def _rel(**kw):
    return WorkRelease(id="it", repo="r", base_sha="a" * 40, title="t", outcome="o",
                       task_class="glue", size="S", data_class="public", scope_paths=("src/**",),
                       acceptance=Acceptance(exec=("true",), files=()), **kw)


def test_work_defaults_empty():
    r = _rel()
    assert r.work == "" and r.work_complete is False


def test_valid_work_ref():
    assert _rel(work="homelab-analytics#1553", work_complete=True).work == "homelab-analytics#1553"


@pytest.mark.parametrize("bad", ["1553", "#12", "repo#", "Repo#1", "repo#0", "repo 1"])
def test_invalid_work_ref(bad):
    with pytest.raises(ContractError):
        _rel(work=bad)


def test_complete_needs_work():
    with pytest.raises(ContractError):
        _rel(work_complete=True)


def test_work_synced_event_registered():
    assert EVENT_TYPES["work.synced"] == ("work", "train_id", "closed", "ok")
