"""Extra coverage for the Stop-hook usage recorder: cursors, edge cases, CLI."""
import io
import json
import time

from lanectl import cli
from lanectl.events import EventLog
from lanectl.usage_hook import handle_hook


def _msg(mid, inp, out, cr=0, cw=0, model="claude-opus-5-5"):
    return {"type": "assistant", "message": {"id": mid, "model": model, "usage": {
        "input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": cr,
        "cache_creation_input_tokens": cw}}}


def _transcript(tmp_path, lines):
    path = tmp_path / "t.jsonl"
    path.write_text("".join(json.dumps(x) + "\n" for x in lines))
    return path


def _payload(path, session="sess-1"):
    return io.StringIO(json.dumps(
        {"session_id": session, "transcript_path": str(path), "hook_event_name": "Stop"}))


def _events(log):
    return [e for e in log.read() if e["type"] == "usage.recorded"]


def test_cursor_is_scoped_to_the_log_state_dir(tmp_path):
    # Two event logs must not share a cursor even for the same session id.
    tr = _transcript(tmp_path, [_msg("m1", 10, 5)])
    a = EventLog(tmp_path / "a" / "events.jsonl")
    b = EventLog(tmp_path / "b" / "events.jsonl")

    assert handle_hook(_payload(tr), a) == 0
    assert handle_hook(_payload(tr), b) == 0
    assert len(_events(a)) == 1
    assert len(_events(b)) == 1
    assert _events(b)[0]["data"]["units"]["input_tokens"] == 10


def test_truncated_transcript_is_reread_without_double_counting(tmp_path):
    tr = _transcript(tmp_path, [_msg("m1", 10, 5), _msg("m2", 20, 8)])
    log = EventLog(tmp_path / "state" / "events.jsonl")
    handle_hook(_payload(tr), log)

    # A replaced/shortened transcript resets the offset; seen ids still dedupe.
    tr.write_text(json.dumps(_msg("m1", 10, 5)) + "\n")
    handle_hook(_payload(tr), log)
    assert len(_events(log)) == 1

    with open(tr, "a") as fh:
        fh.write(json.dumps(_msg("m3", 3, 4)) + "\n")
    handle_hook(_payload(tr), log)
    evs = _events(log)
    assert len(evs) == 2
    assert evs[1]["data"]["units"] == {"input_tokens": 3, "output_tokens": 4,
                                       "cache_read_tokens": 0, "cache_write_tokens": 0,
                                       "messages": 1}


def test_final_line_without_newline_is_consumed_once(tmp_path):
    tr = tmp_path / "t.jsonl"
    tr.write_text(json.dumps(_msg("m1", 1, 2)))
    log = EventLog(tmp_path / "state" / "events.jsonl")

    handle_hook(_payload(tr), log)
    handle_hook(_payload(tr), log)
    assert len(_events(log)) == 1

    with open(tr, "a") as fh:
        fh.write("\n" + json.dumps(_msg("m2", 3, 4)) + "\n")
    handle_hook(_payload(tr), log)
    evs = _events(log)
    assert len(evs) == 2 and evs[1]["data"]["units"]["output_tokens"] == 4


def test_noise_missing_usage_and_missing_ids_are_ignored(tmp_path):
    tr = tmp_path / "t.jsonl"
    tr.write_text("\n".join([
        "not json at all",
        json.dumps({"type": "user", "message": {"content": "hi"}}),
        json.dumps({"type": "assistant", "message": {"id": "no-usage"}}),
        json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 9}}}),
        json.dumps(_msg("ok", 2, 3)),
    ]) + "\n")
    log = EventLog(tmp_path / "state" / "events.jsonl")

    assert handle_hook(_payload(tr), log) == 0
    evs = _events(log)
    assert len(evs) == 1
    assert evs[0]["data"]["units"]["input_tokens"] == 2
    assert evs[0]["data"]["units"]["messages"] == 1


def test_model_is_the_dominant_new_model(tmp_path):
    tr = _transcript(tmp_path, [
        _msg("a", 1, 1, model="claude-opus-5-5"),
        _msg("b", 1, 1, model="claude-haiku-5-5"),
        _msg("c", 1, 1, model="claude-opus-5-5"),
    ])
    log = EventLog(tmp_path / "state" / "events.jsonl")
    handle_hook(_payload(tr), log)
    assert _events(log)[0]["data"]["model"] == "claude-opus-5-5"


def test_cli_records_usage_from_stdin(tmp_path, monkeypatch):
    tr = _transcript(tmp_path, [_msg("m1", 7, 3)])
    monkeypatch.setenv("LANECTL_STATE", str(tmp_path / "state"))
    monkeypatch.setattr("sys.stdin", _payload(tr, session="cli-sess"))

    assert cli.main(["hook", "usage"]) == 0
    evs = _events(EventLog())
    assert len(evs) == 1
    assert evs[0]["data"]["session_id"] == "cli-sess"
    assert evs[0]["data"]["source"] == "claude-code-interactive"


def test_second_run_over_a_ten_megabyte_transcript_is_fast(tmp_path):
    tr = tmp_path / "big.jsonl"
    template = ('{"type":"assistant","message":{"id":"m%07d","model":"claude-opus-5-5",'
                '"usage":{"input_tokens":1,"output_tokens":2,'
                '"cache_read_input_tokens":3,"cache_creation_input_tokens":4}}}')
    with open(tr, "w") as fh:
        written, n = 0, 0
        while written < 10 * 1024 * 1024:
            line = template % n + "\n"
            fh.write(line)
            written += len(line)
            n += 1

    log = EventLog(tmp_path / "state" / "events.jsonl")
    payload = _payload(tr, session="big")
    assert handle_hook(payload, log) == 0
    assert len(_events(log)) == 1

    started = time.monotonic()
    assert handle_hook(_payload(tr, session="big"), log) == 0
    elapsed = time.monotonic() - started
    assert len(_events(log)) == 1
    assert elapsed < 0.5, f"incremental run took {elapsed:.3f}s"
