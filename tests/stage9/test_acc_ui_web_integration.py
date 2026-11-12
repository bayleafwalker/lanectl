def test_web_roundtrips_owner_work():
    from lanectl.lifecycle_web import locator, resolve_locator, render_lifecycle
    row = dict(item_id="ui-work", work_id=2895, attempt_id="ui-work-a1", facts={})
    assert resolve_locator(locator("lanectl", row))["work_id"] == 2895
    assert "2895" in render_lifecycle("lanectl", row)
    assert "--view active" in render_lifecycle("lanectl", row)


def test_web_excludes_runtime_payload_references():
    from lanectl.lifecycle_web import render_lifecycle
    row = dict(item_id="ui-work", work_id=2895, attempt_id="ui-work-a1", facts={
        "work.evidence.tail-v1": {"state": "observed", "source": "owner", "value": {
            "item": {"ref": "https://example.test/safe", "body": {
                "ref": "https://example.test/private-runtime-body"}}}}})
    text = render_lifecycle("lanectl", row)
    assert "https://example.test/safe" in text
    assert "private-runtime-body" not in text


def test_web_ignores_malformed_references_without_crashing():
    from lanectl.lifecycle_web import render_lifecycle
    row = dict(item_id="ui-work", attempt_id="ui-work-a1", facts={
        "work.evidence.tail-v1": {"state": "observed", "source": "owner", "value": {
            "item": {"ref": "https://[invalid"}}}})
    row["facts"]["work.evidence.tail-v1"]["value"]["item"]["ref"] = "https://[invalid"
    assert "snapshot" in render_lifecycle("lanectl", row)


def test_exported_permalink_resolves_through_a_standard_static_server(tmp_path):
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from urllib.request import build_opener, ProxyHandler
    from lanectl.lifecycle_web import locator, export_lifecycle
    row = dict(item_id="ui-work", work_id=2895, attempt_id="ui-work-a1", facts={})
    path = export_lifecycle(tmp_path, "repo name", row)
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(tmp_path)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}" + locator("repo name", row)
        with build_opener(ProxyHandler({})).open(url, timeout=3) as response:
            assert response.status == 200
            assert response.read().decode() == path.read_text()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_review_page_displays_the_shared_accounting_projection_with_unknowns():
    from lanectl.lifecycle_web import render_lifecycle
    from lanectl.accounting import accounting_timeline
    from lanectl.contracts import make_event
    policy = {"revision": 19, "providers": {"test": {"prices": {"models": {
        "model-a": {"offpeak": {"output": 2.0}}}}}}}
    events = [make_event("usage.recorded", dict(provider="test", source="adapter",
        model="model-a", units=dict(output_tokens=1_000_000, steps=3)), item_id="ui-work")]
    accounting = accounting_timeline(events, policy, item_id="ui-work")
    accounting.update(source="lanectl.events", checkpoint=42, observed_at="2026-11-12T10:00:00Z")
    row = dict(item_id="ui-work", work_id=2895, attempt_id="ui-work-a1", facts={}, accounting=accounting)
    page = render_lifecycle("lanectl", row)
    for text in ("Accounting timeline", "queued", "execution", "integration", "verification",
                 "output_tokens", "2.0000", "unknown", "19", "estimate",
                 "lanectl.events", "2026-11-12T10:00:00Z"):
        assert text in page


