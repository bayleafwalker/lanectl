"""Explicit, bounded recovery artifacts for the schema1 lane owner.

A checksum detects corruption, not authenticity. These local operations never
select event authority or establish quiescence, backup custody or hosted durability.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import struct
import tempfile
import time
import zipfile
from contextlib import closing, contextmanager
from pathlib import Path

from .contracts import validate_event
from .stream_store import (
    MAX_BATCH,
    MAX_BYTES,
    SCHEMA_VERSION,
    StreamError,
    StreamStore,
    encode,
)

FORMAT = "lanectl.stream-backup/v1"
RECEIPT = "lanectl.stream-recovery-receipt/v1"
MAX_PAYLOAD = 1024 * 1024 * 1024
MAX_MANIFEST = 1024 * 1024
MAX_EVENTS = 1_000_000
MAX_BATCHES = 100_000
MAX_SCOPES = 4096
CHUNK = 1024 * 1024
MEMBERS = ("manifest.json", "owner.sqlite")
_TABLES = {
    "lane_events": """CREATE TABLE lane_events (
        workspace TEXT NOT NULL, repo TEXT NOT NULL, stream TEXT NOT NULL,
        revision INTEGER NOT NULL, event TEXT NOT NULL, principal TEXT NOT NULL,
        PRIMARY KEY(workspace,repo,stream,revision))""",
    "lane_batches": """CREATE TABLE lane_batches (
        workspace TEXT NOT NULL, repo TEXT NOT NULL, stream TEXT NOT NULL,
        principal TEXT NOT NULL, key TEXT NOT NULL, digest TEXT NOT NULL,
        result TEXT NOT NULL, PRIMARY KEY(workspace,repo,stream,principal,key))""",
}


class RecoveryError(RuntimeError):
    """A refused operation; published identifies any existing unactivated result."""

    def __init__(self, message, *, published=None):
        super().__init__(message)
        self.published = published


def _path(value):
    path = Path(value)
    if ".." in path.parts:
        raise RecoveryError("unsafe-path: parent traversal is not supported")
    path = path.absolute()
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            break
        if stat.S_ISLNK(mode):
            raise RecoveryError("unsafe-path: symlinks are refused")
    return path


@contextmanager
def _parent(path):
    parent = path.parent
    fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise RecoveryError("unsafe-path: parent must be owned and mode0700")
        yield fd
        current = parent.lstat()
        if (
            (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino)
            or not stat.S_ISDIR(current.st_mode)
            or current.st_uid != os.getuid()
            or stat.S_IMODE(current.st_mode) != 0o700
        ):
            raise RecoveryError("unsafe-path: parent identity/permissions changed")
    finally:
        os.close(fd)


def _regular(info):
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_nlink != 1
        or stat.S_IMODE(info.st_mode) not in (0o400, 0o600)
    ):
        raise RecoveryError(
            "unsafe-path: input must be an owned private regular file without aliases"
        )


@contextmanager
def _input(path):
    with _parent(path):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            _regular(os.fstat(fd))
            yield fd
            _same_input(path, fd)
        finally:
            os.close(fd)


def _same_input(path, fd):
    actual, expected = path.lstat(), os.fstat(fd)
    _regular(actual)
    if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
        raise RecoveryError("unsafe-path: input identity changed")


def _fresh(path, parent_fd):
    for name in (
        path.name,
        path.name + "-wal",
        path.name + "-shm",
        path.name + "-journal",
    ):
        try:
            os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        raise RecoveryError(
            "existing-destination: destination or SQLite sidecar exists; inspect the existing unactivated result, replacement is refused"
        )


@contextmanager
def _stage(parent):
    root = Path(tempfile.mkdtemp(prefix=".lanectl-recovery-", dir=parent))
    root.chmod(0o700)
    identity = root.stat()
    owned = {}
    try:
        yield root, owned
    finally:
        try:
            actual = root.lstat()
            if (
                (actual.st_dev, actual.st_ino) != (identity.st_dev, identity.st_ino)
                or not stat.S_ISDIR(actual.st_mode)
                or actual.st_uid != os.getuid()
            ):
                raise RecoveryError(
                    "cleanup-refused: candidate directory identity changed"
                )
            for entry in root.iterdir():
                info = entry.lstat()
                original = os.fstat(owned[entry.name]) if entry.name in owned else None
                if (
                    original is None
                    or not stat.S_ISREG(info.st_mode)
                    or (info.st_dev, info.st_ino) != (original.st_dev, original.st_ino)
                ):
                    raise RecoveryError(
                        "cleanup-refused: unexpected candidate entry retained"
                    )
            for entry in root.iterdir():
                entry.unlink()
            root.rmdir()
        finally:
            for fd in owned.values():
                os.close(fd)


def _new_file(path, owned):
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        # Keep an inode reference through cleanup, preventing inode reuse from
        # disguising a replaced candidate as one this operation created.
        owned[path.name] = os.dup(fd)
        os.fchmod(fd, 0o600)
        return os.fdopen(fd, "w+b")
    except BaseException:
        os.close(fd)
        raise


def _sync_file(path):
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


def _sync_parent(fd):
    os.fsync(fd)


def _link(candidate, destination, parent_fd):
    # Both names are on the destination filesystem. link() cannot replace a name.
    os.link(candidate, destination.name, dst_dir_fd=parent_fd, follow_symlinks=False)


def _check_publication(candidate, destination, parent_fd):
    expected = candidate.lstat()
    actual = os.stat(destination.name, dir_fd=parent_fd, follow_symlinks=False)
    if (
        not stat.S_ISREG(actual.st_mode)
        or actual.st_nlink != 2
        or expected.st_nlink != 2
        or actual.st_uid != os.getuid()
        or stat.S_IMODE(actual.st_mode) != 0o600
        or (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino)
    ):
        raise RecoveryError(
            "publication-identity-changed: inspect the existing unactivated result"
        )
    for suffix in ("-wal", "-shm", "-journal"):
        try:
            os.stat(destination.name + suffix, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        raise RecoveryError(
            "publication-sidecar-appeared: inspect the existing unactivated result"
        )


def _hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _copy(source, destination, *, limit):
    digest, count = hashlib.sha256(), 0
    while chunk := source.read(CHUNK):
        count += len(chunk)
        if count > limit:
            raise RecoveryError("resource-limit: payload exceeds its declared bound")
        destination.write(chunk)
        digest.update(chunk)
    return count, digest.hexdigest()


def _connect(path):
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 2 * MAX_BYTES + 4096)
        db.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 32768)
        db.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("PRAGMA query_only=ON")
        return db
    except BaseException:
        db.close()
        raise


def _normalized(sql):
    return " ".join(sql.split()).lower() if sql is not None else None


def _catalog(db):
    if db.execute("PRAGMA user_version").fetchone() != (SCHEMA_VERSION,):
        raise RecoveryError("unsupported-owner-schema")
    expected = sorted(
        [("table", name, name, _normalized(sql)) for name, sql in _TABLES.items()]
        + [("index", "sqlite_autoindex_" + name + "_1", name, None) for name in _TABLES]
    )
    actual = sorted(
        (kind, name, table, _normalized(sql))
        for kind, name, table, sql in db.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master"
        )
    )
    if actual != expected:
        raise RecoveryError("unsupported-owner-catalog")
    if db.execute("PRAGMA integrity_check(1)").fetchall() != [("ok",)]:
        raise RecoveryError("corrupt-owner-database")


def _scope(values):
    StreamStore._scope(*values)
    return tuple(values)


def _inspect(path):
    if path.stat().st_size > MAX_PAYLOAD:
        raise RecoveryError("resource-limit: database exceeds1GiB")
    with closing(_connect(path)) as db:
        _catalog(db)
        counts = {
            name: db.execute("SELECT count(*) FROM " + name).fetchone()[0]
            for name in _TABLES
        }
        if counts["lane_events"] > MAX_EVENTS or counts["lane_batches"] > MAX_BATCHES:
            raise RecoveryError("resource-limit: event/batch count")
        heads = []
        head_map = {}
        for workspace, repo, stream, head, count in db.execute(
            "SELECT workspace,repo,stream,max(revision),count(*) FROM lane_events "
            "GROUP BY workspace,repo,stream ORDER BY workspace,repo,stream LIMIT ?",
            (MAX_SCOPES + 1,),
        ):
            scope = _scope((workspace, repo, stream))
            if len(heads) >= MAX_SCOPES or type(head) is not int or head != count:
                raise RecoveryError("invalid-owner-history: scope/revision bound")
            head_map[scope] = head
            heads.append(
                dict(zip(("workspace", "repo", "stream", "revision"), (*scope, head)))
            )
        cursor, prior_scope = 0, None
        for workspace, repo, stream, revision, raw, principal in db.execute(
            "SELECT * FROM lane_events ORDER BY workspace,repo,stream,revision"
        ):
            scope = _scope((workspace, repo, stream))
            if scope != prior_scope:
                cursor, prior_scope = 0, scope
            cursor += 1
            if (
                type(revision) is not int
                or revision != cursor
                or not isinstance(principal, str)
                or not principal
            ):
                raise RecoveryError("invalid-owner-history: event revision/principal")
            value = json.loads(raw)
            validate_event(value)
            if encode(value) != raw:
                raise RecoveryError("invalid-owner-history: noncanonical event")
        intervals = {}
        for workspace, repo, stream, principal, key, digest, raw in db.execute(
            "SELECT * FROM lane_batches"
        ):
            scope = _scope((workspace, repo, stream))
            if (
                scope not in head_map
                or not isinstance(principal, str)
                or not principal
                or not isinstance(key, str)
                or not 8 <= len(key) <= 128
                or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
            ):
                raise RecoveryError("invalid-owner-history: batch identity")
            result = json.loads(raw)
            if (
                not isinstance(result, dict)
                or set(result) != {"previous_revision", "revision", "count", "replayed"}
                or any(
                    type(result.get(k)) is not int
                    for k in ("previous_revision", "revision", "count")
                )
                or result["replayed"] is not False
                or result["previous_revision"] < 0
                or not 1 <= result["count"] <= MAX_BATCH
                or result["revision"] != result["previous_revision"] + result["count"]
                or result["revision"] > head_map[scope]
                or encode(result) != raw
            ):
                raise RecoveryError("invalid-owner-history: batch result")
            previous, revision = result["previous_revision"], result["revision"]
            events = db.execute(
                "SELECT event,principal FROM lane_events WHERE workspace=? AND repo=? AND stream=? "
                "AND revision>? AND revision<=? ORDER BY revision",
                (*scope, previous, revision),
            ).fetchall()
            values = [json.loads(event) for event, _ in events]
            encoded = encode(values)
            if (
                len(events) != result["count"]
                or any(p != principal for _, p in events)
                or len(encoded.encode()) > MAX_BYTES
                or hashlib.sha256(encode([previous, values]).encode()).hexdigest()
                != digest
            ):
                raise RecoveryError(
                    "invalid-owner-history: batch/event digest mismatch"
                )
            intervals.setdefault(scope, []).append((previous, revision))
        for scope, head in head_map.items():
            cursor = 0
            for previous, revision in sorted(intervals.get(scope, [])):
                if previous != cursor:
                    raise RecoveryError(
                        "invalid-owner-history: overlapping or missing batch"
                    )
                cursor = revision
            if cursor != head:
                raise RecoveryError("invalid-owner-history: missing batch")
    return {"counts": counts, "heads": heads}


def _backup_progress(status, remaining, total, started, page_size):
    if total * page_size > MAX_PAYLOAD or time.monotonic() - started > 300:
        raise RecoveryError("resource-limit: online backup deadline/pages")


def _online_snapshot(source, destination, owned):
    with _new_file(destination, owned):
        pass
    with (
        closing(_connect(source)) as origin,
        closing(sqlite3.connect(destination)) as snapshot,
    ):
        _catalog(origin)
        page_size = origin.execute("PRAGMA page_size").fetchone()[0]
        if origin.execute("PRAGMA page_count").fetchone()[0] * page_size > MAX_PAYLOAD:
            raise RecoveryError("resource-limit: database exceeds1GiB")
        started = time.monotonic()
        origin.backup(
            snapshot,
            pages=128,
            progress=lambda *args: _backup_progress(*args, started, page_size),
            sleep=0.01,
        )
        # Only the candidate changes journal mode, making its payload standalone.
        snapshot.execute("PRAGMA journal_mode=DELETE")
    _sync_file(destination)


def _info(name):
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    info.compress_type = zipfile.ZIP_STORED
    return info


def _manifest(path):
    return {
        "schema": FORMAT,
        "owner_schema": SCHEMA_VERSION,
        "payload": {
            "member": "owner.sqlite",
            "sha256": _hash(path),
            "bytes": path.stat().st_size,
        },
        **_inspect(path),
    }


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RecoveryError("invalid-manifest: duplicate key")
        result[key] = value
    return result


def _nonfinite(_value):
    raise RecoveryError("invalid-manifest: nonfinite value")


def _manifest_shape(value):
    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "owner_schema", "payload", "counts", "heads"}
        or value["schema"] != FORMAT
        or type(value["owner_schema"]) is not int
        or value["owner_schema"] != SCHEMA_VERSION
    ):
        raise RecoveryError("unsupported-artifact-schema")
    payload, counts, heads = value["payload"], value["counts"], value["heads"]
    if (
        not isinstance(payload, dict)
        or set(payload) != {"member", "sha256", "bytes"}
        or payload["member"] != "owner.sqlite"
        or type(payload["bytes"]) is not int
        or not 1 <= payload["bytes"] <= MAX_PAYLOAD
        or not isinstance(payload["sha256"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", payload["sha256"])
        or not isinstance(counts, dict)
        or set(counts) != set(_TABLES)
        or any(type(n) is not int or n < 0 for n in counts.values())
        or counts["lane_events"] > MAX_EVENTS
        or counts["lane_batches"] > MAX_BATCHES
        or not isinstance(heads, list)
        or len(heads) > MAX_SCOPES
    ):
        raise RecoveryError("invalid-manifest: payload/counts/heads")
    scopes = []
    for head in heads:
        if (
            not isinstance(head, dict)
            or set(head) != {"workspace", "repo", "stream", "revision"}
            or type(head["revision"]) is not int
            or not 1 <= head["revision"] <= MAX_EVENTS
        ):
            raise RecoveryError("invalid-manifest: scope head")
        scopes.append(_scope(tuple(head[k] for k in ("workspace", "repo", "stream"))))
    if scopes != sorted(set(scopes)):
        raise RecoveryError("invalid-manifest: duplicate/unsorted scope")


@contextmanager
def _bundle(stream):
    # Bound central-directory allocation before ZipFile parses untrusted entries.
    size = os.fstat(stream.fileno()).st_size
    if not 22 <= size <= MAX_PAYLOAD + MAX_MANIFEST + 8192:
        raise RecoveryError("resource-limit: artifact size")
    stream.seek(-22, os.SEEK_END)
    end = struct.unpack("<4s4H2LH", stream.read(22))
    if (
        end[:5] != (b"PK\x05\x06", 0, 0, 2, 2)
        or end[-1] != 0
        or end[5] > 4096
        or end[6] + end[5] != size - 22
    ):
        raise RecoveryError("invalid-artifact: closed two-member ZIP required")
    stream.seek(0)
    with zipfile.ZipFile(stream) as bundle:
        infos = bundle.infolist()
        if [i.filename for i in infos] != list(MEMBERS):
            raise RecoveryError("invalid-artifact: exact ordered members required")
        offset = 0
        for info, limit in zip(infos, (MAX_MANIFEST, MAX_PAYLOAD)):
            if (
                info.compress_type != zipfile.ZIP_STORED
                or info.flag_bits != 0
                or info.extra
                or info.comment
                or info.create_system != 3
                or info.external_attr >> 16 != stat.S_IFREG | 0o600
                or info.file_size != info.compress_size
                or not 0 < info.file_size <= limit
                or info.header_offset != offset
            ):
                raise RecoveryError("invalid-artifact: member type/size/flags")
            stream.seek(offset)
            header = struct.unpack("<4s5H3L2H", stream.read(30))
            name = stream.read(header[-2])
            if (
                header[0] != b"PK\x03\x04"
                or header[2] != 0
                or header[3] != 0
                or header[6:9] != (info.CRC, info.compress_size, info.file_size)
                or header[-1] != 0
                or name != info.filename.encode("ascii")
            ):
                raise RecoveryError("invalid-artifact: local member header")
            offset += 30 + len(name) + info.file_size
        if offset != end[6]:
            raise RecoveryError("invalid-artifact: trailing or hidden payload")
        raw = bundle.read("manifest.json")
        manifest = json.loads(
            raw,
            object_pairs_hook=_unique,
            parse_constant=_nonfinite,
        )
        _manifest_shape(manifest)
        if manifest["payload"]["bytes"] != infos[1].file_size:
            raise RecoveryError("invalid-manifest: payload length")
        yield bundle, manifest


def _receipt(operation, artifact, artifact_hash, manifest, destination=None):
    return {
        "schema": RECEIPT,
        "ok": True,
        "operation": operation,
        "artifact": str(artifact),
        "artifact_sha256": artifact_hash,
        "owner_schema": SCHEMA_VERSION,
        "payload_sha256": manifest["payload"]["sha256"],
        **{k: manifest[k] for k in ("counts", "heads")},
        **({"database": str(destination)} if destination else {}),
        "authority_changed": False,
        "quiescence": "not-asserted",
    }


def backup(database, artifact):
    published = None
    try:
        database, artifact = _path(database), _path(artifact)
        with _input(database) as source_fd, _parent(artifact) as parent_fd:
            _fresh(artifact, parent_fd)
            if os.fstat(source_fd).st_size > MAX_PAYLOAD:
                raise RecoveryError("resource-limit: database exceeds1GiB")
            with _stage(artifact.parent) as (stage, owned):
                snapshot, candidate = stage / "snapshot.sqlite", stage / "artifact.tmp"
                _online_snapshot(database, snapshot, owned)
                _same_input(database, source_fd)
                manifest = _manifest(snapshot)
                encoded = encode(manifest).encode()
                if len(encoded) > MAX_MANIFEST:
                    raise RecoveryError("resource-limit: manifest size")
                with (
                    _new_file(candidate, owned) as output,
                    zipfile.ZipFile(output, "w", allowZip64=False) as bundle,
                ):
                    bundle.writestr(_info("manifest.json"), encoded)
                    with (
                        snapshot.open("rb") as payload,
                        bundle.open(_info("owner.sqlite"), "w") as target,
                    ):
                        _copy(payload, target, limit=MAX_PAYLOAD)
                _sync_file(candidate)
                artifact_hash = _hash(candidate)
                _fresh(artifact, parent_fd)
                _link(candidate, artifact, parent_fd)
                published = str(artifact)
                _sync_parent(parent_fd)
                _check_publication(candidate, artifact, parent_fd)
            return _receipt("backup", artifact, artifact_hash, manifest)
    except (
        OSError,
        sqlite3.Error,
        zipfile.BadZipFile,
        struct.error,
        RecursionError,
        NotImplementedError,
        ValueError,
        TypeError,
        KeyError,
        StreamError,
        RecoveryError,
    ) as error:
        raise RecoveryError(str(error), published=published) from error


def restore(artifact, destination):
    published = None
    try:
        artifact, destination = _path(artifact), _path(destination)
        with _input(artifact) as source_fd, _parent(destination) as parent_fd:
            _fresh(destination, parent_fd)
            with _stage(destination.parent) as (stage, owned):
                # Parse a bounded owned copy, so the receipt hashes exactly the
                # artifact bytes consumed even if a caller writes its input.
                artifact_copy = stage / "artifact.tmp"
                original_stat = os.fstat(source_fd)
                with (
                    os.fdopen(os.dup(source_fd), "rb") as source,
                    _new_file(artifact_copy, owned) as copied,
                ):
                    artifact_bytes, artifact_hash = _copy(
                        source, copied, limit=MAX_PAYLOAD + MAX_MANIFEST + 8192
                    )
                current_stat = os.fstat(source_fd)
                if (
                    original_stat.st_size,
                    original_stat.st_mtime_ns,
                    original_stat.st_ctime_ns,
                ) != (
                    current_stat.st_size,
                    current_stat.st_mtime_ns,
                    current_stat.st_ctime_ns,
                ) or artifact_bytes != original_stat.st_size:
                    raise RecoveryError("unsafe-path: artifact changed while copying")
                candidate = stage / "owner.sqlite"
                with (
                    artifact_copy.open("rb") as stream,
                    _bundle(stream) as (bundle, manifest),
                    _new_file(candidate, owned) as output,
                ):
                    with bundle.open("owner.sqlite") as payload:
                        count, digest = _copy(
                            payload, output, limit=manifest["payload"]["bytes"]
                        )
                    if (count, digest) != (
                        manifest["payload"]["bytes"],
                        manifest["payload"]["sha256"],
                    ):
                        raise RecoveryError(
                            "invalid-artifact: payload length/hash mismatch"
                        )
                if _inspect(candidate) != {k: manifest[k] for k in ("counts", "heads")}:
                    raise RecoveryError(
                        "invalid-artifact: measured counts/heads mismatch"
                    )
                _sync_file(candidate)
                _same_input(artifact, source_fd)
                _fresh(destination, parent_fd)
                _link(candidate, destination, parent_fd)
                published = str(destination)
                _sync_parent(parent_fd)
                _check_publication(candidate, destination, parent_fd)
            return _receipt("restore", artifact, artifact_hash, manifest, destination)
    except (
        OSError,
        sqlite3.Error,
        zipfile.BadZipFile,
        struct.error,
        RecursionError,
        NotImplementedError,
        ValueError,
        TypeError,
        KeyError,
        StreamError,
        RecoveryError,
    ) as error:
        raise RecoveryError(str(error), published=published) from error
