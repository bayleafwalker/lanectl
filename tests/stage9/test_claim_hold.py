"""Claim-only holds: preview reasoning, refusal, and exact journal recovery."""
import argparse
import subprocess
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from lanectl import claim_hold as hold
from lanectl.claim_preview import PreviewRefused
from lanectl.coordination import Coordinator, VuoroClient
from tests.stage9.test_acc_claim_preview import config
from tests.stage9.test_coordination import owner


@contextmanager
def setup(tmp_path, monkeypatch):
    """The peer owner fixture, plus the catalog-advertised public item read."""
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
                              input_schema={"type": "object", "properties": {
                                  "work_id": {"type": "integer"}}, "required": ["work_id"]},
                              result_schema={"type": "object", "properties": {}, "required": [
                                  "authority", "state", "as_of", "item"]})
            return result

        client.discover = catalog
        yield Coordinator(client, tmp_path / "hold.sqlite"), state, release, lane, repos


def mutations(state):
    return [call for call in state["calls"]
            if not call["operation"].endswith(("item-v1", "tail-v1"))]


def test_preview_is_read_only_stable_and_binds_reason_and_owner_identity(tmp_path, monkeypatch):
    with setup(tmp_path, monkeypatch) as (coordinator, state, release, lane, repos):
        first = hold.preview_hold(coordinator.client, release, lane, repos, reason="Handoff at 15:00")
        assert first["allowed"], first
        assert first["mode"] == "claim-only" and first["work_id"] == 2895
        assert first["reason"] == "Handoff at 15:00" and first["digest"].startswith("sha256:")
        assert state["tail"] is None and mutations(state) == []
        same = hold.preview_hold(coordinator.client, release, lane, repos, reason="Handoff at 15:00")
        assert same["digest"] == first["digest"]
        other = hold.preview_hold(coordinator.client, release, lane, repos, reason="Handoff at 16:00")
        assert other["digest"] != first["digest"]
        state["completion"]["item"]["status"] = "active"
        refused = hold.preview_hold(coordinator.client, release, lane, repos, reason="Handoff at 15:00")
        assert not refused["allowed"]
        assert any("not pending" in reason for reason in refused["reasons"])


def test_execute_refuses_changed_disallowed_or_non_claim_only_previews(tmp_path, monkeypatch):
    with setup(tmp_path, monkeypatch) as (coordinator, state, release, lane, repos):
        preview = hold.preview_hold(coordinator.client, release, lane, repos, reason="Review contract")
        for tampered in (dict(preview, reason="different plan"),
                         dict(preview, mode="claim-and-run"),
                         dict(preview, digest="sha256:" + "0" * 64)):
            with pytest.raises(PreviewRefused):
                hold.execute_hold(tampered, coordinator=coordinator)
        state["completion"]["item"]["status"] = "active"
        with pytest.raises(PreviewRefused):
            hold.execute_hold(preview, coordinator=coordinator)
        assert mutations(state) == []


def test_lost_evidence_ack_resumes_exact_observation_without_reacquiring(tmp_path, monkeypatch):
    with setup(tmp_path, monkeypatch) as (coordinator, state, release, lane, repos):
        preview = hold.preview_hold(coordinator.client, release, lane, repos, reason="Review contract")
        state["drop"] = "work.evidence.append-v1"
        result = hold.execute_hold(preview, coordinator=coordinator)
        assert result["state"] == "unknown" and result["expires_at"] == state["lease"]["expires_at"]
        assert result["worker_started"] is False and result["reason"] == "Review contract"
        acquires = [call for call in state["calls"] if call["operation"] == "work.lease.acquire-v1"]
        resumed = hold.resume_hold(result["claim_id"], coordinator=coordinator)
        assert resumed["state"] == "observed" and resumed["expires_at"] == result["expires_at"]
        assert [call for call in state["calls"]
                if call["operation"] == "work.lease.acquire-v1"] == acquires
        appends = [call for call in state["calls"] if call["operation"] == "work.evidence.append-v1"]
        assert len(appends) == 2 and appends[0] == appends[1]
        assert state["tail"]["claims"][0]["detail"]["reason"] == "Review contract"
        assert not any("heartbeat" in call["operation"] or "report-outcome" in call["operation"]
                       for call in state["calls"])


def test_lost_registration_ack_resumes_exact_registration_then_holds(tmp_path, monkeypatch):
    with setup(tmp_path, monkeypatch) as (coordinator, state, release, lane, repos):
        preview = hold.preview_hold(coordinator.client, release, lane, repos, reason="Inspect owner contract")
        state["drop"] = "work.run.register-v1"
        result = hold.execute_hold(preview, coordinator=coordinator)
        assert result["state"] == "unknown" and result["claim_id"] and result["run_id"] is None
        resumed = hold.resume_hold(result["claim_id"], coordinator=coordinator)
        assert resumed["state"] == "observed" and resumed["run_id"] == "run_test"
        registrations = [call for call in state["calls"]
                         if call["operation"] == "work.run.register-v1"]
        assert len(registrations) == 2 and registrations[0] == registrations[1]
        assert len([call for call in state["calls"]
                    if call["operation"] == "work.lease.acquire-v1"]) == 1
        assert state["tail"]["claims"][0]["detail"]["worker_started"] is False


