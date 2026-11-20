#!/usr/bin/env python3
"""Deploy a digest-pinned train image inside an already provisioned namespace."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("deploy", "health", "teardown"))
    parser.add_argument("--binding", required=True, type=Path)
    parser.add_argument("--kubeconfig", required=True, type=Path)
    args = parser.parse_args()
    train = os.environ["LANE_TRAIN_ID"]
    namespace = os.environ["LANE_NAMESPACE"]
    commit = os.environ["LANE_CHECKED_SHA"]
    if not re.fullmatch(r"train-[a-z0-9-]{1,40}", train) or namespace != f"lane-dev-{train}":
        raise ValueError("namespace must match the LANECTL train")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("checked train commit is required")

    binding = json.loads(args.binding.read_text())
    image = binding["image"]
    if binding["commit"] != commit or not re.fullmatch(
        r"[a-z0-9][a-z0-9./:_-]*@sha256:[0-9a-f]{64}", image
    ):
        raise ValueError("reviewed image binding must match the checked commit and use a digest")
    port = binding["port"]
    path = binding["health_path"]
    if type(port) is not int or not 1024 <= port <= 65535 or not re.fullmatch(r"/[a-zA-Z0-9/_-]*", path):
        raise ValueError("invalid train health endpoint")

    command = ["kubectl", "--kubeconfig", str(args.kubeconfig), "--namespace", namespace, "--request-timeout=10s"]

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
    if args.action == "deploy":
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

    if args.action == "teardown" and existing is not None:
        kube("delete", "deployment", "lane-train", "--ignore-not-found", "--wait=false")
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        current = deployment()
        if args.action == "teardown" and current is None:
            return
        if args.action == "health" and current is not None:
            status = current.get("status", {})
            if (status.get("observedGeneration") == current["metadata"]["generation"]
                    and status.get("readyReplicas") == 1):
                return
        time.sleep(0.5)
    raise RuntimeError(f"train {args.action} did not complete")


if __name__ == "__main__":
    main()
