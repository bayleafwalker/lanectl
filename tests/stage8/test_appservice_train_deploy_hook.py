import json
import os
from pathlib import Path
import subprocess
import sys


HOOK = Path(__file__).resolve().parents[2] / "contrib" / "appservice-train-deploy.py"


def test_deploy_uses_only_exact_digest_bound_to_train(tmp_path, monkeypatch):
    fake_kubectl = tmp_path / "kubectl"
    fake_kubectl.write_text(
        "#!/bin/sh\n"
        'case "$6" in\n'
        'get) exit 0;;\n'
        'create) cat >"$MANIFEST";;\n'
        '*) exit 91;;\n'
        "esac\n"
    )
    fake_kubectl.chmod(0o755)
    manifest = tmp_path / "deployment.json"
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ.get('PATH', os.defpath)}")
    monkeypatch.setenv("MANIFEST", str(manifest))
    monkeypatch.setenv("LANE_TRAIN_ID", "train-proof")
    monkeypatch.setenv("LANE_NAMESPACE", "lane-dev-train-proof")
    monkeypatch.setenv("LANE_CHECKED_SHA", "a" * 40)
    binding = tmp_path / "binding.json"
    image = "registry.example/train@sha256:" + "c" * 64
    spec = {"commit": "b" * 40, "image": image, "port": 8080, "health_path": "/healthz"}
    binding.write_text(json.dumps(spec))
    command = [sys.executable, str(HOOK), "deploy", "--binding", str(binding),
               "--kubeconfig", str(tmp_path / "scope")]
    rejected = subprocess.run(command, capture_output=True, text=True, check=False)
    assert rejected.returncode and "must match the checked commit" in rejected.stderr
    assert not manifest.exists()

    binding.write_text(json.dumps(dict(spec, commit="a" * 40)))
    subprocess.run(command, capture_output=True, text=True, check=True)
    deployed = json.loads(manifest.read_text())
    assert deployed["metadata"]["namespace"] == "lane-dev-train-proof"
    pod = deployed["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["containers"][0]["image"] == image
    assert pod["containers"][0]["readinessProbe"]["httpGet"] == {"path": "/healthz", "port": 8080}


    monkeypatch.setenv("LANE_NAMESPACE", "default")
    manifest.unlink()
    assert subprocess.run(command, capture_output=True, check=False).returncode
    assert not manifest.exists()

    monkeypatch.setenv("LANE_NAMESPACE", "lanectl-train-preview")
    subprocess.run(command, capture_output=True, check=True)
    deployed = json.loads(manifest.read_text())
    assert deployed["metadata"]["namespace"] == "lanectl-train-preview"
    assert deployed["metadata"]["name"] == "lane-train-proof"
    assert deployed["spec"]["selector"]["matchLabels"] == {"app.kubernetes.io/name": "lane-train-proof"}

def test_teardown_waits_for_foreground_cascade(tmp_path, monkeypatch):
    fake_kubectl = tmp_path / "kubectl"
    fake_kubectl.write_text(
        "#!/bin/sh\n"
        'case "$6" in\n'
        'get) if [ -f "$DELETED" ]; then touch "$CONFIRMED"; else cat "$DEPLOYMENT"; fi;;\n'
        'delete) [ "$*" != "${*%--cascade=foreground*}" ] || exit 91; touch "$DELETED";;\n'
        '*) exit 92;;\n'
        "esac\n"
    )
    fake_kubectl.chmod(0o755)
    commit = "a" * 40
    image = "registry.example/train@sha256:" + "c" * 64
    deployment = tmp_path / "deployment.json"
    deployment.write_text(json.dumps({
        "metadata": {"annotations": {"lanectl.io/checked-sha": commit}},
        "spec": {"template": {"spec": {"containers": [{"image": image}]}}},
    }))
    deleted = tmp_path / "deleted"
    confirmed = tmp_path / "confirmed"
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ.get('PATH', os.defpath)}")
    monkeypatch.setenv("DEPLOYMENT", str(deployment))
    monkeypatch.setenv("DELETED", str(deleted))
    monkeypatch.setenv("CONFIRMED", str(confirmed))
    monkeypatch.setenv("LANE_TRAIN_ID", "train-proof")
    monkeypatch.setenv("LANE_NAMESPACE", "lane-dev-train-proof")
    monkeypatch.setenv("LANE_CHECKED_SHA", commit)
    binding = tmp_path / "binding.json"
    binding.write_text(json.dumps({"commit": commit, "image": image, "port": 8080, "health_path": "/healthz"}))

    subprocess.run([sys.executable, str(HOOK), "teardown", "--binding", str(binding),
                    "--kubeconfig", str(tmp_path / "scope")], check=True)
    assert confirmed.is_file()


