"""Run train commands through the host's fixed separate-UID systemd service.

Contract: ``backlog/fenced-train-client/files/host-contract.md``. Only the
root-owned receipt decides the outcome; every failure fails closed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
import time
from pathlib import Path, PurePosixPath

TRAIN_ROOT = Path("/var/lib/lanectl-train/trains")
RESULT_ROOT = Path("/var/lib/lanectl-train/results")
UNIT = "lanectl-train@{}.service"
SHELL = "/run/current-system/sw/bin/bash"
TRUSTED_UID = 0
MAX_TIMEOUT_S, REQUEST_MAX = 21600, 256 * 1024
POLL_S, WAIT_MARGIN_S, RECEIPT_GRACE_S, STOP_WAIT_S = 0.25, 180.0, 20.0, 600.0
TOOL_TIMEOUT_S, GIT_TIMEOUT_S = 30, 120
TERMINAL = ("inactive", "failed")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_FIELDS = ("version", "train_id", "request_sha256", "outcome",
           "service_result", "exit_code", "exit_status", "handed_back")
_STR_FIELDS = ("train_id", "request_sha256", "outcome", "service_result",
               "exit_code", "exit_status")
_SUCCESS = ("succeeded", "success", "exited", "0")


class FenceError(RuntimeError):
    """A fenced train could not be launched, observed or trusted."""


def receipt_returncode(record, *, train_id: str, request_sha256: str) -> int:
    """0 only for a coherent success receipt bound to this request's bytes."""
    if not isinstance(record, dict):
        raise ValueError("receipt is not an object")
    missing = [name for name in _FIELDS if name not in record]
    if missing:
        raise ValueError(f"receipt is missing {', '.join(missing)}")
    version = record["version"]
    if isinstance(version, bool) or version != 1:
        raise ValueError("unsupported receipt version")
    for name in _STR_FIELDS:
        if not isinstance(record[name], str):
            raise ValueError(f"receipt {name} must be a string")
    if not isinstance(record["handed_back"], bool):
        raise ValueError("receipt handed_back must be a boolean")
    if record["train_id"] != train_id:
        raise ValueError("receipt belongs to a different train")
    if record["request_sha256"] != request_sha256:
        raise ValueError("receipt request digest does not match")
    if record["handed_back"] and tuple(record[name] for name in _STR_FIELDS[2:]) == _SUCCESS:
        return 0
    try:
        status = int(record["exit_status"])
    except ValueError:
        status = 1
    return status if status > 0 else 1


