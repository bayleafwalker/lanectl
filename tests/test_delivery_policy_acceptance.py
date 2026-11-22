"""Independent prospective-policy acceptance using synthetic local histories."""

import subprocess

import pytest

from lanectl import evaluator
from tests.seed.test_end_to_end import estate  # noqa: F401


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def test_unavailable_size_denominator_is_not_reported_as_zero(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "synthetic.py").write_text("x = 1\n")
    git(tmp_path, "add", "-A")
    git(
        tmp_path,
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "base",
    )
    seed = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "synthetic.py").write_text("x = 2\ny = 3\n")
    git(tmp_path, "add", "-A")
    git(
        tmp_path,
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "change",
    )
    head = git(tmp_path, "rev-parse", "HEAD")
    actual = evaluator.features(tmp_path, seed, head, None, ())
    assert actual["changed_lines"] == 3
    assert actual.get("changed_lines_ratio") is None


def prospective(estate):
    import os
    import re
    from pathlib import Path

    lane = Path(os.environ["LANECTL_HOME"]) / "governance/lanes/implement.toml"
    text = lane.read_text()
    if re.search(r"(?m)^delivery_policy\s*=", text):
        text = re.sub(
            r"(?m)^delivery_policy\s*=.*$", 'delivery_policy = "review-progress"', text
        )
    else:
        text = text.replace(
            "[routing]", '[routing]\ndelivery_policy = "review-progress"'
        )
    text = text.replace('mode = "systemd-run"', 'mode = "none"')
    lane.write_text(text)
    return estate


def large_correct(wt):
    (wt / "src/calc.py").write_text(
        "def add(a, b):\n    return a + b\n\n"
        "def sub(a, b):\n    return a - b\n" + "# synthetic diagnostic line\n" * 300
    )
    (wt / "tests/test_sub_extra.py").write_text(
        "from calc import sub\n\ndef test_neg():\n    assert sub(1, 2) == -1\n"
    )


def test_prospective_large_correct_change_is_not_failed_by_old_size_cap(estate):
    from lanectl import runner
    from tests.seed.test_end_to_end import SUB_TEST, scripted

    _, release, log = prospective(estate)
    release("synthetic-large", SUB_TEST)
    claim = runner.admit("implement", log)
    assert not isinstance(claim, str), claim
    result = runner.execute(claim, log, adapter_fn=scripted(large_correct))
    assert "-> candidate" in result, result
    assert not any(
        "size-budget" in str(e["data"].get("violations", []))
        for e in log.read()
        if e["type"] == "gate.result"
    )


def test_prospective_failed_acceptance_and_protected_edit_do_not_succeed(estate):
    from lanectl import runner
    from lanectl.events import project_items
    from tests.seed.test_end_to_end import SUB_TEST, scripted

    _, release, log = prospective(estate)
    release("synthetic-fail", SUB_TEST)
    result = runner.execute(
        runner.admit("implement", log),
        log,
        adapter_fn=scripted(
            lambda wt: (wt / "src/calc.py").write_text(
                "def sub(a, b):\n    return 999\n"
            )
        ),
    )
    assert "candidate" not in result, result
    assert project_items(log.read())["synthetic-fail"].state != "candidate"
    assert project_items(log.read())["synthetic-fail"].state != "requeued"
    release("synthetic-protected", SUB_TEST)

    def alter_acceptance(wt):
        (wt / "tests/test_acc_synthetic_protected.py").write_text(
            "def test_sub():\n    assert True\n"
        )

    result = runner.execute(
        runner.admit("implement", log, only="synthetic-protected"),
        log,
        adapter_fn=scripted(alter_acceptance),
    )
    assert "protected-path" in result and "candidate" not in result, result


