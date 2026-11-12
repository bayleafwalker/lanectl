from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from lanectl import claim_hold as hold
from lanectl.coordination import Coordinator, VuoroClient
from lanectl.claim_preview import PreviewRefused
from tests.stage9.test_coordination import owner
from tests.stage9.test_acc_claim_preview import config


@contextmanager
def setup(tmp_path, monkeypatch):
    release, lane, repos = config(monkeypatch)
    monkeypatch.setattr(hold, "load_releases", lambda: [release])
    monkeypatch.setattr(hold, "load_lane", lambda name: lane)
    monkeypatch.setattr(hold, "load_repos", lambda: repos)
    with owner() as (url, state):
        state["completion"]["item"].update(work_id=2895, status="pending")
        client = VuoroClient(url, "repo-a", lambda: "synthetic-runner")
        discover = client.discover
        def catalog():
            result = discover()
            for op in result["operations"]:
                if op["name"] == "work.public.item-v1":
                    op.update(repo_scoped=True, execution_semantics="read",
                        input_schema={"type": "object", "properties": {"work_id": {"type": "integer"}}, "required": ["work_id"]},
                        result_schema={"type": "object", "properties": {}, "required": ["authority", "state", "as_of", "item"]})
            return result
        client.discover = catalog
        yield Coordinator(client, tmp_path / "hold.sqlite"), state, release, lane, repos


def mutations(state):
    return [p for p in state["calls"] if not p["operation"].endswith(("item-v1", "tail-v1"))]


def test_hold_is_previewed_reasoned_owner_bounded_and_never_starts_a_worker(tmp_path, monkeypatch):
    from lanectl import runner
    monkeypatch.setattr(runner, "admit", lambda *a, **k: pytest.fail("hold must not admit"))
    monkeypatch.setattr(runner, "execute", lambda *a, **k: pytest.fail("hold must not execute"))
    with setup(tmp_path, monkeypatch) as (coordinator, state, release, lane, repos):
        preview = hold.preview_hold(coordinator.client, release, lane, repos, reason="Inspect before handoff")
        assert preview["allowed"] and mutations(state) == []
        result = hold.execute_hold(preview, coordinator=coordinator)
        assert result["state"] == "observed" and result["mode"] == "claim-only"
        assert result["worker_started"] is False and result["item_id"] == 2895
        assert result["expires_at"] == state["lease"]["expires_at"]
        assert datetime.fromisoformat(result["expires_at"].replace("Z", "+00:00")) > datetime.now(timezone.utc)
        assert result["source"] and result["observed_at"] and result["run_id"]
        assert state["tail"]["claims"][0]["detail"]["reason"] == "Inspect before handoff"
        before = list(mutations(state))
        state["completion"]["item"]["status"] = "active"
        resumed = hold.resume_hold(result["claim_id"], coordinator=coordinator)
        assert resumed["expires_at"] == result["expires_at"]
        assert resumed["worker_started"] is False and mutations(state) == before
        assert not any("heartbeat" in p["operation"] or "report-outcome" in p["operation"] for p in state["calls"])


def test_lost_acquire_ack_replays_the_exact_request_without_extending_or_starting(tmp_path, monkeypatch):
    with setup(tmp_path, monkeypatch) as (coordinator, state, release, lane, repos):
        preview = hold.preview_hold(coordinator.client, release, lane, repos, reason="Handoff inspection")
        state["drop"] = "work.lease.acquire-v1"
        result = hold.execute_hold(preview, coordinator=coordinator)
        assert result["state"] == "unknown" and result["claim_id"] and result["worker_started"] is False
        assert result["run_id"] == "run_test"
        resumed = hold.resume_hold(result["claim_id"], coordinator=coordinator)
        assert resumed["state"] == "observed" and resumed["expires_at"] == state["lease"]["expires_at"]
        requests = [p for p in state["calls"] if p["operation"] == "work.lease.acquire-v1"]
        assert len(requests) == 2 and requests[0] == requests[1]
        assert len([p for p in state["calls"] if p["operation"] == "work.run.register-v1"]) == 1
        assert not any("heartbeat" in p["operation"] or "report-outcome" in p["operation"] for p in state["calls"])


def test_unknown_recovery_and_blank_reason_refuse_without_mutation(tmp_path, monkeypatch):
    with setup(tmp_path, monkeypatch) as (coordinator, state, release, lane, repos):
        with pytest.raises((PreviewRefused, ValueError)):
            hold.resume_hold("hold-unknown", coordinator=coordinator)
        with pytest.raises((PreviewRefused, ValueError)):
            hold.preview_hold(coordinator.client, release, lane, repos, reason=" ")
        assert mutations(state) == []


def test_printed_hold_command_preserves_reason_as_literal_shell_text():
    import subprocess
    from lanectl.claim_hold import command
    reason = "Inspect `printf EXPANDED` and $(printf EXPANDED)"
    preview = dict(release_id="aa", lane="implement", reason=reason, digest="sha256:example")
    script = 'lanectl() { printf "%s\\n" "$@"; }\n' + command(preview)
    result = subprocess.run(["bash", "-c", script], text=True, capture_output=True, check=True)
    assert reason in result.stdout.splitlines()