def run_command(repo, checkout, command, timeout_s=1800):
    """Run one train command in the fixed service; any failure is nonzero."""
    command = str(command)
    train_id = _new_id()
    unit = UNIT.format(train_id)
    train_dir = TRAIN_ROOT / train_id
    receipt_path = RESULT_ROOT / f"{train_id}.json"
    sysctl = jctl = None
    started = terminal = keep = created = False
    commit, tracked, before = "", [], {}
    code, out, err = 1, "", ""
    try:
        timeout = _timeout(timeout_s)
        sysctl, jctl = _tools()
        if not TRAIN_ROOT.is_dir() or not RESULT_ROOT.is_dir():
            raise FenceError(f"fixed spool {TRAIN_ROOT} or receipt dir {RESULT_ROOT} is missing")
        train_dir.mkdir(mode=0o700)
        created = True
        control = train_dir / ".lanectl-train"
        control.mkdir(mode=0o700)
        (control / "home").mkdir(mode=0o700)
        commit, tracked, before = _stage(checkout, train_dir / "repo")
        request = _request(repo, command, timeout)
        (control / "request.json").write_bytes(request)
        digest = "sha256:" + hashlib.sha256(request).hexdigest()
        started = True
        _start(sysctl, unit)
        terminal = False
        if not _wait_terminal(sysctl, unit, receipt_path, timeout):
            if not _stop_terminal(sysctl, unit):
                keep = True
                raise FenceError(f"timed out and could not prove {unit} stopped; "
                                 f"orphan left running in {train_dir}")
            terminal = True
            raise FenceError(f"timed out after {timeout + WAIT_MARGIN_S:.0f}s; {unit} stopped")
        terminal = True
        record = _read_receipt(train_id)
        code = receipt_returncode(record, train_id=train_id, request_sha256=digest)
        out = _journal(jctl, unit)
        changed = _mutation(train_dir / "repo", commit, tracked, before)
        if changed:
            code, err = 1, f"checks changed tracked source or HEAD ({changed}); result refused"
        elif code:
            err = (f"train {train_id} {record.get('outcome')}: "
                   f"service_result={record.get('service_result')} "
                   f"exit_code={record.get('exit_code')} exit_status={record.get('exit_status')}")
    except KeyboardInterrupt as exc:
        if started and not terminal:
            if _stop_terminal(sysctl, unit) if sysctl else False:
                terminal = True
            else:
                keep = True
        if keep:
            raise KeyboardInterrupt(
                f"fenced train could not prove {unit} stopped; orphan left running in {train_dir}"
            ) from exc
        try:
            if created and train_dir.exists():
                _remove(train_dir)
        except OSError as cleanup_exc:
            raise KeyboardInterrupt(
                f"fenced train cleanup failed for {train_dir}: {cleanup_exc}") from exc
        raise
    except FenceError as exc:
        if started and not terminal and not keep:
            terminal = _stop_terminal(sysctl, unit)
            keep = not terminal
        code, err = 1, str(exc)
    except Exception as exc:
        if started and not terminal and not keep:
            terminal = _stop_terminal(sysctl, unit)
            keep = not terminal
        code, err = 1, f"{type(exc).__name__}: {exc}"

    if not err and code:
        err = f"train {train_id} failed"
    if keep:
        err += f"\nfenced train could not prove {unit} stopped; orphan left running (dir {train_dir})"
    else:
        try:
            if created and train_dir.exists():
                _remove(train_dir)
        except OSError as exc:
            code = 1
            err += f"\nfenced train cleanup failed for {train_dir}: {exc}"
    if code:
        err = "fenced train: " + err
    return subprocess.CompletedProcess(command, code, out, err)


def _new_id() -> str:
    train_id = "fenced-" + secrets.token_hex(8)
    if not _ID.fullmatch(train_id):
        raise FenceError("generated train id is unsafe")
    return train_id


def _timeout(value) -> int:
    if isinstance(value, bool):
        raise FenceError("timeout must be an integer")
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        raise FenceError("timeout must be an integer") from None
    if not 1 <= timeout <= MAX_TIMEOUT_S:
        raise FenceError(f"timeout {timeout} outside 1..{MAX_TIMEOUT_S}")
    return timeout


def _tools():
    sysctl = shutil.which("systemctl")
    if not sysctl:
        raise FenceError("systemctl is unavailable on PATH; the fixed host systemd "
                         "train service cannot be used")
    return sysctl, shutil.which("journalctl")


def _tool_env() -> dict:
    return {"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C", "SYSTEMD_PAGER": "cat"}


