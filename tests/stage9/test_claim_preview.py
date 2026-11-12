"""Preview is read-only; execution re-checks and only uses the existing run path."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from lanectl import claim_preview as cp
from lanectl import runner
from lanectl.config import load_lane, load_repos, load_releases
from lanectl.coordination import CoordinationError, VuoroClient
from tests.stage9.test_lifecycle import Client, schema


class Owner(Client):
    """Catalog-schema owner exposing the declared ``work.public.item-v1`` shape."""

    def __init__(self):
        super().__init__()
        self.value = {"authority": "sprintctl", "state": "ok", "as_of": "2026-11-12T10:00:00Z",
                      "item": {"work_id": 2895, "status": "pending", "resolution": None}}
        for operation in self.catalog["operations"]:
            if operation["name"] == "work.public.item-v1":
                operation["result_schema"] = schema({}, [])
        self.fail = None

    def invoke(self, envelope):
        if envelope["operation"] == "work.public.item-v1":
            self.calls.append(envelope)
            if self.fail:
                raise CoordinationError(self.fail)
            return deepcopy(self.value)
        return super().invoke(envelope)


class Log:
    """Fails loudly if preview or a refused execution writes/reads the log."""

    def __init__(self):
        self.calls = []

    def append(self, *args, **kwargs):
        self.calls.append(("append", args, kwargs))

    def read(self):
        self.calls.append(("read", (), {}))
        return []


def config(monkeypatch):
    release = replace(load_releases()[0], id="preview-work", repo="lanectl",
                      work="lanectl#2895", work_complete=True, draft=False)
    lane, repos = load_lane("implement"), load_repos()
    monkeypatch.setattr(cp, "readiness", lambda *args: [])
    return release, lane, repos


def reload(monkeypatch, release, lane, repos):
    monkeypatch.setattr(cp, "load_releases", lambda: [release])
    monkeypatch.setattr(cp, "load_lane", lambda name: lane)
    monkeypatch.setattr(cp, "load_repos", lambda: repos)


def runner_calls(monkeypatch, admit):
    calls = []

    def fake_admit(*args, **kwargs):
        calls.append(("admit", args, kwargs))
        return admit()

    def fake_execute(*args, **kwargs):
        calls.append(("execute", args, kwargs))
        return "executed"

    monkeypatch.setattr(runner, "admit", fake_admit)
    monkeypatch.setattr(runner, "execute", fake_execute)
    return calls


def claim(release, repos, lane):
    return runner.Claim(release, repos[release.repo], lane, f"{release.id}-a1",
                        "scripted/model", "claude")


def test_default_preview_never_registers_leases_admits_or_writes(monkeypatch):
    release, lane, repos = config(monkeypatch)
    before = (deepcopy(release), deepcopy(lane), deepcopy(repos))
    calls = runner_calls(monkeypatch, lambda: pytest.fail("preview must not admit"))
    log = Log()
    owner = Owner()
    preview = cp.preview_claim(owner, release, lane, repos)
    assert preview["allowed"], preview
    assert {call["operation"] for call in owner.calls} == {"work.public.item-v1"}
    assert calls == [] and log.calls == []
    assert (release, lane, repos) == before


def test_unknown_mismatched_and_unsafe_owner_facts_never_allow(monkeypatch):
    release, lane, repos = config(monkeypatch)
    owner = Owner()
    owner.fail = "owner refused: runner-operation-denied (HTTP 403)"
    preview = cp.preview_claim(owner, release, lane, repos)
    assert not preview["allowed"]
    assert any("owner item unavailable" in reason for reason in preview["reasons"])

    owner.fail = None
    for change in ({"state": "unavailable"},
                   {"item": {"work_id": 999, "status": "pending", "resolution": None}},
                   {"item": {"work_id": 2895, "status": "active", "resolution": None}},
                   {"item": {"work_id": 2895, "status": "pending"}}):
        owner.value = dict(deepcopy(Owner().value), **change)
        assert not cp.preview_claim(owner, release, lane, repos)["allowed"], change
    owner.value = {}
    assert not cp.preview_claim(owner, release, lane, repos)["allowed"]

    owner.value = deepcopy(Owner().value)
    for broken in (replace(release, repo="unconfigured", work="unconfigured#2895"),
                   replace(release, work="other#2895"),
                   replace(release, work_complete=False)):
        assert not cp.preview_claim(owner, broken, lane, repos)["allowed"], broken


def test_work_ref_must_be_complete_and_match_the_repository():
    assert cp.work_id(SimpleNamespace(repo="lanectl", work="lanectl#2895", work_complete=True)) == 2895
    for work, complete, repo in (("lanectl#abc", True, "lanectl"), ("other#2895", True, "lanectl"),
                                 ("lanectl#2895", False, "lanectl"), ("", False, "lanectl")):
        assert cp.work_id(SimpleNamespace(repo=repo, work=work, work_complete=complete)) is None


def test_digest_ignores_read_time_and_binds_owner_and_configuration(monkeypatch):
    release, lane, repos = config(monkeypatch)
    owner = Owner()
    ticks = iter(range(1000))
    monkeypatch.setattr(cp, "_now", lambda: f"2026-11-12T10:00:{next(ticks):04d}Z")
    first = cp.preview_claim(owner, release, lane, repos)
    second = cp.preview_claim(owner, release, lane, repos)
    assert first["observed_at"] != second["observed_at"]
    assert first["digest"] == second["digest"]

    owner.catalog["revision"] = "r8"
    assert cp.preview_claim(owner, release, lane, repos)["digest"] != first["digest"]
    owner.catalog["revision"] = "r7"
    owner.value["as_of"] = "2026-11-12T12:00:00Z"
    assert cp.preview_claim(owner, release, lane, repos)["digest"] == first["digest"]

    owner.value = deepcopy(Owner().value)
    assert cp.preview_claim(owner, release, replace(lane, revision=lane.revision + 1), repos)["digest"] != first["digest"]
    changed = dict(repos, lanectl=replace(repos["lanectl"], check_cmd=repos["lanectl"].check_cmd + " --x"))
    assert cp.preview_claim(owner, release, lane, changed)["digest"] != first["digest"]
    assert cp.preview_claim(owner, replace(release, revision=release.revision + 1), lane, repos)["digest"] != first["digest"]


def test_fresh_read_refusal_is_refused_before_admission(monkeypatch):
    release, lane, repos = config(monkeypatch)
    owner = Owner()
    preview = cp.preview_claim(owner, release, lane, repos)
    reload(monkeypatch, release, lane, repos)
    calls = runner_calls(monkeypatch, lambda: pytest.fail("admission must not run"))
    owner.value["item"]["status"] = "active"
    with pytest.raises(cp.PreviewRefused, match="not allowed"):
        cp.execute_preview(preview, Log(), client=owner)
    assert calls == []

    owner.value["item"]["status"] = "pending"
    owner.fail = "owner refused: token-revoked"
    with pytest.raises(cp.PreviewRefused):
        cp.execute_preview(preview, Log(), client=owner)
    assert calls == []


def test_changed_configuration_refuses_before_admission(monkeypatch):
    release, lane, repos = config(monkeypatch)
    owner = Owner()
    preview = cp.preview_claim(owner, release, lane, repos)
    reload(monkeypatch, replace(release, revision=release.revision + 1), lane, repos)
    calls = runner_calls(monkeypatch, lambda: pytest.fail("admission must not run"))
    with pytest.raises(cp.PreviewRefused, match="changed"):
        cp.execute_preview(preview, Log(), client=owner)
    assert calls == []


def test_missing_coordination_refuses_before_admission(monkeypatch):
    release, lane, repos = config(monkeypatch)
    owner = Owner()
    reload(monkeypatch, release, lane, repos)
    preview = cp.preview_claim(owner, release, lane, repos)
    monkeypatch.setattr(cp, "configured", lambda name: None)
    calls = runner_calls(monkeypatch, lambda: pytest.fail("admission must not run"))
    with pytest.raises(cp.PreviewRefused, match="not configured"):
        cp.execute_preview(preview, Log())
    assert calls == []


def test_duplicate_admission_text_never_executes_and_never_retries(monkeypatch):
    release, lane, repos = config(monkeypatch)
    owner = Owner()
    preview = cp.preview_claim(owner, release, lane, repos)
    reload(monkeypatch, release, lane, repos)
    calls = runner_calls(monkeypatch, lambda: "cap: concurrency 3/3")
    log = Log()
    assert cp.execute_preview(preview, log, client=owner) == "cap: concurrency 3/3"
    assert [name for name, *_ in calls] == ["admit"]
    assert log.calls == []


def test_mismatched_admission_claim_never_executes(monkeypatch):
    release, lane, repos = config(monkeypatch)
    owner = Owner()
    preview = cp.preview_claim(owner, release, lane, repos)
    reload(monkeypatch, release, lane, repos)
    calls = runner_calls(monkeypatch, lambda: claim(replace(release, revision=release.revision + 1),
                                                    repos, lane))
    with pytest.raises(cp.PreviewRefused, match="different release content"):
        cp.execute_preview(preview, Log(), client=owner)
    assert [name for name, *_ in calls] == ["admit"]


def test_matching_claim_uses_the_existing_execute(monkeypatch):
    release, lane, repos = config(monkeypatch)
    owner = Owner()
    preview = cp.preview_claim(owner, release, lane, repos)
    reload(monkeypatch, release, lane, repos)
    matched = claim(release, repos, lane)
    calls = runner_calls(monkeypatch, lambda: matched)
    log = Log()
    assert cp.execute_preview(preview, log, client=owner) == "executed"
    assert [name for name, *_ in calls] == ["admit", "execute"]
    assert calls[0][2]["only"] == release.id and calls[1][1][0] is matched


def test_cli_preview_prints_identity_and_next_command(monkeypatch, capsys):
    release, lane, repos = config(monkeypatch)
    reload(monkeypatch, release, lane, repos)
    owner = Owner()
    calls = runner_calls(monkeypatch, lambda: pytest.fail("preview must not admit"))
    args = SimpleNamespace(item=release.id, lane="implement", json=False, execute=False, expect=None)
    assert cp._cmd(args, Log(), client=owner) == 0
    out = capsys.readouterr().out
    preview = cp.preview_claim(owner, release, lane, repos)
    for value in ("preview-work", "lanectl#2895", "implement r", preview["digest"],
                  "release", "revision"):
        assert value in out
    assert cp.command(preview) in out and calls == []

    args.json = True
    assert cp._cmd(args, Log(), client=owner) == 0
    assert '"release_id": "preview-work"' in capsys.readouterr().out


def test_cli_execute_requires_an_exact_expect_and_a_complete_preview(monkeypatch, capsys):
    release, lane, repos = config(monkeypatch)
    reload(monkeypatch, release, lane, repos)
    owner = Owner()
    executed, admitted = [], []
    monkeypatch.setattr(cp, "execute_preview", lambda preview, log, **kwargs: executed.append(preview) or "ran")
    monkeypatch.setattr(runner, "admit", lambda *args, **kwargs: admitted.append(args) or pytest.fail("no admit"))
    base = dict(item=release.id, lane="implement", json=False, execute=True)
    assert cp._cmd(SimpleNamespace(**base, expect=None), Log(), client=owner) == 1
    assert "without --expect" in capsys.readouterr().out
    assert cp._cmd(SimpleNamespace(**base, expect="sha256:wrong"), Log(), client=owner) == 1
    assert "is not the current digest" in capsys.readouterr().out
    digest = cp.preview_claim(owner, release, lane, repos)["digest"]
    assert cp._cmd(SimpleNamespace(**base, expect=digest), Log(), client=owner) == 0
    assert capsys.readouterr().out.strip().endswith("ran")
    assert len(executed) == 1 and admitted == []

    owner.value["item"]["status"] = "active"
    assert cp._cmd(SimpleNamespace(**base, expect=digest), Log(), client=owner) == 1
    assert "preview is not allowed" in capsys.readouterr().out
    assert len(executed) == 1


def test_cli_registers_claim_run_with_preview_defaults():
    import argparse
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    assert cp.register(sub) == {"claim-run": cp._cmd}
    args = parser.parse_args(["claim-run", "--item", "x"])
    assert (args.item, args.lane, args.json, args.execute, args.expect) == ("x", "implement", False, False, None)
