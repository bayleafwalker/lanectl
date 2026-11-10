"""Acceptance: landing reports to the release's tracker item (planner-owned, V1)."""
import inspect
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

from lanectl import cli, runner, work
from lanectl.config import RepoSpec, load_release
from lanectl.contracts import Acceptance, WorkRelease


def _rel(**kw):
    return WorkRelease(id="hla-x", repo="homelab-analytics", base_sha="a" * 40, title="t",
                       outcome="o", task_class="glue", size="S", data_class="public",
                       scope_paths=("src/**",), acceptance=Acceptance(exec=("true",), files=()),
                       **kw)


REPOS = {"homelab-analytics": RepoSpec(name="homelab-analytics", path="/srv/hla", main="main",
                                       test_cmd="true", check_cmd="true", worktree_root="/x")}


class Fake:
    def __init__(self, statuses=(), fail_on=None):
        self.calls, self.statuses, self.fail_on = [], list(statuses), fail_on

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        sub = cmd[cmd.index("sprintctl") + 1:]
        if self.fail_on and self.fail_on in sub:
            return SimpleNamespace(returncode=1, stdout="", stderr="boom " * 100)
        if sub[:2] == ["item", "show"]:
            s = self.statuses.pop(0)
            return SimpleNamespace(returncode=0, stdout=json.dumps(
                {"item": {"id": 7, "status": s, "status_revision": f"rev:{s}"}}), stderr="")
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    def subs(self):
        return [c[c.index("sprintctl") + 1:] for c, _ in self.calls]


def test_tracker_path():
    assert work.tracker_path("homelab-analytics#7", REPOS) == "/srv/hla"
    assert work.tracker_path("vuoro-cloud#7", REPOS) == "/projects/dev/vuoro-cloud"


def test_no_work_no_calls():
    f = Fake()
    assert work.sync(_rel(), "train-1", "b" * 40, REPOS, run=f) is None
    assert f.calls == []


def test_note_only_when_incomplete():
    f = Fake()
    r = work.sync(_rel(work="homelab-analytics#7"), "train-1", "b" * 40, REPOS, run=f)
    assert r == {"work": "homelab-analytics#7", "train_id": "train-1", "closed": False, "ok": True}
    (sub,) = f.subs()
    assert sub[:4] == ["item", "note", "--id", "homelab-analytics#7"]
    assert "--git-sha" in sub and "b" * 40 in sub and "train-1" in " ".join(sub)
    cmd, kw = f.calls[0]
    assert cmd[:3] == ["direnv", "exec", "/srv/hla"] and kw.get("cwd") == "/srv/hla"
    assert kw.get("stdin") == subprocess.DEVNULL


def test_complete_from_pending_goes_active_then_done():
    f = Fake(statuses=["pending", "active"])
    r = work.sync(_rel(work="homelab-analytics#7", work_complete=True), "train-1", "b" * 40,
                  REPOS, run=f)
    assert r["ok"] is True and r["closed"] is True
    statuses = [s for s in f.subs() if s[:2] == ["item", "status"]]
    assert [s[s.index("--status") + 1] for s in statuses] == ["active", "done"]
    assert statuses[0][statuses[0].index("--expected-revision") + 1] == "rev:pending"
    assert statuses[1][statuses[1].index("--expected-revision") + 1] == "rev:active"


def test_complete_already_done_is_closed_without_transition():
    f = Fake(statuses=["done"])
    r = work.sync(_rel(work="homelab-analytics#7", work_complete=True), "t", "b" * 40, REPOS, run=f)
    assert r["ok"] is True and r["closed"] is True
    assert not [s for s in f.subs() if s[:2] == ["item", "status"]]


def test_failure_is_reported_not_raised():
    f = Fake(statuses=["active"], fail_on="status")
    r = work.sync(_rel(work="homelab-analytics#7", work_complete=True), "t", "b" * 40, REPOS, run=f)
    assert r["ok"] is False and r["closed"] is False
    assert 0 < len(r["error"]) <= 300

    def explode(cmd, **kw):
        raise OSError("no direnv")
    r = work.sync(_rel(work="homelab-analytics#7"), "t", "b" * 40, REPOS, run=explode)
    assert r["ok"] is False and "no direnv" in r["error"]


def test_land_records_work_synced():
    src = inspect.getsource(runner.land)
    assert "work.synced" in src and "sync(" in src


NEW = ["backlog", "new", "aa-work", "--repo", "target", "--title", "T", "--size", "S",
       "--class", "glue", "--scope", "src/**", "--test", "tests/test_acc_w.py"]


def test_backlog_new_writes_work(estate):
    assert cli.main(NEW + ["--work", "target#12", "--work-complete"]) == 0
    rel = load_release(Path(os.environ["LANECTL_HOME"]) / "backlog" / "aa-work")
    assert rel.work == "target#12" and rel.work_complete is True


def test_backlog_new_complete_needs_work(estate):
    assert cli.main(NEW + ["--work-complete"]) == 2
