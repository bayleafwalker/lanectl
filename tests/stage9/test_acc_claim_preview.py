from copy import deepcopy
from types import SimpleNamespace

from lanectl import claim_preview as cp
from tests.stage9.test_lifecycle import Client, schema


class Owner(Client):
    def __init__(self):
        super().__init__()
        self.value = dict(authority="sprintctl", state="ok", as_of="2026-11-12T10:00:00Z",
                          item=dict(work_id=2895, status="pending", resolution=None))
        for operation in self.catalog["operations"]:
            if operation["name"] == "work.public.item-v1":
                operation["result_schema"] = schema({}, [])

    def invoke(self, envelope):
        if envelope["operation"] == "work.public.item-v1":
            self.calls.append(envelope)
            return deepcopy(self.value)
        return super().invoke(envelope)


def config(monkeypatch):
    from lanectl.config import load_releases, load_lane, load_repos
    from dataclasses import replace
    release = replace(load_releases()[0], id="preview-work", repo="lanectl",
                      work="lanectl#2895", work_complete=True, draft=False)
    lane, repos = load_lane("implement"), load_repos()
    monkeypatch.setattr(cp, "readiness", lambda *args: [])
    return release, lane, repos


def test_preview_is_read_only_stable_and_identifies_authority(monkeypatch):
    release, lane, repos = config(monkeypatch)
    owner = Owner()
    preview = cp.preview_claim(owner, release, lane, repos)
    assert preview["allowed"], preview
    assert preview["repo"] == "lanectl" and preview["work_id"] == 2895
    assert preview["release_id"] == "preview-work" and preview["lane"] == "implement"
    assert preview["owner_revision"] == "r7" and preview["observed_at"]
    assert all(call["operation"] in ("work.public.item-v1", "work.run.resolve-v1",
               "work.lease.read-v1", "work.evidence.tail-v1") for call in owner.calls)
    assert cp.preview_claim(owner, release, lane, repos)["digest"] == preview["digest"]
    owner.catalog["revision"] = "r8"
    assert cp.preview_claim(owner, release, lane, repos)["digest"] != preview["digest"]


def test_unknown_mismatch_and_owner_active_never_allow_claim(monkeypatch):
    release, lane, repos = config(monkeypatch)
    owner = Owner()
    owner.value["item"]["work_id"] = 999
    assert not cp.preview_claim(owner, release, lane, repos)["allowed"]
    owner.value["item"]["work_id"] = 2895
    owner.value["item"]["status"] = "active"
    assert not cp.preview_claim(owner, release, lane, repos)["allowed"]
    owner.value = {}
    assert not cp.preview_claim(owner, release, lane, repos)["allowed"]


def test_execution_rechecks_before_admission_and_never_retries(monkeypatch):
    from lanectl import runner
    release, lane, repos = config(monkeypatch)
    owner = Owner()
    preview = cp.preview_claim(owner, release, lane, repos)
    monkeypatch.setattr(cp, "load_releases", lambda: [release])
    monkeypatch.setattr(cp, "load_lane", lambda name: lane)
    monkeypatch.setattr(cp, "load_repos", lambda: repos)
    calls = []
    monkeypatch.setattr(runner, "admit", lambda *args, **kwargs: calls.append("admit") or "already claimed")
    monkeypatch.setattr(runner, "execute", lambda *args: calls.append("execute"))
    owner.value["item"]["status"] = "active"
    try:
        cp.execute_preview(preview, SimpleNamespace(), client=owner)
    except (ValueError, RuntimeError):
        pass
    assert calls == []
    owner.value["item"]["status"] = "pending"
    assert "already claimed" in cp.execute_preview(preview, SimpleNamespace(), client=owner)
    assert calls == ["admit"]