def test_mutated_lane_cannot_change_claim_recovery_or_evaluation(estate, tmp_path):
    import copy
    import json
    import os
    from datetime import datetime, timedelta, timezone
    from pathlib import Path

    from lanectl import runner
    from lanectl.events import EventLog, project_items
    from lanectl.reap import reap
    from tests.seed.test_end_to_end import SUB_TEST, scripted

    _, release, log = prospective(estate)
    release("synthetic-recovery", SUB_TEST)
    claim = runner.admit("implement", log)
    assert not isinstance(claim, str), claim
    lane_path = Path(os.environ["LANECTL_HOME"]) / "governance/lanes/implement.toml"
    changed = lane_path.read_text().replace(
        'delivery_policy = "review-progress"', 'delivery_policy = "legacy"'
    )
    changed = changed.replace("S = 250", "S = 1").replace(
        "max_attempts = 2", "max_attempts = 1"
    )
    lane_path.write_text(changed)
    result = runner.execute(claim, log, adapter_fn=scripted(large_correct))
    assert "-> candidate" in result, result
    lines = Path(log.path).read_text().splitlines()
    last = max(
        i for i, line in enumerate(lines) if json.loads(line)["type"] == "gate.result"
    )
    Path(log.path).write_text("\n".join(lines[: last + 1]) + "\n")
    conflict = EventLog(tmp_path / "conflicting-claim.jsonl")
    for event in log.read():
        data = copy.deepcopy(event["data"])
        if event["type"] == "item.claimed":
            data["effective_policy"]["lane"]["delivery_policy"] = "legacy"
        conflict.append(event["type"], data, item_id=event["item_id"])
    assert (
        evaluator.evaluate_attempt(
            conflict,
            claim.attempt_id,
            {"revision": 1, "default": "accept", "rules": []},
        )
        is None
    )
    assert not any(e["type"] == "evaluation.recorded" for e in conflict.read())
    assert reap(
        log,
        now=datetime.now(timezone.utc) + timedelta(days=1),
        older_than_s=60,
        max_attempts=1,
    ) == [claim.attempt_id]
    assert project_items(log.read())["synthetic-recovery"].state == "candidate"
    evaluation = evaluator.evaluate_attempt(
        log, claim.attempt_id, {"revision": 1, "default": "accept", "rules": []}
    )
    assert evaluation is not None
    assert evaluation["verdict"] not in ("accept", "candidate")
    assert evaluation["features"]["changed_lines"] > 250
    assert 1 < evaluation["features"]["changed_lines_ratio"] < 2


def test_legacy_parked_history_does_not_reopen_on_higher_revision(estate):
    from lanectl import runner
    from lanectl.events import project_items
    from tests.seed.test_end_to_end import SUB_TEST
    from pathlib import Path
    import os

    _, release, log = prospective(estate)
    release("synthetic-history", SUB_TEST)
    item = "synthetic-history"
    log.append("release.published", {"release_id": item, "revision": 1}, item_id=item)
    for number in (1, 2):
        aid = f"{item}-a{number}"
        log.append(
            "item.claimed",
            {
                "attempt_id": aid,
                "lane": "implement",
                "model": "scripted/model",
                "worker": "scripted",
                "release_revision": 1,
            },
            item_id=item,
        )
        log.append(
            "attempt.finished",
            {
                "attempt_id": aid,
                "outcome": "done",
                "exit_code": 0,
                "head_sha": "a" * 40,
            },
            item_id=item,
        )
        log.append(
            "decision.recorded",
            {
                "attempt_id": aid,
                "decision": "rejected",
                "reasons": ["original acceptance failure"],
                "rules_revision": "decision-rules/v3",
            },
            item_id=item,
        )
    log.append("item.parked", {"reason": "legacy attempts exhausted"}, item_id=item)
    before = log.read()
    release_file = Path(os.environ["LANECTL_HOME"]) / "backlog" / item / "release.toml"
    release_file.write_text("revision = 2\n" + release_file.read_text())
    runner.admit("implement", log, only=item)
    after = log.read()
    view = project_items(after)[item]
    assert view.release_revision == 2
    assert any(
        e["type"] == "release.published" and e["data"]["revision"] == 2 for e in after
    )
    assert view.state == "parked"
    assert len(view.attempts) == 2
    assert after[: len(before)] == before
    assert not any(e["type"] == "item.claimed" for e in after[len(before) :])
    assert not any(e["type"] == "integrator.fix" for e in after)


def test_prospective_retry_requires_substantive_recorded_review_not_count(estate):
    import pytest
    from lanectl import runner
    from lanectl.events import project_items
    from tests.seed.test_end_to_end import SUB_TEST, scripted

    _, release, log = prospective(estate)
    release("synthetic-retry", SUB_TEST)
    item = "synthetic-retry"
    for number in (1, 2):
        claim = runner.admit("implement", log, only=item)
        assert not isinstance(claim, str), claim
        result = runner.execute(
            claim,
            log,
            adapter_fn=scripted(
                lambda wt: (wt / "src/calc.py").write_text(
                    "def sub(a, b):\n    return 999\n"
                )
            ),
        )
        assert "candidate" not in result
        assert project_items(log.read())[item].state == "parked"
        assert isinstance(runner.admit("implement", log, only=item), str)
        with pytest.raises((ValueError, TypeError)):
            runner.review_progress(log, claim.attempt_id, "continue", "", "", "")
        assert project_items(log.read())[item].state == "parked"
        result = runner.review_progress(
            log,
            claim.attempt_id,
            "continue",
            "Identified wrong subtraction result",
            "Implement subtraction and pass independent test",
            "The concrete failure can be repaired",
        )
        assert "continue" in result
        assert project_items(log.read())[item].state == "requeued"
    third = runner.admit("implement", log, only=item)
    assert not isinstance(third, str), third
    assert len(project_items(log.read())[item].attempts) == 3
    result = runner.execute(third, log, adapter_fn=scripted(large_correct))
    assert "-> candidate" in result, result
    assert sum(e["type"] == "progress.reviewed" for e in log.read()) == 2