def _start(sysctl: str, unit: str) -> None:
    try:
        p = subprocess.run([sysctl, "start", "--no-block", unit], env=_tool_env(),
                           capture_output=True, text=True, timeout=TOOL_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FenceError(f"systemctl start for {unit} could not run: {type(exc).__name__}") from exc
    if p.returncode:
        detail = " ".join((p.stderr or p.stdout).split())[:300]
        raise FenceError(f"systemctl start refused for {unit} (exit {p.returncode}): {detail}")


def _active(sysctl: str, unit: str):
    """ActiveState, or None when liveness is unknown (never treated as stopped)."""
    try:
        p = subprocess.run([sysctl, "show", "-p", "ActiveState", unit], env=_tool_env(),
                           capture_output=True, text=True, timeout=TOOL_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode:
        return None
    for line in p.stdout.splitlines():
        if line.startswith("ActiveState="):
            return line.split("=", 1)[1].strip()
    return None


def _wait_terminal(sysctl: str, unit: str, receipt: Path, timeout: int) -> bool:
    deadline = time.monotonic() + timeout + WAIT_MARGIN_S
    while True:
        if _active(sysctl, unit) in TERMINAL:
            grace = time.monotonic() + RECEIPT_GRACE_S
            while time.monotonic() < grace and not os.path.lexists(receipt):
                time.sleep(POLL_S)
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(POLL_S)


def _stop_terminal(sysctl, unit: str) -> bool:
    if not sysctl:
        return False
    try:
        subprocess.run([sysctl, "stop", unit], env=_tool_env(), capture_output=True,
                       timeout=STOP_WAIT_S)
    except (OSError, subprocess.TimeoutExpired):
        pass
    deadline = time.monotonic() + STOP_WAIT_S
    while time.monotonic() < deadline:
        if _active(sysctl, unit) in TERMINAL:
            return True
        time.sleep(POLL_S)
    return False


def _journal(jctl, unit: str) -> str:
    if not jctl:
        return ""
    try:
        p = subprocess.run([jctl, "-u", unit, "-o", "cat", "--no-pager"], env=_tool_env(),
                           capture_output=True, text=True, timeout=TOOL_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (p.stdout + p.stderr)[-20000:]


def _remove(path: Path) -> None:
    if not stat.S_ISDIR(os.lstat(path).st_mode):
        raise OSError(f"{path} is not a directory")
    shutil.rmtree(path)


def _read_receipt(train_id: str) -> dict:
    try:
        parent = os.open(RESULT_ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise FenceError(f"root receipt directory is unavailable: {exc}") from exc
    try:
        st = os.fstat(parent)
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != TRUSTED_UID or st.st_mode & 0o022:
            raise FenceError(f"receipt directory {RESULT_ROOT} is not a trusted root-owned directory")
        try:
            fd = os.open(f"{train_id}.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                         dir_fd=parent)
        except FileNotFoundError:
            raise FenceError(f"root receipt for {train_id} is missing after the unit became "
                             "inactive") from None
        except OSError as exc:
            raise FenceError(f"root receipt for {train_id} is not a safe regular file: {exc}") from exc
        try:
            fst = os.fstat(fd)
            if not stat.S_ISREG(fst.st_mode):
                raise FenceError("root receipt is not a regular file")
            if fst.st_uid != TRUSTED_UID:
                raise FenceError("root receipt is not owned by root")
            if fst.st_mode & 0o022:
                raise FenceError("root receipt is writable by group or others")
            chunks, total = [], 0
            while chunk := os.read(fd, 65536):
                total += len(chunk)
                if total > REQUEST_MAX:
                    raise FenceError("root receipt is oversized")
                chunks.append(chunk)
        finally:
            os.close(fd)
    finally:
        os.close(parent)
    try:
        record = json.loads(b"".join(chunks))
    except (UnicodeDecodeError, ValueError) as exc:
        raise FenceError(f"root receipt is not valid JSON: {exc}") from exc
    if not isinstance(record, dict):
        raise FenceError("root receipt is not an object")
    return record


def _request(repo, command: str, timeout: int) -> bytes:
    setup = (getattr(repo, "setup_cmd", "") or "").strip()
    script = command
    if setup and setup != command.strip():
        script = f"set -e\n{setup}\n{command}"
    payload = {"version": 1, "argv": [SHELL, "-lc", script], "cwd": "repo",
               "env": {}, "timeout_sec": timeout, "nonce": secrets.token_hex(16)}
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    if len(data) > REQUEST_MAX:
        raise FenceError("train request exceeds the host's 256 KiB limit")
    return data


def _git_env(home: str) -> dict:
    return {"PATH": os.environ.get("PATH", os.defpath), "HOME": home, "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}


def _git(args, home: str) -> bytes:
    git = shutil.which("git")
    if not git:
        raise FenceError("git is unavailable on PATH; cannot stage the train checkout")
    argv = [git, "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", *map(str, args)]
    try:
        p = subprocess.run(argv, env=_git_env(home), capture_output=True, timeout=GIT_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FenceError(f"git staging failed: {type(exc).__name__}") from exc
    if p.returncode:
        raise FenceError(f"git {args[0]} refused: "
                         f"{p.stderr.decode('utf-8', 'replace').strip()[:200]}")
    return p.stdout


def _stage(checkout, dest: Path):
    """Copy the exact source commit as a self-contained checkout plus manifest."""
    home = tempfile.mkdtemp(prefix="lanectl-stage-")
    try:
        commit = _git(["-C", checkout, "rev-parse", "--verify", "HEAD"], home).strip().decode()
        if not _HEX40.fullmatch(commit):
            raise FenceError(f"source HEAD {commit[:16]!r} is not a SHA-1 commit id")
        common = _git(["-C", checkout, "rev-parse", "--path-format=absolute",
                       "--git-common-dir"], home).strip().decode()
        if (Path(common) / "objects/info/alternates").exists():
            raise FenceError("source checkout uses object alternates; cannot stage a self-contained train")
        _git(["clone", "--local", "--no-hardlinks", "--no-checkout", "--quiet",
              checkout, dest], home)
        if (dest / ".git/objects/info/alternates").exists():
            raise FenceError("staged checkout would use object alternates")
        _git(["-C", dest, "remote", "remove", "origin"], home)
        _git(["-C", dest, "checkout", "--quiet", "--detach", commit], home)
        tracked = [os.fsdecode(rel) for rel in
                   _git(["-C", dest, "ls-files", "-z"], home).split(b"\0") if rel]
        return commit, tracked, _manifest(dest, tracked)
    finally:
        shutil.rmtree(home, ignore_errors=True)


_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


def _parent(root, parts) -> int:
    """Descriptor of parts[:-1] under root, walked without following any link."""
    fd = os.open(root, _DIR)
    try:
        for name in parts[:-1]:
            nxt = os.open(name, _DIR, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise


def _manifest(root: Path, tracked) -> dict:
    out = {}
    for rel in tracked:
        parts = PurePosixPath(rel).parts
        try:
            pfd = _parent(root, parts)
        except OSError as exc:
            out[rel] = ("unreadable", type(exc).__name__)
            continue
        try:
            out[rel] = _leaf(pfd, parts[-1])
        finally:
            os.close(pfd)
    return out


def _leaf(pfd: int, name: str):
    try:
        st = os.lstat(name, dir_fd=pfd)
    except OSError:
        return ("missing",)
    try:
        if stat.S_ISLNK(st.st_mode):
            return ("link", os.readlink(name, dir_fd=pfd))
        if not stat.S_ISREG(st.st_mode):
            return ("other", stat.S_IFMT(st.st_mode))
        with os.fdopen(os.open(name, _FILE, dir_fd=pfd), "rb") as handle:
            fst = os.fstat(handle.fileno())
            if not stat.S_ISREG(fst.st_mode):
                return ("other", stat.S_IFMT(fst.st_mode))
            digest = hashlib.sha256()
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return ("file", st.st_mode & 0o111, digest.hexdigest())
    except OSError as exc:
        return ("unreadable", type(exc).__name__)


def _read_head(root: Path, commit: str) -> bool:
    try:
        pfd = _parent(root, (".git", "HEAD"))
        try:
            fd = os.open("HEAD", _FILE, dir_fd=pfd)
        finally:
            os.close(pfd)
    except OSError:
        return False
    try:
        st = os.fstat(fd)
        return (stat.S_ISREG(st.st_mode) and st.st_size <= 4096
                and os.read(fd, 4097) == (commit + "\n").encode())
    finally:
        os.close(fd)


def _mutation(root: Path, commit: str, tracked, before: dict) -> str:
    if not _read_head(root, commit):
        return "HEAD changed"
    after = _manifest(root, tracked)
    changed = sorted(rel for rel in before if before[rel] != after.get(rel))
    if not changed:
        return ""
    more = f" (+{len(changed) - 5} more)" if len(changed) > 5 else ""
    return ", ".join(changed[:5]) + more
