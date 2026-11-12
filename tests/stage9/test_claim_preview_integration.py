"""Preview and guarded execution against a real invocation/v1 owner transport."""
import json
import threading
from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from lanectl import claim_preview as cp
from lanectl import runner
from lanectl.config import load_lane, load_repos, load_releases
from lanectl.coordination import VuoroClient


ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "authority": {"type": "string"}, "state": {"type": "string"},
        "as_of": {"type": "string"},
        "item": {"type": "object", "properties": {
            "work_id": {"type": "integer"}, "status": {"type": "string"},
            "resolution": {"type": "null"}},
            "required": ["work_id", "status", "resolution"]},
    },
    "required": ["authority", "state", "as_of", "item"],
}


@contextmanager
def service():
    """A loopback owner for exactly the catalog-checked item read."""
    state = {"posts": [], "verdict": "ok", "catalog": "catalog-r1",
             "item": {"work_id": 2895, "status": "pending", "resolution": None}}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, value, status=200):
            data = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/api/meta/v1/handshake":
                return self.respond({"client_protocol": {"minimum": 1, "maximum": 1},
                                     "environment": {"name": "test"}})
            assert self.path == "/api/catalog/v1"
            self.respond({"revision": state["catalog"], "operations": [{
                "name": "work.public.item-v1", "repo_scoped": True,
                "execution_semantics": "read",
                "input_schema": {"type": "object", "properties": {"work_id": {"type": "integer"}},
                                 "required": ["work_id"]},
                "result_schema": ITEM_SCHEMA}]})

        def do_POST(self):
            assert self.path == "/api/invoke/v1"
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["posts"].append(body)
            assert body["operation"] == "work.public.item-v1"
            if state["verdict"] != "ok":
                return self.respond({"status": "rejected", "error": {"code": "token-revoked"}}, 403)
            self.respond({"schema_version": "invocation-result/v1",
                          "request_id": body["request_id"], "operation": body["operation"],
                          "catalog_revision": body["catalog_revision"], "status": "accepted",
                          "result": {"authority": "sprintctl", "state": "ok",
                                     "as_of": "2026-11-12T10:00:00Z", "item": dict(state["item"])}})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class Log:
    def __init__(self):
        self.calls = []

    def append(self, *args, **kwargs):
        self.calls.append(("append", args, kwargs))


def setup(monkeypatch):
    release = replace(load_releases()[0], id="preview-work", repo="lanectl",
                      work="lanectl#2895", work_complete=True, draft=False)
    lane, repos = load_lane("implement"), load_repos()
    monkeypatch.setattr(cp, "readiness", lambda *args: [])
    monkeypatch.setattr(cp, "load_releases", lambda: [release])
    monkeypatch.setattr(cp, "load_lane", lambda name: lane)
    monkeypatch.setattr(cp, "load_repos", lambda: repos)
    return release, lane, repos


def test_owner_transport_preview_then_execute_rechecks_and_never_retries(monkeypatch):
    release, lane, repos = setup(monkeypatch)
    admissions = []
    executions = []

    def admit(lane_name, log, only=None):
        admissions.append(only)
        if len(admissions) == 1:
            return "already claimed"
        return runner.Claim(release, repos[release.repo], lane, f"{release.id}-a1",
                            "scripted/model", "claude")

    monkeypatch.setattr(runner, "admit", admit)
    monkeypatch.setattr(runner, "execute", lambda claim, log: executions.append(claim) or "ran")
    with service() as (url, state):
        client = VuoroClient(url, "repo-a", lambda: "synthetic-runner")
        preview = cp.preview_claim(client, release, lane, repos)
        assert preview["allowed"], preview
        assert len(state["posts"]) == 1 and state["posts"][0]["arguments"] == {"work_id": 2895}
        assert cp.preview_claim(client, release, lane, repos)["digest"] == preview["digest"]
        assert len(state["posts"]) == 2

        log = Log()
        assert cp.execute_preview(preview, log, client=client) == "already claimed"
        assert admissions == ["preview-work"] and executions == [] and log.calls == []

        state["item"]["status"] = "active"
        monkeypatch.setattr(runner, "admit", lambda *args, **kwargs: pytest.fail("must not admit"))
        with pytest.raises(cp.PreviewRefused, match="not allowed"):
            cp.execute_preview(preview, log, client=client)
        assert executions == []

        state["item"]["status"] = "pending"
        state["verdict"] = "unavailable"
        with pytest.raises(cp.PreviewRefused, match="not allowed"):
            cp.execute_preview(preview, log, client=client)
        assert executions == []


def test_owner_transport_digest_tracks_the_owner_catalog_revision(monkeypatch):
    release, lane, repos = setup(monkeypatch)
    with service() as (url, state):
        client = VuoroClient(url, "repo-a", lambda: "synthetic-runner")
        first = cp.preview_claim(client, release, lane, repos)
        assert first["owner_revision"] == "catalog-r1"
        state["catalog"] = "catalog-r2"
        assert cp.preview_claim(client, release, lane, repos)["digest"] != first["digest"]
        assert len(state["posts"]) == 2
