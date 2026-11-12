def test_page_uses_shared_coverage_and_outside_scope_counts():
    import re
    from html import unescape
    from lanectl.accounting import accounting_timeline
    from lanectl.contracts import make_event
    from lanectl.lifecycle_web import render_lifecycle
    def usage(item):
        return make_event("usage.recorded", dict(provider="test", source="adapter", units={}), item_id=item)
    for unknown, expected in ((True, "unknown"), (False, "100%")):
        events = [usage("aa"), usage("bb")] + ([usage(None)] if unknown else [])
        accounting = accounting_timeline(events, {}, item_id="aa")
        row = dict(item_id="aa", attempt_id="aa-a1", facts={}, accounting=accounting)
        text = " ".join(unescape(re.sub("<[^>]+>", " ", render_lifecycle("lanectl", row))).split())
        assert f"coverage {expected}" in text and "outside scope 1" in text
