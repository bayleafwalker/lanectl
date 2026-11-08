"""Window exhaustion detection: tolerant parsing and record idempotency."""
from lanectl import cli
from lanectl.contracts import make_event
from lanectl.events import EventLog
from lanectl.windows import detect, provider_for, reset_at


def claimed(aid, model="opencode-go/deepseek-v4.1-flash", ts="2026-11-08T11:55:00Z"):
    e = make_event("item.claimed", {"attempt_id": aid, "base_sha": "a" * 40, "branch": f"lane/{aid}",
                                    "lane": "implement", "lane_digest": "sha256:x", "lane_revision": 2,
                                    "model": model, "release_revision": 1, "worker": "opencode"},
                   item_id=aid.rsplit("-a", 1)[0])
    e["ts"] = ts
    return e


def finished(aid, tail, outcome="failed", ts="2026-11-08T12:00:00Z", exit_code=1):
    e = make_event("attempt.finished", {"attempt_id": aid, "elapsed_s": 3.0, "escalation_reason": None,
                                        "exit_code": exit_code, "final_tail": tail, "head_sha": "b" * 40,
                                        "isolation_breach": False, "main_changed": False,
                                        "outcome": outcome, "seed_sha": "c" * 40},
                   item_id=aid.rsplit("-a", 1)[0])
    e["ts"] = ts
    return e


def test_provider_mapping_is_tolerant_of_unknown_models():
    assert provider_for("opencode-go/anything") == "opencode"
    assert provider_for("claude-opus-9") == "anthropic"
    assert provider_for("gpt-5") is None
    assert provider_for(None) is None


def test_escalated_attempts_are_detected_too():
    obs = detect([claimed("it-1-a1"), finished("it-1-a1", "Provider quota exceeded", outcome="escalated",
                                               exit_code=0)])
    assert obs == [{"provider": "opencode", "window": "5h",
                    "observed": {"attempt_id": "it-1-a1",
                                 "exhausted_at": "2026-11-08T12:00:00Z", "reset_at": None}}]


def test_reset_parsing_variants():
    ts = "2026-11-08T12:00:00Z"
    assert reset_at("resets at 2026-11-08T15:00:00Z", ts) == "2026-11-08T15:00:00Z"
    assert reset_at("RESET AT 2026-11-08T15:00:00+00:00", ts) == "2026-11-08T15:00:00Z"
    assert reset_at("try again in 2 hours", ts) == "2026-11-08T14:00:00Z"
    assert reset_at("retry after 30 seconds", ts) == "2026-11-08T12:00:30Z"
    assert reset_at("nothing to see here", ts) is None


def test_unknown_provider_is_ignored():
    assert detect([claimed("it-1-a1", model="gpt-5"), finished("it-1-a1", "429 rate limit")]) == []


def test_unmatched_attempt_without_claim_is_ignored():
    assert detect([finished("it-1-a1", "429 rate limit")]) == []


def test_windows_command_prints_and_records(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LANECTL_STATE", str(tmp_path))
    log = EventLog()
    for e in [claimed("it-1-a1"), finished("it-1-a1", "usage limit reached, resets at 2026-11-08T15:00:00Z")]:
        log.append(e["type"], e["data"], item_id=e["item_id"])
    assert cli.main(["windows"]) == 0
    assert "it-1-a1" in capsys.readouterr().out
    assert not [e for e in log.read() if e["type"] == "window.observed"]
    assert cli.main(["windows", "--record"]) == 0
    recorded = [e for e in log.read() if e["type"] == "window.observed"]
    assert len(recorded) == 1
    assert recorded[0]["data"]["observed"]["reset_at"] == "2026-11-08T15:00:00Z"