def test_revision_inherits_publication_policy_after_lane_mutation(estate):
    import os
    from pathlib import Path
    from lanectl import runner
    from lanectl.config import load_releases
    from tests.seed.test_end_to_end import SUB_TEST

    _, release, log = prospective(estate)
    item = "synthetic-revision"
    release(item, SUB_TEST)
    claim = runner.admit("implement", log)
    assert not isinstance(claim, str), claim
    original = next(
        e["data"]["effective_policy"]
        for e in log.read()
        if e["type"] == "release.published" and e["item_id"] == item
    )
    claimed = next(
        e["data"]["effective_policy"]
        for e in log.read()
        if e["type"] == "item.claimed" and e["item_id"] == item
    )
    assert original == claimed
    home = Path(os.environ["LANECTL_HOME"])
    lane_path = home / "governance/lanes/implement.toml"
    lane_path.write_text(
        lane_path.read_text()
        .replace('delivery_policy = "review-progress"', 'delivery_policy = "legacy"')
        .replace("S = 250", "S = 1")
    )
    path = home / "backlog" / item / "release.toml"
    path.write_text("revision = 2\n" + path.read_text())
    runner.sync_releases(log, load_releases())
    pubs = [
        e["data"]
        for e in log.read()
        if e["type"] == "release.published" and e["item_id"] == item
    ]
    assert [p["revision"] for p in pubs] == [1, 2]
    assert pubs[1]["effective_policy"] == original


def test_prospective_capacity_still_blocks_second_claim(estate):
    import os
    from pathlib import Path
    from lanectl import runner
    from tests.seed.test_end_to_end import SUB_TEST

    _, release, log = prospective(estate)
    path = Path(os.environ["LANECTL_HOME"]) / "governance/lanes/implement.toml"
    path.write_text(path.read_text().replace("concurrency = 3", "concurrency = 1"))
    release("synthetic-cap-first", SUB_TEST)
    release("synthetic-cap-second", SUB_TEST)
    first = runner.admit("implement", log, only="synthetic-cap-first")
    assert not isinstance(first, str), first
    second = runner.admit("implement", log, only="synthetic-cap-second")
    assert isinstance(second, str) and "concurrency" in second
    assert len([e for e in log.read() if e["type"] == "item.claimed"]) == 1


def test_legacy_recovery_uses_recorded_git_digest_not_current_policy(estate):
    import os
    import re
    from datetime import datetime, timedelta, timezone
    from pathlib import Path
    from lanectl.config import load_lane
    from lanectl.events import project_items
    from lanectl.reap import reap
    from tests.seed.test_end_to_end import SUB_TEST

    _, release, log = estate
    item = "synthetic-legacy"
    release(item, SUB_TEST)
    home = Path(os.environ["LANECTL_HOME"])
    lane_path = home / "governance/lanes/implement.toml"
    lane_path.write_text(
        re.sub(r"(?m)^delivery_policy\s*=.*\n", "", lane_path.read_text())
    )
    git(home, "init", "-q", "-b", "main")
    git(home, "add", "governance/lanes/implement.toml")
    git(
        home,
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "legacy policy",
    )
    old = load_lane("implement")
    aid = item + "-a1"
    log.append("release.published", {"release_id": item, "revision": 1}, item_id=item)
    log.append(
        "item.claimed",
        {
            "attempt_id": aid,
            "lane": "implement",
            "model": "scripted/model",
            "worker": "scripted",
            "release_revision": 1,
            "lane_revision": old.revision,
            "lane_digest": old.digest,
            "base_sha": "a" * 40,
        },
        item_id=item,
    )
    log.append(
        "attempt.finished",
        {"attempt_id": aid, "outcome": "done", "exit_code": 0, "head_sha": "b" * 40},
        item_id=item,
    )
    log.append(
        "gate.result",
        {
            "attempt_id": aid,
            "gate": "acceptance",
            "passed": False,
            "violations": ["synthetic failure"],
        },
        item_id=item,
    )
    lane_path.write_text(
        lane_path.read_text()
        .replace("[routing]", '[routing]\ndelivery_policy = "review-progress"')
        .replace("max_attempts = 2", "max_attempts = 1")
    )
    assert reap(
        log,
        now=datetime.now(timezone.utc) + timedelta(days=1),
        older_than_s=60,
        max_attempts=1,
    ) == [aid]
    view = project_items(log.read())[item]
    assert view.state == "requeued"
    assert len(view.attempts) == 1 and view.attempts[0]["decision"] == "rejected"
    assert any(
        "synthetic failure" in str(e["data"])
        for e in log.read()
        if e["type"] == "decision.recorded"
    )


