"""Protected host bridge for one resident episode and its systemd tool cgroup.

Only the commissioning/dispatch owner runs this module as root. The native
launcher runs in a different UID and cgroup. No command, property or credential
is accepted from an agent result. The runner must call ``cleanup`` before any
checkpoint, including after SIGKILL of the bridge; a Python finally block
cannot establish that guarantee by itself.
"""
from __future__ import annotations

import argparse
import grp
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys

from .resident import assert_protected_file


class SystemdBridgeError(ValueError):
    pass


_EPISODE = re.compile(r"ep-[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_UNIT = re.compile(r"lanectl-resident-[a-z0-9_-]+\.service\Z")
_ENVIRONMENT = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}


def _root():
    if os.geteuid() != 0:
        raise SystemdBridgeError("resident systemd bridge requires the protected root dispatcher")


def _absolute(value, label):
    if (not isinstance(value, str) or not value.startswith("/") or len(value) > 4096
            or any(c.isspace() or ord(c) < 32 for c in value)
            or ".." in Path(value).parts or "\\" in value or "%" in value):
        raise SystemdBridgeError(f"{label} must be a bounded absolute path without specifiers")
    return value


def _read_protected(path):
    assert_protected_file(path)
    with Path(path).resolve().open("rb") as stream:
        data = stream.read(65537)
    if len(data) > 65536:
        raise SystemdBridgeError("protected JSON exceeds its byte bound")
    try:
        value = json.loads(data)
    except (ValueError, UnicodeDecodeError) as exc:
        raise SystemdBridgeError("invalid protected JSON") from exc
    if not isinstance(value, dict):
        raise SystemdBridgeError("protected JSON must be an object")
    return value


def load_launch_config(path):
    cfg = _read_protected(path)
    required = {"schema", "worker_user", "worker_group", "workspace", "runtime_root", "control_root",
                "tool_unit", "coordinator_unit", "systemd_run", "systemctl", "env_executable",
                "native_argv", "timeout_s", "memory_max", "tasks_max", "cpu_quota", "gateway_port", "gateway_socket",
                "gateway_config", "host_policy_sha256"}
    if set(cfg) != required or cfg.get("schema") != "lanectl.resident-systemd/v1":
        raise SystemdBridgeError("invalid systemd bridge config fields/schema")
    for field in ("worker_user", "worker_group"):
        if not isinstance(cfg[field], str) or not _NAME.fullmatch(cfg[field]) or cfg[field] == "root":
            raise SystemdBridgeError("bridge requires a dedicated non-root account")
    for field in ("tool_unit", "coordinator_unit"):
        if not isinstance(cfg[field], str) or not _UNIT.fullmatch(cfg[field]):
            raise SystemdBridgeError("unit must be a fixed resident service name")
    if cfg["tool_unit"] == cfg["coordinator_unit"]:
        raise SystemdBridgeError("tool and coordinator units must differ")
    for field in ("workspace", "runtime_root", "control_root", "systemd_run", "systemctl", "env_executable", "gateway_socket"):
        _absolute(cfg[field], field)
    roots = [Path(cfg[field]) for field in ("workspace", "runtime_root", "control_root")]
    if any(a == b or a in b.parents or b in a.parents for i, a in enumerate(roots) for b in roots[i + 1:]):
        raise SystemdBridgeError("workspace, native runtime and control roots must be disjoint")
    for field in ("systemd_run", "systemctl", "env_executable"):
        assert_protected_file(cfg[field])
    assert_protected_file(_absolute(cfg["gateway_config"], "gateway config"))
    if not isinstance(cfg["host_policy_sha256"], str) or not _DIGEST.fullmatch(cfg["host_policy_sha256"]):
        raise SystemdBridgeError("bridge requires the bound host policy digest")
    argv = cfg["native_argv"]
    if (not isinstance(argv, list) or len(argv) != 7
            or any(not isinstance(arg, str) or not arg or len(arg) > 4096
                   or any(ord(c) < 32 for c in arg) for arg in argv)
            or argv[1:6] != ["-I", "-m", "lanectl.resident_native", "run", "--config"]):
        raise SystemdBridgeError("invalid fixed native command")
    assert_protected_file(_absolute(argv[0], "native executable"))
    assert_protected_file(_absolute(argv[6], "native profile"))
    if type(cfg["timeout_s"]) is not int or not 1 <= cfg["timeout_s"] <= 2700:
        raise SystemdBridgeError("invalid native runtime limit")
    if type(cfg["tasks_max"]) is not int or not 16 <= cfg["tasks_max"] <= 4096:
        raise SystemdBridgeError("invalid task bound")
    if not isinstance(cfg["memory_max"], str) or not re.fullmatch(r"[1-9][0-9]{0,5}[MG]", cfg["memory_max"]):
        raise SystemdBridgeError("invalid host RAM bound")
    if not isinstance(cfg["cpu_quota"], str) or not re.fullmatch(r"[1-9][0-9]{0,3}%", cfg["cpu_quota"]):
        raise SystemdBridgeError("invalid CPU quota")
    if type(cfg["gateway_port"]) is not int or not 1024 <= cfg["gateway_port"] <= 65535:
        raise SystemdBridgeError("invalid gateway port")
    return cfg


