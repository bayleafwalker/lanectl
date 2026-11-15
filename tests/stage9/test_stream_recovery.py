"""Owner recovery preserves WAL state and acknowledged idempotency across processes."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from contextlib import closing
from pathlib import Path

import pytest

from lanectl import stream_recovery as recovery
from lanectl.contracts import make_event
from lanectl.stream_store import StreamError, StreamStore, initialize


def event(label="release-a"):
    return make_event(
        "release.published", {"release_id": label, "revision": 1}, item_id=label
    )


@pytest.fixture
def owner(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path / "source.sqlite"
    initialize(path)
    path.chmod(0o600)
    return path, StreamStore(path)


def rows(path):
    with closing(sqlite3.connect(path)) as db:
        return {
            table: db.execute(
                "SELECT * FROM " + table + " ORDER BY 1,2,3,4,5"
            ).fetchall()
            for table in ("lane_events", "lane_batches")
        }


def cli(*args, state):
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).parents[2] / "src"),
        "LANECTL_STATE": str(state),
    }
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "from lanectl.cli import main; raise SystemExit(main())",
            "stream",
            *map(str, args),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_bundle_restores_every_row_and_acknowledged_replay_in_second_process(
    owner, tmp_path
):
    source, store = owner
    recorded_event = event()
    original = store.append(
        "workspace-a",
        "repo-a",
        "control",
        "issuer:runner:1",
        "batch-0001",
        0,
        [recorded_event],
    )
    store.append(
        "workspace-b",
        "repo-a",
        "control",
        "issuer:runner:2",
        "batch-0001",
        0,
        [event("other")],
    )
    artifact, destination = tmp_path / "snapshot.lane", tmp_path / "restored.sqlite"
    backup = cli("backup", source, artifact, state=tmp_path / "must-not-create-state")
    assert backup.returncode == 0, backup.stderr + backup.stdout
    receipt = json.loads(backup.stdout)
    assert receipt["authority_changed"] is False
    assert receipt["counts"] == {"lane_events": 2, "lane_batches": 2}
    assert artifact.stat().st_mode & 0o777 == 0o600
    with zipfile.ZipFile(artifact) as bundle:
        assert bundle.namelist() == ["manifest.json", "owner.sqlite"]
        manifest = json.loads(bundle.read("manifest.json"))
        payload = bundle.read("owner.sqlite")
        assert manifest["payload"]["sha256"] == hashlib.sha256(payload).hexdigest()
        assert manifest["payload"]["bytes"] == len(payload)
    restored = cli(
        "restore", artifact, destination, state=tmp_path / "must-not-create-state"
    )
    assert restored.returncode == 0, restored.stderr + restored.stdout
    result = json.loads(restored.stdout)
    assert result["authority_changed"] is False
    assert (
        result["artifact_sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()
    )
    assert destination.stat().st_mode & 0o777 == 0o600
    assert rows(destination) == rows(source)
    reopened = StreamStore(destination)
    assert reopened.append(
        "workspace-a",
        "repo-a",
        "control",
        "issuer:runner:1",
        "batch-0001",
        0,
        [recorded_event],
    ) == {**original, "replayed": True}
    with pytest.raises(StreamError) as conflict:
        reopened.append(
            "workspace-a",
            "repo-a",
            "control",
            "issuer:runner:1",
            "batch-0001",
            0,
            [event("changed")],
        )
    assert conflict.value.code == "idempotency-conflict"
    assert (
        reopened.append(
            "workspace-a",
            "repo-a",
            "control",
            "issuer:runner:1",
            "batch-0002",
            1,
            [event("next")],
        )["revision"]
        == 2
    )
    for workspace, repo, stream in (
        ("foreign", "repo-a", "control"),
        ("workspace-a", "foreign", "control"),
        ("workspace-a", "repo-a", "foreign"),
    ):
        assert reopened.read(workspace, repo, stream)["events"] == []
    assert not (tmp_path / "must-not-create-state").exists()


def test_online_backup_includes_committed_uncheckpointed_wal(owner, tmp_path):
    source, store = owner
    with sqlite3.connect(source) as reader:
        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM lane_events").fetchone()
        store.append("ws", "repo", "control", "p", "batch-0001", 0, [event()])
        assert Path(str(source) + "-wal").stat().st_size > 0
        naive = tmp_path / "naive.sqlite"
        shutil.copyfile(source, naive)
        assert rows(naive)["lane_events"] == []  # Falsify a live main-file copy.
        artifact = tmp_path / "snapshot.lane"
        receipt = recovery.backup(source, artifact)
        assert receipt["counts"] == {"lane_events": 1, "lane_batches": 1}
        destination = tmp_path / "restored.sqlite"
        recovery.restore(artifact, destination)
        assert rows(destination) == rows(source)


def rewrite(artifact, target, mutate_manifest=None, mutate_payload=None, members=None):
    with zipfile.ZipFile(artifact) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        payload = bundle.read("owner.sqlite")
    if mutate_payload:
        payload = mutate_payload(payload)
    if mutate_manifest:
        mutate_manifest(manifest)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as bundle:
        for name, body in members or [
            ("manifest.json", json.dumps(manifest).encode()),
            ("owner.sqlite", payload),
        ]:
            info = zipfile.ZipInfo(name)
            info.external_attr = 0o100600 << 16
            bundle.writestr(info, body)
    target.chmod(0o600)


@pytest.mark.parametrize(
    "mutation",
    [
        "hash",
        "schema",
        "truncated",
        "extra",
        "duplicate",
        "missing-batches",
        "wrong-catalog",
    ],
)
def test_untrusted_bundle_refusals_never_publish(owner, tmp_path, mutation):
    source, store = owner
    store.append("ws", "repo", "control", "p", "batch-0001", 0, [event()])
    original, bad, destination = (
        tmp_path / name for name in ("good.lane", "bad.lane", "restored.sqlite")
    )
    recovery.backup(source, original)
    if mutation == "hash":
        rewrite(
            original,
            bad,
            mutate_manifest=lambda m: m["payload"].update(sha256="0" * 64),
        )
    elif mutation == "schema":
        rewrite(original, bad, mutate_manifest=lambda m: m.update(owner_schema=2))
    elif mutation == "truncated":
        bad.write_bytes(original.read_bytes()[:-20])
        bad.chmod(0o600)
    elif mutation in {"extra", "duplicate"}:
        with zipfile.ZipFile(original) as z:
            entries = [(name, z.read(name)) for name in z.namelist()]
        entries.append(("manifest.json" if mutation == "duplicate" else "extra", b"{}"))
        if mutation == "duplicate":
            with pytest.warns(UserWarning, match="Duplicate name"):
                rewrite(original, bad, members=entries)
        else:
            rewrite(original, bad, members=entries)
    else:
        payload_path = tmp_path / "mutated.sqlite"
        with zipfile.ZipFile(original) as z:
            payload_path.write_bytes(z.read("owner.sqlite"))
        with sqlite3.connect(payload_path) as db:
            db.execute(
                "DELETE FROM lane_batches"
                if mutation == "missing-batches"
                else "CREATE TABLE foreign_table(value)"
            )
        payload = payload_path.read_bytes()
        rewrite(
            original,
            bad,
            mutate_payload=lambda _: payload,
            mutate_manifest=lambda m: m["payload"].update(
                sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload)
            ),
        )
    with pytest.raises(recovery.RecoveryError):
        recovery.restore(bad, destination)
    assert not destination.exists()
    assert original.exists() and rows(source)["lane_events"]


@pytest.mark.parametrize(
    "unsafe",
    [
        "existing",
        "wal",
        "shm",
        "journal",
        "symlink",
        "alias",
        "parent-permissions",
        "file-permissions",
    ],
)
def test_unsafe_paths_refuse_without_replacement(owner, tmp_path, unsafe):
    source, _ = owner
    artifact, destination = tmp_path / "snapshot.lane", tmp_path / "restored.sqlite"
    recovery.backup(source, artifact)
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"preserve")
    if unsafe == "existing":
        destination.write_bytes(b"preserve")
    elif unsafe in {"wal", "shm", "journal"}:
        Path(str(destination) + "-" + unsafe).write_bytes(b"preserve")
    elif unsafe == "symlink":
        destination.symlink_to(sentinel)
    elif unsafe == "alias":
        os.link(artifact, tmp_path / "artifact-alias")
    elif unsafe == "parent-permissions":
        tmp_path.chmod(0o755)
    else:
        artifact.chmod(0o644)
    with pytest.raises(recovery.RecoveryError):
        recovery.restore(artifact, destination)
    assert sentinel.read_bytes() == b"preserve"
    if unsafe == "existing":
        assert destination.read_bytes() == b"preserve"


@pytest.mark.parametrize(
    "phase", ["backup", "copy", "file-fsync", "publication", "parent-fsync"]
)
def test_faults_never_report_success_or_erase_source_or_published_result(
    owner, tmp_path, monkeypatch, phase
):
    source, store = owner
    store.append("ws", "repo", "control", "p", "batch-0001", 0, [event()])
    before = rows(source)
    artifact = tmp_path / "snapshot.lane"
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"preserve")

    def fail(*args, **kwargs):
        raise OSError("injected " + phase)

    with monkeypatch.context() as patch:
        patch.setattr(
            recovery,
            {
                "backup": "_online_snapshot",
                "copy": "_copy",
                "file-fsync": "_sync_file",
                "publication": "_link",
                "parent-fsync": "_sync_parent",
            }[phase],
            fail,
        )
        with pytest.raises(recovery.RecoveryError) as caught:
            recovery.backup(source, artifact)
    assert rows(source) == before and sentinel.read_bytes() == b"preserve"
    if phase == "parent-fsync":
        assert caught.value.published == str(artifact)
        assert artifact.exists()
        recovery.restore(artifact, tmp_path / "restored.sqlite")
    else:
        assert not artifact.exists()


def test_concurrent_writer_backup_preserves_a_complete_snapshot_and_restored_cas(
    owner, tmp_path, monkeypatch
):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    source, store = owner
    events = [event(f"release-{n}") for n in range(30)]
    for value in events:
        value["data"]["padding"] = "x" * 24000
    store.append("ws", "repo", "control", "p", "batch-0001", 0, events)
    begin, written = threading.Event(), threading.Event()

    def writer():
        try:
            assert begin.wait(10)
            store.append(
                "ws",
                "repo",
                "control",
                "other-p",
                "batch-0002",
                30,
                [event("concurrent")],
            )
        finally:
            written.set()

    original_progress = recovery._backup_progress
    observed = []

    def progress(status, remaining, total, started, page_size):
        if remaining and not observed:
            observed.append((remaining, total))
            begin.set()
            assert written.wait(10)
        original_progress(status, remaining, total, started, page_size)

    monkeypatch.setattr(recovery, "_backup_progress", progress)
    artifact, restored = tmp_path / "concurrent.lane", tmp_path / "restored.sqlite"
    with ThreadPoolExecutor(max_workers=1) as writer_pool:
        future = writer_pool.submit(writer)
        try:
            result = recovery.backup(source, artifact)
        finally:
            begin.set()
        future.result(timeout=15)
    assert observed
    recovery.restore(artifact, restored)
    recovered = StreamStore(restored)
    head = recovered.read("ws", "repo", "control")["revision"]
    assert head in (30, 31) and result["counts"]["lane_events"] == head
    assert (
        recovered.read("ws", "repo", "control")["events"]
        == store.read("ws", "repo", "control")["events"][:head]
    )

    def compete(principal):
        try:
            return recovered.append(
                "ws",
                "repo",
                "control",
                principal,
                "restored-cas-key",
                head,
                [event(principal)],
            )["revision"]
        except StreamError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        answers = set(pool.map(compete, ("winner-a", "winner-b")))
    assert answers == {head + 1, "revision-conflict"}


@pytest.mark.parametrize(
    "mutation",
    [
        "payload-schema",
        "missing-batch-table",
        "principal",
        "duplicate-range",
        "boolean-count",
        "wrong-head",
        "extra-manifest-key",
        "manifest-limit",
        "payload-limit",
        "member-symlink",
        "compressed-member",
    ],
)
def test_deep_bundle_and_resource_refusals(owner, tmp_path, monkeypatch, mutation):
    source, store = owner
    store.append("ws", "repo", "control", "p", "batch-0001", 0, [event()])
    good, bad, destination = (
        tmp_path / name for name in ("good.lane", "bad.lane", "destination.sqlite")
    )
    recovery.backup(source, good)
    if mutation in {
        "payload-schema",
        "missing-batch-table",
        "principal",
        "duplicate-range",
    }:
        payload_path = tmp_path / "tampered.sqlite"
        with zipfile.ZipFile(good) as z:
            payload_path.write_bytes(z.read("owner.sqlite"))
        with sqlite3.connect(payload_path) as db:
            if mutation == "payload-schema":
                db.execute("PRAGMA user_version=2")
            elif mutation == "missing-batch-table":
                db.execute("DROP TABLE lane_batches")
            elif mutation == "principal":
                db.execute("UPDATE lane_events SET principal='forged'")
            else:
                db.execute(
                    "INSERT INTO lane_batches SELECT workspace,repo,stream,principal,'duplicate-key',digest,result FROM lane_batches"
                )
        payload = payload_path.read_bytes()
        rewrite(
            good,
            bad,
            mutate_payload=lambda _: payload,
            mutate_manifest=lambda m: m["payload"].update(
                bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest()
            ),
        )
    elif mutation in {"member-symlink", "compressed-member"}:
        with zipfile.ZipFile(good) as z, zipfile.ZipFile(bad, "w") as target:
            for name in z.namelist():
                info = zipfile.ZipInfo(name)
                info.external_attr = (
                    0o120600 if mutation == "member-symlink" else 0o100600
                ) << 16
                info.compress_type = (
                    zipfile.ZIP_DEFLATED
                    if mutation == "compressed-member"
                    else zipfile.ZIP_STORED
                )
                target.writestr(info, z.read(name))
        bad.chmod(0o600)
    else:

        def mutate(m):
            if mutation == "boolean-count":
                m["counts"]["lane_events"] = True
            elif mutation == "wrong-head":
                m["heads"][0]["revision"] = 2
            elif mutation == "extra-manifest-key":
                m["unreviewed"] = True

        rewrite(good, bad, mutate_manifest=mutate)
        if mutation == "manifest-limit":
            monkeypatch.setattr(recovery, "MAX_MANIFEST", 32)
        if mutation == "payload-limit":
            monkeypatch.setattr(recovery, "MAX_PAYLOAD", 4096)
    with pytest.raises(recovery.RecoveryError):
        recovery.restore(bad, destination)
    assert not destination.exists() and rows(source)["lane_events"]


@pytest.mark.parametrize("operation", ["backup", "restore"])
def test_exclusive_publication_race_preserves_caller_sentinel(
    owner, tmp_path, monkeypatch, operation
):
    source, _ = owner
    artifact, destination = tmp_path / "good.lane", tmp_path / "destination.sqlite"
    recovery.backup(source, artifact)
    final = tmp_path / "raced.lane" if operation == "backup" else destination
    original = recovery._link

    def collision(candidate, target, parent_fd):
        target.write_bytes(b"caller sentinel")
        original(candidate, target, parent_fd)

    monkeypatch.setattr(recovery, "_link", collision)
    with pytest.raises(recovery.RecoveryError):
        if operation == "backup":
            recovery.backup(source, final)
        else:
            recovery.restore(artifact, final)
    assert final.read_bytes() == b"caller sentinel"


@pytest.mark.parametrize("phase", ["copy", "file-fsync", "publication", "parent-fsync"])
def test_restore_faults_preserve_original_artifact_and_never_claim_success(
    owner, tmp_path, monkeypatch, phase
):
    source, _ = owner
    artifact, destination = tmp_path / "good.lane", tmp_path / "restored.sqlite"
    recovery.backup(source, artifact)
    original = artifact.read_bytes()

    def fail(*args, **kwargs):
        raise OSError("injected restore " + phase)

    with monkeypatch.context() as patch:
        patch.setattr(
            recovery,
            {
                "copy": "_copy",
                "file-fsync": "_sync_file",
                "publication": "_link",
                "parent-fsync": "_sync_parent",
            }[phase],
            fail,
        )
        with pytest.raises(recovery.RecoveryError) as caught:
            recovery.restore(artifact, destination)
    assert artifact.read_bytes() == original
    if phase == "parent-fsync":
        assert caught.value.published == str(destination)
        assert StreamStore(destination).read("ws", "repo", "control")["revision"] == 0
        with pytest.raises(recovery.RecoveryError, match="existing-destination"):
            recovery.restore(artifact, destination)
    else:
        assert not destination.exists()


def test_interruption_after_publication_retains_an_unactivated_result(
    owner, tmp_path, monkeypatch
):
    source, _ = owner
    artifact = tmp_path / "snapshot.lane"

    def interrupt(fd):
        raise KeyboardInterrupt("after exclusive publication")

    with monkeypatch.context() as patch:
        patch.setattr(recovery, "_sync_parent", interrupt)
        with pytest.raises(KeyboardInterrupt):
            recovery.backup(source, artifact)
    assert artifact.exists()
    recovery.restore(artifact, tmp_path / "restored.sqlite")
    with pytest.raises(recovery.RecoveryError, match="existing-destination"):
        recovery.backup(source, artifact)


def test_candidate_cleanup_cannot_erase_an_unowned_replacement(
    owner, tmp_path, monkeypatch
):
    source, _ = owner
    snapshot = recovery._online_snapshot
    retained = []

    def replace_candidate(database, destination, owned):
        snapshot(database, destination, owned)
        destination.unlink()
        destination.write_bytes(b"caller sentinel")
        retained.append(destination)
        raise OSError("injected failure after candidate replacement")

    monkeypatch.setattr(recovery, "_online_snapshot", replace_candidate)
    with pytest.raises(recovery.RecoveryError, match="cleanup-refused"):
        recovery.backup(source, tmp_path / "snapshot.lane")
    assert retained[0].read_bytes() == b"caller sentinel"
    assert not (tmp_path / "snapshot.lane").exists()


@pytest.mark.parametrize("race", ["replace-result", "sidecar"])
def test_post_publication_races_refuse_without_deleting_existing_effect(
    owner, tmp_path, monkeypatch, race
):
    source, _ = owner
    artifact = tmp_path / "snapshot.lane"
    original_link = recovery._link

    def raced(candidate, destination, parent_fd):
        original_link(candidate, destination, parent_fd)
        if race == "replace-result":
            destination.unlink()
            destination.write_bytes(b"caller sentinel")
        else:
            Path(str(destination) + "-wal").write_bytes(b"caller sentinel")

    monkeypatch.setattr(recovery, "_link", raced)
    with pytest.raises(recovery.RecoveryError) as caught:
        recovery.backup(source, artifact)
    assert caught.value.published == str(artifact)
    sentinel = artifact if race == "replace-result" else Path(str(artifact) + "-wal")
    assert sentinel.read_bytes() == b"caller sentinel"


def test_backup_never_changes_source_catalog_or_journal_mode(owner, tmp_path):
    source, store = owner
    store.append("ws", "repo", "control", "p", "batch-0001", 0, [event()])

    def observe():
        with sqlite3.connect(source) as db:
            return (
                db.execute("PRAGMA journal_mode").fetchone(),
                db.execute(
                    "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY 1,2"
                ).fetchall(),
                rows(source),
            )

    before = observe()
    recovery.backup(source, tmp_path / "snapshot.lane")
    assert observe() == before
    assert before[0] == ("wal",)


def test_partial_payload_copy_is_never_published(owner, tmp_path, monkeypatch):
    source, _ = owner

    def partial(origin, destination, **kwargs):
        destination.write(origin.read(32))
        raise OSError("injected partial write")

    monkeypatch.setattr(recovery, "_copy", partial)
    with pytest.raises(recovery.RecoveryError):
        recovery.backup(source, tmp_path / "snapshot.lane")
    assert not (tmp_path / "snapshot.lane").exists()
    assert not list(tmp_path.glob(".lanectl-recovery-*"))


def test_complete_artifact_file_fsync_must_pass_before_publication(
    owner, tmp_path, monkeypatch
):
    source, _ = owner
    original = recovery._sync_file

    def fail_final(path):
        if path.name == "artifact.tmp":
            raise OSError("injected completed artifact fsync failure")
        original(path)

    monkeypatch.setattr(recovery, "_sync_file", fail_final)
    with pytest.raises(recovery.RecoveryError):
        recovery.backup(source, tmp_path / "snapshot.lane")
    assert not (tmp_path / "snapshot.lane").exists()


def test_second_process_reads_all_rows_and_independent_processes_preserve_cas(
    owner, tmp_path
):
    source, store = owner
    for workspace, repo, stream in (
        ("ws-a", "repo-a", "control"),
        ("ws-b", "repo-a", "control"),
        ("ws-a", "repo-b", "other"),
    ):
        store.append(
            workspace, repo, stream, "issuer:runner:1", "batch-0001", 0, [event()]
        )
    artifact, restored = tmp_path / "snapshot.lane", tmp_path / "restored.sqlite"
    assert cli("backup", source, artifact, state=tmp_path / "unused").returncode == 0
    assert cli("restore", artifact, restored, state=tmp_path / "unused").returncode == 0
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[2] / "src")}
    read_code = """
