from html.parser import HTMLParser
from pathlib import Path

import pytest

from lanectl.lifecycle_web import locator, resolve_locator, render_lifecycle, export_lifecycle


def snapshot():
    return {"item_id": "release-42", "attempt_id": "release-42-a2", "run_id": "run-42",
            "train_id": "train-42", "facts": {
        "work.public.item-v1": {"state": "unknown", "source": "work.public.item-v1",
            "revision": "catalog-19", "observed_at": "2026-11-12T10:00:00Z", "reason": "owner unavailable"},
        "local.receipt": {"state": "observed", "source": "lanectl.events", "checkpoint": 42,
            "revision": 7, "observed_at": "2026-11-12T10:01:00Z", "value": [{
                "type": "item.landed", "data": {"train_id": "train-42",
                "landed_sha": "abc", "body": "raw secret transcript", "log": "/home/user/private",
                "ref": "https://example.test/receipt?token=secret"}}]},
        "work.evidence.tail-v1": {"state": "unknown", "source": "work.evidence.tail-v1",
            "observed_at": "2026-11-12T10:00:00Z", "reason": "<script>alert(1)</script>"}},
        "reasons": [{"code": "owner-unknown", "next_actions": ["refresh owner"]}]}


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.tags = []
    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        attrs = dict(attrs)
        self.links.extend(v for k, v in attrs.items() if k in ("href", "src"))
        assert not any(key.startswith("on") for key in attrs)


def test_locator_roundtrips_every_lifecycle_identifier():
    row = snapshot()
    url = locator("repo name", row, base_url="https://lanes.example.test")
    identity = resolve_locator(url)
    assert identity == dict(repo="repo name", item_id=row["item_id"],
        attempt_id=row["attempt_id"], run_id=row["run_id"], train_id=row["train_id"])
    assert locator("repo name", row, base_url="https://lanes.example.test") == url
    assert "/lifecycle/" in url and "repo%20name" in url


def test_review_page_is_self_contained_escaped_and_provenanced():
    page = render_lifecycle("lanectl", snapshot())
    parser = Links()
    parser.feed(page)
    assert "script" not in parser.tags
    assert "table" in parser.tags and "h1" in parser.tags
    for text in ("release-42", "release-42-a2", "run-42", "train-42", "owner-unknown",
                 "catalog-19", "2026-11-12T10:00:00Z", "lanectl.events", "42",
                 "local-only", "lanectl tui", "--repo", "--item", "--attempt"):
        assert text in page
    assert "unavailable" in page.lower() and "snapshot" in page.lower()
    assert "raw secret transcript" not in page and "/home/user/private" not in page
    assert "token=secret" not in page
    assert not any(link.startswith(("file:", "javascript:", "/home/")) for link in parser.links)
    assert not any("<script>" in part for part in page.split("<style>")[:1])


def test_export_is_deterministic_and_maps_to_permalink_path(tmp_path):
    from urllib.parse import urlsplit, unquote
    row = snapshot()
    path = export_lifecycle(tmp_path, "lanectl", row)
    assert isinstance(path, Path) and path.is_file()
    assert path == export_lifecycle(tmp_path, "lanectl", row)
    url_path = urlsplit(locator("lanectl", row)).path
    assert path.relative_to(tmp_path).as_posix().rstrip("index.html").rstrip("/") == url_path.strip("/")
    assert "snapshot" in path.read_text().lower()


@pytest.mark.parametrize("url", ["javascript:alert(1)", "https://u:p@host/lifecycle/r/i/a",
    "/lifecycle/../secret/a", "/lifecycle/r/%2E%2E/a", "/lifecycle/r/i/a?run_id=one&run_id=two"])
def test_malformed_and_unsafe_locators_refuse(url):
    with pytest.raises(ValueError):
        resolve_locator(url)


def test_export_refuses_symlink_escape(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "site"
    root.mkdir()
    (root / "lifecycle").symlink_to(outside, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        export_lifecycle(root, "lanectl", snapshot())
    assert not list(outside.iterdir())