def test_await_binding_reads_exact_response_without_creating_workloads(tmp_path, monkeypatch):
    fake_kubectl = tmp_path / "kubectl"
    fake_kubectl.write_text(
        "#!/bin/sh\n"
        'printf "%s %s %s %s\n" "$4" "$6" "$7" "$8" >>"$CALLS"\n'
        'case "$6:$7" in\n'
        'get:configmap) cat "$RESPONSE";;\n'
        'get:deployment) exit 0;;\n'
        'create:-f) cat >"$MANIFEST";;\n'
        '*) exit 91;;\n'
        "esac\n"
    )
    fake_kubectl.chmod(0o755)
    calls, manifest, response = (tmp_path / name for name in ("calls", "manifest", "response"))
    train, commit = "train-proof", "a" * 40
    binding_name = f"binding-{train}-{commit}"
    binding = {"commit": commit, "port": 18080, "health_path": "/document",
               "image": f"registry.example/train@sha256:{'b' * 64}"}
    response.write_text(json.dumps({
        "immutable": True, "metadata": {"name": binding_name, "namespace": "lanectl-train-handoff"},
        "data": {"binding.json": json.dumps(binding)},
    }))
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ.get('PATH', os.defpath)}")
    for name, value in {
        "CALLS": calls, "MANIFEST": manifest, "RESPONSE": response, "LANE_TRAIN_ID": train,
        "LANE_NAMESPACE": f"lane-dev-{train}", "LANE_CHECKED_SHA": commit,
    }.items():
        monkeypatch.setenv(name, str(value))

    common = ["--binding-from-handoff", "--kubeconfig", str(tmp_path / "scope")]
    subprocess.run([sys.executable, str(HOOK), "await-binding", *common], check=True)
    assert calls.read_text().splitlines() == [f"lanectl-train-handoff get configmap {binding_name}"]
    assert not manifest.exists()

    response.write_text("")
    missed = subprocess.run([sys.executable, str(HOOK), "await-binding", *common],
                            capture_output=True, text=True, check=False)
    assert missed.returncode and "no published image binding" in missed.stderr
    assert not manifest.exists()


def test_projected_identity_uses_rotatable_token_file(tmp_path, monkeypatch):
    fake_kubectl = tmp_path / "kubectl"
    fake_kubectl.write_text('#!/bin/sh\ncat "$2" > "$CAPTURE"\nprintf "%s" "$2" > "$TEMP_CONFIG"\n')
    fake_kubectl.chmod(0o755)
    capture = tmp_path / "capture.json"
    config_path = tmp_path / "config-path"
    identity = tmp_path / "identity"
    identity.mkdir()
    commit = "a" * 40
    bindings = tmp_path / "bindings"
    train = bindings / "train-proof"
    train.mkdir(parents=True)
    binding = train / f"{commit}.json"
    spec = {"commit": commit, "image": "registry.example/train@sha256:" + "c" * 64,
            "port": 8080, "health_path": "/healthz"}
    (train / f"{'b' * 40}.json").write_text(json.dumps(spec))
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ.get('PATH', os.defpath)}")
    monkeypatch.setenv("CAPTURE", str(capture))
    monkeypatch.setenv("TEMP_CONFIG", str(config_path))
    monkeypatch.setenv("LANE_TRAIN_ID", "train-proof")
    monkeypatch.setenv("LANE_NAMESPACE", "lane-dev-train-proof")
    monkeypatch.setenv("LANE_CHECKED_SHA", commit)
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "2001:db8::5")
    monkeypatch.setenv("KUBERNETES_SERVICE_PORT_HTTPS", "443")
    command = [sys.executable, str(HOOK), "teardown", "--bindings-directory", str(bindings),
               "--projected-identity", str(identity)]
    stale = subprocess.run(command, capture_output=True, text=True, check=False)
    assert stale.returncode and "no published image binding" in stale.stderr
    assert not capture.exists()
    binding.write_text(json.dumps(spec))
    failure = subprocess.run(command, capture_output=True, text=True, check=False)
    assert failure.returncode and "projected identity requires" in failure.stderr
    assert not capture.exists()

    (identity / "token").write_text("synthetic-projected-token")
    (identity / "ca.crt").write_text("synthetic-ca")
    subprocess.run(command, check=True)
    config = json.loads(capture.read_text())
    assert config["clusters"][0]["cluster"] == {
        "server": "https://[2001:db8::5]:443", "certificate-authority": str(identity / "ca.crt")
    }
    assert config["users"][0]["user"] == {"tokenFile": str(identity / "token")}
    assert config["contexts"][0]["context"]["namespace"] == "lane-dev-train-proof"
    assert not Path(config_path.read_text()).exists()


