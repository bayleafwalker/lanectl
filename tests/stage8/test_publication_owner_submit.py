import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


HOOK = Path(__file__).resolve().parents[2] / "contrib" / "appservice-docs-train-publish.py"
spec = importlib.util.spec_from_file_location("publication_hook", HOOK)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


def test_publication_requires_complete_checked_landing_and_exact_replay(tmp_path, monkeypatch):
    train, commit = "train-proof", "b" * 40
    events = tmp_path / "events.jsonl"
    args = SimpleNamespace(train=train, checked_sha=commit, events=events, repository=tmp_path,
                           submit_publication_kubeconfig=tmp_path / "scope")
    receipt = {"type": "train.built", "data": {
        "repo": "lanectl", "train_id": train, "passed": True,
        "base_sha": "a" * 40, "checked_sha": commit, "attempts": ["one-a1", "two-a1"]}}
    monkeypatch.setattr(hook, "git", lambda *_: commit.encode())

    def landed(attempt):
        return {"type": "item.landed", "data": {
            "train_id": train, "attempt_id": attempt, "landed_sha": commit}}

    def record(*rows):
        events.write_text("".join(json.dumps(row) + "\n" for row in rows))

    record(receipt, landed("one-a1"))
    with pytest.raises(ValueError, match="every checked attempt"):
        hook.submit_publication(args)
    record(receipt, landed("one-a1"), landed("two-a1"))

    def export(args, destination):
        destination.mkdir()
        (destination / "events.jsonl").write_text(json.dumps(receipt) + "\n")
        (destination / "train.bundle").write_bytes(b"sealed bundle")
        return commit

    captured = []

    def create(command, *, input, **kwargs):
        captured.append(json.loads(input))
        return SimpleNamespace(returncode=int(len(captured) > 1))

    def get(*args, **kwargs):
        return json.dumps(captured[0])

    monkeypatch.setattr(hook, "export_bundle", export)
    monkeypatch.setattr(hook.subprocess, "run", create)
    monkeypatch.setattr(hook.subprocess, "check_output", get)
    hook.submit_publication(args)
    hook.submit_publication(args)
    manifest = captured[0]
    assert captured == [manifest, manifest]
    assert manifest["immutable"] is True
    assert manifest["metadata"]["name"] == f"publish-{train}-{commit}"
    assert json.loads(manifest["data"]["publication.json"])["commit"] == commit
    manifest["binaryData"]["train.bundle"] = "different"
    with pytest.raises(ValueError, match="differs from the exact"):
        hook.submit_publication(args)


def test_publication_owner_rejects_intent_that_disagrees_with_imported_receipt(tmp_path, monkeypatch):
    from contextlib import contextmanager

    train, base, commit = "train-proof", "a" * 40, "b" * 40
    intent = {"schema": "lanectl.publication-intent/v1", "repo": "lanectl", "train": train,
              "base": base, "commit": commit}
    path = tmp_path / "publication.json"
    path.write_text(json.dumps({
        "kind": "ConfigMap", "immutable": True,
        "metadata": {"namespace": "lanectl-train-publication", "name": f"publish-{train}-{commit}"},
        "data": {"publication.json": json.dumps(intent), "events.jsonl": "{}"},
        "binaryData": {"train.bundle": "eA=="},
    }))
    checked = {"base_sha": "c" * 40, "checked_sha": commit, "attempts": ["attempt-a1"]}

    @contextmanager
    def import_bundle(args, actual_train, actual_base, actual_commit, receipt, bundle):
        assert (actual_train, actual_base, actual_commit, receipt, bundle) == (train, base, commit, b"{}", b"x")
        yield object()

    monkeypatch.setattr(hook, "import_checked_bundle", import_bundle)
    monkeypatch.setattr(hook, "checked_receipt", lambda _: {"data": checked})
    args = SimpleNamespace(verify_publication_request=path)
    with pytest.raises(ValueError, match="differs from the passing train"):
        with hook.publication_checkout(args):
            pytest.fail("mismatched intent reached the publication owner")
    checked["base_sha"] = base
    with hook.publication_checkout(args) as (verified, _):
        assert verified == intent