def admitted_environment(cfg, source):
    episode = source.get("LANECTL_RESIDENT_EPISODE", "")
    generation = source.get("LANECTL_RESIDENT_GENERATION", "")
    digest = source.get("LANECTL_RESIDENT_CONTEXT_SHA256", "")
    if not _EPISODE.fullmatch(episode) or not re.fullmatch(r"[1-9][0-9]{0,9}", generation):
        raise SystemdBridgeError("invalid admitted episode/generation")
    if not _DIGEST.fullmatch(digest):
        raise SystemdBridgeError("invalid admitted context digest")
    directory = Path(cfg["workspace"]) / ".lanectl-resident-results"
    expected = {"LANECTL_RESIDENT_RESULT": str(directory / (episode + ".json")),
                "HOME": str(directory / (episode + "-home"))}
    if any(source.get(key) != value for key, value in expected.items()):
        raise SystemdBridgeError("admitted result and HOME must match the exact episode")
    return {**_ENVIRONMENT, **expected, "LANECTL_RESIDENT_EPISODE": episode,
            "LANECTL_RESIDENT_GENERATION": generation, "LANECTL_RESIDENT_CONTEXT_SHA256": digest}


def _identity(cfg):
    user, group = pwd.getpwnam(cfg["worker_user"]), grp.getgrnam(cfg["worker_group"])
    if (user.pw_uid == 0 or group.gr_gid == 0 or user.pw_gid != group.gr_gid
            or set(os.getgrouplist(user.pw_name, user.pw_gid)) != {group.gr_gid}
            or Path(user.pw_shell).name not in {"nologin", "false"}):
        raise SystemdBridgeError("worker must be a non-login account with only its private group")
    return user.pw_uid, group.gr_gid


