#!/usr/bin/env python3
"""Build and publish a checked LANECTL documentation train on the owner host."""
import argparse
import base64
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory, mkdtemp
from uuid import uuid4


IMAGE = '''
let
  pkgs = (builtins.getFlake ("path:" + builtins.getEnv "TRAIN_NIXPKGS_FLAKE")).inputs.nixpkgs.legacyPackages.x86_64-linux;
  document = builtins.path { path = builtins.toPath (builtins.getEnv "TRAIN_DOCUMENT"); name = "checked-document"; };
  commit = builtins.getEnv "TRAIN_COMMIT";
  served = pkgs.runCommand "lanectl-train-document" {} \'\'
    install -Dm0444 ${document} "$out/document"
  \'\';
in pkgs.dockerTools.buildLayeredImage {
  name = "lanectl-docs-train";
  tag = commit;
  config = {
    User = "11001:11001";
    Entrypoint = [ "${pkgs.python3}/bin/python3" "-I" "-m" "http.server"
      "18080" "--bind" "0.0.0.0" "--directory" served ];
    Labels."org.opencontainers.image.revision" = commit;
    Labels."io.lanectl.train.document" = builtins.getEnv "TRAIN_DOCUMENT_PATH";
  };
}
'''


def checked_receipt(args):
    lines = (json.loads(line) for line in args.events.read_text().splitlines() if line.strip())
    latest = None
    for event in lines:
        if event["type"] == "train.built" and event["data"].get("train_id") == args.train:
            latest = event
    if latest is None or latest["data"].get("repo") != "lanectl" or latest["data"].get("passed") is not True:
        raise ValueError("train has no passing LANECTL build receipt")
    commit = latest["data"].get("checked_sha")
    if not isinstance(commit, str) or not re.fullmatch("[a-f0-9]{40}", commit):
        raise ValueError("train receipt has no checked commit")
    tip = git(args.repository, "rev-parse", "--verify", f"refs/heads/train/{args.train}").decode().strip()
    if tip != commit:
        raise ValueError("train ref differs from the checked commit")
    return latest


def checked_commit(args):
    return checked_receipt(args)["data"]["checked_sha"]


