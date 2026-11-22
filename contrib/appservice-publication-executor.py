#!/usr/bin/env python3
"""Execute the protected publisher's commands with repository-scoped leases."""
import os
import re
import subprocess
import sys

REPOSITORY = "bayleafwalker/lanectl"
REMOTE = f"https://github.com/{REPOSITORY}.git"
SHA = re.compile(r"[a-f0-9]{40}")
BRANCH = re.compile(r"lanes/train-[a-z0-9][a-z0-9-]{0,39}")
CHECKED_REF = re.compile(rf"{SHA.pattern}:refs/heads/{BRANCH.pattern}")


def pr_capability(args):
    action, *options = args
    if action in {"list", "create"} and options[:3] == ["-R", REPOSITORY, "--head"]:
        if len(options) >= 4 and BRANCH.fullmatch(options[3]):
            if action == "list" and options[4:] in (
                ["--state", "all", "--json", "number,state,headRefOid"],
                ["--state", "open", "--json", "number,state,headRefOid"],
            ):
                return "pr.read"
            if (action == "create" and len(options) == 10
                    and options[4:7] == ["--base", "main", "--title"] and options[8] == "--body"):
                return "pr.manage"
    if len(options) >= 3 and re.fullmatch(r"[1-9][0-9]*", options[0]) and options[1:3] == ["-R", REPOSITORY]:
        flags = options[3:]
        if action == "checks" and flags in (
            ["--watch"], ["--required", "--json", "name,bucket,state"],
        ):
            return "pr.read"
        if (action == "merge" and len(flags) == 3
                and flags[:2] == ["--merge", "--match-head-commit"] and SHA.fullmatch(flags[2])):
            return "pr.merge"
    return None


def scoped_command(args):
    if len(args) == 4 and args[:3] == ["git", "push", "origin"] and CHECKED_REF.fullmatch(args[3]):
        return [
            "credctl", "exec", "repo.write", "--repository", f"github:{REPOSITORY}", "--",
            "git", "-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential",
            "-c", "credential.useHttpPath=true", *args[1:],
        ]
    if args[:2] == ["git", "-C"] and len(args) >= 5:
        if args[3:] in (["fetch", "--no-tags", "origin", "main"],
                        ["ls-remote", "--exit-code", "origin", "refs/heads/main"],
                        ["rev-parse", "FETCH_HEAD"],
                        ["config", "--get", "claude.canonicalRemote"]):
            return args
        if (len(args) == 7 and args[3:5] == ["merge-base", "--is-ancestor"]
                and all(SHA.fullmatch(sha) for sha in args[5:])):
            return args
    if args[:2] == ["gh", "pr"] and len(args) >= 3:
        capability = pr_capability(args[2:])
        if capability:
            return ["credctl", "exec", capability, "--repository", f"github:{REPOSITORY}", "--", *args]
    raise ValueError("command outside the LANECTL publication contract")


def main():
    args = sys.argv[1:]
    try:
        command = scoped_command(args)
        if args[:2] == ["git", "push"]:
            remote = subprocess.check_output(
                ["git", "remote", "get-url", "--push", "origin"], text=True
            ).strip()
            if remote != REMOTE:
                raise ValueError("push URL differs from canonical LANECTL")
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"publication executor: {exc}", file=sys.stderr)
        return 2
    os.environ["GIT_TERMINAL_PROMPT"] = "0"
    os.execvp(command[0], command)


if __name__ == "__main__":
    sys.exit(main())
