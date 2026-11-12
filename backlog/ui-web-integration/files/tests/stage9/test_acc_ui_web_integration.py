def test_web_roundtrips_owner_work():
    from lanectl.lifecycle_web import locator, resolve_locator, render_lifecycle
    row = dict(item_id="ui-work", work_id=2895, attempt_id="ui-work-a1", facts={})
    assert resolve_locator(locator("lanectl", row))["work_id"] == 2895
    assert "2895" in render_lifecycle("lanectl", row)


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