def test_uncertain_acquire_receipt_keeps_the_journalled_run_id(tmp_path, monkeypatch):
    with setup(tmp_path, monkeypatch) as (coordinator, state, release, lane, repos):
        preview = hold.preview_hold(coordinator.client, release, lane, repos, reason="Handoff inspection")
        state["drop"] = "work.lease.acquire-v1"
        result = hold.execute_hold(preview, coordinator=coordinator)
        assert result["state"] == "unknown" and result["claim_id"]
        assert result["worker_started"] is False
        assert result["run_id"] == "run_test"
        resumed = hold.resume_hold(result["claim_id"], coordinator=coordinator)
        assert resumed["state"] == "observed" and resumed["run_id"] == "run_test"


class RefusingCoordinator:
    """A recovery that must refuse before touching any journal or owner byte."""

    def __init__(self, metadata, client):
        self.metadata, self.client = metadata, client

    def saved_metadata(self, claim_id):
        return self.metadata

    def recorded_binding(self, claim_id):
        pytest.fail("a refused resume must not read or replay the binding")

    def start(self, *args, **kwargs):
        pytest.fail("a refused resume must not start or reacquire")


def test_resume_refuses_unknown_foreign_or_rebound_intents(tmp_path, monkeypatch):
    with setup(tmp_path, monkeypatch) as (coordinator, state, release, lane, repos):
        with pytest.raises(PreviewRefused):
            hold.resume_hold("hold-unknown", coordinator=coordinator)
        assert mutations(state) == []
        preview = hold.preview_hold(coordinator.client, release, lane, repos, reason="Review contract")
        result = hold.execute_hold(preview, coordinator=coordinator)
        saved = coordinator.saved_metadata(result["claim_id"])
        assert saved["mode"] == "claim-only"
        other_owner = SimpleNamespace(endpoint="https://other.example", repo_id="repo-b",
                                      expected_environment=None)
        with pytest.raises(PreviewRefused):
            hold.resume_hold(result["claim_id"], coordinator=RefusingCoordinator(saved, other_owner))
        other_plan = dict(saved, reason="different plan", digest="sha256:" + "1" * 64)
        with pytest.raises(PreviewRefused):
            hold.resume_hold(result["claim_id"],
                             coordinator=RefusingCoordinator(other_plan, coordinator.client))
        not_claim_only = dict(saved, mode="claim-and-run")
        with pytest.raises(PreviewRefused):
            hold.resume_hold(result["claim_id"],
                             coordinator=RefusingCoordinator(not_claim_only, coordinator.client))
        collision = hold.preview_hold(coordinator.client, release, lane, repos,
                                      reason="Collision plan")
        coordinator.start(hold._claim_id(collision["digest"]), 2895, "scripted/model",
                          "sha256:" + "a" * 64)
        before = mutations(state)
        with pytest.raises(PreviewRefused):
            hold.execute_hold(collision, coordinator=coordinator)
        assert mutations(state) == before


def test_printed_command_shell_quotes_the_reason_as_literal_text():
    reason = "Inspect `printf EXPANDED` and $(printf EXPANDED)"
    preview = dict(release_id="aa", lane="implement", reason=reason, digest="sha256:example")
    script = 'lanectl() { printf "%s\\n" "$@"; }\n' + hold.command(preview)
    result = subprocess.run(["bash", "-c", script], text=True, capture_output=True, check=True)
    assert reason in result.stdout.splitlines()


def test_cli_preview_is_read_only_and_execute_requires_the_exact_digest(
        tmp_path, monkeypatch, capsys):
    with setup(tmp_path, monkeypatch) as (coordinator, state, release, lane, repos):
        parser = argparse.ArgumentParser()
        handlers = hold.register(parser.add_subparsers(dest="cmd", required=True))

        def run(*argv):
            return handlers["claim-hold"](parser.parse_args(["claim-hold", *argv]), None,
                                          coordinator=coordinator)

        assert run("--item", release.id, "--reason", "CLI preview") == 0
        assert mutations(state) == []
        assert run("--item", release.id, "--reason", "CLI preview", "--execute") == 1
        assert mutations(state) == []
        preview = hold.preview_hold(coordinator.client, release, lane, repos, reason="CLI preview")
        assert run("--item", release.id, "--reason", "CLI preview",
                   "--execute", "--expect", preview["digest"]) == 0
        assert len([call for call in state["calls"]
                    if call["operation"] == "work.lease.acquire-v1"]) == 1
        assert run("--repo", "repo-a", "--resume", "hold-unknown") == 1
        assert len([call for call in state["calls"]
                    if call["operation"] == "work.lease.acquire-v1"]) == 1
        assert "UTC owner lease expiry" in capsys.readouterr().out
