"""Lane tests: repo gate jobs run as ``job:<name>`` gates after acceptance."""
import os
from pathlib import Path

from lanectl import gatejobs, runner
from lanectl.adapters import AdapterResult
from lanectl.config import GateJob

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


def _jobs(*blocks):
    p = Path(os.environ["LANECTL_HOME"]) / "governance" / "repos.toml"
    p.write_text(p.read_text() + "".join("\n[[repos.target.gate_jobs]]\n" + b for b in blocks))


def _gates(log):
    return {e["data"]["gate"]: e["data"] for e in log.read() if e["type"] == "gate.result"}


def test_run_jobs_keeps_listed_order_and_passes_on_zero_exit(tmp_path):
    (tmp_path / "marker").write_text("")
    jobs = (GateJob("first", "true"), GateJob("second", "test -f marker"))
    out = gatejobs.run_jobs(jobs, tmp_path)
    assert list(out) == ["job:first", "job:second"]
    assert out == {"job:first": [], "job:second": []}


def test_run_jobs_failure_is_exit_name_and_last_600_chars(tmp_path):
    job = GateJob("lint", "seq 1 200; echo tail-end; exit 3")
    (violation,) = gatejobs.run_jobs((job,), tmp_path)["job:lint"]
    assert violation.startswith("exit 3: lint :: ")
    tail = violation.split(" :: ", 1)[1]
    assert tail.endswith("tail-end\n") and "196" in tail and len(tail) <= 600


def test_run_jobs_timeout_names_the_job(tmp_path):
    out = gatejobs.run_jobs((GateJob("slow", "sleep 5", 1),), tmp_path)
    assert out == {"job:slow": ["timeout after 1s: slow"]}


def test_run_jobs_wraps_each_command_when_a_sandbox_is_given(tmp_path):
    seen = []

    def wrap(cmd, wt):
        seen.append((cmd, wt))
        return cmd

    gatejobs.run_jobs((GateJob("wrapped", "true"),), tmp_path, wrap)
    assert seen == [("true", tmp_path)]


def test_repo_jobs_become_gates_after_acceptance(estate):
    _, release, log = estate
    release("ee-jobs", SUB_TEST)
    _jobs('name = "sees-acceptance"\ncmd = "test -f tests/test_acc_ee_jobs.py"\n',
          'name = "second"\ncmd = "true"\n')
    out = runner.execute(runner.admit("implement", log), log, adapter_fn=_scripted(_good))
    assert "-> candidate" in out, out
    gates = _gates(log)
    assert gates["job:sees-acceptance"]["passed"] is True
    assert gates["job:second"]["passed"] is True


def test_failing_job_rejects_with_its_exit_and_output(estate):
    _, release, log = estate
    release("ff-jobs", SUB_TEST)
    _jobs('name = "lint"\ncmd = "echo job-said-no; exit 7"\n')
    out = runner.execute(runner.admit("implement", log), log, adapter_fn=_scripted(_good))
    assert "-> rejected" in out and "job:lint" in out, out
    (violation,) = _gates(log)["job:lint"]["violations"]
    assert violation.startswith("exit 7: lint ::"), violation
    assert "job-said-no" in violation