def test_reconcile_requires_exact_owner_response_and_observed_readiness(monkeypatch):
    import importlib.util

    import pytest

    spec = importlib.util.spec_from_file_location("preview_hook", HOOK)
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    train, commit = "train-proof", "a" * 40
    intent = {"schema": "lanectl.preview-intent/v1", "action": "deploy",
              "train": train, "commit": commit}
    image = "registry.example/train@sha256:" + "b" * 64
    response = {"kind": "ConfigMap", "immutable": True, "metadata": {
        "namespace": "lanectl-train-handoff", "name": f"binding-{train}-{commit}"},
        "data": {"binding.json": json.dumps({"commit": commit, "image": image,
                                            "port": 18080, "health_path": "/document"})}}
    calls = []

    def operate(action, kubeconfig, namespace, checked_sha, digest, path, port, name):
        calls.append(action)
        assert (namespace, checked_sha, digest, name) == (
            "lanectl-train-preview", commit, image, "lane-train-proof")

    monkeypatch.setattr(hook, "operate", operate)
    with pytest.raises(ValueError, match="exact immutable"):
        hook.reconcile_intent(intent, dict(response, immutable=False), Path("/scope"))
    with pytest.raises(ValueError, match="exact immutable"):
        hook.reconcile_intent(dict(intent, commit="c" * 40), response, Path("/scope"))
    assert calls == []
    result = hook.reconcile_intent(intent, response, Path("/scope"))
    assert calls == ["deploy", "health"]
    assert result == {"schema": "lanectl.preview-result/v1", "action": "deploy",
                      "train": train, "commit": commit, "image": image,
                      "namespace": "lanectl-train-preview", "state": "ready"}
    assert hook.reconcile_intent(dict(intent, action="teardown"), response, Path("/scope"))["state"] == "absent"
    assert calls[-1] == "teardown"

    def remains_unready(*args):
        if args[0] == "health":
            raise RuntimeError("health did not complete")

    monkeypatch.setattr(hook, "operate", remains_unready)
    with pytest.raises(RuntimeError, match="health did not complete"):
        hook.reconcile_intent(intent, response, Path("/scope"))


def test_preview_inbox_resumes_unfinished_intents_and_never_redeploys_after_teardown(monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("preview_hook", HOOK)
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)

    def request(action, train):
        intent = {"schema": "lanectl.preview-intent/v1", "action": action,
                  "train": train, "commit": "a" * 40}
        return {"metadata": {"name": hook.preview_intent_name(intent)}, "immutable": True,
                "data": {"intent.json": json.dumps(intent)}}

    objects = [request("deploy", "train-missing"), request("deploy", "train-proof"),
               request("teardown", "train-proof")]
    calls = []

    def execute(intent, response, kubeconfig, *, read_binding):
        assert read_binding and response is None
        calls.append((intent["train"], intent["action"]))
        if intent["train"] == "train-missing":
            raise ValueError("binding not yet published")
        return {"state": "absent"}

    def exchange(kubeconfig, *args, manifest=None):
        if manifest is None:
            return json.dumps({"items": objects})
        objects.append(manifest)

    monkeypatch.setattr(hook, "reconcile_intent", execute)
    monkeypatch.setattr(hook, "preview_command", exchange)
    assert hook.reconcile_inbox(Path("/scope")) == 1
    assert calls == [("train-missing", "deploy"), ("train-proof", "teardown")]
    assert objects[-1]["immutable"] is True
    assert objects[-1]["metadata"]["name"] == "result-" + objects[-2]["metadata"]["name"]
    assert hook.reconcile_inbox(Path("/scope")) == 1
    assert calls[-1] == ("train-missing", "deploy")
    assert len(calls) == 3


def test_preview_request_replays_exact_intent_and_rejects_wrong_receipt(monkeypatch):
    import importlib.util

    import pytest

    spec = importlib.util.spec_from_file_location("preview_hook", HOOK)
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    intent = {"schema": "lanectl.preview-intent/v1", "action": "deploy",
              "train": "train-proof", "commit": "a" * 40}
    name = hook.preview_intent_name(intent)
    receipt = {"schema": "lanectl.preview-result/v1", "action": "deploy",
               "train": "train-proof", "commit": "b" * 40,
               "image": "registry.example/train@sha256:" + "c" * 64,
               "namespace": "lanectl-train-preview", "state": "ready"}
    existing = {name: {"intent.json": json.dumps(intent, sort_keys=True)}}

    def submit(kubeconfig, *args, manifest):
        assert manifest["metadata"]["name"] == name
        raise subprocess.CalledProcessError(1, "kubectl create")

    def read(kubeconfig, key):
        if key == f"result-{name}":
            return {"result.json": json.dumps(receipt)}
        return existing.get(key)

    monkeypatch.setattr(hook, "preview_command", submit)
    monkeypatch.setattr(hook, "read_preview_object", read)
    with pytest.raises(ValueError, match="does not match"):
        hook.request_preview(Path("/scope"), intent, 0)
    receipt["commit"] = intent["commit"]
    assert hook.request_preview(Path("/scope"), intent, 0) == receipt
    existing[hook.preview_intent_name(dict(intent, action="teardown"))] = {}
    with pytest.raises(ValueError, match="retired"):
        hook.request_preview(Path("/scope"), intent, 0)
