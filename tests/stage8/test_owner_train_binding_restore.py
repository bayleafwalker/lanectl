import argparse
import importlib.util
import json
from pathlib import Path


PUBLISHER = Path(__file__).resolve().parents[2] / "contrib" / "appservice-docs-train-publish.py"
spec = importlib.util.spec_from_file_location("docs_train_publisher", PUBLISHER)
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


def test_fresh_owner_validates_and_reuses_the_immutable_response(tmp_path, monkeypatch):
    commit = "a" * 40
    train = "train-proof"
    document = Path("docs/proof.md")
    registry = "registry.example/train"
    image = f"{registry}@sha256:{'b' * 64}"
    local_binding = tmp_path / train / f"{commit}.json"
    binding = {"commit": commit, "image": image, "port": 18080, "health_path": "/document"}
    response = {"metadata": {"name": f"binding-{train}-{commit}"},
                "immutable": True, "data": {"binding.json": json.dumps(binding)}}
    request = {"metadata": {"name": f"request-{train}-{commit}"}}
    args = argparse.Namespace(bindings_directory=tmp_path, document=document, registry=registry,
                              repository=tmp_path, image_policy=tmp_path / "policy.json",
                              nixpkgs_flake=tmp_path,
                              return_binding_kubeconfig=tmp_path / "scope",
                              insecure_registry=False)
    calls = []

    def check_output(command, **kwargs):
        calls.append(command[0])
        if command[0] == "kubectl":
            return json.dumps({"items": [request, response]})
        assert command[0] == "skopeo"
        assert command[-1] == f"docker://{image}"
        return json.dumps({"config": {"Labels": {
            "org.opencontainers.image.revision": commit,
            "io.lanectl.train.document": str(document),
        }}})

    def consume(selected, *existing_binding):
        assert json.loads(selected.consume_request.read_text()) == request
        return publisher.publish(selected, *existing_binding)

    monkeypatch.setattr(publisher, "consume_request", consume)
    monkeypatch.setattr(publisher, "checked_commit", lambda _: commit)
    monkeypatch.setattr(publisher, "git", lambda *args: b"100644 blob ")
    monkeypatch.setattr(publisher.subprocess, "check_output", check_output)

    response["data"]["binding.json"] = json.dumps(dict(binding, commit="c" * 40))
    assert publisher.reconcile_handoffs(args) == 1
    assert calls == ["kubectl"]
    assert not local_binding.exists()

    response["data"]["binding.json"] = json.dumps(binding)
    assert publisher.reconcile_handoffs(args) == 0
    assert calls == ["kubectl", "kubectl", "skopeo"]
    assert local_binding.read_text() == response["data"]["binding.json"]

    assert publisher.reconcile_handoffs(args) == 0
    assert calls == ["kubectl", "kubectl", "skopeo", "kubectl"]

    local_binding.write_text("{}")
    assert publisher.reconcile_handoffs(args) == 1
    assert local_binding.read_text() == "{}"
