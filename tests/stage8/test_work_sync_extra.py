"""Extra coverage: work.sync's call sequence, failure reporting and land wiring."""
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from lanectl import cli, runner, work
from lanectl.config import RepoSpec, load_release
from lanectl.contracts import Acceptance, WorkRelease

REPOS = {"homelab-analytics": RepoSpec(name="homelab-analytics", path="/srv/hla", main="main",
                                       test_cmd="true", check_cmd="true", worktree_root="/x")}


def _rel(**kw):
    return WorkRelease(id="hla-x", repo="homelab-analytics", base_sha="a" * 40, title="t",
                       outcome="o", task_class="glue", size="S", data_class="public",
                       scope_paths=("src/**",), acceptance=Acceptance(exec=("true",), files=()),
                       **kw)


class Tracker:
    """Fake sprintctl: records calls, answers ``item show`` from a status script."""

    def __init__(self, shows=(), fail_on=None, raw_show=None):
        self.calls, self.shows, self.fail_on, self.raw_show = [], list(shows), fail_on, raw_show

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        sub = cmd[cmd.index("sprintctl") + 1:]
        if self.fail_on and self.fail_on in sub:
            return SimpleNamespace(returncode=1, stdout="", stderr="boom")
        if sub[:2] == ["item", "show"]:
            if self.raw_show is not None:
                return SimpleNamespace(returncode=0, stdout=self.raw_show, stderr="")
            s = self.shows.pop(0)
            return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps(
                {"item": {"status": s, "status_revision": f"rev:{s}"}}))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def subs(self):
        return [c[c.index("sprintctl") + 1:] for c, _ in self.calls]


# ------------------------------------------------------------------ tracker_path

def test_tracker_path_falls_back_to_the_estate_root():
    assert work.tracker_path("vuoro-cloud#7", {}) == "/projects/dev/vuoro-cloud"
    assert work.tracker_path("homelab-analytics#7", REPOS) == "/srv/hla"


# ------------------------------------------------------------------ call shapes

def test_note_is_the_first_and_only_call_when_incomplete():
    t = Tracker()
    work.sync(_rel(work="homelab-analytics#7"), "train-1", "b" * 40, REPOS, run=t)
    assert t.subs() == [["item", "note", "--id", "homelab-analytics#7", "--type", "update",
                         "--summary", "lanectl landed hla-x in train-1",
                         "--git-sha", "b" * 40, "--actor", "lanectl"]]
    cmd, kw = t.calls[0]
    assert cmd == ["direnv", "exec", "/srv/hla", "sprintctl",
                   "item", "note", "--id", "homelab-analytics#7", "--type", "update",
                   "--summary", "lanectl landed hla-x in train-1",
                   "--git-sha", "b" * 40, "--actor", "lanectl"]
    assert kw == {"cwd": "/srv/hla", "capture_output": True, "text": True,
                  "stdin": subprocess.DEVNULL}


def test_unmapped_repo_runs_from_its_sibling_checkout():
    t = Tracker()
    work.sync(_rel(work="vuoro-cloud#7"), "t", "b" * 40, REPOS, run=t)
    cmd, kw = t.calls[0]
    assert cmd[:3] == ["direnv", "exec", "/projects/dev/vuoro-cloud"]
    assert kw["cwd"] == "/projects/dev/vuoro-cloud"


def test_blocked_is_promoted_through_active():
    t = Tracker(shows=["blocked", "active"])
    r = work.sync(_rel(work="homelab-analytics#7", work_complete=True), "t", "b" * 40,
                  REPOS, run=t)
    assert r == {"work": "homelab-analytics#7", "train_id": "t", "closed": True, "ok": True}
    statuses = [s for s in t.subs() if s[:2] == ["item", "status"]]
    assert [(s[s.index("--status") + 1], s[s.index("--expected-revision") + 1])
            for s in statuses] == [("active", "rev:blocked"), ("done", "rev:active")]


def test_active_goes_straight_to_done():
    t = Tracker(shows=["active"])
    r = work.sync(_rel(work="homelab-analytics#7", work_complete=True), "t", "b" * 40,
                  REPOS, run=t)
    assert r["closed"] is True and r["ok"] is True
    statuses = [s for s in t.subs() if s[:2] == ["item", "status"]]
    assert len(statuses) == 1
    assert statuses[0][statuses[0].index("--status") + 1] == "done"
    assert statuses[0][statuses[0].index("--expected-revision") + 1] == "rev:active"


def test_a_bare_item_object_is_read_too():
    t = Tracker(raw_show=json.dumps({"status": "done", "status_revision": "rev:7"}))
    r = work.sync(_rel(work="homelab-analytics#7", work_complete=True), "t", "b" * 40,
                  REPOS, run=t)
    assert r["closed"] is True and r["ok"] is True
    assert not [s for s in t.subs() if s[:2] == ["item", "status"]]


# ------------------------------------------------------------------ failures

def test_a_note_failure_stops_before_any_show():
    t = Tracker(fail_on="note")
    r = work.sync(_rel(work="homelab-analytics#7", work_complete=True), "t", "b" * 40,
                  REPOS, run=t)
    assert r["ok"] is False and r["closed"] is False and r["error"] == "boom"
    assert len(t.subs()) == 1


def test_an_unparseable_show_is_a_reported_failure():
    t = Tracker(raw_show="not json")
    r = work.sync(_rel(work="homelab-analytics#7", work_complete=True), "t", "b" * 40,
                  REPOS, run=t)
    assert r["ok"] is False and r["closed"] is False
    assert "not JSON" in r["error"]


