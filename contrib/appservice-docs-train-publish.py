#!/usr/bin/env python3
"""Build and publish a checked LANECTL documentation train on the owner host."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from tempfile import TemporaryDirectory
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


def checked_commit(args):
    lines = (json.loads(line) for line in args.events.read_text().splitlines() if line.strip())
    latest = None
    for event in lines:
        if event["type"] == "train.built" and event["data"].get("train_id") == args.train:
            latest = event["data"]
    if latest is None or latest.get("repo") != "lanectl" or latest.get("passed") is not True:
        raise ValueError("train has no passing LANECTL build receipt")
    commit = latest.get("checked_sha")
    if not isinstance(commit, str) or not re.fullmatch("[a-f0-9]{40}", commit):
        raise ValueError("train receipt has no checked commit")
    tip = git(args.repository, "rev-parse", "--verify", f"refs/heads/train/{args.train}").decode().strip()
    if tip != commit:
        raise ValueError("train ref differs from the checked commit")
    return commit


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
        print(binding)
        return
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
    print(binding)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--events", required=True, type=Path, help="Trusted LANECTL train event log")
    parser.add_argument("--train", required=True)
    parser.add_argument("--document", required=True, type=PurePosixPath)
    parser.add_argument("--nixpkgs-flake", required=True, type=Path)
    parser.add_argument("--image-policy", required=True, type=Path)
    parser.add_argument("--registry", required=True, help="Destination image repository without tag")
    parser.add_argument("--insecure-registry", action="store_true")
    parser.add_argument("--bindings-directory", required=True, type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"train-[a-z0-9-]{1,40}", args.train):
        parser.error("invalid train ID")
    if (not args.document.parts or args.document.parts[0] != "docs" or ".." in args.document.parts
            or args.document.suffix != ".md"):
        parser.error("document must be a Markdown path within docs/")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.:-]*/[a-z0-9][a-z0-9._/-]*", args.registry):
        parser.error("registry must be an image repository without a tag")
    if not args.bindings_directory.is_absolute():
        parser.error("bindings directory must be absolute")
    publish(args)


if __name__ == "__main__":
    main()
