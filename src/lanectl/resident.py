"""Bounded resident episodes under the existing lanectl execution owner.

No timer, model loop, WorkRelease acceptance or automatic publication lives
here. A protected profile selects an already qualified launcher. File locks
exclude coordinators on this host; the existing event log owns receipts and
generation state. A native persistent Goal is a different execution profile.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import signal
import stat
import subprocess
import sys
import time
import uuid

from . import child_process, reap
from .contracts import ContractError, check_id
from .events import EventLog
from .resident_contract import WORKER_STOPS, generation as validate_generation, sha256


MAX_CONTEXT = 256 * 1024
MAX_RESULT = 64 * 1024
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
MAX_ARTIFACTS = 128
MAX_OUTPUT = 2 * 1024 * 1024


class ResidentError(ValueError):
    pass


def _require_local_log(log):
    # Buffered remote append and host-local locks do not establish a durable,
    # distributed admission/fence critical section. Never silently substitute
    # a local log for an already selected served authority.
    if type(log) is not EventLog:
        raise ResidentError("resident episodes require the local durable EventLog on one protected host; "
                            "remote or buffered backends are not qualified")


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                       allow_nan=False) + "\n").encode()


def _canonical(value):
    """AgentOps resident-context/v1 canonical JSON (no trailing newline)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode()