def test_a_show_without_status_is_a_reported_failure():
    t = Tracker(raw_show=json.dumps({"item": {"id": 7}}))
    r = work.sync(_rel(work="homelab-analytics#7", work_complete=True), "t", "b" * 40,
                  REPOS, run=t)
    assert r["ok"] is False and r["closed"] is False and r["error"]


def test_a_raising_runner_is_reported_not_raised():
    def explode(cmd, **kw):
        raise OSError("no direnv")

    r = work.sync(_rel(work="homelab-analytics#7"), "t", "b" * 40, REPOS, run=explode)
    assert r["ok"] is False and "no direnv" in r["error"]


# ------------------------------------------------------------------ land wiring

CLAIM = {"lane": "implement", "model": "scripted/model", "worker": "scripted"}


def _set_work(item: str, ref: str, complete: bool) -> None:
    """Add a tracker reference to a scaffolded release (the seed helper has none)."""
    toml = Path(os.environ["LANECTL_HOME"]) / "backlog" / item / "release.toml"
    extra = f'work = "{ref}"\n' + ("work_complete = true\n" if complete else "")
    text = toml.read_text()
    toml.write_text(text.replace('data_class = "public"\n',
                                 'data_class = "public"\n' + extra, 1))


def _head(repo):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


def _train(log, repo, item, base):
    """A passed train that contains one attempt of *item*, built on *base*."""
    attempt = f"{item}-a1"
    log.append("item.claimed", dict(CLAIM, attempt_id=attempt), item_id=item)
    subprocess.run(["git", "-C", str(repo), "branch", "train/tt", base], check=True)
    log.append("train.built", {"train_id": "tt", "repo": "target", "base_sha": base,
                               "attempts": [attempt], "excluded": [], "passed": True,
                               "worktree": str(Path(str(repo)).parent / "wt" / "tt")})
    return attempt


def test_land_syncs_a_worked_release(estate, monkeypatch):
    repo, release, log = estate
    release("aa-work", "def test_ok():\n    assert True\n")
    _set_work("aa-work", "target#12", True)
    base = _head(repo)
    attempt = _train(log, repo, "aa-work", base)
    seen = []

    def fake_sync(rel, train_id, landed_sha, repos):
        seen.append((rel.id, train_id, landed_sha, sorted(repos)))
        return {"work": rel.work, "train_id": train_id, "closed": True, "ok": True}

    monkeypatch.setattr(runner.work, "sync", fake_sync)
    out = runner.land(log, "tt")
    assert "landed" in out
    assert seen == [("aa-work", "tt", base, ["target"])]
    synced = [e for e in log.read() if e["type"] == "work.synced"]
    assert [e["item_id"] for e in synced] == ["aa-work"]
    assert synced[0]["data"] == {"work": "target#12", "train_id": "tt",
                                 "closed": True, "ok": True}
    assert [e["item_id"] for e in log.read() if e["type"] == "item.landed"] == ["aa-work"]
    assert attempt


def test_land_skips_releases_without_work(estate, monkeypatch):
    repo, release, log = estate
    release("bb-plain", "def test_ok():\n    assert True\n")
    base = _head(repo)
    _train(log, repo, "bb-plain", base)
    monkeypatch.setattr(runner.work, "sync", lambda *a, **kw: pytest.fail("synced unworked"))
    assert "landed" in runner.land(log, "tt")
    assert not [e for e in log.read() if e["type"] == "work.synced"]


def test_land_survives_a_raising_sync(estate, monkeypatch):
    repo, release, log = estate
    release("cc-work", "def test_ok():\n    assert True\n")
    _set_work("cc-work", "target#12", False)
    base = _head(repo)
    _train(log, repo, "cc-work", base)

    def explode(*a, **kw):
        raise RuntimeError("tracker down")

    monkeypatch.setattr(runner.work, "sync", explode)
    assert "landed" in runner.land(log, "tt")
    assert [e["item_id"] for e in log.read() if e["type"] == "item.landed"] == ["cc-work"]


# ------------------------------------------------------------------ backlog new

NEW = ["backlog", "new", "aa-work", "--repo", "target", "--title", "T", "--size", "S",
       "--class", "glue", "--scope", "src/**", "--test", "tests/test_acc_w.py"]


def _home():
    return Path(os.environ["LANECTL_HOME"])


def test_new_work_without_complete_notes_only(estate):
    assert cli.main(NEW + ["--work", "target#12"]) == 0
    rel = load_release(_home() / "backlog" / "aa-work")
    assert rel.work == "target#12" and rel.work_complete is False


def test_new_without_work_writes_no_work_lines(estate):
    assert cli.main(NEW) == 0
    rel = load_release(_home() / "backlog" / "aa-work")
    assert rel.work == "" and rel.work_complete is False
    assert "work = " not in (_home() / "backlog" / "aa-work" / "release.toml").read_text()
    assert "work_complete" not in (_home() / "backlog" / "aa-work" / "release.toml").read_text()


def test_new_rejects_a_malformed_work_ref(estate, capsys):
    assert cli.main(NEW + ["--work", "1553"]) == 2
    assert not (_home() / "backlog" / "aa-work").exists()
    assert "--work" in capsys.readouterr().err


def test_new_complete_needs_work_even_for_a_valid_ref(estate, capsys):
    assert cli.main(NEW + ["--work-complete"]) == 2
    assert not (_home() / "backlog" / "aa-work").exists()
    assert "--work-complete" in capsys.readouterr().err
