"""A served sprintctl backend refuses --expected-revision; sync retries without it."""
import json
from types import SimpleNamespace

from lanectl import work
from lanectl.contracts import Acceptance, WorkRelease

REL = WorkRelease(id="rel-x", repo="r", base_sha="a" * 40, title="t", outcome="o", task_class="glue",
                  size="S", data_class="public", scope_paths=("src/**",),
                  acceptance=Acceptance(exec=("true",), files=()), work="r#7", work_complete=True)


def test_served_backend_closes_without_cas():
    calls, statuses = [], ["pending", "active"]

    def run(cmd, **kw):
        sub = cmd[cmd.index("sprintctl") + 1:]
        calls.append(sub)
        if sub[:2] == ["item", "show"]:
            s = statuses.pop(0)
            return SimpleNamespace(returncode=0, stderr="",
                                   stdout=json.dumps({"status": s, "status_revision": s}))
        if "--expected-revision" in sub:
            return SimpleNamespace(returncode=2, stdout="", stderr=(
                "Error: --expected-revision is a direct-backend CAS option; served lifecycle "
                "commands already carry their immutable basis revision.\n"))
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    r = work.sync(REL, "t", "b" * 40, {}, run=run)
    assert r["ok"] is True and r["closed"] is True
    done = [c for c in calls if c[:2] == ["item", "status"] and "--expected-revision" not in c]
    assert [c[c.index("--status") + 1] for c in done] == ["active", "done"]


def test_other_failures_are_not_retried():
    def run(cmd, **kw):
        sub = cmd[cmd.index("sprintctl") + 1:]
        if sub[:2] == ["item", "show"]:
            return SimpleNamespace(returncode=0, stderr="",
                                   stdout=json.dumps({"status": "active", "status_revision": "v"}))
        if sub[:2] == ["item", "status"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="stale-basis")
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")
    r = work.sync(REL, "t", "b" * 40, {}, run=run)
    assert r["ok"] is False and "stale-basis" in r["error"]
