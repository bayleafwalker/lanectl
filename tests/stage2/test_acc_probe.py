"""Acceptance: OpenCode stats probe and ledger drift (planner-owned; sample is real output)."""
STATS = '''{"range": {"from": 1794088800000, "to": 1794161457152}, "sessions": 37, "subagents": 0,
 "prompts": 36, "steps": 691, "tokens": {"input": 1418156, "output": 192154, "reasoning": 300896,
 "cache": {"read": 23329012, "write": 0}}, "cost": 0, "tools": {"mode": "detail"}}'''

from lanectl.contracts import make_event, validate_event
from lanectl.probe import drift, probe_opencode


def _usage(n, ts, provider="opencode"):
    e = make_event("usage.recorded", {"attempt_id": "it-1-a1", "model": "opencode-go/deepseek-v4.1-flash",
                                      "provider": provider, "source": "adapter",
                                      "units": {"output_tokens": n, "input_tokens": 1}}, item_id="it-1")
    e["ts"] = ts
    return e


def test_probe_payload_from_stats_json():
    calls = []
    p = probe_opencode(lambda argv: calls.append(argv) or STATS)
    assert calls == [["opencode", "stats", "--days", "0", "--json"]]
    assert p["provider"] == "opencode" and p["window"] == "day"
    o = p["observed"]
    assert o["source"] == "opencode-stats"
    assert (o["output_tokens"], o["input_tokens"], o["reasoning_tokens"], o["cache_read_tokens"], o["sessions"]) \
        == (192154, 1418156, 300896, 23329012, 37)
    assert o["range_from"] == "2026-11-07T22:00:00Z" and o["range_to"] == "2026-11-08T18:10:57Z"
    validate_event({**make_event("window.observed", p)})


def test_drift_counts_ledger_inside_probe_range():
    p = probe_opencode(lambda argv: STATS)
    obs = make_event("window.observed", p)
    obs["ts"] = "2026-11-08T18:11:00Z"
    ev = [_usage(100000, "2026-11-08T10:00:00Z"), _usage(2154, "2026-11-08T17:00:00Z"),
          _usage(5, "2026-11-07T21:59:59Z"), _usage(7, "2026-11-08T12:00:00Z", provider="anthropic"), obs]
    d = drift(ev)
    assert (d["probe"], d["ledger"], d["unrecorded"]) == (192154, 102154, 90000)


def test_no_probe_no_drift():
    assert drift([_usage(1, "2026-11-08T10:00:00Z")]) is None