def test_legacy_unknown_provenance_is_not_reinterpreted(estate):
    from datetime import datetime, timedelta, timezone
    from lanectl.reap import reap
    from tests.seed.test_end_to_end import SUB_TEST

    _, release, log = prospective(estate)
    item = "synthetic-unknown"
    release(item, SUB_TEST)
    log.append("release.published", {"release_id": item, "revision": 1}, item_id=item)
    log.append(
        "item.claimed",
        {
            "attempt_id": item + "-a1",
            "lane": "implement",
            "model": "scripted/model",
            "worker": "scripted",
            "release_revision": 1,
            "lane_revision": 3,
            "lane_digest": "sha256:0000000000000000",
        },
        item_id=item,
    )
    before = log.read()
    assert (
        reap(
            log,
            now=datetime.now(timezone.utc) + timedelta(days=1),
            older_than_s=60,
            max_attempts=1,
        )
        == []
    )
    assert log.read() == before


def test_prospective_worker_deadline_does_not_become_success(estate):
    import sys
    from lanectl import runner
    from lanectl.adapters import AdapterResult
    from lanectl.child_process import communicate
    from lanectl.events import project_items
    from tests.seed.test_end_to_end import SUB_TEST

    _, release, log = prospective(estate)
    item = "synthetic-deadline"
    release(item, SUB_TEST)
    claim = runner.admit("implement", log)
    assert not isinstance(claim, str), claim

    def deadline_worker(*, worktree, **_):
        (worktree / "src/calc.py").write_text("def sub(a, b):\n    return 999\n")
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _, _, stopped = communicate(child, 0.05)
        assert stopped == "timeout" and child.poll() is not None
        return AdapterResult("failed", 124, "deadline elapsed", None)

    result = runner.execute(claim, log, adapter_fn=deadline_worker)
    assert "candidate" not in result, result
    assert project_items(log.read())[item].state != "candidate"
    finishes = [
        e["data"]
        for e in log.read()
        if e["type"] == "attempt.finished"
        and e["data"]["attempt_id"] == claim.attempt_id
    ]
    assert len(finishes) == 1 and finishes[0]["exit_code"] == 124


def test_conflicting_claim_binding_cannot_override_publication(estate):
    import copy
    from datetime import datetime, timedelta, timezone
    from lanectl import runner
    from lanectl.reap import reap
    from tests.seed.test_end_to_end import SUB_TEST

    _, release, log = prospective(estate)
    item = "synthetic-conflict"
    release(item, SUB_TEST)
    runner.sync_releases(
        log, __import__("lanectl.config", fromlist=["load_releases"]).load_releases()
    )
    publication = next(
        e["data"]["effective_policy"]
        for e in log.read()
        if e["type"] == "release.published" and e["item_id"] == item
    )
    forged = copy.deepcopy(publication)
    forged["lane"]["delivery_policy"] = "legacy"
    forged["lane"]["max_attempts"] = 2
    aid = item + "-a1"
    log.append(
        "item.claimed",
        {
            "attempt_id": aid,
            "lane": "implement",
            "model": "scripted/model",
            "worker": "scripted",
            "release_revision": 1,
            "effective_policy": forged,
        },
        item_id=item,
    )
    before = log.read()
    assert (
        reap(
            log,
            now=datetime.now(timezone.utc) + timedelta(days=1),
            older_than_s=60,
            max_attempts=2,
        )
        == []
    )
    assert log.read() == before


