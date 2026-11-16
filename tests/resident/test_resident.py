"""Resident episodes are bounded work, never a pretend persistent native Goal."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from lanectl import resident
from lanectl.contracts import ContractError, make_event
from lanectl.events import EventLog


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True))
    return path


def packet_bytes(**changes):
    packet = {"schema": "resident-context/v1", "status": "ready", "authorizes_effects": False,
              "scope": {"resident": "writer-one", "project": "stories", "branch": "canon"},
              "budget": {"max_bytes": 65536, "max_tokens": None, "token_measurement": "not-measured"},
              "source_refs": [], "blockers": [], "omissions": [],
              "sections": [{"kind": name, "items": []} for name in
                           ("instructions", "current_work", "required_sources", "orientation", "memories", "worker_outputs")]}
    packet["sections"][0]["items"] = [{"id": "instructions", "content": "Write within the admitted scope."}]
    packet["sections"][1]["items"] = [{"id": "current_work", "content": {"next_action": "draft the story"}}]
    packet.update(changes)
    canonical = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"),
                                         ensure_ascii=False, allow_nan=False).encode()
    packet["digest"] = digest(canonical(packet))
    return canonical(packet)


SCRIPT = '''import json, os, pathlib, sys
root = pathlib.Path.cwd()
context = sys.stdin.buffer.read()
(root / "drafts").mkdir(exist_ok=True)
(root / "drafts/story.txt").write_text("A bridge and a rumour.\\n")
result = {"schema": "lanectl.resident-result/v1", "episode_id": os.environ["LANECTL_RESIDENT_EPISODE"],
          "generation": int(os.environ["LANECTL_RESIDENT_GENERATION"]), "stop_reason": "completed",
          "artifacts": ["drafts/story.txt"], "continuation": {"next": "Ask the witness"}}
pathlib.Path(os.environ["LANECTL_RESIDENT_RESULT"]).write_text(json.dumps(result))
'''


@pytest.fixture
def setup(tmp_path, monkeypatch):
    # Real child execution; only file ownership is emulated because tests run
    # unprivileged. Production requires root-protected profile/qualification.
    monkeypatch.setattr(resident, "_protected_file", lambda path: None)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state = tmp_path / "state"
    profile = tmp_path / "profile.json"
    qualification = tmp_path / "qualification.json"
    packet = tmp_path / "context.json"
    packet.write_bytes(packet_bytes())
    log = EventLog(tmp_path / "events.jsonl")

    def configure(*, script=SCRIPT, enabled=True, timeout=3, roots=None, require_recheck=False):
        raw = {"schema": "lanectl.resident-profile/v1", "resident_id": "writer-one",
               "workspace": str(workspace), "state_dir": str(state),
               "artifact_roots": roots or ["drafts"],
               "require_source_recheck": require_recheck,
               "execution": {"enabled": enabled, "route": "local-fixture",
                             "argv": [sys.executable, "-c", script], "timeout_s": timeout,
                             "executable_sha256": digest(Path(sys.executable).resolve().read_bytes()),
                             "qualification_file": str(qualification)}}
        write_json(profile, raw)
        qualification_record = {
            "schema": "lanectl.resident-qualification/v1",
            "recipe_sha256": resident.describe_profile(profile)["recipe_sha256"],
            "valid_until": "2099-01-01T00:00:00Z", "provider_credentials_isolated": True,
            "execution_boundary_enforced": True, "budget_enforced": True,
            "source_recheck_enforced": True,
        }
        write_json(qualification, qualification_record)
        raw["execution"]["qualification_sha256"] = digest(qualification.read_bytes())
        write_json(profile, raw)
        return raw

    configure()
    return {"workspace": workspace, "state": state, "profile": profile,
            "qualification": qualification, "packet": packet, "log": log,
            "configure": configure}


def run(s, wake="wake-01", generation=1, **kwargs):
    return resident.run_episode(s["log"], profile_path=s["profile"], wake_id=wake,
                                generation=generation, context_path=s["packet"],
                                context_sha256=digest(s["packet"].read_bytes()),
                                work_ref="stories#1", **kwargs)


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.02)
    raise AssertionError("condition not observed before deadline")


def test_disabled_is_default_and_never_launches(setup):
    raw = json.loads(setup["profile"].read_text())
    raw.pop("execution")
    write_json(setup["profile"], raw)
    receipt = run(setup)
    assert receipt["status"] == "refused"
    assert receipt["stop_reason"] == "execution_disabled"
    assert not (setup["workspace"] / "drafts").exists()


def test_real_child_checkpoint_contains_exact_bytes_and_provenance(setup):
    receipt = run(setup)
    assert receipt["outcome"] == "done"
    checkpoint_bytes = Path(receipt["checkpoint_path"]).read_bytes()
    assert digest(checkpoint_bytes) == receipt["checkpoint_sha256"]
    checkpoint = json.loads(checkpoint_bytes)
    assert checkpoint["context_sha256"] == digest(setup["packet"].read_bytes())
    assert checkpoint["work_ref"] == "stories#1"
    assert checkpoint["continuation"] == {"next": "Ask the witness"}
    artifact = checkpoint["artifacts"][0]
    assert artifact["path"] == "drafts/story.txt"
    assert Path(artifact["snapshot_path"]).read_bytes() == b"A bridge and a rumour.\n"
    assert artifact["sha256"] == digest(Path(artifact["snapshot_path"]).read_bytes())
    assert resident.status(setup["log"], setup["profile"])["active"] == []


def test_duplicate_wake_returns_original_episode_without_reexecution(setup):
    first = run(setup)
    (setup["workspace"] / "drafts/story.txt").write_text("manually revised")
    second = run(setup)
    assert second["status"] == "duplicate"
    assert second["episode_id"] == first["episode_id"]
    assert second["checkpoint_sha256"] == first["checkpoint_sha256"]
    assert (setup["workspace"] / "drafts/story.txt").read_text() == "manually revised"
    assert len([e for e in setup["log"].read() if e["type"] == "resident.episode.started"]) == 1
    assert setup["log"].read()[-1]["data"]["status"] == "duplicate"


def test_reused_wake_with_changed_context_is_a_conflict(setup):
    run(setup)
    packet = json.loads(packet_bytes())
    packet["sections"][1]["items"][0]["content"] = {"next_action": "different task"}
    packet.pop("digest")
    setup["packet"].write_bytes(packet_bytes(**packet))
    with pytest.raises(resident.ResidentError, match="wake.*conflict"):
        run(setup)


def test_context_digest_mismatch_cannot_start_child(setup):
    with pytest.raises(resident.ResidentError, match="context.*digest"):
        resident.run_episode(setup["log"], profile_path=setup["profile"], wake_id="wake-01",
                             generation=1, context_path=setup["packet"], context_sha256="0" * 64)
    assert not (setup["workspace"] / "drafts").exists()


@pytest.mark.parametrize("changes", [
    {"schema": "unrecognized/v1"}, {"status": "blocked"}, {"authorizes_effects": True},
    {"scope": {"resident": "other", "project": "stories", "branch": "canon"}},
    {"budget": {"max_bytes": 1}}, {"blockers": ["missing source"]},
])
def test_context_envelope_is_not_just_an_arbitrary_file_hash(setup, changes):
    setup["packet"].write_bytes(packet_bytes(**changes))
    with pytest.raises(resident.ResidentError, match="context"):
        run(setup)
    assert not (setup["workspace"] / "drafts").exists()


def test_context_internal_digest_is_verified_separately_from_file_sha(setup):
    packet = json.loads(setup["packet"].read_bytes())
    packet["digest"] = "0" * 64
    write_json(setup["packet"], packet)
    with pytest.raises(resident.ResidentError, match="context.*digest"):
        run(setup)


def test_context_source_union_cannot_be_forged(setup):
    packet = json.loads(packet_bytes())
    packet["sections"][2]["items"] = [{"id": "canon", "content": "bridge collapsed", "status": "current", "source_refs": [
        {"source_id": "canon", "revision": "r1", "sha256": "1" * 64}]}]
    packet.pop("digest")
    setup["packet"].write_bytes(packet_bytes(**packet))
    with pytest.raises(resident.ResidentError, match="context.*source"):
        run(setup)


def test_unscoped_memory_cannot_be_smuggled_inside_an_otherwise_valid_packet(setup):
    packet = json.loads(packet_bytes())
    ref = {"source_id": "canon", "revision": "r1", "sha256": "1" * 64}
    packet["sections"][4]["items"] = [{"id": "memo", "content": "historical observation",
                                       "status": "current", "source_refs": [ref]}]
    packet["source_refs"] = [ref]
    packet.pop("digest")
    setup["packet"].write_bytes(packet_bytes(**packet))
    with pytest.raises(resident.ResidentError, match="context.*scope"):
        run(setup)


def test_context_duplicate_json_keys_are_refused(setup):
    data = setup["packet"].read_bytes()
    setup["packet"].write_bytes(data.replace(b'"authorizes_effects":false',
        b'"authorizes_effects":true,"authorizes_effects":false'))
    with pytest.raises(resident.ResidentError, match="context.*duplicate"):
        run(setup)


def test_context_sections_cannot_be_duplicated(setup):
    packet = json.loads(packet_bytes())
    packet["sections"][2]["kind"] = "instructions"
    packet.pop("digest")
    setup["packet"].write_bytes(packet_bytes(**packet))
    with pytest.raises(resident.ResidentError, match="context.*section"):
        run(setup)


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(extra="unrecognized"),
    lambda p: p["sections"][0].update(extra="unrecognized"),
    lambda p: p["sections"][0]["items"][0].update(extra="unrecognized"),
    lambda p: p["sections"][0]["items"][0].update(id="other"),
    lambda p: p["sections"][0]["items"][0].update(content=""),
    lambda p: p["sections"][1]["items"][0].update(content={}),
    lambda p: p["sections"][3].update(items=[{"id": "orientation", "content": "one"},
                                           {"id": "other", "content": "two"}]),
    lambda p: p["budget"].pop("max_tokens"),
    lambda p: p["budget"].update(token_measurement="claimed"),
    lambda p: p.update(omissions=[{"section": "current_work", "id": "current_work", "reason": "budget"}]),
    lambda p: p.update(omissions=[{"section": "memories", "id": "memo", "reason": "unsupported"}]),
])
def test_context_requires_the_actual_mandatory_and_diagnostic_schema(setup, mutate):
    packet = json.loads(packet_bytes())
    mutate(packet)
    packet.pop("digest")
    setup["packet"].write_bytes(packet_bytes(**packet))
    with pytest.raises(resident.ResidentError, match="context"):
        run(setup)
    assert not (setup["workspace"] / "drafts").exists()


def test_required_source_recheck_must_be_fresh_and_bound(setup):
    setup["configure"](require_recheck=True)
    with pytest.raises(resident.ResidentError, match="source.recheck"):
        run(setup)
    now = datetime.now(timezone.utc)
    q = {"schema": "resident-context-recheck/v1", "status": "unchanged", "authorizes_effects": False,
         "context_digest": json.loads(setup["packet"].read_bytes())["digest"],
         "context_sha256": digest(setup["packet"].read_bytes()), "generation": 1,
         "checked_at": now.isoformat(), "valid_until": (now + timedelta(seconds=30)).isoformat()}
    path = setup["profile"].parent / "recheck.json"
    write_json(path, q)
    receipt = run(setup, source_recheck_path=path, source_recheck_sha256=digest(path.read_bytes()))
    assert receipt["outcome"] == "done"
    checkpoint = json.loads(Path(receipt["checkpoint_path"]).read_bytes())
    assert checkpoint["source_recheck_sha256"] == digest(path.read_bytes())
    q["valid_until"] = (now - timedelta(seconds=1)).isoformat()
    write_json(path, q)
    with pytest.raises(resident.ResidentError, match="source.recheck.*fresh"):
        run(setup, wake="wake-02", source_recheck_path=path,
            source_recheck_sha256=digest(path.read_bytes()))


def test_source_recheck_cannot_claim_an_unbounded_freshness_window(setup):
    setup["configure"](require_recheck=True)
    now = datetime.now(timezone.utc)
    q = {"schema": "resident-context-recheck/v1", "status": "unchanged", "authorizes_effects": False,
         "context_digest": json.loads(setup["packet"].read_bytes())["digest"],
         "context_sha256": digest(setup["packet"].read_bytes()), "generation": 1,
         "checked_at": now.isoformat(), "valid_until": (now + timedelta(hours=1)).isoformat()}
    path = write_json(setup["profile"].parent / "recheck.json", q)
    with pytest.raises(resident.ResidentError, match="source.recheck.*fresh"):
        run(setup, source_recheck_path=path, source_recheck_sha256=digest(path.read_bytes()))


def test_qualification_is_bound_to_recipe_and_expiration(setup):
    raw = json.loads(setup["profile"].read_text())
    raw["execution"]["argv"][-1] += "\nprint('changed recipe')"
    write_json(setup["profile"], raw)
    with pytest.raises(resident.ResidentError, match="qualification.*recipe"):
        run(setup)
    setup["configure"]()
    q = json.loads(setup["qualification"].read_text())
    q["valid_until"] = "2020-01-01T00:00:00Z"
    write_json(setup["qualification"], q)
    raw = json.loads(setup["profile"].read_text())
    raw["execution"]["qualification_sha256"] = digest(setup["qualification"].read_bytes())
    write_json(setup["profile"], raw)
    with pytest.raises(resident.ResidentError, match="qualification.*expired"):
        run(setup)


def test_unprotected_profile_is_refused_before_execution(setup, monkeypatch):
    monkeypatch.setattr(resident, "_protected_file", resident.assert_protected_file)
    with pytest.raises(resident.ResidentError, match="protected|root"):
        run(setup)


def test_child_does_not_inherit_provider_credentials_or_operator_home(setup, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-cross")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-cross")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", "/do-not-pass")
    monkeypatch.setenv("PYTHONPATH", "/do-not-import")
    script = SCRIPT.replace('(root / "drafts/story.txt").write_text("A bridge and a rumour.\\n")',
                            '(root / "drafts/story.txt").write_text(json.dumps(dict(os.environ)))')
    setup["configure"](script=script)
    receipt = run(setup)
    assert receipt["outcome"] == "done"
    env = json.loads((setup["workspace"] / "drafts/story.txt").read_text())
    assert not {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CREDENTIALS_DIRECTORY", "PYTHONPATH"} & env.keys()
    assert env["HOME"] != os.environ["HOME"]


def test_timeout_is_bounded_and_explicit(setup):
    setup["configure"](script="import time; time.sleep(30)", timeout=.15)
    began = time.monotonic()
    receipt = run(setup)
    assert time.monotonic() - began < 4
    assert receipt["outcome"] == "interrupted"
    assert receipt["stop_reason"] == "timeout"


def test_timeout_preserves_partial_artifacts_without_claiming_completion(setup):
    setup["configure"](script="import pathlib,time; pathlib.Path('drafts').mkdir(); "
                         "pathlib.Path('drafts/partial.md').write_text('Unfinished scene'); time.sleep(30)", timeout=.2)
    receipt = run(setup)
    assert receipt["stop_reason"] == "timeout"
    checkpoint = json.loads(Path(receipt["checkpoint_path"]).read_bytes())
    assert checkpoint["artifacts"][0]["path"] == "drafts/partial.md"
    assert Path(checkpoint["artifacts"][0]["snapshot_path"]).read_text() == "Unfinished scene"


def test_output_watchdog_stops_a_noisy_child(setup, monkeypatch):
    monkeypatch.setattr(resident, "MAX_OUTPUT", 1024)
    setup["configure"](script="import os,time; os.write(1,b'x'*8192); time.sleep(30)")
    receipt = run(setup)
    assert receipt["stop_reason"] == "output_limit"
    assert receipt["outcome"] == "interrupted"


def test_concurrent_wake_cannot_start_second_coordinator(setup):
    setup["configure"](script="import time; time.sleep(.5)\n" + SCRIPT)
    outcomes = []
    thread = threading.Thread(target=lambda: outcomes.append(run(setup)))
    thread.start()
    try:
        wait_for(lambda: [e for e in setup["log"].read() if e["type"] == "resident.episode.started"])
        second = run(setup, wake="wake-02")
        assert second["status"] == "busy"
        assert len([e for e in setup["log"].read() if e["type"] == "resident.episode.started"]) == 1
    finally:
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert outcomes[0]["outcome"] == "done"


def test_generation_fence_interrupts_old_work_and_rejects_old_generation(setup):
    setup["configure"](script="import time; time.sleep(30)")
    outcomes = []
    thread = threading.Thread(target=lambda: outcomes.append(run(setup)))
    thread.start()
    try:
        wait_for(lambda: [e for e in setup["log"].read() if e["type"] == "resident.episode.started"])
        result = resident.fence(setup["log"], setup["profile"], expected_generation=1, reason="replace runtime")
        assert result["generation"] == 2
    finally:
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert outcomes[0]["stop_reason"] == "stale_generation"
    with pytest.raises(resident.ResidentError, match="generation"):
        run(setup, wake="wake-02", generation=1)


def test_old_wake_remains_a_receipt_lookup_after_generation_fence(setup):
    first = run(setup)
    resident.fence(setup["log"], setup["profile"], expected_generation=1, reason="replace setup")
    duplicate = run(setup)
    assert duplicate["status"] == "duplicate"
    assert duplicate["episode_id"] == first["episode_id"]


@pytest.mark.parametrize("path", ["../outside", "/etc/passwd", "drafts/../secret", "other/secret"])
def test_artifact_paths_must_be_within_declared_roots(setup, path):
    setup["configure"](script=SCRIPT.replace('["drafts/story.txt"]', json.dumps([path])))
    receipt = run(setup)
    assert receipt["outcome"] == "failed"
    assert receipt["stop_reason"] == "invalid_result"


def test_artifact_symlink_cannot_escape_workspace(setup, tmp_path):
    outside = tmp_path / "private"
    outside.write_text("private")
    script = SCRIPT.replace('(root / "drafts/story.txt").write_text("A bridge and a rumour.\\n")',
                            f'(root / "drafts/story.txt").symlink_to({str(outside)!r})')
    setup["configure"](script=script)
    receipt = run(setup)
    assert receipt["stop_reason"] == "invalid_result"
    assert not any(p.read_bytes() == b"private" for p in setup["state"].rglob("*.blob"))


def test_stale_worker_result_cannot_claim_completion(setup):
    setup["configure"](script=SCRIPT.replace('int(os.environ["LANECTL_RESIDENT_GENERATION"])', "999"))
    receipt = run(setup)
    assert receipt["outcome"] == "failed"
    assert receipt["stop_reason"] == "invalid_result"


def test_nonzero_exit_cannot_be_masked_by_successful_result(setup):
    setup["configure"](script=SCRIPT + "\nraise SystemExit(7)\n")
    receipt = run(setup)
    assert receipt["outcome"] == "failed"
    assert receipt["stop_reason"] == "process_failed"
    assert receipt["checkpoint_sha256"]


def test_unfinished_episode_requires_recovery_not_replay(setup):
    first = run(setup)
    rows = [e for e in setup["log"].read() if e["type"] != "resident.episode.finished"]
    # A separate append-only test history models a crash before the finish.
    crashlog = EventLog(setup["state"].parent / "crash.jsonl")
    for e in rows:
        crashlog.append(e["type"], e["data"])
    with pytest.raises(resident.ResidentError, match="recovery|unfinished"):
        resident.run_episode(crashlog, profile_path=setup["profile"], wake_id="wake-02",
                             generation=1, context_path=setup["packet"],
                             context_sha256=digest(setup["packet"].read_bytes()))
    assert first["episode_id"]


def test_foreign_runner_is_not_declared_dead(setup):
    run(setup)
    rows = setup["log"].read()
    crashlog = EventLog(setup["state"].parent / "foreign.jsonl")
    for event in rows:
        if event["type"] == "resident.episode.finished":
            continue
        data = dict(event["data"])
        if event["type"] == "resident.episode.started":
            data["runner_process"] = dict(data["runner_process"], host="foreign-host")
        crashlog.append(event["type"], data)
    result = resident.recover(crashlog, setup["profile"], expected_generation=1)
    assert result["status"] == "uncertain"
    assert resident.status(crashlog, setup["profile"])["generation"] == 1


def test_crashed_coordinator_child_is_stopped_and_generation_recovers(setup):
    setup["configure"](script="import pathlib,time; pathlib.Path('started').touch(); time.sleep(30)")
    arguments = {"profile_path": str(setup["profile"]), "wake_id": "wake-crash", "generation": 1,
                 "context_path": str(setup["packet"]), "context_sha256": digest(setup["packet"].read_bytes())}
    script = ("import json; from pathlib import Path; from lanectl import resident; "
              "from lanectl.events import EventLog; resident._protected_file=lambda path:None; "
              f"resident.run_episode(EventLog(Path({str(setup['log'].path)!r})), **json.loads({json.dumps(arguments)!r}))")
    parent = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    child = None
    try:
        wait_for(lambda: (setup["workspace"] / "started").exists())
        child = resident.status(setup["log"], setup["profile"])["active"][0]["child_process"]["pid"]
        parent.kill()
        parent.wait(timeout=3)
        recovered = resident.recover(setup["log"], setup["profile"], expected_generation=1)
        assert recovered["status"] == "recovered"
        assert recovered["generation"] == 2
        assert not resident._group_active(child)
        state = resident.status(setup["log"], setup["profile"])
        assert state["active"] == []
        assert state["finished"][0]["outcome"] == "interrupted"
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=3)
        if child and resident._group_active(child):
            os.killpg(child, signal.SIGKILL)


def test_failed_durable_child_admission_never_executes_launcher(setup, monkeypatch):
    original = setup["log"].append

    def fail_started(etype, data, **kwargs):
        if etype == "resident.episode.started":
            raise OSError("admission journal unavailable")
        return original(etype, data, **kwargs)

    monkeypatch.setattr(setup["log"], "append", fail_started)
    receipt = run(setup)
    assert receipt["stop_reason"] == "launch_failed"
    assert not (setup["workspace"] / "drafts").exists()


def test_failed_object_write_cannot_publish_a_partial_digest_object(setup, monkeypatch):
    p = resident.load_profile(setup["profile"])
    content = b"an exact immutable checkpoint"
    original = os.fsync

    def fail_sync(fd):
        raise OSError("simulated power-loss boundary")

    monkeypatch.setattr(os, "fsync", fail_sync)
    with pytest.raises(OSError, match="power-loss"):
        resident._store(p, content)
    assert not (p.root / "objects" / (digest(content) + ".blob")).exists()
    monkeypatch.setattr(os, "fsync", original)
    path, checksum = resident._store(p, content)
    assert checksum == digest(content)
    assert path.read_bytes() == content


def test_fence_between_durable_start_and_gate_cannot_release_old_generation(setup, monkeypatch):
    original = resident._source_recheck
    calls, admissions = [], []
    original_write = os.write

    def fence_after_start(*args, **kwargs):
        value = original(*args, **kwargs)
        calls.append(None)
        if len(calls) == 2:
            resident.fence(setup["log"], setup["profile"], expected_generation=1,
                           reason="race at final child admission")
        return value

    def record_write(fd, data):
        if data == b"1":
            admissions.append(data)
        return original_write(fd, data)

    monkeypatch.setattr(resident, "_source_recheck", fence_after_start)
    monkeypatch.setattr(os, "write", record_write)
    receipt = run(setup)
    assert admissions == []
    assert receipt["stop_reason"] == "stale_generation"
    assert not (setup["workspace"] / "drafts").exists()


def test_unresolved_process_cleanup_keeps_slot_unknown_even_after_fencing(setup, monkeypatch):
    calls = []

    def unresolved(group):
        if not calls:
            resident.fence(setup["log"], setup["profile"], expected_generation=1,
                           reason="fence during unresolved process cleanup")
        calls.append(group)
        return True

    monkeypatch.setattr(resident, "_group_active", unresolved)
    receipt = run(setup)
    assert receipt["outcome"] == "unknown"
    assert receipt["stop_reason"] == "execution_uncertain"
    assert resident.status(setup["log"], setup["profile"])["active"]


def test_cleanup_never_signals_an_observed_reused_process_identity(setup, monkeypatch):
    original_identity = resident.reap.process_identity
    original_signal = os.killpg
    recorded, signals = {}, []

    def identity(pid=None):
        if pid is None:
            return original_identity()
        if pid not in recorded:
            recorded[pid] = original_identity(pid)
            return recorded[pid]
        return dict(recorded[pid], start_ticks=str(int(recorded[pid]["start_ticks"]) + 1))

    def signal_group(group, sig):
        if sig == signal.SIGKILL:
            signals.append(group)
        return original_signal(group, sig)

    monkeypatch.setattr(resident.reap, "process_identity", identity)
    monkeypatch.setattr(os, "killpg", signal_group)
    receipt = run(setup)
    assert signals == []
    assert receipt["outcome"] == "unknown"
    assert resident.status(setup["log"], setup["profile"])["active"]


@pytest.mark.parametrize("command", ["run", "status", "fence", "recover"])
def test_remote_or_buffered_backends_are_explicitly_unsupported(setup, command):
    class BufferedLog(EventLog):
        """The local EventLog durability contract cannot be assumed for subtypes."""

    setup["log"] = BufferedLog(setup["log"].path)
    with pytest.raises(resident.ResidentError, match="local.*EventLog|EventLog.*local"):
        if command == "run":
            run(setup)
        elif command == "status":
            resident.status(setup["log"], setup["profile"])
        elif command == "fence":
            resident.fence(setup["log"], setup["profile"], expected_generation=1, reason="test")
        else:
            resident.recover(setup["log"], setup["profile"], expected_generation=1)
    assert setup["log"].read() == []


def test_exited_launcher_cannot_leave_background_descendants(setup):
    script = ("import subprocess,sys,pathlib\n"
              "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])\n"
              "pathlib.Path('descendant.pid').write_text(str(p.pid))\n" + SCRIPT)
    setup["configure"](script=script)
    receipt = run(setup)
    child = int((setup["workspace"] / "descendant.pid").read_text())
    try:
        assert receipt["outcome"] == "done"
        text = Path(f"/proc/{child}/stat")
        assert not text.exists() or text.read_text().split(") ", 1)[1].startswith(("Z ", "X "))
    finally:
        try:
            os.kill(child, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_workspace_cannot_rebind_to_a_second_resident_or_lock_root(setup):
    run(setup)
    raw = json.loads(setup["profile"].read_text())
    raw["resident_id"] = "writer-two"
    raw["state_dir"] += "-alternate"
    write_json(setup["profile"], raw)
    setup["packet"].write_bytes(packet_bytes(scope={"resident": "writer-two", "project": "stories", "branch": "canon"}))
    with pytest.raises(resident.ResidentError, match="workspace.*bound"):
        run(setup, wake="wake-02")


def test_result_directory_swap_cannot_read_outside_workspace(setup, monkeypatch, tmp_path):
    original = resident._parse_result

    def swapped(p, episode, generation):
        directory = p.workspace / ".lanectl-resident-results"
        directory.rename(p.workspace / "old-results")
        directory.symlink_to(tmp_path)
        write_json(tmp_path / f"{episode}.json", {"schema": "lanectl.resident-result/v1",
                   "episode_id": episode, "generation": generation, "stop_reason": "completed",
                   "artifacts": [], "continuation": {"secret": "not-for-checkpoint"}})
        return original(p, episode, generation)

    monkeypatch.setattr(resident, "_parse_result", swapped)
    receipt = run(setup)
    assert receipt["stop_reason"] == "invalid_result"
    assert b"not-for-checkpoint" not in Path(receipt["checkpoint_path"]).read_bytes()


def test_resident_event_validation_cannot_pollute_item_projection():
    data = {"resident_id": "writer-one", "workspace": "/work", "state_dir": "/state", "generation": 1}
    with pytest.raises(ContractError):
        make_event("resident.initialized", data, item_id="software-item")
    with pytest.raises(ContractError):
        make_event("resident.initialized", dict(data, generation=True))


def test_cli_discovery_exposes_resident_without_general_scheduler():
    result = subprocess.run([sys.executable, "-m", "lanectl.cli", "resident", "--help"],
                            text=True, capture_output=True)
    assert result.returncode == 0
    assert all(name in result.stdout for name in ("run", "status", "fence", "recover"))
