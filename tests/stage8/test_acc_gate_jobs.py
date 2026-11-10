"""Acceptance: s3-gate-jobs - repo gate jobs run after acceptance as job:<name> gates."""
import os
from pathlib import Path

from lanectl import runner
from lanectl.adapters import AdapterResult

SUB_TEST = "from calc import sub\n\ndef test_sub():\n    assert sub(5, 3) == 2\n"


def _good(wt):
    (wt / "src" / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n")
    (wt / "tests" / "test_sub_extra.py").write_text(
        "from calc import sub\n\ndef test_neg():\n    assert sub(1, 2) == -1\n")


def _scripted(edit):
    def fn(*, worktree, **_):
        edit(Path(worktree))
        return AdapterResult("done", 0, "ok", None)
    return fn


def _home():
    return Path(os.environ["LANECTL_HOME"])


def _no_sandbox():
    p = _home() / "governance" / "lanes" / "implement.toml"
    p.write_text(p.read_text().replace('mode = "systemd-run"', 'mode = "none"'))


def _jobs(*blocks):
    p = _home() / "governance" / "repos.toml"
    p.write_text(p.read_text() + "".join("\n[[repos.target.gate_jobs]]\n" + b for b in blocks))


def _gates(log):
    return {e["data"]["gate"]: e["data"] for e in log.read() if e["type"] == "gate.result"}


def test_passing_jobs_are_recorded_and_item_is_candidate(estate):
    _, release, log = estate
    release("aa-jobs", SUB_TEST)
    _jobs('name = "first-ok"\ncmd = "true"\n', 'name = "sees-acceptance"\n'
          'cmd = "test -f tests/test_acc_aa_jobs.py"\n')
    out = runner.execute(runner.admit("implement", log), log, adapter_fn=_scripted(_good))
    assert "-> candidate" in out, out
    gates = _gates(log)
    assert gates["job:first-ok"]["passed"] is True
    assert gates["job:sees-acceptance"]["passed"] is True


def test_failing_job_rejects_with_exit_and_output(estate):
    _, release, log = estate
    release("bb-jobs", SUB_TEST)
    _jobs('name = "lint"\ncmd = "echo lint-said-no; exit 3"\n')
    out = runner.execute(runner.admit("implement", log), log, adapter_fn=_scripted(_good))
    assert "-> rejected" in out and "job:lint" in out, out
    (violation,) = _gates(log)["job:lint"]["violations"]
    assert violation.startswith("exit 3: lint ::") and "lint-said-no" in violation


def test_job_timeout_is_a_violation(estate):
    _, release, log = estate
    release("cc-jobs", SUB_TEST)
    _jobs('name = "slow"\ncmd = "sleep 5"\ntimeout_s = 1\n')
    out = runner.execute(runner.admit("implement", log), log, adapter_fn=_scripted(_good))
    assert "-> rejected" in out, out
    assert _gates(log)["job:slow"]["violations"] == ["timeout after 1s: slow"]


def test_jobs_do_not_run_when_acceptance_fails(estate, tmp_path):
    _, release, log = estate
    _no_sandbox()
    marker = tmp_path / "job-ran"
    release("dd-jobs", SUB_TEST)
    _jobs(f'name = "marker"\ncmd = "touch {marker}"\n')
    out = runner.execute(runner.admit("implement", log), log, adapter_fn=_scripted(lambda wt: None))
    assert "-> rejected" in out and "acceptance" in out, out
    assert not marker.exists()
    assert "job:marker" not in _gates(log)
