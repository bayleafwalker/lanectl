"""The probe command plugin: latest-probe selection, boundaries and recording."""
import argparse
import json

from lanectl import probe
from lanectl.contracts import make_event
from lanectl.events import EventLog

STATS = json.dumps({
    "range": {"from": 1794088800000, "to": 1794161457152}, "sessions": 3,
    "tokens": {"input": 10, "output": 100, "reasoning": 5,
               "cache": {"read": 7, "write": 0}},
})


def _usage(n, ts, provider="opencode", units=None):
    e = make_event("usage.recorded", {"provider": provider, "source": "adapter",
                                      "units": units or {"output_tokens": n}})
    e["ts"] = ts
    return e


def _observed(payload, ts):
    e = make_event("window.observed", payload)
    e["ts"] = ts
    return e


def test_drift_range_bounds_are_inclusive():
    p = probe.probe_opencode(lambda argv: STATS)
    events = [
        _observed(p, "2026-11-08T19:00:00Z"),
        _usage(4, "2026-11-07T22:00:00Z"),   # exactly range_from
        _usage(6, "2026-11-08T18:10:57Z"),   # exactly range_to
        _usage(9, "2026-11-07T21:59:59Z"),   # just before
        _usage(8, "2026-11-08T18:10:58Z"),   # just after
    ]
    assert probe.drift(events)["ledger"] == 10


def test_drift_uses_the_latest_probe():
    old = probe.probe_opencode(lambda argv: STATS)
    old["observed"]["output_tokens"] = 999
    recent = probe.probe_opencode(lambda argv: STATS)
    recent["observed"]["output_tokens"] = 50
    recent["observed"]["range_from"] = "2026-11-08T12:00:00Z"
    events = [
        _observed(old, "2026-11-08T01:00:00Z"),
        _observed(recent, "2026-11-08T18:11:00Z"),
        _usage(40, "2026-11-08T13:00:00Z"),
        _usage(70, "2026-11-08T10:00:00Z"),   # inside the old range only
    ]
    d = probe.drift(events)
    assert (d["probe"], d["ledger"], d["unrecorded"]) == (50, 40, 10)
    assert d["range_from"] == "2026-11-08T12:00:00Z"


def test_probe_defaults_missing_counters_to_zero():
    payload = probe.probe_opencode(lambda argv: json.dumps(
        {"range": {"from": 0, "to": 1000}}))
    o = payload["observed"]
    assert o["range_from"] == "1970-01-01T00:00:00Z"
    assert o["range_to"] == "1970-01-01T00:00:01Z"
    assert (o["output_tokens"], o["input_tokens"], o["sessions"]) == (0, 0, 0)


def test_register_wires_the_probe_command():
    parser = argparse.ArgumentParser()
    handlers = probe.register(parser.add_subparsers(dest="cmd", required=True))
    args = parser.parse_args(["probe", "opencode", "--record"])
    assert handlers.keys() == {"probe"}
    assert args.target == "opencode" and args.record is True


def test_cmd_records_the_observed_window(tmp_path, capsys, monkeypatch):
    log = EventLog(tmp_path / "events.jsonl")
    monkeypatch.setattr(probe, "_real_run", lambda argv: STATS)
    rc = probe._cmd(argparse.Namespace(target="opencode", record=True), log)
    out = capsys.readouterr().out
    assert rc == 0
    recorded = [e for e in log.read() if e["type"] == "window.observed"]
    assert len(recorded) == 1
    assert recorded[0]["data"]["observed"]["output_tokens"] == 100
    assert '"unrecorded": 100' in out
