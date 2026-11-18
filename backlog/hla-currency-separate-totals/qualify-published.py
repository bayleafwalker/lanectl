#!/usr/bin/env python3
"""Run the mandatory source-bound published-path qualification in an HLA checkout."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=True, **kwargs).stdout.strip()


root = Path.cwd()
if not (root / "packages/storage/postgres_reporting.py").is_file():
    sys.exit("Run from the candidate homelab-analytics repository root")
if not os.environ.get("CURRENCY_ACCEPTANCE_POSTGRES_DSN"):
    sys.exit("Set CURRENCY_ACCEPTANCE_POSTGRES_DSN to an isolated disposable PostgreSQL instance")
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
tests = [source / "test_acc_currency_separate_totals.py", source / "currency_published_qualification.py", source / "test_acc_currency_empty_schema.py", source / "test_acc_currency_consumers.py"]
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


bound_files = [*tests, Path(__file__).resolve()]
before = {str(path): digest(path) for path in bound_files}
version = run(str(root / ".venv/bin/python"), "-c", "import os, psycopg; c=psycopg.connect(os.environ['CURRENCY_ACCEPTANCE_POSTGRES_DSN']); print(c.info.server_version); c.close()")
with tempfile.TemporaryDirectory(prefix="hla-currency-qualification-") as scratch:
    junit = Path(scratch) / "result.xml"
    command = [os.environ.get("CURRENCY_ACCEPTANCE_MAKE", "make"), "test-target", f"TEST={tests[1]} -p no:cacheprovider --tb=short --junitxml={junit}"]
    result = subprocess.run(command, text=True, capture_output=True)
    if run("git", "rev-parse", "HEAD") != sha or run("git", "status", "--porcelain=v1", "--untracked-files=all"):
        sys.exit("Candidate changed during qualification; evidence rejected")
    try:
        after = {str(path): digest(path) for path in bound_files}
    except OSError:
        sys.exit("Criterion or harness disappeared during qualification; evidence rejected")
    if before != after:
        sys.exit("Criterion or harness changed during qualification; evidence rejected")
    try:
        report = ET.parse(junit).getroot()
        cases = list(report.iter("testcase"))
        suites = list(report.iter("testsuite"))
        valid = (
            result.returncode == 0 and len(cases) == 1 and bool(suites)
            and cases[0].get("name") == "test_currency_published_reporting_survives_warehouse_clear_without_fallback"
            and cases[0].get("classname", "").split(".")[-1] == "currency_published_qualification"
            and not any(cases[0].find(tag) is not None for tag in ("failure", "error", "skipped"))
            and all(int(s.get(tag, "0")) == 0 for s in suites for tag in ("errors", "failures", "skipped"))
            and all(int(s.get("tests", "-1")) == 1 for s in suites)
        )
    except (OSError, ET.ParseError, ValueError):
        valid = False
    if not valid:
        print(result.stdout + result.stderr)
        sys.exit("Qualification rejected: expected exactly the published testcase executed and passed, with no failures, errors or skips")

record = {
    "kind": "hla-currency-published-qualification/v1", "recorded_utc": datetime.now(timezone.utc).isoformat(),
    "candidate_commit": sha, "candidate_status": "clean before and after",
    "criterion_sha256": {p.name: before[str(p)] for p in tests},
    "harness_sha256": before[str(Path(__file__).resolve())],
    "postgres_server_version_num": version, "command": command,
    "exit_code": result.returncode, "executed_passed_test": cases[0].get("name"),
    "output": result.stdout + result.stderr,
}
evidence.write_text(json.dumps(record, indent=2) + "\n")
print(f"Candidate {sha}; PostgreSQL server version {version}; exit {result.returncode}; evidence {evidence}")
print(record["output"])