def handoff_home(cfg, env, uid, gid):
    """Chown only the runner-created empty episode HOME, through held dir fds.

    There is no recursive chown, pathname following or change to a model-selected
    artifact. The results parent is precreated by host tmpfiles for the worker.
    """
    fds = []
    try:
        workspace = os.open(cfg["workspace"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fds.append(workspace)
        results = os.open(".lanectl-resident-results", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                          dir_fd=workspace)
        fds.append(results)
        for fd in (workspace, results):
            info = os.fstat(fd)
            if info.st_uid != uid or info.st_gid != gid or info.st_mode & 0o077:
                raise SystemdBridgeError("workspace/results must be private and worker-owned")
        episode = env["LANECTL_RESIDENT_EPISODE"]
        try:
            os.stat(episode + ".json", dir_fd=results, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise SystemdBridgeError("episode result already exists")
        home = os.open(episode + "-home", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=results)
        fds.append(home)
        info = os.fstat(home)
        if info.st_uid != os.geteuid() or info.st_mode & 0o077 or os.listdir(home):
            raise SystemdBridgeError("episode HOME is not the empty private coordinator-created directory")
        os.fchown(home, uid, gid)
        os.fchmod(home, 0o700)
    finally:
        for fd in reversed(fds):
            os.close(fd)


def launch_command(cfg, env):
    properties = {
        "User": cfg["worker_user"], "Group": cfg["worker_group"],
        "WorkingDirectory": cfg["workspace"],
        "BindsTo": cfg["coordinator_unit"], "PartOf": cfg["coordinator_unit"],
        "After": cfg["coordinator_unit"],
        "KillMode": "control-group", "SendSIGKILL": "yes", "TimeoutStopSec": "10",
        "RuntimeMaxSec": str(cfg["timeout_s"]), "Restart": "no", "Delegate": "no",
        "UMask": "0077", "NoNewPrivileges": "yes", "CapabilityBoundingSet": "",
        "AmbientCapabilities": "", "ProtectHome": "yes", "ProtectSystem": "strict",
        "ReadWritePaths": cfg["workspace"] + " " + cfg["runtime_root"],
        "BindPaths": cfg["workspace"] + " " + cfg["runtime_root"],
        "BindReadOnlyPaths": cfg["gateway_socket"],
        # PrivateNetwork hides host loopback and abstract Unix sockets. Private
        # /run and /var hide pathname sockets; only the one model capability and
        # the two writable data roots are deliberately rebound from the host.
        "InaccessiblePaths": "-/nix/var -/projects -/mnt -/media -/srv -/etc/ssh -/etc/nixos",
        "TemporaryFileSystem": "/run:ro /var:ro", "PrivateNetwork": "yes",
        "PrivateTmp": "disconnected", "PrivateDevices": "yes", "PrivateIPC": "yes",
        "ProtectProc": "invisible", "ProcSubset": "pid", "ProtectKernelTunables": "yes",
        "ProtectKernelModules": "yes", "ProtectKernelLogs": "yes", "ProtectControlGroups": "yes",
        "ProtectClock": "yes", "RestrictSUIDSGID": "yes", "RestrictRealtime": "yes",
        "RestrictNamespaces": "yes", "LockPersonality": "yes", "SystemCallArchitectures": "native",
        "SystemCallFilter": "~@mount @privileged @reboot @swap @module @raw-io @obsolete",
        "RestrictAddressFamilies": "AF_UNIX AF_INET AF_INET6",
        "MemoryMax": cfg["memory_max"], "MemorySwapMax": "0", "TasksMax": str(cfg["tasks_max"]),
        "CPUQuota": cfg["cpu_quota"],
    }
    return [cfg["systemd_run"], "--quiet", "--pipe", "--wait", "--collect", "--service-type=exec",
            "--unit=" + cfg["tool_unit"],
            *[f"--property={key}={value}" for key, value in properties.items()],
            "--", cfg["env_executable"], "-i", *[f"{key}={value}" for key, value in env.items()],
            *cfg["native_argv"]]


def _cgroup_empty(group):
    if not group:
        return True
    if not group.startswith("/") or ".." in Path(group).parts:
        return False
    root = Path("/sys/fs/cgroup")
    path = root / group.lstrip("/")
    try:
        if not path.is_relative_to(root) or path.is_symlink():
            return False
        events = dict(line.split() for line in (path / "cgroup.events").read_text().splitlines())
        return events.get("populated") == "0"
    except FileNotFoundError:
        return not path.exists()
    except (OSError, ValueError):
        return False


def cleanup(cfg):
    """Return only after PID1 reports inactive and the cgroup is empty/gone."""
    subprocess.run([cfg["systemctl"], "stop", cfg["tool_unit"]], env=_ENVIRONMENT,
                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                   timeout=20, check=False)
    result = subprocess.run([cfg["systemctl"], "show", cfg["tool_unit"],
                             "--property=LoadState,ActiveState,ControlGroup"], env=_ENVIRONMENT,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=3, check=False, text=True)
    fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if (result.returncode != 0 or fields.get("LoadState") not in {"loaded", "not-found"}
            or fields.get("ActiveState") not in {"inactive", "failed"}):
        raise SystemdBridgeError("cannot establish inactive resident tool unit")
    if "ControlGroup" not in fields or not _cgroup_empty(fields["ControlGroup"]):
        raise SystemdBridgeError("resident tool cgroup remains populated or unobservable")


def launch(cfg):
    env = admitted_environment(cfg, os.environ)
    uid, gid = _identity(cfg)
    handoff_home(cfg, env, uid, gid)
    # systemd-run refuses an already-existing fixed unit name. A collision
    # fails this episode, then cleans the owned fixed unit instead of replacing
    # its running command. The outer owner retains its receipt/recovery state.
    try:
        completed = subprocess.run(launch_command(cfg, env), env=_ENVIRONMENT, check=False)
        return completed.returncode
    finally:
        # Normal exits are cleaned here. SIGKILL is covered by the resident
        # runner's mandatory cleanup hook and the coordinator's ExecStopPost.
        cleanup(cfg)


def _admission_path(value, directory):
    _absolute(value, "admission input")
    path, root = Path(value), Path(directory)
    if path == root or root not in path.parents or root.resolve() not in path.resolve().parents:
        raise SystemdBridgeError("input must be below the protected admission directory")
    return value


def episode_command(cfg, request):
    required = {"schema", "wake_id", "generation", "work_ref", "context", "context_sha256",
                "source_recheck", "source_recheck_sha256"}
    if set(request) != required or request.get("schema") != "lanectl.resident-admission/v1":
        raise SystemdBridgeError("invalid admission request fields/schema")
    if (not isinstance(request["wake_id"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}", request["wake_id"])
            or type(request["generation"]) is not int or request["generation"] < 1
            or not isinstance(request["work_ref"], str) or len(request["work_ref"]) > 512
            or any(ord(c) < 32 for c in request["work_ref"])):
        raise SystemdBridgeError("invalid admitted wake, generation or work reference")
    for key in ("context_sha256", "source_recheck_sha256"):
        if not isinstance(request[key], str) or not _DIGEST.fullmatch(request[key]):
            raise SystemdBridgeError("invalid admission digest")
    context = _admission_path(request["context"], cfg["admission_dir"])
    recheck = _admission_path(request["source_recheck"], cfg["admission_dir"])
    return ([cfg["python_executable"], "-I", "-m", "lanectl.cli", "resident", "run", "--profile", cfg["profile"],
             "--wake-id", request["wake_id"], "--generation", str(request["generation"]),
             "--work-ref", request["work_ref"], "--context", context,
             "--context-sha256", request["context_sha256"], "--source-recheck", recheck,
             "--source-recheck-sha256", request["source_recheck_sha256"]],
            {**_ENVIRONMENT, "LANECTL_STATE": cfg["event_state_dir"]})


def episode(path):
    cfg = _read_protected(path)
    fields = {"schema", "python_executable", "profile", "event_state_dir", "admission_dir", "request_file"}
    if set(cfg) != fields or cfg.get("schema") != "lanectl.resident-dispatch/v1":
        raise SystemdBridgeError("invalid protected dispatcher config")
    for field in fields - {"schema"}:
        _absolute(cfg[field], field)
    for field in ("python_executable", "profile"):
        assert_protected_file(cfg[field])
    request_path = _admission_path(cfg["request_file"], cfg["admission_dir"])
    request = _read_protected(request_path)
    command, env = episode_command(cfg, request)
    for field in ("context", "source_recheck"):
        assert_protected_file(request[field])
    # open_log() retains any served-backend marker in this explicitly selected
    # state root and refuses the resident pilot. Never delete/reset that marker.
    os.execve(command[0], command, env)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("episode", "launch", "cleanup"))
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    try:
        _root()
        if args.action == "episode":
            episode(args.config)
            return 0
        cfg = load_launch_config(args.config)
        if args.action == "cleanup":
            cleanup(cfg)
            return 0
        return launch(cfg)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"resident systemd bridge refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
