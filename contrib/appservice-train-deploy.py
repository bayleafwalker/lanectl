#!/usr/bin/env python3
"""Deploy a digest-pinned train image inside an already provisioned namespace."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("deploy", "health", "teardown"))
    bindings = parser.add_mutually_exclusive_group(required=True)
    bindings.add_argument("--binding", type=Path)
    bindings.add_argument("--bindings-directory", type=Path,
                          help="Owner-provided root containing <train>/<checked-commit>.json")
    bindings.add_argument("--binding-from-handoff", action="store_true",
                          help="Read the exact immutable owner binding from lanectl-train-handoff")
    credentials = parser.add_mutually_exclusive_group(required=True)
    credentials.add_argument("--kubeconfig", type=Path)
    credentials.add_argument("--projected-identity", type=Path,
                             help="Kubernetes projection containing token and ca.crt")
    args = parser.parse_args()
    train = os.environ["LANE_TRAIN_ID"]
    namespace = os.environ["LANE_NAMESPACE"]
    commit = os.environ["LANE_CHECKED_SHA"]
    if not re.fullmatch(r"train-[a-z0-9-]{1,40}", train) or namespace != f"lane-dev-{train}":
        raise ValueError("namespace must match the LANECTL train")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("checked train commit is required")

    binding_path = args.binding
    if args.bindings_directory is not None:
        if not args.bindings_directory.is_absolute():
            raise ValueError("train bindings directory must be absolute")
        binding_path = args.bindings_directory / train / f"{commit}.json"
        if not binding_path.is_file():
            raise ValueError(f"no published image binding for {train} at {commit}")
    if args.binding_from_handoff:
        binding = None
    else:
        binding = json.loads(binding_path.read_text())
        if not isinstance(binding, dict):
            raise ValueError("train binding must be a JSON object")
    if args.kubeconfig is not None:
        deploy_bound(args.action, args.kubeconfig, namespace, train, commit, binding)
        return
    with TemporaryDirectory(prefix="lanectl-train-") as scratch:
        config = Path(scratch) / "kubeconfig"
        config.write_text(json.dumps(projected_kubeconfig(args.projected_identity, namespace)))
        deploy_bound(args.action, config, namespace, train, commit, binding)


def deploy_bound(action, kubeconfig, namespace, train, commit, binding):
    if binding is None:
        name = f"binding-{train}-{commit}"
        raw = subprocess.run(
            ["kubectl", "--kubeconfig", str(kubeconfig), "--namespace", "lanectl-train-handoff",
             "--request-timeout=10s", "get", "configmap", name, "-o", "json"],
            capture_output=True, text=True, check=True, timeout=15,
        ).stdout
        configmap = json.loads(raw)
        metadata = configmap.get("metadata", {})
        if (configmap.get("immutable") is not True or metadata.get("name") != name
                or metadata.get("namespace") != "lanectl-train-handoff"):
            raise ValueError("owner binding must be the exact immutable handoff ConfigMap")
        binding = json.loads(configmap["data"]["binding.json"])

    image = binding["image"]
    if binding["commit"] != commit or not re.fullmatch(
        r"[a-z0-9][a-z0-9./:_-]*@sha256:[0-9a-f]{64}", image
    ):
        raise ValueError("reviewed image binding must match the checked commit and use a digest")
    port = binding["port"]
    path = binding["health_path"]
    if type(port) is not int or not 1024 <= port <= 65535 or not re.fullmatch(r"/[a-zA-Z0-9/_-]*", path):
        raise ValueError("invalid train health endpoint")
    operate(action, kubeconfig, namespace, commit, image, path, port)


def projected_kubeconfig(identity, namespace):
    token, ca = identity / "token", identity / "ca.crt"
    if not identity.is_absolute() or not token.is_file() or not ca.is_file():
        raise ValueError("projected identity requires an absolute mount with token and ca.crt")
    host = ipaddress.ip_address(os.environ["KUBERNETES_SERVICE_HOST"])
    port = int(os.environ["KUBERNETES_SERVICE_PORT_HTTPS"])
    if not 1 <= port <= 65535:
        raise ValueError("invalid Kubernetes service port")
    address = f"[{host}]" if host.version == 6 else str(host)
    return {
        "apiVersion": "v1", "kind": "Config", "current-context": "train",
        "clusters": [{"name": "appservice", "cluster": {
            "server": f"https://{address}:{port}", "certificate-authority": str(ca)}}],
        "users": [{"name": "train", "user": {"tokenFile": str(token)}}],
        "contexts": [{"name": "train", "context": {
            "cluster": "appservice", "user": "train", "namespace": namespace}}],
    }


def operate(action, kubeconfig, namespace, commit, image, path, port):
    command = ["kubectl", "--kubeconfig", str(kubeconfig), "--namespace", namespace, "--request-timeout=10s"]

    def kube(*arguments, data=None):
        return subprocess.run([*command, *arguments], input=data,
                              stdout=subprocess.PIPE, text=True, check=True, timeout=15).stdout

    def deployment():
        raw = kube("get", "deployment", "lane-train", "--ignore-not-found", "-o", "json")
        if not raw:
            return None
        resource = json.loads(raw)
        if (resource["metadata"].get("annotations", {}).get("lanectl.io/checked-sha") != commit
                or resource["spec"]["template"]["spec"]["containers"][0]["image"] != image):
            raise ValueError("existing Deployment does not match the checked train binding")
        return resource

    existing = deployment()
    if action == "deploy":
        if existing is None:
            labels = {"app.kubernetes.io/name": "lane-train"}
            probe = {"httpGet": {"path": path, "port": port}}
            manifest = {
                "apiVersion": "apps/v1", "kind": "Deployment",
                "metadata": {"name": "lane-train", "namespace": namespace,
                             "annotations": {"lanectl.io/checked-sha": commit}},
                "spec": {"replicas": 1, "selector": {"matchLabels": labels}, "template": {
                    "metadata": {"labels": labels}, "spec": {
                        "automountServiceAccountToken": False,
                        "securityContext": {"runAsNonRoot": True, "runAsUser": 11001,
                                            "seccompProfile": {"type": "RuntimeDefault"}},
                        "containers": [{
                            "name": "train", "image": image, "readinessProbe": probe,
                            "securityContext": {"allowPrivilegeEscalation": False,
                                                "readOnlyRootFilesystem": True,
                                                "capabilities": {"drop": ["ALL"]}},
                            "resources": {"requests": {"cpu": "50m", "memory": "64Mi"},
                                          "limits": {"cpu": "1", "memory": "512Mi"}},
                        }],
                    },
                }},
            }
            kube("create", "-f", "-", data=json.dumps(manifest))
        return

    if action == "teardown" and existing is not None:
        # Keep the Deployment visible until Kubernetes has collected its dependents.
        kube("delete", "deployment", "lane-train", "--ignore-not-found",
             "--cascade=foreground", "--wait=false")
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        current = deployment()
        if action == "teardown" and current is None:
            return
        if action == "health" and current is not None:
            status = current.get("status", {})
            if (status.get("observedGeneration") == current["metadata"]["generation"]
                    and status.get("readyReplicas") == 1):
                return
        time.sleep(0.5)
    raise RuntimeError(f"train {action} did not complete")


if __name__ == "__main__":
    main()
