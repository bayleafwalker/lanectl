"""Acceptance: provider window exhaustion detected from attempt failures (planner-owned)."""

from lanectl.contracts import make_event


def claimed(aid, model="opencode-go/deepseek-v4.1-flash", ts="2026-11-08T11:55:00Z"):
    item = aid.rsplit("-a", 1)[0]
    e = make_event("item.claimed", {"attempt_id": aid, "base_sha": "a" * 40, "branch": f"lane/{aid}",
                                    "lane": "implement", "lane_digest": "sha256:x", "lane_revision": 2,
                                    "model": model, "release_revision": 1, "worker": "opencode"}, item_id=item)
    e["ts"] = ts
    return e


def finished(aid, tail, outcome="failed", ts="2026-11-08T12:00:00Z", exit_code=1):
    item = aid.rsplit("-a", 1)[0]
    e = make_event("attempt.finished", {"attempt_id": aid, "elapsed_s": 3.0, "escalation_reason": None,
                                        "exit_code": exit_code, "final_tail": tail, "head_sha": "b" * 40,
                                        "isolation_breach": False, "main_changed": False, "outcome": outcome,
                                        "seed_sha": "c" * 40}, item_id=item)
    e["ts"] = ts
    return e

from lanectl import cli
from lanectl.events import EventLog
from lanectl.windows import detect


def _one(tail, **kw):
    return detect([claimed("it-1-a1", **{k: v for k, v in kw.items() if k == "model"}),
                   finished("it-1-a1", tail, **{k: v for k, v in kw.items() if k != "model"})])


def test_reset_timestamp_is_parsed():
    obs = _one("Error: 429 Too Many Requests: usage limit reached, resets at 2026-11-08T15:00:00Z")
    assert obs == [{"provider": "opencode", "window": "5h",
                    "observed": {"attempt_id": "it-1-a1", "exhausted_at": "2026-11-08T12:00:00Z",
                                 "reset_at": "2026-11-08T15:00:00Z"}}]


def test_relative_resets():
    assert _one("rate limit exceeded; try again in 90 minutes")[0]["observed"]["reset_at"] == "2026-11-08T13:30:00Z"
    assert _one("Rate Limited. Retry after 3600 seconds")[0]["observed"]["reset_at"] == "2026-11-08T13:00:00Z"
    assert _one("quota exhausted for this plan")[0]["observed"]["reset_at"] is None


def test_provider_follows_model():
    obs = _one("429 rate limit", model="claude-sonnet-5-5")
    assert obs[0]["provider"] == "anthropic"


def test_non_exhaustion_and_successes_are_ignored():
    assert _one("E   AssertionError: assert 1 == 2") == []
    assert _one("handled the rate limit case in the parser", outcome="done", exit_code=0) == []


def test_recorded_attempts_are_not_detected_again(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LANECTL_STATE", str(tmp_path))
    log = EventLog()
    for e in [claimed("it-1-a1"), finished("it-1-a1", "usage limit reached")]:
        log.append(e["type"], e["data"], item_id=e["item_id"])
    assert cli.main(["windows", "--record"]) == 0
    assert cli.main(["windows", "--record"]) == 0
    assert [e["type"] for e in log.read()].count("window.observed") == 1
    assert detect(log.read()) == []