def _regular_bytes(path, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ResidentError("expected a regular file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ResidentError("file exceeds the configured byte bound")
        return data
    finally:
        os.close(fd)


def assert_protected_file(path):
    """Root-owned configuration, including both symlink and target ancestry.

NixOS /etc symlinks into the store are valid. A profile in an agent-writable
checkout is not qualification, even if it happens to contain qualified=true.
"""
    path = Path(path).absolute()
    for candidate in dict.fromkeys((path, *path.parents, path.resolve(), *path.resolve().parents)):
        info = candidate.lstat()
        if info.st_uid != 0 or (not stat.S_ISLNK(info.st_mode) and info.st_mode & 0o022):
            raise ResidentError(f"configuration must be root-protected: {candidate}")
    if not path.resolve().is_file():
        raise ResidentError("protected configuration must resolve to a regular file")


_protected_file = assert_protected_file


def _relative(value):
    if (not isinstance(value, str) or not value or "\\" in value
            or any(ord(c) < 32 for c in value) or value.startswith("/")):
        raise ResidentError("artifact path must be a safe relative path")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ResidentError("artifact path must be a safe relative path")
    return PurePosixPath(value)


@dataclass(frozen=True)
class Profile:
    path: Path
    raw: dict
    digest: str
    recipe_digest: str
    resident_id: str
    workspace: Path
    state_dir: Path
    artifact_roots: tuple[str, ...]

    @property
    def execution(self):
        return self.raw.get("execution", {})

    @property
    def root(self):
        return self.state_dir / self.resident_id


def load_profile(path):
    path = Path(path).absolute()
    data = _regular_bytes(path.resolve(), MAX_RESULT)
    try:
        raw = json.loads(data)
        if not isinstance(raw, dict) or raw.get("schema") != "lanectl.resident-profile/v1":
            raise ResidentError("invalid resident profile schema")
        check_id("resident_id", raw.get("resident_id"))
        for key in ("workspace", "state_dir"):
            if not isinstance(raw.get(key), str) or not Path(raw[key]).is_absolute():
                raise ResidentError(f"profile {key} must be an absolute path")
        workspace, state_dir = Path(raw["workspace"]).resolve(), Path(raw["state_dir"]).resolve()
        if not workspace.is_dir():
            raise ResidentError("resident workspace does not exist")
        if workspace == state_dir or workspace in state_dir.parents or state_dir in workspace.parents:
            raise ResidentError("resident state and workspace must be separate trees")
        if path == workspace or workspace in path.parents:
            raise ResidentError("resident profile cannot live in its writable workspace")
        roots = raw.get("artifact_roots", [])
        if not isinstance(roots, list) or not roots or len(roots) > MAX_ARTIFACTS:
            raise ResidentError("explicit artifact_roots are required")
        for root in roots:
            _relative(root)
        execution = raw.get("execution", {})
        if not isinstance(execution, dict) or type(execution.get("enabled", False)) is not bool:
            raise ResidentError("invalid execution profile")
        if type(raw.get("require_source_recheck", True)) is not bool:
            raise ResidentError("require_source_recheck must be a boolean")
        recipe = dict(raw, execution={k: v for k, v in execution.items()
                                     if k not in ("qualification_file", "qualification_sha256")})
        return Profile(path, raw, _digest(data), _digest(_json_bytes(recipe)), raw["resident_id"],
                       workspace, state_dir, tuple(roots))
    except (ContractError, TypeError, json.JSONDecodeError) as exc:
        raise ResidentError(f"invalid resident profile: {exc}") from exc


def describe_profile(path):
    p = load_profile(path)
    return {"schema": "lanectl.resident-profile-description/v1", "resident_id": p.resident_id,
            "profile_sha256": p.digest, "recipe_sha256": p.recipe_digest,
            "execution_enabled": p.execution.get("enabled", False),
            "workspace": str(p.workspace), "state_dir": str(p.state_dir)}


def _qualify(p):
    e = p.execution
    argv = e.get("argv")
    if (not isinstance(argv, list) or not argv or len(argv) > 64
            or any(not isinstance(arg, str) or "\0" in arg or len(arg) > MAX_RESULT for arg in argv)
            or not Path(argv[0]).is_absolute()):
        raise ResidentError("qualified launcher requires a bounded absolute argv")
    if not isinstance(e.get("route"), str) or not e["route"].strip():
        raise ResidentError("an explicit qualified route is required")
    timeout = e.get("timeout_s", 2700)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not .01 <= timeout <= 2700:
        raise ResidentError("episode timeout must be between .01 and 2700 seconds")
    try:
        sha256(e.get("executable_sha256"), "executable_sha256")
        sha256(e.get("qualification_sha256"), "qualification_sha256")
    except ContractError as exc:
        raise ResidentError(str(exc)) from exc
    _protected_file(Path(argv[0]))
    executable = Path(argv[0]).resolve()
    if _digest(_regular_bytes(executable, 256 * 1024 * 1024)) != e["executable_sha256"]:
        raise ResidentError("qualified executable digest changed")
    qpath = e.get("qualification_file")
    if not isinstance(qpath, str) or not Path(qpath).is_absolute():
        raise ResidentError("protected qualification_file is required")
    _protected_file(Path(qpath))
    qbytes = _regular_bytes(Path(qpath).resolve(), MAX_RESULT)
    if _digest(qbytes) != e["qualification_sha256"]:
        raise ResidentError("qualification receipt digest mismatch")
    q = json.loads(qbytes)
    if not isinstance(q, dict) or q.get("schema") != "lanectl.resident-qualification/v1":
        raise ResidentError("invalid qualification receipt")
    if q.get("recipe_sha256") != p.recipe_digest:
        raise ResidentError("qualification does not bind this recipe")
    for field in ("provider_credentials_isolated", "execution_boundary_enforced", "budget_enforced",
                  "source_recheck_enforced"):
        if q.get(field) is not True:
            raise ResidentError(f"qualification does not establish {field}")
    try:
        until = datetime.fromisoformat(q["valid_until"].replace("Z", "+00:00"))
        if until.tzinfo is None or until <= datetime.now(timezone.utc):
            raise ResidentError("qualification has expired")
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ResidentError):
            raise
        raise ResidentError("qualification expiry is invalid") from exc
    return argv, float(timeout)


def _validate_context(p, data):
    try:
        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ResidentError("context contains a duplicate JSON object key")
                result[key] = value
            return result

        packet = json.loads(data, object_pairs_hook=unique_object)
        if (not isinstance(packet, dict) or packet.get("schema") != "resident-context/v1"
                or packet.get("status") != "ready" or packet.get("authorizes_effects") is not False
                or packet.get("blockers") != []):
            raise ResidentError("context must be a ready, non-authorizing resident-context/v1 packet")
        sha256(packet.get("digest"), "context internal digest")
        body = {key: value for key, value in packet.items() if key != "digest"}
        if _digest(_canonical(body)) != packet["digest"]:
            raise ResidentError("context internal digest mismatch")
        if set(packet) != {"schema", "scope", "status", "authorizes_effects", "budget", "sections",
                           "blockers", "omissions", "source_refs", "digest"}:
            raise ResidentError("context has unknown or missing envelope fields")
        scope = packet.get("scope")
        if (not isinstance(scope, dict) or set(scope) != {"resident", "project", "branch"}
                or scope.get("resident") != p.resident_id
                or any(not isinstance(v, str) or not v.strip() or len(v) > 256 for v in scope.values())):
            raise ResidentError("context scope does not match the resident profile")
        if "context_scope" in p.raw and p.raw["context_scope"] != scope:
            raise ResidentError("context scope does not match the qualified project/branch")
        sections = packet.get("sections")
        expected = ("instructions", "current_work", "required_sources", "orientation", "memories", "worker_outputs")
        if (not isinstance(sections, list) or len(sections) != len(expected)
                or any(not isinstance(s, dict) or set(s) != {"kind", "items"} for s in sections)
                or tuple(s.get("kind") for s in sections) != expected):
            raise ResidentError("context sections must have the exact ordered, unique schema")
        sources = {}
        section_ids = {kind: set() for kind in expected}
        for section in sections:
            items = section.get("items")
            if not isinstance(items, list) or len(items) > 256:
                raise ResidentError("context section items are invalid")
            if section["kind"] in ("instructions", "current_work") and len(items) != 1:
                raise ResidentError("context requires one instructions and current-work entry")
            if section["kind"] == "orientation" and len(items) > 1:
                raise ResidentError("context permits only one orientation entry")
            identifiers = section_ids[section["kind"]]
            for item in items:
                if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                        or not item["id"].strip() or len(item["id"]) > 256 or item["id"] in identifiers):
                    raise ResidentError("context section item identities are invalid or duplicated")
                if section["kind"] in ("instructions", "current_work", "orientation"):
                    if set(item) != {"id", "content"} or item["id"] != section["kind"]:
                        raise ResidentError("context mandatory section item has invalid identity or fields")
                    content = item["content"]
                    if section["kind"] == "current_work" and isinstance(content, dict) and content:
                        continue
                    if not isinstance(content, str) or not content.strip():
                        raise ResidentError("context mandatory section content is empty or malformed")
                    continue
                identifiers.add(item["id"])
                if set(item) not in ({"id", "content", "source_refs", "status"},
                                     {"id", "content", "source_refs", "status", "scope"}):
                    raise ResidentError("context source-bearing entry has unknown or missing fields")
                refs = item.get("source_refs", [])
                if not isinstance(refs, list) or len(refs) > 64:
                    raise ResidentError("context item source references are invalid")
                if section["kind"] in ("required_sources", "memories", "worker_outputs"):
                    if (not refs or item.get("status") not in ("current", "advisory", "provisional", "supported",
                                                               "disputed", "observation", "candidate")
                            or not isinstance(item.get("content"), str) or not item["content"].strip()):
                        raise ResidentError("context source-bearing entry lacks a usable basis/status/content")
                    if ((section["kind"] != "required_sources" or "scope" in item)
                            and item.get("scope") != scope):
                        raise ResidentError("context memory/worker scope is missing or mismatched")
                for ref in refs:
                    if (not isinstance(ref, dict) or set(ref) != {"source_id", "revision", "sha256"}
                            or any(not isinstance(ref.get(k), str) or not ref[k].strip() or len(ref[k]) > 512
                                   for k in ("source_id", "revision"))):
                        raise ResidentError("context source reference is malformed")
                    sha256(ref.get("sha256"), "context source sha256")
                    sources[(ref["source_id"], ref["revision"], ref["sha256"])] = ref
        if packet.get("source_refs") != [sources[key] for key in sorted(sources)]:
            raise ResidentError("context source_refs must equal the exact section reference union")
        budget = packet["budget"]
        if not isinstance(budget, dict) or set(budget) != {"max_bytes", "max_tokens", "token_measurement"}:
            raise ResidentError("context budget fields are invalid")
        bound, tokens = budget["max_bytes"], budget["max_tokens"]
        if (type(bound) is not int or not 1 <= bound <= 16 * 1024 * 1024
                or len(_canonical(packet)) > bound):
            raise ResidentError("context exceeds its declared serialized budget")
        if ((tokens is not None and (type(tokens) is not int or tokens < 1))
                or budget["token_measurement"] != ("not-measured" if tokens is None else "caller-tokenizer")):
            raise ResidentError("context token measurement is invalid")
        omissions = packet["omissions"]
        reasons = {"scope-unavailable", "scope-mismatch", "inactive-or-unsupported-status",
                   "source-basis-unavailable", "source-unavailable", "source-changed", "budget"}
        if not isinstance(omissions, list) or len(omissions) > 513:
            raise ResidentError("context omissions are invalid")
        for omitted in omissions:
            if not isinstance(omitted, dict) or set(omitted) != {"section", "id", "reason"}:
                raise ResidentError("context omission fields are invalid")
            kind, ident, reason = omitted["section"], omitted["id"], omitted["reason"]
            if (kind not in ("orientation", "memories", "worker_outputs")
                    or not isinstance(ident, str) or not ident.strip() or len(ident) > 256
                    or not isinstance(reason, str) or reason not in reasons or ident in section_ids[kind]):
                raise ResidentError("context omission contradicts the included sections")
            if kind == "orientation" and (ident != "orientation" or reason != "budget" or sections[3]["items"]):
                raise ResidentError("context orientation omission is invalid")
            section_ids[kind].add(ident)
            if len(section_ids[kind]) > 256:
                raise ResidentError("context section and omission count exceeds its bound")
        return packet
    except (TypeError, ValueError, AttributeError) as exc:
        if isinstance(exc, ResidentError):
            raise
        raise ResidentError(f"invalid context packet: {exc}") from exc


