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
