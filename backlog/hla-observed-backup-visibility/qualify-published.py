#!/usr/bin/env python3
"""Run the mandatory source-bound published-path qualification in an HLA checkout."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=True, **kwargs).stdout.strip()


root = Path.cwd()
if not (root / "packages/storage/postgres_reporting.py").is_file():
    sys.exit("Run from the candidate homelab-analytics repository root")
if not os.environ.get("BACKUP_ACCEPTANCE_POSTGRES_DSN"):
    sys.exit("Set BACKUP_ACCEPTANCE_POSTGRES_DSN to an isolated disposable PostgreSQL instance")
if len(sys.argv) != 2:
    sys.exit("Usage: qualify-published.py /absolute/path/to/evidence.json")
evidence = Path(sys.argv[1])
if not evidence.is_absolute() or evidence.exists():
    sys.exit("Evidence path must be absolute and must not already exist")
sha = run("git", "rev-parse", "HEAD")
status = run("git", "status", "--porcelain=v1", "--untracked-files=all")
if status:
    sys.exit("Candidate checkout must be clean to bind evidence to its commit:\n" + status)
source = Path(__file__).resolve().parent / "files/tests"
tests = [source / "test_acc_observed_backup_visibility.py", source / "backup_published_qualification.py"]
version = run(str(root / ".venv/bin/python"), "-c", "import os, psycopg; c=psycopg.connect(os.environ['BACKUP_ACCEPTANCE_POSTGRES_DSN']); print(c.info.server_version); c.close()")
command = [os.environ.get("BACKUP_ACCEPTANCE_MAKE", "make"), "test-target", f"TEST={tests[1]} -p no:cacheprovider --tb=short"]
result = subprocess.run(command, text=True, capture_output=True)
if run("git", "rev-parse", "HEAD") != sha or run("git", "status", "--porcelain=v1", "--untracked-files=all"):
    sys.exit("Candidate changed during qualification; evidence rejected")
record = {
    "kind": "hla-backup-published-qualification/v1", "recorded_utc": datetime.now(timezone.utc).isoformat(),
    "candidate_commit": sha, "candidate_status": "clean before and after",
    "criterion_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in tests},
    "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    "postgres_server_version_num": version, "command": command,
    "exit_code": result.returncode, "output": result.stdout + result.stderr,
}
evidence.write_text(json.dumps(record, indent=2) + "\n")
print(f"Candidate {sha}; PostgreSQL server version {version}; exit {result.returncode}; evidence {evidence}")
print(record["output"])
sys.exit(result.returncode)