def export_bundle(args, destination):
    receipt = checked_receipt(args)
    commit = receipt["data"]["checked_sha"]
    base = receipt["data"].get("base_sha")
    if not isinstance(base, str) or not re.fullmatch("[a-f0-9]{40}", base) or base == commit:
        raise ValueError("passing receipt must identify a distinct base commit")
    git(args.repository, "merge-base", "--is-ancestor", base, commit)
    staging = Path(mkdtemp(prefix=".checked-train-", dir=destination.parent))
    try:
        git(args.repository, "bundle", "create", str(staging / "train.bundle"),
            f"refs/heads/train/{args.train}", f"^{base}")
        head = git(args.repository, "bundle", "list-heads", str(staging / "train.bundle")).decode().strip()
        if head != f"{commit} refs/heads/train/{args.train}" or checked_receipt(args) != receipt:
            raise ValueError("train changed during bundle export")
        (staging / "events.jsonl").write_text(json.dumps(receipt) + "\n")
        if destination.exists():
            raise FileExistsError(destination)
        staging.rename(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return commit


def submit_bundle(args):
    namespace = "lanectl-train-handoff"
    with TemporaryDirectory(prefix="lanectl-submit-") as scratch:
        export = Path(scratch) / "export"
        commit = export_bundle(args, export)
        name = f"request-{args.train}-{commit}"
        receipt = (export / "events.jsonl").read_bytes()
        bundle = (export / "train.bundle").read_bytes()
        if not 1 <= len(receipt) <= 4096 or not 1 <= len(bundle) <= 500000:
            raise ValueError("checked train request exceeds the handoff payload bounds")
        manifest = {
            "apiVersion": "v1", "kind": "ConfigMap",
            "metadata": {"name": name, "namespace": namespace},
            "immutable": True, "data": {"events.jsonl": receipt.decode("utf-8")},
            "binaryData": {"train.bundle": base64.b64encode(bundle).decode("ascii")},
        }
        result = subprocess.run(
            ["kubectl", "--kubeconfig", str(args.submit_kubeconfig), "--namespace", namespace,
             "--request-timeout=10s", "create", "-f", "-"],
            input=json.dumps(manifest), capture_output=True, text=True, timeout=15,
        )
        exists = f'Error from server (AlreadyExists): error when creating "STDIN": configmaps "{name}" already exists'
        if result.returncode and result.stderr.strip() != exists:
            raise RuntimeError(f"checked train submission failed: {result.stderr.strip()}")
    print(f"{namespace}/{name}")


def consume_request(args):
    request = json.loads(args.consume_request.read_text())
    metadata = request["metadata"]
    data, binary = request["data"], request["binaryData"]
    if (request.get("kind") != "ConfigMap" or metadata.get("namespace") != "lanectl-train-handoff"
            or request.get("immutable") is not True or set(data) != {"events.jsonl"}
            or set(binary) != {"train.bundle"}):
        raise ValueError("invalid checked train request")
    receipt = data["events.jsonl"].encode("utf-8")
    bundle = base64.b64decode(binary["train.bundle"], validate=True)
    if not 1 <= len(receipt) <= 4096 or not 1 <= len(bundle) <= 500000:
        raise ValueError("checked train request exceeds the handoff payload bounds")
    event = json.loads(receipt)
    details = event["data"]
    base, commit = details.get("base_sha"), details.get("checked_sha")
    if (event["type"] != "train.built" or details.get("repo") != "lanectl"
            or details.get("train_id") != args.train or details.get("passed") is not True
            or any(not isinstance(value, str) or not re.fullmatch("[a-f0-9]{40}", value)
                   for value in (base, commit))
            or metadata.get("name") != f"request-{args.train}-{commit}"):
        raise ValueError("request identity does not match a passing checked train receipt")
    trusted = args.repository.resolve(strict=True)
    trusted_tip = git(trusted, "rev-parse", "--verify", "refs/remotes/origin/main").decode().strip()
    git(trusted, "merge-base", "--is-ancestor", base, trusted_tip)
    with TemporaryDirectory(prefix="lanectl-train-owner-") as scratch:
        root = Path(scratch)
        repository = root / "repository.git"
        events = root / "events.jsonl"
        archive = root / "train.bundle"
        events.write_bytes(receipt)
        archive.write_bytes(bundle)
        git(root, "init", "--quiet", "--bare", str(repository))
        git(repository, "fetch", "--quiet", "--no-tags", str(trusted), base)
        git(repository, "bundle", "verify", str(archive))
        ref = f"refs/heads/train/{args.train}"
        head = git(repository, "bundle", "list-heads", str(archive)).decode().strip()
        if head != f"{commit} {ref}":
            raise ValueError("request bundle does not advertise the exact checked train")
        git(repository, "fetch", "--quiet", "--no-tags", str(archive), f"{ref}:{ref}")
        git(repository, "merge-base", "--is-ancestor", base, commit)
        return publish(argparse.Namespace(**(vars(args) | {"repository": repository, "events": events})))


def git(repository, *args):
    return subprocess.check_output(["git", "-C", str(repository), *args])


def verify_image(args, image, commit):
    if not re.fullmatch(re.escape(args.registry) + r"@sha256:[0-9a-f]{64}", image):
        raise ValueError("binding does not name a digest in the configured registry")
    tls = [] if not args.insecure_registry else ["--tls-verify=false"]
    config = json.loads(subprocess.check_output(
        ["skopeo", "--policy", str(args.image_policy), "inspect", *tls, "--config", f"docker://{image}"]))
    labels = config["config"]["Labels"]
    if (labels.get("org.opencontainers.image.revision") != commit
            or labels.get("io.lanectl.train.document") != str(args.document)):
        raise ValueError("registry image does not match the checked commit and document")


def verify_binding(args, binding, commit):
    spec = json.loads(binding.read_text())
    if (spec.get("commit") != commit or spec.get("port") != 18080
            or spec.get("health_path") != "/document" or not isinstance(spec.get("image"), str)):
        raise ValueError("published binding does not match this checked train")
    verify_image(args, spec["image"], commit)


def publish(args):
    commit = checked_commit(args)
    entry = git(args.repository, "ls-tree", commit, "--", str(args.document))
    if not entry.startswith((b"100644 blob ", b"100755 blob ")):
        raise ValueError("checked train documentation must be a regular Git blob")
    binding = args.bindings_directory / args.train / f"{commit}.json"
    binding.parent.mkdir(parents=True, exist_ok=True)
    if binding.exists():
        verify_binding(args, binding, commit)
        return binding
    with TemporaryDirectory(prefix=".train-publish-", dir=binding.parent) as scratch:
        root = Path(scratch)
        doc = root / "document"
        doc.write_bytes(git(args.repository, "show", f"{commit}:{args.document}"))
        env = {**os.environ, "TRAIN_DOCUMENT": str(doc), "TRAIN_COMMIT": commit,
               "TRAIN_DOCUMENT_PATH": str(args.document),
               "TRAIN_NIXPKGS_FLAKE": str(args.nixpkgs_flake.resolve(strict=True))}
        archive = subprocess.check_output(
            ["nix", "build", "--impure", "--no-link", "--print-out-paths", "--expr", IMAGE],
            text=True, env=env,
        ).strip()
        if checked_commit(args) != commit:
            raise ValueError("train changed while building its image")

        digest = root / "digest"
        tag = f"{commit}-{uuid4().hex}"
        skopeo = ["skopeo", "--policy", str(args.image_policy)]
        tls = [] if not args.insecure_registry else ["--dest-tls-verify=false"]
        subprocess.run([*skopeo, "copy", *tls, "--digestfile", str(digest),
                        f"docker-archive:{archive}", f"docker://{args.registry}:{tag}"], check=True,
                       stdout=subprocess.DEVNULL)
        value = digest.read_text().strip()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
            raise ValueError("registry copy did not return a valid digest")
        image = f"{args.registry}@{value}"
        verify_image(args, image, commit)
        if checked_commit(args) != commit:
            raise ValueError("train changed before binding publication")
        result = {"commit": commit, "image": image, "port": 18080, "health_path": "/document"}
        staged = root / "binding.json"
        staged.write_text(json.dumps(result) + "\n")
        try:
            os.link(staged, binding)
        except FileExistsError:
            verify_binding(args, binding, commit)
    return binding


def return_binding(args, binding):
    namespace = "lanectl-train-handoff"
    name = f"binding-{args.train}-{binding.stem}"
    contents = binding.read_text()
    manifest = {
        "apiVersion": "v1", "kind": "ConfigMap",
        "metadata": {"name": name, "namespace": namespace},
        "immutable": True, "data": {"binding.json": contents},
    }
    cmd = ["kubectl", "--kubeconfig", str(args.return_binding_kubeconfig), "--namespace", namespace,
           "--request-timeout=10s"]
    result = subprocess.run([*cmd, "create", "-f", "-"], input=json.dumps(manifest),
                            capture_output=True, text=True, timeout=15)
    if result.returncode:
        exists = f'Error from server (AlreadyExists): error when creating "STDIN": configmaps "{name}" already exists'
        if result.stderr.strip() != exists:
            raise RuntimeError(f"owner binding submission failed: {result.stderr.strip()}")
        existing = json.loads(subprocess.check_output([*cmd, "get", "configmap", name, "-o", "json"],
                                                      timeout=15))
        if existing.get("immutable") is not True or existing.get("data") != manifest["data"]:
            raise ValueError("the immutable response differs from the verified binding")
    print(f"{namespace}/{name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--events", type=Path, help="Trusted LANECTL train event log")
    parser.add_argument("--train", required=True)
    transfer = parser.add_mutually_exclusive_group()
    transfer.add_argument("--export-bundle", type=Path, help="Export a passing receipt and incremental Git bundle")
    transfer.add_argument("--consume-request", type=Path, help="Immutable ConfigMap JSON obtained from the handoff namespace")
    transfer.add_argument("--submit-kubeconfig", type=Path,
                          help="Submit the checked export using the dedicated handoff identity")
    parser.add_argument("--return-binding-kubeconfig", type=Path,
                        help="Publish the verified owner response using a separate owner identity")
    parser.add_argument("--document", type=PurePosixPath)
    parser.add_argument("--nixpkgs-flake", type=Path)
    parser.add_argument("--image-policy", type=Path)
    parser.add_argument("--registry", help="Destination image repository without tag")
    parser.add_argument("--insecure-registry", action="store_true")
    parser.add_argument("--bindings-directory", type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"train-[a-z0-9][a-z0-9-]{0,39}", args.train):
        parser.error("invalid train ID")
    if args.return_binding_kubeconfig is not None and args.consume_request is None:
        parser.error("returning a binding requires --consume-request")
    if args.consume_request is None and args.events is None:
        parser.error("--events is required when not consuming a request")
    if args.export_bundle is not None:
        if not args.export_bundle.is_absolute():
            parser.error("bundle destination must be absolute")
        export_bundle(args, args.export_bundle)
        print(args.export_bundle)
        return
    if args.submit_kubeconfig is not None:
        submit_bundle(args)
        return
    if None in (args.document, args.nixpkgs_flake, args.image_policy, args.registry, args.bindings_directory):
        parser.error("publishing requires --document, --nixpkgs-flake, --image-policy, --registry and --bindings-directory")
    if (not args.document.parts or args.document.parts[0] != "docs" or ".." in args.document.parts
            or args.document.suffix != ".md"):
        parser.error("document must be a Markdown path within docs/")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.:-]*/[a-z0-9][a-z0-9._/-]*", args.registry):
        parser.error("registry must be an image repository without a tag")
    if not args.bindings_directory.is_absolute():
        parser.error("bindings directory must be absolute")
    binding = consume_request(args) if args.consume_request is not None else publish(args)
    if args.return_binding_kubeconfig is not None:
        return_binding(args, binding)
    else:
        print(binding)


if __name__ == "__main__":
    main()
