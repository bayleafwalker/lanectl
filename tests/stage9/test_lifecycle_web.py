"""Lifecycle web permalinks: identity round-trips, safe rendering and exports."""
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from lanectl.lifecycle_web import (
    export_lifecycle,
    locator,
    render_lifecycle,
    resolve_locator,
    _origin,
)


def snapshot(**overrides):
    row = {"item_id": "release-42", "attempt_id": "release-42-a2",
           "run_id": "run-42", "train_id": "train-42", "facts": {
        "work.public.item-v1": {"state": "unknown", "source": "work.public.item-v1",
            "revision": "catalog-19", "observed_at": "2026-11-12T10:00:00Z",
            "reason": "owner unavailable"},
        "local.receipt": {"state": "observed", "source": "lanectl.events",
            "checkpoint": 42, "revision": 7,
            "observed_at": "2026-11-12T10:01:00Z", "value": [{
                "type": "item.landed", "data": {"train_id": "train-42",
                "landed_sha": "abc", "body": "raw secret transcript",
                "log": "/home/user/private",
                "ref": "https://example.test/receipt?token=secret"}}]},
        "work.evidence.tail-v1": {"state": "unknown",
            "source": "work.evidence.tail-v1",
            "observed_at": "2026-11-12T10:00:00Z",
            "reason": "<script>alert(1)</script>"}},
        "reasons": [{"code": "owner-unknown", "next_actions": ["refresh owner"]}]}
    row.update(overrides)
    return row


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.attrs = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.attrs.append((tag, attrs))
        self.links.extend(v for k, v in attrs.items() if k in ("href", "src"))


def test_locator_is_relative_without_origin_and_prefixed_with_one():
    row = snapshot()
    relative = locator("lanectl", row)
    assert relative.startswith("/lifecycle/")
    assert not relative.startswith("http")
    absolute = locator("lanectl", row, base_url="https://lanes.example.test")
    assert absolute == "https://lanes.example.test" + relative


def test_locator_omits_unknown_linked_ids_and_resolves_them_to_none():
    row = snapshot()
    del row["run_id"], row["train_id"]
    url = locator("lanectl", row)
    assert "?" not in url
    assert resolve_locator(url)["run_id"] is None
    assert resolve_locator(url)["train_id"] is None


def test_roundtrip_unicode_and_spaces():
    row = snapshot()
    row["item_id"] = "release 42"
    url = locator("répo name", row, base_url="https://x.test")
    assert resolve_locator(url) == {"repo": "répo name", "item_id": "release 42",
                                    "attempt_id": "release-42-a2", "run_id": "run-42",
                                    "train_id": "train-42"}


def test_resolve_locator_rejects_unknown_query_and_fragment():
    for url in ("/lifecycle/r/i/a?run_id=x&other=y",
                "/lifecycle/r/i/a?train_id=x&train_id=y#frag",
                "https://h.test/lifecycle/r/i/a#frag"):
        with pytest.raises(ValueError):
            resolve_locator(url)


def test_resolve_locator_rejects_non_https_scheme_and_userinfo():
    for url in ("http://h.test/lifecycle/r/i/a", "javascript:alert(1)",
                "https://user:pw@h.test/lifecycle/r/i/a"):
        with pytest.raises(ValueError):
            resolve_locator(url)


def test_resolve_locator_rejects_empty_or_over_encoded_segments():
    for url in ("/lifecycle/r//a", "/lifecycle/r/%41/a", "/lifecycle/r/i/a/extra",
                "/lifecycle/r/i"):
        with pytest.raises(ValueError):
            resolve_locator(url)


def test_resolve_locator_rejects_non_string():
    with pytest.raises(ValueError):
        resolve_locator(42)


def test_render_never_leaks_bodies_logs_credentials_or_unsafe_refs():
    page = render_lifecycle("lanectl", snapshot())
    for secret in ("raw secret transcript", "/home/user/private", "token=secret",
                   "landed_sha"):
        assert secret not in page
    parser = Links()
    parser.feed(page)
    assert not any(link.startswith(("file:", "javascript:", "/home/", "data:"))
                   for link in parser.links)


def test_render_shows_a_safe_https_reference_as_a_link():
    row = snapshot()
    row["facts"]["local.receipt"]["value"] = [{
        "type": "item.landed",
        "data": {"ref": "https://example.test/receipt", "body": "hidden"}}]
    page = render_lifecycle("lanectl", row)
    parser = Links()
    parser.feed(page)
    assert "https://example.test/receipt" in parser.links
    assert "hidden" not in page


def test_render_is_self_contained_with_no_scripts_or_external_assets():
    page = render_lifecycle("lanectl", snapshot())
    parser = Links()
    parser.feed(page)
    assert "script" not in [tag for tag, _ in parser.attrs]
    assert not any(link.startswith(("http://", "//")) for link in parser.links)
    assert "@import" not in page and "url(" not in page
    assert "<img" not in page and "<iframe" not in page
    assert not re.search(r"https?://[^/\"' ]+\.(css|js|woff)", page)


def test_render_marks_missing_identifiers_unavailable():
    row = snapshot()
    del row["run_id"], row["train_id"]
    page = render_lifecycle("lanectl", row).lower()
    assert page.count("unavailable") >= 2
    assert "run" in page and "train" in page


def test_render_includes_source_reasons_and_local_only_label():
    page = render_lifecycle("lanectl", snapshot())
    assert "local-only" in page
    assert "owner-unknown" in page
    # The documented reason code carries its rule text.
    assert "could not establish a fact" in page
    assert "lanectl tui" in page and "--repo" in page and "--attempt" in page


def test_export_is_deterministic_and_self_contained(tmp_path):
    row = snapshot()
    first = export_lifecycle(tmp_path, "lanectl", row)
    second = export_lifecycle(tmp_path, "lanectl", row)
    assert first == second and first.is_file()
    assert "snapshot" in first.read_text().lower()


def test_export_refuses_traversal_identity(tmp_path):
    for repo in ("..", "a/b", ""):
        row = snapshot()
        with pytest.raises(ValueError):
            export_lifecycle(tmp_path, repo, row)


def test_export_refuses_symlink_destination(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "site"
    root.mkdir()
    (root / "lifecycle").symlink_to(outside, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        export_lifecycle(root, "lanectl", snapshot())
    assert not list(outside.iterdir())


def test_origin_requires_https_and_rejects_paths_or_credentials():
    assert _origin("https://lanes.example.test/") == "https://lanes.example.test"
    for bad in ("http://x.test", "https://u:p@x.test", "https://x.test/path",
                "https://x.test?q=1", "https://x.test#frag"):
        with pytest.raises(ValueError):
            _origin(bad)
