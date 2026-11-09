"""Train merges use hook-safe subjects and report the real failure reason."""
import stat
import subprocess

from lanectl import runner
from tests.seed.test_end_to_end import SUB_TEST, scripted  # estate comes from tests/stage7/conftest.py


def good(wt):
    (wt / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n")
    (wt / "tests" / "test_sub_extra.py").write_text("from calc import sub\n\ndef test_neg():\n    assert sub(1, 2) == -1\n")


def _hook(repo, body):
    d = repo / "githooks"
    d.mkdir(exist_ok=True)
    h = d / "commit-msg"
    h.write_text("#!/bin/sh\n" + body)
    h.chmod(h.stat().st_mode | stat.S_IXUSR)
    subprocess.run(["git", "-C", str(repo), "config", "--local", "core.hooksPath", str(d)], check=True)


def _train(log):
    return [e["data"] for e in log.read() if e["type"] == "train.built"][-1]


def _candidate(release, log, name="add-sub", acc=SUB_TEST, edit=good):
    release(name, acc)
    c = runner.admit("implement", log)
    assert not isinstance(c, str), c
    assert "-> candidate" in runner.execute(c, log, adapter_fn=scripted(edit)), c
    return c


def test_merge_subject_is_git_style(estate):
    repo, release, log = estate
    c = _candidate(release, log)
    _hook(repo, 'head -1 "$1" | grep -q "^Merge lane/' + c.attempt_id + ': " '
               '|| { echo "bad subject: $(head -1 "$1")" >&2; exit 1; }\n')
    runner.build_train(log, "target")
    t = _train(log)
    assert t["excluded"] == [] and t["attempts"] == [c.attempt_id] and t["passed"] is True
    subject = subprocess.run(["git", "-C", t["worktree"], "log", "-1", "--format=%s"],
                             capture_output=True, text=True).stdout.strip()
    assert subject == f"Merge lane/{c.attempt_id}: add-sub"


def test_rejection_reason_is_the_hook_stderr(estate):
    repo, release, log = estate
    _candidate(release, log)
    _hook(repo, 'echo "policy says no" >&2; exit 1\n')
    runner.build_train(log, "target")
    ex = _train(log)["excluded"]
    assert len(ex) == 1
    assert ex[0]["reason"].startswith("merge failed:")
    assert "policy says no" in ex[0]["reason"]


def test_rejection_reason_uses_last_stderr_line_clipped(estate):
    repo, release, log = estate
    _candidate(release, log)
    long_line = "x" * 500
    _hook(repo, f'echo "first line" >&2; echo "{long_line}" >&2; exit 1\n')
    runner.build_train(log, "target")
    reason = _train(log)["excluded"][0]["reason"]
    assert reason == "merge failed: " + long_line[:200]


def test_unmerged_paths_are_a_conflict(estate):
    repo, release, log = estate
    def edit(marker):
        def fn(wt):
            (wt / "src" / "calc.py").write_text(
                "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n\n"
                f"# {marker}\n")
        return fn

    _candidate(release, log, "left", SUB_TEST, edit("left"))
    _candidate(release, log, "right", SUB_TEST, edit("right"))
    runner.build_train(log, "target")
    t = _train(log)
    assert len(t["excluded"]) == 1 and t["excluded"][0]["reason"] == "merge conflict"
    assert len(t["attempts"]) == 1
    subjects = subprocess.run(["git", "-C", t["worktree"], "log", "--merges", "--format=%s",
                               t["base_sha"] + ".."],
                              capture_output=True, text=True).stdout.splitlines()
    assert subjects and all(s.startswith("Merge lane/") for s in subjects if s.strip())