@pytest.mark.parametrize("finished", [False, True])
def test_legacy_consumers_follow_each_claims_retained_policy(estate, tmp_path, finished):
    """Independent consumer oracle: later legacy claims may have different limits."""
    import os
    import re
    from datetime import datetime, timedelta, timezone
    from pathlib import Path

    from lanectl.config import load_lane
    from lanectl.events import EventLog, project_items
    from lanectl.reap import reap
    from tests.seed.test_end_to_end import SUB_TEST

    repo, release, log = estate
    item = "synthetic-two-policies"
    release(item, SUB_TEST)
    home = Path(os.environ["LANECTL_HOME"])
    lane_file = home / "governance/lanes/implement.toml"
    original = lane_file.read_text()
    git(home, "init", "-q", "-b", "main")
    lanes = []
    for revision, budget, attempts in ((2, 250, 2), (3, 500, 3)):
        text = re.sub(r"(?m)^revision = .*$", f"revision = {revision}", original)
        text = re.sub(r"(?m)^max_attempts = .*$", f"max_attempts = {attempts}", text)
        lane_file.write_text(text.replace("S = 250", f"S = {budget}"))
        git(home, "add", "governance/lanes/implement.toml")
        git(home, "-c", "user.name=test", "-c", "user.email=test@example.invalid",
            "commit", "-qm", str(revision))
        lanes.append(load_lane("implement"))
    assert lanes[0].digest != lanes[1].digest
    seed = git(repo, "rev-parse", "HEAD")
    (repo / "src/synthetic.py").write_text("x = 1\n" * 400)
    git(repo, "add", "src/synthetic.py")
    git(repo, "-c", "user.name=test", "-c", "user.email=test@example.invalid",
        "commit", "-qm", "synthetic diff")
    head = git(repo, "rev-parse", "HEAD")
    log.append("release.published", {"release_id": item, "revision": 1}, item_id=item)
    for number, lane in enumerate(lanes, 1):
        aid = f"{item}-a{number}"
        log.append("item.claimed", {
            "attempt_id": aid, "lane": "implement", "model": "scripted/model",
            "worker": "scripted", "release_revision": 1, "lane_revision": lane.revision,
            "lane_digest": lane.digest, "base_sha": seed,
        }, item_id=item)
        if number == 1 or finished:
            log.append("attempt.finished", {"attempt_id": aid, "outcome": "done",
                "exit_code": 0, "head_sha": head}, item_id=item)
            log.append("gate.result", {"attempt_id": aid, "gate": "acceptance",
                "passed": False, "violations": ["synthetic failure"]}, item_id=item)
        if number == 1:
            log.append("decision.recorded", {"attempt_id": aid, "decision": "rejected",
                "reasons": ["synthetic failure"], "rules_revision": "test"}, item_id=item)
            log.append("item.requeued", {"reason": "synthetic failure"}, item_id=item)
    before_reap = log.read()
    assert reap(log, now=datetime.now(timezone.utc) + timedelta(days=1),
                older_than_s=60, max_attempts=999) == [aid]
    assert project_items(log.read())[item].state == "requeued"

    evaluation_log = EventLog(tmp_path / "evaluation.jsonl")
    for event in before_reap:
        evaluation_log.append(event["type"], event["data"], item_id=event.get("item_id"))
    if not finished:
        evaluation_log.append("attempt.finished", {"attempt_id": aid, "outcome": "done",
            "exit_code": 0, "head_sha": head}, item_id=item)
    rules = {"revision": 1, "default": "accept", "rules": [{"name": "size",
        "feature": "changed_lines_ratio", "op": ">", "value": 1, "verdict": "reject"}]}
    result = evaluator.evaluate_attempt(evaluation_log, aid, rules)
    assert result["features"]["changed_lines_ratio"] == 0.8
    assert result["verdict"] == "accept"


def test_omitting_daily_claim_quota_unblocks_work_published_with_old_quota(estate):
    import os
    from pathlib import Path
    from lanectl import runner
    from tests.seed.test_end_to_end import SUB_TEST

    _, release, log = prospective(estate)
    path = Path(os.environ["LANECTL_HOME"]) / "governance/lanes/implement.toml"
    lines = path.read_text().splitlines(keepends=True)
    old = "".join("items_per_day = 1\n" if line.startswith("items_per_day") else line
                  for line in lines)
    path.write_text(old)
    release("first-daily-claim", SUB_TEST)
    release("second-daily-claim", SUB_TEST)
    first = runner.admit("implement", log, only="first-daily-claim")
    assert not isinstance(first, str), first
    blocked = runner.admit("implement", log, only="second-daily-claim")
    assert "items_per_day 1/1" in blocked
    path.write_text("".join(line for line in lines if not line.startswith("items_per_day")))
    second = runner.admit("implement", log, only="second-daily-claim")
    assert not isinstance(second, str), second