def _check_recheck_window(receipt):
    checked = datetime.fromisoformat(receipt["checked_at"].replace("Z", "+00:00"))
    until = datetime.fromisoformat(receipt["valid_until"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    if (checked.tzinfo is None or until.tzinfo is None or not checked <= now <= until
            or not 0 < (until - checked).total_seconds() <= 60):
        raise ResidentError("source-recheck receipt is not fresh within a maximum 60-second window")


def _source_recheck(p, packet, context_sha256, generation, path, digest):
    if path is None:
        if p.raw.get("require_source_recheck", True):
            raise ResidentError("a protected source-recheck receipt is required")
        return None
    _protected_file(Path(path))
    data = _regular_bytes(Path(path).resolve(), MAX_RESULT)
    if _digest(data) != digest:
        raise ResidentError("source-recheck file digest mismatch")
    try:
        receipt = json.loads(data)
        if (not isinstance(receipt, dict) or receipt.get("schema") != "resident-context-recheck/v1"
                or receipt.get("status") != "unchanged" or receipt.get("authorizes_effects") is not False
                or receipt.get("context_digest") != packet["digest"]
                or receipt.get("context_sha256") != context_sha256
                or type(receipt.get("generation")) is not int or receipt["generation"] != generation
                or receipt.get("changes", []) != []):
            raise ResidentError("source-recheck receipt does not bind the admitted context/generation")
        _check_recheck_window(receipt)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        if isinstance(exc, ResidentError):
            raise
        raise ResidentError(f"invalid source-recheck receipt: {exc}") from exc
    return data


def _view(events, p):
    for event in events:
        if (event["type"] == "resident.initialized" and event["data"]["workspace"] == str(p.workspace)
                and (event["data"]["resident_id"] != p.resident_id
                     or event["data"]["state_dir"] != str(p.state_dir))):
            raise ResidentError("workspace is already bound to a resident and coordination root")
    rows = [e for e in events if e["type"].startswith("resident.")
            and e["data"]["resident_id"] == p.resident_id]
    initial = next((e["data"] for e in rows if e["type"] == "resident.initialized"), None)
    if initial and (initial["workspace"] != str(p.workspace) or initial["state_dir"] != str(p.state_dir)):
        raise ResidentError("resident identity is already bound to another workspace/state root")
    gen = initial["generation"] if initial else 1
    finished, started, wakes = {}, {}, {}
    for e in rows:
        d = e["data"]
        if e["type"] == "resident.generation.fenced":
            if d["previous_generation"] != gen:
                raise ResidentError("resident generation history is inconsistent")
            gen = d["generation"]
        elif e["type"] == "resident.wake" and d["status"] != "duplicate":
            wakes.setdefault(d["wake_id"], d)
        elif e["type"] == "resident.episode.started":
            started[d["episode_id"]] = d
        elif e["type"] == "resident.episode.finished":
            finished[d["episode_id"]] = d
    active = [dict(w, **started.get(w["episode_id"], {})) for w in wakes.values()
              if w["status"] == "admitted"
              and finished.get(w["episode_id"], {}).get("outcome", "unknown") == "unknown"]
    return {"initialized": initial is not None, "generation": gen, "wakes": wakes,
            "started": started, "finished": finished, "active": active}


def _read_view(log, p):
    with log.locked():
        return _view(log.read(), p)


def _initialize(log, p):
    view = _view(log.read(), p)
    if not view["initialized"]:
        log.append("resident.initialized", {"resident_id": p.resident_id,
                   "workspace": str(p.workspace), "state_dir": str(p.state_dir), "generation": 1})
    return view


@contextmanager
def _coordinator(p):
    locks = p.state_dir / "workspace-locks"
    locks.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = locks / (_digest(str(p.workspace).encode()) + ".lock")
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    acquired = False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            pass
        yield acquired
    finally:
        if acquired:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _store(p, data):
    digest = _digest(data)
    directory = p.root / "objects"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / f"{digest}.blob"
    staged = directory / f".{digest}-{uuid.uuid4().hex}.tmp"
    fd = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            # Same-filesystem no-clobber publication occurs only after all bytes
            # are durable. A crash may leave staging debris, never a partial
            # object under its final content digest.
            os.link(staged, path, follow_symlinks=False)
        except FileExistsError:
            if _regular_bytes(path, max(len(data), 1)) != data:
                raise ResidentError("immutable checkpoint object is corrupt")
        dirfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        staged.unlink(missing_ok=True)
    return path, digest


def _artifact_bytes(p, name, limit):
    relative = _relative(name)
    if not any(relative == PurePosixPath(root) or PurePosixPath(root) in relative.parents
               for root in p.artifact_roots):
        raise ResidentError("artifact lies outside declared artifact_roots")
    return _workspace_bytes(p, relative, limit)


def _workspace_bytes(p, relative, limit):
    """Open every workspace path component without following agent symlinks."""
    fd = os.open(p.workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in relative.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        filefd = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            if not stat.S_ISREG(os.fstat(filefd).st_mode):
                raise ResidentError("artifact is not a regular file")
            with os.fdopen(filefd, "rb", closefd=False) as stream:
                data = stream.read(limit + 1)
            if len(data) > limit:
                raise ResidentError("artifact checkpoint exceeds byte bound")
            return data
        finally:
            os.close(filefd)
    finally:
        os.close(fd)


def _result_path(p, episode):
    return p.workspace / ".lanectl-resident-results" / (episode + ".json")


def _prepare_output(p, episode):
    workspace = os.open(p.workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    directory = None
    try:
        try:
            os.mkdir(".lanectl-resident-results", mode=0o700, dir_fd=workspace)
        except FileExistsError:
            pass
        directory = os.open(".lanectl-resident-results", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=workspace)
        os.mkdir(episode + "-home", mode=0o700, dir_fd=directory)
    finally:
        if directory is not None:
            os.close(directory)
        os.close(workspace)
    result = _result_path(p, episode)
    return result, result.parent / (episode + "-home")


def _parse_result(p, episode, generation):
    data = _workspace_bytes(p, PurePosixPath(".lanectl-resident-results", episode + ".json"), MAX_RESULT)
    result = json.loads(data)
    if (not isinstance(result, dict) or result.get("schema") != "lanectl.resident-result/v1"
            or result.get("episode_id") != episode or type(result.get("generation")) is not int
            or result["generation"] != generation or result.get("stop_reason") not in WORKER_STOPS):
        raise ResidentError("worker result identity, generation or stop reason is invalid")
    artifacts = result.get("artifacts")
    if (not isinstance(artifacts, list) or len(artifacts) > MAX_ARTIFACTS
            or any(not isinstance(name, str) for name in artifacts)
            or len(set(artifacts)) != len(artifacts)):
        raise ResidentError("invalid artifact manifest")
    if not isinstance(result.get("continuation", {}), dict):
        raise ResidentError("continuation must be an object")
    return result, _digest(data)


def _partial_artifacts(p):
    """Bounded descriptor-relative walk preserves drafts after a missing result."""
    names, directories = set(), 0

    def visit(fd, relative, depth):
        nonlocal directories
        directories += 1
        if directories > 512 or depth > 64:
            raise ResidentError("partial artifact directory traversal exceeds bound")
        with os.scandir(fd) as entries:
            for entry in entries:
                name = relative / entry.name
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISREG(info.st_mode):
                    names.add(str(name))
                    if len(names) > MAX_ARTIFACTS:
                        raise ResidentError("partial artifact count exceeds bound")
                elif stat.S_ISDIR(info.st_mode):
                    child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    try:
                        visit(child, name, depth + 1)
                    finally:
                        os.close(child)
                else:
                    raise ResidentError("partial artifacts contain a symlink or nonregular file")

    for root in p.artifact_roots:
        relative = _relative(root)
        fd = os.open(p.workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            try:
                for part in relative.parts[:-1]:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    os.close(fd)
                    fd = child
                info = os.stat(relative.name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            if stat.S_ISREG(info.st_mode):
                names.add(root)
            elif stat.S_ISDIR(info.st_mode):
                child = os.open(relative.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    visit(child, relative, 0)
                finally:
                    os.close(child)
            else:
                raise ResidentError("artifact root is a symlink or nonregular file")
        finally:
            os.close(fd)
    return sorted(names)


def _checkpoint(p, episode, generation, context_hash, profile_hash, work_ref, result=None,
                result_hash=None, error=None, source_recheck_hash=None):
    artifacts, remaining = [], MAX_ARTIFACT_BYTES
    try:
        names = result["artifacts"] if result is not None else _partial_artifacts(p)
        for name in names:
            data = _artifact_bytes(p, name, remaining)
            remaining -= len(data)
            path, digest = _store(p, data)
            artifacts.append({"path": name, "sha256": digest, "bytes": len(data), "snapshot_path": str(path)})
    except (OSError, ValueError) as exc:
        if result is not None:
            raise
        error = ((error or "") + f"; partial capture unavailable: {type(exc).__name__}: {exc}")[:2000]
    payload = {"schema": "lanectl.resident-checkpoint/v1", "resident_id": p.resident_id,
               "episode_id": episode, "generation": generation, "context_sha256": context_hash,
               "profile_sha256": profile_hash, "work_ref": work_ref, "artifacts": artifacts,
               "continuation": (result or {}).get("continuation", {}), "result_sha256": result_hash,
               "source_recheck_sha256": source_recheck_hash, "capture_error": error}
    path, digest = _store(p, _json_bytes(payload))
    return {"checkpoint_path": str(path), "checkpoint_sha256": digest}


def _receipt(wake, finish=None, *, status=None):
    finish = finish or {}
    return {"schema": "lanectl.resident-receipt/v1",
            **{key: wake.get(key) for key in ("resident_id", "wake_id", "episode_id", "generation",
                                             "context_sha256", "profile_sha256")},
            "status": status or ("finished" if finish else wake["status"]),
            "outcome": finish.get("outcome", "unknown" if wake["status"] == "admitted" else "not_started"),
            "stop_reason": finish.get("stop_reason", wake.get("stop_reason")),
            **{key: finish[key] for key in ("checkpoint_path", "checkpoint_sha256") if key in finish}}


def _repeat(log, p, view, request):
    wake = view["wakes"].get(request["wake_id"])
    if wake is None:
        return None
    if any(wake.get(k) != request.get(k) for k in
           ("generation", "context_sha256", "profile_sha256", "work_ref")):
        raise ResidentError("wake id conflict: an earlier receipt binds different input")
    log.append("resident.wake", dict(wake, status="duplicate"))
    return _receipt(wake, view["finished"].get(wake["episode_id"]), status="duplicate")


class _Cancellation:
    def __init__(self, log, profile, generation, streams):
        self.log, self.profile, self.generation, self.streams = log, profile, generation, streams
        self.reason = None

    def is_set(self):
        if sum(os.fstat(stream.fileno()).st_size for stream in self.streams) > MAX_OUTPUT:
            self.reason = "output_limit"
        elif _read_view(self.log, self.profile)["generation"] != self.generation:
            self.reason = "stale_generation"
        return self.reason is not None


def run_episode(log, *, profile_path, wake_id, generation, context_path, context_sha256, work_ref="",
                source_recheck_path=None, source_recheck_sha256=None):
    """Run one admitted episode; repeated wake IDs return the original receipt."""
    _require_local_log(log)
    p = load_profile(profile_path)
    _protected_file(p.path)
    try:
        check_id("wake_id", wake_id)
        validate_generation(generation)
        sha256(context_sha256, "context_sha256")
    except ContractError as exc:
        raise ResidentError(str(exc)) from exc
    if not isinstance(work_ref, str) or len(work_ref) > 512:
        raise ResidentError("work_ref must be a bounded string")
    context = _regular_bytes(Path(context_path), MAX_CONTEXT)
    if _digest(context) != context_sha256:
        raise ResidentError("context digest mismatch")
    packet = _validate_context(p, context)
    request = {"resident_id": p.resident_id, "wake_id": wake_id, "generation": generation,
               "context_sha256": context_sha256, "profile_sha256": p.digest,
               "work_ref": work_ref, "episode_id": None}
    with _coordinator(p) as acquired:
        with log.locked():
            view = _initialize(log, p)
            repeated = _repeat(log, p, view, request)
            if repeated:
                return repeated
            if generation != view["generation"]:
                raise ResidentError("requested generation is fenced")
            if not acquired:
                request.update(status="busy", stop_reason="coordinator_busy")
                log.append("resident.wake", request)
                return _receipt(request)
            if view["active"]:
                raise ResidentError("unfinished resident episode requires recovery before new work")
            if not p.execution.get("enabled", False):
                request.update(status="refused", stop_reason="execution_disabled")
                log.append("resident.wake", request)
                return _receipt(request)
        argv, timeout = _qualify(p)
        recheck_bytes = _source_recheck(p, packet, context_sha256, generation,
                                        source_recheck_path, source_recheck_sha256)
        runner_identity = reap.process_identity()
        if runner_identity is None:
            raise ResidentError("coordinator birth identity is unavailable")
        episode = "ep-" + uuid.uuid4().hex
        request.update(episode_id=episode, status="admitted", runner_process=runner_identity)
        if recheck_bytes is not None:
            _, request["source_recheck_sha256"] = _store(p, recheck_bytes)
        packet_path, _ = _store(p, context)
        directory = p.root / "episodes" / episode
        directory.mkdir(parents=True, mode=0o700)
        result_path, home = _prepare_output(p, episode)
        environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                       "HOME": str(home), "LANECTL_RESIDENT_EPISODE": episode,
                       "LANECTL_RESIDENT_GENERATION": str(generation),
                       "LANECTL_RESIDENT_CONTEXT_SHA256": context_sha256,
                       "LANECTL_RESIDENT_RESULT": str(result_path)}
        with log.locked():
            view = _view(log.read(), p)
            repeated = _repeat(log, p, view, request)
            if repeated:
                return repeated
            if view["active"]:
                raise ResidentError("unfinished resident episode requires recovery before new work")
            if view["generation"] != generation:
                raise ResidentError("generation changed before admission")
            log.append("resident.wake", request)
        gate_read, gate_write = os.pipe()
        proc = child_identity = None
        stopped, code, diagnostic = None, -1, None
        try:
            with packet_path.open("rb") as stdin, (directory / "stdout.log").open("wb") as stdout, \
                    (directory / "stderr.log").open("wb") as stderr:
                proc = subprocess.Popen([sys.executable, "-I", str(Path(__file__).with_name("resident_child.py")),
                                         str(gate_read), json.dumps(argv)],
                                        cwd=p.workspace, env=environment, stdin=stdin, stdout=stdout,
                                        stderr=stderr, start_new_session=True, pass_fds=(gate_read,))
                os.close(gate_read)
                gate_read = -1
                child_identity = reap.process_identity(proc.pid)
                if child_identity is None:
                    raise ResidentError("child birth identity is unavailable")
                with log.locked():
                    if _view(log.read(), p)["generation"] != generation:
                        raise ResidentError("generation changed before child admission")
                    log.append("resident.episode.started", dict(request, child_process=child_identity))
                # A slow durable admission cannot extend a source observation's
                # validity. Future effects still need their own owner checks.
                recheck_bytes = _source_recheck(p, packet, context_sha256, generation,
                                                source_recheck_path, source_recheck_sha256)
                # The started transaction has already durably committed. This
                # separate critical section prevents a fence between the final
                # generation check and release of the exec gate.
                with log.locked():
                    if _view(log.read(), p)["generation"] != generation:
                        raise ResidentError("generation changed before final child admission")
                    if recheck_bytes is not None:
                        _check_recheck_window(json.loads(recheck_bytes))
                    os.write(gate_write, b"1")
                os.close(gate_write)
                gate_write = -1
                cancel = _Cancellation(log, p, generation, (stdout, stderr))
                _, _, stopped = child_process.communicate(proc, timeout, cancel)
                stopped = cancel.reason or stopped
                code = proc.returncode
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            diagnostic = f"{type(exc).__name__}: {exc}"[:1000]
            stopped = "launch_failed"
        finally:
            for fd in (gate_read, gate_write):
                if fd >= 0:
                    os.close(fd)
            if proc is not None:
                # A successful launcher can still have left children behind.
                # Close the owned process group before capturing any artifacts.
                if not _cleanup_child(proc, child_identity):
                    stopped = "execution_uncertain"
        outcome, reason = ("interrupted", stopped) if stopped else ("failed", "process_failed")
        if stopped == "launch_failed":
            outcome = "failed"
        if stopped == "execution_uncertain":
            outcome = "unknown"
        result = result_hash = None
        try:
            result, result_hash = _parse_result(p, episode, generation)
            checkpoint = _checkpoint(p, episode, generation, context_sha256, p.digest, work_ref, result,
                                     result_hash, source_recheck_hash=request.get("source_recheck_sha256"))
            if not stopped and code == 0:
                reason = result["stop_reason"]
                outcome = "done" if reason == "completed" else "stopped"
        except (OSError, ValueError) as exc:
            diagnostic = f"{type(exc).__name__}: {exc}"[:1000]
            if not stopped and code == 0:
                outcome, reason = "failed", "invalid_result"
            checkpoint = _checkpoint(p, episode, generation, context_sha256, p.digest, work_ref,
                                     error=diagnostic, source_recheck_hash=request.get("source_recheck_sha256"))
        with log.locked():
            if outcome != "unknown" and _view(log.read(), p)["generation"] != generation:
                outcome, reason = "interrupted", "stale_generation"
            finish = {"resident_id": p.resident_id, "episode_id": episode, "generation": generation,
                      "outcome": outcome, "stop_reason": reason, "exit_code": code,
                      "diagnostic": diagnostic, **checkpoint}
            log.append("resident.episode.finished", finish)
        return _receipt(request, finish)


def status(log, profile_path):
    _require_local_log(log)
    p = load_profile(profile_path)
    view = _read_view(log, p)
    return {"schema": "lanectl.resident-status/v1", "resident_id": p.resident_id,
            "generation": view["generation"], "initialized": view["initialized"],
            "active": view["active"], "finished": list(view["finished"].values())}


def fence(log, profile_path, *, expected_generation, reason):
    _require_local_log(log)
    p = load_profile(profile_path)
    _protected_file(p.path)
    validate_generation(expected_generation)
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
        raise ResidentError("a bounded fencing reason is required")
    with log.locked():
        view = _initialize(log, p)
        if view["generation"] != expected_generation:
            raise ResidentError("generation changed; fencing requires current basis")
        data = {"resident_id": p.resident_id, "previous_generation": expected_generation,
                "generation": expected_generation + 1, "reason": reason}
        log.append("resident.generation.fenced", data)
    return dict(data, schema="lanectl.resident-fence/v1")


def _group_active(group):
    """Ignore zombies, but fail closed when process inspection is unavailable."""
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    unknown = False
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            text = (entry / "stat").read_text()
            fields = text[text.rfind(")") + 2:].split()
            if int(fields[2]) == group and fields[0] not in ("Z", "X"):
                return True
        except FileNotFoundError:
            continue
        except (OSError, ValueError, IndexError):
            unknown = True
    return unknown


def _cleanup_child(proc, identity):
    """Never signal a group whose leader is observed to have another birth.

Full process-tree containment and cleanup are still a qualified cgroup/launcher
property. This guard prevents an observed reused PID from becoming a target.
"""
    current = reap.process_identity(proc.pid)
    if (identity is None or (current is not None and current != identity)
            or (current is None and not reap.runner_dead(identity))):
        return False
    try:
        if current is not None and os.getpgid(proc.pid) != proc.pid:
            return False
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:
        return False
    try:
        if proc.poll() is None:
            proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        return False
    deadline = time.monotonic() + 2
    while _group_active(proc.pid) and time.monotonic() < deadline:
        time.sleep(.02)
    return not _group_active(proc.pid)


def _stop_abandoned(identity):
    local = reap.process_identity()
    if (not isinstance(identity, dict) or local is None or identity.get("host") != local["host"]
            or identity.get("machine_id") != local["machine_id"]):
        return False
    if identity.get("boot_id") != local["boot_id"]:
        return bool(identity.get("boot_id"))
    pid = identity.get("pid")
    if type(pid) is not int or pid < 1:
        return False
    current = reap.process_identity(pid)
    if current is None:
        return reap.runner_dead(identity) and not _group_active(pid)
    if current != identity:
        return reap.runner_dead(identity) and not _group_active(pid)
    try:
        if os.getpgid(pid) != pid:
            return False
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:
        return False
    deadline = time.monotonic() + 2
    while _group_active(pid) and time.monotonic() < deadline:
        time.sleep(.02)
    return not _group_active(pid)


def recover(log, profile_path, *, expected_generation):
    """Recover proven local abandonment; unknown processes never free the slot."""
    _require_local_log(log)
    p = load_profile(profile_path)
    _protected_file(p.path)
    validate_generation(expected_generation)
    with _coordinator(p) as acquired:
        if not acquired:
            return {"status": "busy", "recovered": []}
        view = _read_view(log, p)
        if view["generation"] != expected_generation:
            raise ResidentError("recovery generation changed")
        if not view["active"]:
            return {"status": "idle", "recovered": [], "generation": view["generation"]}
        for attempt in view["active"]:
            if not reap.runner_dead(attempt.get("runner_process")):
                return {"status": "uncertain", "recovered": [], "generation": view["generation"]}
            if attempt.get("child_process") and not _stop_abandoned(attempt["child_process"]):
                return {"status": "uncertain", "recovered": [], "generation": view["generation"]}
        next_generation = fence(log, p.path, expected_generation=expected_generation,
                                reason="recover proven abandoned resident episode")["generation"]
        recovered = []
        for attempt in view["active"]:
            result = result_hash = None
            error = None
            try:
                result, result_hash = _parse_result(p, attempt["episode_id"], attempt["generation"])
                checkpoint = _checkpoint(p, attempt["episode_id"], attempt["generation"],
                    attempt["context_sha256"], attempt["profile_sha256"], attempt.get("work_ref", ""), result, result_hash,
                    source_recheck_hash=attempt.get("source_recheck_sha256"))
            except (OSError, ValueError) as exc:
                error = f"{type(exc).__name__}: {exc}"[:1000]
                checkpoint = _checkpoint(p, attempt["episode_id"], attempt["generation"],
                    attempt["context_sha256"], attempt["profile_sha256"], attempt.get("work_ref", ""), error=error,
                    source_recheck_hash=attempt.get("source_recheck_sha256"))
            finish = {"resident_id": p.resident_id, "episode_id": attempt["episode_id"],
                      "generation": attempt["generation"], "outcome": "interrupted", "stop_reason": "recovered",
                      "diagnostic": error, **checkpoint}
            with log.locked():
                log.append("resident.episode.finished", finish)
            recovered.append(attempt["episode_id"])
        return {"status": "recovered", "recovered": recovered, "generation": next_generation}


def register(sub):
    parser = sub.add_parser("resident", help="bounded logical resident episodes (no native Goal or scheduler)")
    commands = parser.add_subparsers(dest="resident_action", required=True)
    for name in ("describe", "status", "run", "fence", "recover"):
        command = commands.add_parser(name)
        command.add_argument("--profile", required=True, type=Path)
        if name in ("run", "fence", "recover"):
            command.add_argument("--generation", required=True, type=int)
        if name == "run":
            command.add_argument("--wake-id", required=True)
            command.add_argument("--context", required=True, type=Path)
            command.add_argument("--context-sha256", required=True)
            command.add_argument("--work-ref", default="")
            command.add_argument("--source-recheck", type=Path)
            command.add_argument("--source-recheck-sha256")
        if name == "fence":
            command.add_argument("--reason", required=True)
    return {"resident": _cmd}


def _cmd(args, log):
    try:
        if args.resident_action == "describe":
            out = describe_profile(args.profile)
        elif args.resident_action == "status":
            out = status(log, args.profile)
        elif args.resident_action == "fence":
            out = fence(log, args.profile, expected_generation=args.generation, reason=args.reason)
        elif args.resident_action == "recover":
            out = recover(log, args.profile, expected_generation=args.generation)
        else:
            out = run_episode(log, profile_path=args.profile, wake_id=args.wake_id,
                              generation=args.generation, context_path=args.context,
                              context_sha256=args.context_sha256, work_ref=args.work_ref,
                              source_recheck_path=args.source_recheck,
                              source_recheck_sha256=args.source_recheck_sha256)
        print(json.dumps(out, sort_keys=True))
        return 0 if out.get("outcome") not in ("failed", "unknown", "interrupted", "not_started") \
            and out.get("status") not in ("uncertain", "busy", "refused") else 3
    except (OSError, ValueError, ContractError) as exc:
        print(json.dumps({"schema": "lanectl.resident-error/v1", "error": str(exc)}))
        return 2