import json, sqlite3, sys
with sqlite3.connect(sys.argv[1]) as db:
    print(json.dumps({table: db.execute('SELECT * FROM '+table+' ORDER BY 1,2,3,4,5').fetchall()
        for table in ('lane_events','lane_batches')}))
"""
    readback = subprocess.run(
        [sys.executable, "-c", read_code, str(restored)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(readback.stdout) == json.loads(json.dumps(rows(source)))
    writer_code = """
import json, sys
from lanectl.stream_store import StreamStore, StreamError
from lanectl.contracts import make_event
owner = StreamStore(sys.argv[1])
print('ready', flush=True)
sys.stdin.readline()
try:
    result = owner.append('ws-a','repo-a','control',sys.argv[2],'process-cas-key',1,
        [make_event('item.parked', {'reason':'independent process'}, item_id='release-a')])
except StreamError as error:
    result = {'error':error.code}
print(json.dumps(result), flush=True)
"""
    children = [
        subprocess.Popen(
            [sys.executable, "-c", writer_code, str(restored), principal],
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for principal in ("process-a", "process-b")
    ]
    try:
        for child in children:
            assert child.stdout.readline().strip() == "ready"
        for child in children:
            child.stdin.write("go\n")
            child.stdin.flush()
        outcomes = [json.loads(child.communicate(timeout=15)[0]) for child in children]
        assert all(child.returncode == 0 for child in children)
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.communicate()
    assert sorted(value.get("error", "accepted") for value in outcomes) == [
        "accepted",
        "revision-conflict",
    ]
    assert StreamStore(restored).read("ws-a", "repo-a", "control")["revision"] == 2


@pytest.mark.parametrize("changed", ["uid", "alias"])
def test_input_owner_and_alias_refusals_are_measured(
    owner, tmp_path, monkeypatch, changed
):
    source, _ = owner
    if changed == "uid":
        monkeypatch.setattr(recovery.os, "getuid", lambda: source.stat().st_uid + 1)
    else:
        os.link(source, tmp_path / "source-alias")
    with pytest.raises(recovery.RecoveryError):
        recovery.backup(source, tmp_path / "snapshot.lane")
    assert source.exists() and not (tmp_path / "snapshot.lane").exists()


def test_backup_resource_deadline_and_pages_guard_is_forced_to_fail():
    with pytest.raises(recovery.RecoveryError, match="resource-limit"):
        recovery._backup_progress(
            0, 1, recovery.MAX_PAYLOAD // 4096 + 1, recovery.time.monotonic(), 4096
        )
    with pytest.raises(recovery.RecoveryError, match="resource-limit"):
        recovery._backup_progress(0, 1, 1, recovery.time.monotonic() - 301, 4096)


def test_large_source_refuses_before_online_copy(owner, tmp_path, monkeypatch):
    source, _ = owner
    monkeypatch.setattr(recovery, "MAX_PAYLOAD", source.stat().st_size - 1)

    def forbidden(*args, **kwargs):
        pytest.fail("oversized source started a copy")

    monkeypatch.setattr(recovery, "_online_snapshot", forbidden)
    with pytest.raises(recovery.RecoveryError, match="resource-limit"):
        recovery.backup(source, tmp_path / "snapshot.lane")
    assert not list(tmp_path.glob(".lanectl-recovery-*"))


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate-json-key",
        "nonfinite",
        "deep-json",
        "boolean-schema",
        "duplicate-scope",
        "raw-payload-truncated",
    ],
)
def test_closed_manifest_parser_and_truncated_sqlite_refuse(owner, tmp_path, mutation):
    source, store = owner
    store.append("ws", "repo", "control", "p", "batch-0001", 0, [event()])
    good, bad, destination = (
        tmp_path / name for name in ("good.lane", "bad.lane", "destination.sqlite")
    )
    recovery.backup(source, good)
    with zipfile.ZipFile(good) as archive:
        manifest = archive.read("manifest.json")
        payload = archive.read("owner.sqlite")
    if mutation == "duplicate-json-key":
        manifest = manifest.replace(
            b'"owner_schema":1', b'"owner_schema":1,"owner_schema":1'
        )
    elif mutation == "nonfinite":
        manifest = manifest.replace(b'"owner_schema":1', b'"owner_schema":NaN')
    elif mutation == "deep-json":
        manifest = b'{"heads":' + b"[" * 1100 + b"0" + b"]" * 1100 + b"}"
    else:
        parsed = json.loads(manifest)
        if mutation == "boolean-schema":
            parsed["owner_schema"] = True
        elif mutation == "duplicate-scope":
            parsed["heads"] *= 2
        else:
            payload = payload[:-4096]
            parsed["payload"].update(
                bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest()
            )
        manifest = json.dumps(parsed).encode()
    rewrite(good, bad, members=[("manifest.json", manifest), ("owner.sqlite", payload)])
    with pytest.raises(recovery.RecoveryError):
        recovery.restore(bad, destination)
    assert not destination.exists()


def test_cli_refusal_is_structured_and_does_not_select_authority(owner, tmp_path):
    source, _ = owner
    artifact = tmp_path / "snapshot.lane"
    first = cli("backup", source, artifact, state=tmp_path / "unused")
    assert first.returncode == 0
    preserved = artifact.read_bytes()
    repeated = cli("backup", source, artifact, state=tmp_path / "unused")
    assert repeated.returncode == 1
    refusal = json.loads(repeated.stdout)
    assert refusal["ok"] is False and refusal["operation"] == "backup"
    assert refusal["authority_changed"] is False
    assert "existing-destination" in refusal["error"]
    assert artifact.read_bytes() == preserved and not (tmp_path / "unused").exists()


def test_failed_readonly_connection_setup_closes_its_handle(tmp_path, monkeypatch):
    closed = []

    class Connection:
        def setlimit(self, *args):
            pass

        def execute(self, *args):
            raise sqlite3.DatabaseError("malformed candidate schema")

        def close(self):
            closed.append(True)

    monkeypatch.setattr(
        recovery.sqlite3, "connect", lambda *args, **kwargs: Connection()
    )
    with pytest.raises(sqlite3.DatabaseError):
        recovery._connect(tmp_path / "candidate.sqlite")
    assert closed == [True]


@pytest.mark.parametrize("operation", ["backup", "restore"])
@pytest.mark.parametrize("invalid_event", [None, [], {"schema": "lanectl.event/v1"}])
def test_cli_rejects_malformed_event_envelopes_without_traceback_or_publication(
    owner, tmp_path, operation, invalid_event
):
    source, store = owner
    store.append("ws", "repo", "control", "p", "batch-0001", 0, [event()])
    good, bad, destination = (
        tmp_path / name for name in ("good.lane", "bad.lane", "destination.sqlite")
    )
    recovery.backup(source, good)
    original_artifact = good.read_bytes()
    if operation == "backup":
        with sqlite3.connect(source) as db:
            db.execute("UPDATE lane_events SET event=?", (json.dumps(invalid_event),))
        before = rows(source)
        result = cli("backup", source, destination, state=tmp_path / "unused")
        assert rows(source) == before
    else:
        payload_path = tmp_path / "corrupt.sqlite"
        with zipfile.ZipFile(good) as archive:
            payload_path.write_bytes(archive.read("owner.sqlite"))
        with sqlite3.connect(payload_path) as db:
            db.execute("UPDATE lane_events SET event=?", (json.dumps(invalid_event),))
        payload = payload_path.read_bytes()
        rewrite(
            good,
            bad,
            mutate_payload=lambda _: payload,
            mutate_manifest=lambda m: m["payload"].update(
                bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest()
            ),
        )
        before = rows(source)
        result = cli("restore", bad, destination, state=tmp_path / "unused")
        assert rows(source) == before
    assert result.returncode == 1
    refusal = json.loads(result.stdout)
    assert refusal["ok"] is False and refusal["authority_changed"] is False
    assert "Traceback" not in result.stderr
    assert not destination.exists() and not (tmp_path / "unused").exists()
    assert good.read_bytes() == original_artifact


@pytest.mark.parametrize("redirect", ["hardlink", "symlink"])
def test_cli_refuses_unsafe_existing_shm_before_sqlite_can_touch_canary(
    owner, tmp_path, redirect
):
    source, store = owner
    keeper = sqlite3.connect(source)
    try:
        keeper.execute("BEGIN")
        keeper.execute("SELECT count(*) FROM lane_events").fetchone()
        store.append("ws", "repo", "control", "p", "batch-0001", 0, [event()])
        shm = Path(str(source) + "-shm")
        canary = tmp_path / "caller-shm-canary"
        canary.write_bytes(shm.read_bytes())
        canary.chmod(0o600)
        shm.unlink()
        if redirect == "hardlink":
            os.link(canary, shm)
        else:
            shm.symlink_to(canary)
        original = canary.read_bytes()
        artifact = tmp_path / "snapshot.lane"
        result = cli("backup", source, artifact, state=tmp_path / "unused")
        assert result.returncode == 1
        refusal = json.loads(result.stdout)
        assert "unsafe-source-shm" in refusal["error"]
        assert canary.read_bytes() == original
        assert not artifact.exists() and not (tmp_path / "unused").exists()
        assert not list(tmp_path.glob(".lanectl-recovery-*"))
    finally:
        keeper.close()


def test_readonly_wal_alias_does_not_expand_the_writable_shm_guard(owner, tmp_path):
    source, store = owner
    keeper = sqlite3.connect(source)
    try:
        keeper.execute("BEGIN")
        keeper.execute("SELECT count(*) FROM lane_events").fetchone()
        store.append("ws", "repo", "control", "p", "batch-0001", 0, [event()])
        wal = Path(str(source) + "-wal")
        alias = tmp_path / "wal-readonly-alias"
        os.link(wal, alias)
        before = alias.read_bytes()
        result = cli(
            "backup", source, tmp_path / "snapshot.lane", state=tmp_path / "unused"
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert alias.read_bytes() == before
    finally:
        keeper.close()


def test_restore_publishes_a_complete_wal_owner_and_measures_its_distinct_hash(
    owner, tmp_path
):
    from contextlib import closing

    source, store = owner
    store.append("ws", "repo", "control", "p", "batch-0001", 0, [event()])
    artifact, destination = tmp_path / "snapshot.lane", tmp_path / "restored.sqlite"
    backup = recovery.backup(source, artifact)
    original = artifact.read_bytes()
    result = cli("restore", artifact, destination, state=tmp_path / "unused")
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads(result.stdout)
    with closing(sqlite3.connect(destination)) as db:
        assert db.execute("PRAGMA journal_mode").fetchone() == ("wal",)
    assert receipt["journal_mode"] == "wal"
    assert receipt["payload_sha256"] == backup["payload_sha256"]
    assert (
        receipt["restored_database_sha256"]
        == hashlib.sha256(destination.read_bytes()).hexdigest()
    )
    assert receipt["restored_database_sha256"] != receipt["payload_sha256"]
    assert artifact.read_bytes() == original
    assert rows(destination) == rows(source)
    assert not Path(str(destination) + "-wal").exists()
    assert not Path(str(destination) + "-shm").exists()
    main_only = tmp_path / "main-only.sqlite"
    shutil.copyfile(destination, main_only)
    assert rows(main_only) == rows(source)


def test_wal_preparation_failure_is_prepublication_and_preserves_original_artifact(
    owner, tmp_path, monkeypatch
):
    source, _ = owner
    artifact, destination = tmp_path / "snapshot.lane", tmp_path / "restored.sqlite"
    recovery.backup(source, artifact)
    original = artifact.read_bytes()

    def fail(path):
        raise sqlite3.OperationalError("injected private WAL preparation failure")

    with monkeypatch.context() as patch:
        patch.setattr(recovery, "_prepare_wal", fail)
        with pytest.raises(recovery.RecoveryError):
            recovery.restore(artifact, destination)
    assert not destination.exists() and artifact.read_bytes() == original
    recovery.restore(artifact, tmp_path / "new-restored.sqlite")


@pytest.mark.parametrize("observations", [("delete",), ("wal", "delete")])
def test_private_wal_preparation_must_verify_the_actual_mode(
    tmp_path, monkeypatch, observations
):
    closed = []
    observed = iter(observations)

    class Connection:
        def execute(self, command):
            return self

        def fetchone(self):
            return (next(observed),)

        def close(self):
            closed.append(True)

    monkeypatch.setattr(
        recovery.sqlite3, "connect", lambda *args, **kwargs: Connection()
    )
    with pytest.raises(recovery.RecoveryError):
        recovery._prepare_wal(tmp_path / "owned-candidate.sqlite")
    assert closed == [True]


def test_unpublished_candidate_sidecars_refuse_before_publication_without_cleanup_loss(
    owner, tmp_path, monkeypatch
):
    source, _ = owner
    artifact, destination = tmp_path / "snapshot.lane", tmp_path / "restored.sqlite"
    recovery.backup(source, artifact)
    original = artifact.read_bytes()
    prepare = recovery._prepare_wal
    retained = []

    def inject(path):
        prepare(path)
        sidecar = Path(str(path) + "-wal")
        sidecar.write_bytes(b"caller sentinel")
        retained.append(sidecar)

    monkeypatch.setattr(recovery, "_prepare_wal", inject)
    with pytest.raises(recovery.RecoveryError):
        recovery.restore(artifact, destination)
    assert not destination.exists() and artifact.read_bytes() == original
    assert retained[0].read_bytes() == b"caller sentinel"


def test_private_wal_preparation_cannot_change_verified_owner_data(
    owner, tmp_path, monkeypatch
):
    source, store = owner
    store.append("ws", "repo", "control", "p", "batch-0001", 0, [event()])
    artifact, destination = tmp_path / "snapshot.lane", tmp_path / "restored.sqlite"
    recovery.backup(source, artifact)
    original = artifact.read_bytes()
    prepare = recovery._prepare_wal

    def corrupt_candidate(path):
        prepare(path)
        with closing(sqlite3.connect(path)) as db:
            db.execute("UPDATE lane_events SET principal='changed'")
            db.commit()

    monkeypatch.setattr(recovery, "_prepare_wal", corrupt_candidate)
    with pytest.raises(recovery.RecoveryError):
        recovery.restore(artifact, destination)
    assert not destination.exists() and artifact.read_bytes() == original
    assert StreamStore(source).read("ws", "repo", "control")["revision"] == 1


def test_private_wal_preparation_cannot_rewrite_consistent_principals(
    owner, tmp_path, monkeypatch
):
    source, store = owner
    store.append("ws", "repo", "control", "p", "batch-0001", 0, [event()])
    artifact, destination = tmp_path / "snapshot.lane", tmp_path / "restored.sqlite"
    recovery.backup(source, artifact)
    original = artifact.read_bytes()
    prepare = recovery._prepare_wal

    def rewrite_consistent_data(path):
        prepare(path)
        with closing(sqlite3.connect(path)) as db:
            db.execute("UPDATE lane_events SET principal='changed'")
            db.execute("UPDATE lane_batches SET principal='changed'")
            db.commit()

    monkeypatch.setattr(recovery, "_prepare_wal", rewrite_consistent_data)
    with pytest.raises(recovery.RecoveryError):
        recovery.restore(artifact, destination)
    assert not destination.exists() and artifact.read_bytes() == original
