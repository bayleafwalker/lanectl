"""Host bridge contracts; these tests do not qualify a running systemd sandbox."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from lanectl import resident_systemd as bridge


EPISODE = "ep-" + "a" * 32


def config(tmp_path):
    workspace = tmp_path / "workspace"
    runtime = tmp_path / "runtime"
    control = tmp_path / "control"
    for path in (workspace, runtime, control):
        path.mkdir(mode=0o700)
    (workspace / ".lanectl-resident-results").mkdir(mode=0o700)
    (workspace / ".lanectl-resident-results" / (EPISODE + "-home")).mkdir(mode=0o700)
    return {
        "schema": "lanectl.resident-systemd/v1",
        "worker_user": "resident-worker", "worker_group": "resident-worker",
        "workspace": str(workspace), "runtime_root": str(runtime), "control_root": str(control),
        "tool_unit": "lanectl-resident-tools.service",
        "coordinator_unit": "lanectl-resident-episode.service",
        "systemd_run": "/nix/store/systemd/bin/systemd-run",
        "systemctl": "/nix/store/systemd/bin/systemctl",
        "env_executable": "/nix/store/coreutils/bin/env",
        "native_argv": ["/nix/store/python/bin/python", "-I", "-m", "lanectl.resident_native",
                        "run", "--config", "/nix/store/profile/native.json"],
        "timeout_s": 2700, "memory_max": "8G", "tasks_max": 256,
        "cpu_quota": "200%", "gateway_port": 18021,
        "gateway_socket": "/run/lanectl-resident-model/model.sock",
        "gateway_config": "/nix/store/gateway/config.json", "host_policy_sha256": "c" * 64,
    }


def metadata(cfg):
    return {
        "LANECTL_RESIDENT_EPISODE": EPISODE,
        "LANECTL_RESIDENT_GENERATION": "1",
        "LANECTL_RESIDENT_CONTEXT_SHA256": "b" * 64,
        "LANECTL_RESIDENT_RESULT": str(Path(cfg["workspace"]) / ".lanectl-resident-results" / (EPISODE + ".json")),
        "HOME": str(Path(cfg["workspace"]) / ".lanectl-resident-results" / (EPISODE + "-home")),
        "OPENAI_API_KEY": "must-not-be-forwarded", "DBUS_SYSTEM_BUS_ADDRESS": "must-not-be-forwarded",
    }


def test_command_has_fixed_identity_boundary_and_clean_environment(tmp_path):
    cfg = config(tmp_path)
    clean = bridge.admitted_environment(cfg, metadata(cfg))
    command = bridge.launch_command(cfg, clean)
    assert "--property=User=resident-worker" in command
    assert "--property=KillMode=control-group" in command
    assert "--property=Delegate=no" in command
    assert "--property=PrivateDevices=yes" in command
    assert "--property=TemporaryFileSystem=/run:ro /var:ro" in command
    assert "--property=PrivateNetwork=yes" in command
    assert "--property=PrivateTmp=disconnected" in command
    assert "--property=BindReadOnlyPaths=/run/lanectl-resident-model/model.sock" in command
    assert "--property=ProtectHome=yes" in command
    assert "--property=ProtectSystem=strict" in command
    assert "--property=BindsTo=lanectl-resident-episode.service" in command
    assert "--property=RuntimeMaxSec=2700" in command
    assert "--property=MemorySwapMax=0" in command
    assert "--property=CapabilityBoundingSet=" in command
    assert "--property=RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6" in command
    assert "--property=BindPaths=" + cfg["workspace"] + " " + cfg["runtime_root"] in command
    assert command[command.index("--") + 1:][:2] == [cfg["env_executable"], "-i"]
    assert not any("must-not-be-forwarded" in item or "DBUS_SYSTEM_BUS_ADDRESS" in item for item in command)
    assert command[-len(cfg["native_argv"]):] == cfg["native_argv"]
    # IP-only systemd filters cannot enforce the required gateway port boundary.
    assert not any("IPAddressAllow=" in item for item in command)


@pytest.mark.parametrize("key,value", [
    ("LANECTL_RESIDENT_EPISODE", "ep-../../other"),
    ("LANECTL_RESIDENT_GENERATION", "01"),
    ("LANECTL_RESIDENT_GENERATION", "0"),
    ("LANECTL_RESIDENT_CONTEXT_SHA256", "not-a-digest"),
    ("LANECTL_RESIDENT_RESULT", "/etc/passwd"),
    ("HOME", "/home/regular-user"),
])
def test_only_exact_admitted_metadata_can_cross_bridge(tmp_path, key, value):
    cfg = config(tmp_path)
    source = metadata(cfg)
    source[key] = value
    with pytest.raises(bridge.SystemdBridgeError):
        bridge.admitted_environment(cfg, source)


def test_home_handoff_changes_only_exact_opened_directory(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    env = bridge.admitted_environment(cfg, metadata(cfg))
    calls = []
    monkeypatch.setattr(bridge.os, "fchown", lambda fd, uid, gid: calls.append((os.fstat(fd).st_ino, uid, gid)))
    bridge.handoff_home(cfg, env, os.getuid(), os.getgid())
    home = Path(env["HOME"])
    assert calls == [(home.stat().st_ino, os.getuid(), os.getgid())]
    assert home.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("target", ["home", "results"])
def test_symlink_cannot_redirect_privileged_handoff(tmp_path, monkeypatch, target):
    cfg = config(tmp_path)
    env = bridge.admitted_environment(cfg, metadata(cfg))
    outside = tmp_path / "outside"
    outside.mkdir()
    home = Path(env["HOME"])
    if target == "home":
        home.rmdir()
        home.symlink_to(outside, target_is_directory=True)
    else:
        home.rmdir()
        home.parent.rmdir()
        home.parent.symlink_to(outside, target_is_directory=True)
    calls = []
    monkeypatch.setattr(bridge.os, "fchown", lambda *args: calls.append(args))
    with pytest.raises((OSError, bridge.SystemdBridgeError)):
        bridge.handoff_home(cfg, env, os.getuid(), os.getgid())
    assert calls == []


def test_existing_result_is_never_overwritten_by_handoff(tmp_path):
    cfg = config(tmp_path)
    env = bridge.admitted_environment(cfg, metadata(cfg))
    Path(env["LANECTL_RESIDENT_RESULT"]).write_text("existing")
    with pytest.raises(bridge.SystemdBridgeError, match="result"):
        bridge.handoff_home(cfg, env, os.getuid(), os.getgid())


def test_cleanup_requires_inactive_unit_and_empty_cgroup(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="LoadState=loaded\nActiveState=inactive\nControlGroup=/system.slice/tools.service\n")
    monkeypatch.setattr(bridge.subprocess, "run", run)
    monkeypatch.setattr(bridge, "_cgroup_empty", lambda path: True)
    bridge.cleanup(cfg)
    assert calls[0] == [cfg["systemctl"], "stop", cfg["tool_unit"]]
    monkeypatch.setattr(bridge, "_cgroup_empty", lambda path: False)
    with pytest.raises(bridge.SystemdBridgeError, match="cgroup"):
        bridge.cleanup(cfg)


def test_failed_stop_does_not_produce_clean_receipt_for_active_unit(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    monkeypatch.setattr(bridge.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(returncode=1, stdout="LoadState=loaded\nActiveState=active\nControlGroup=/system.slice/tools.service\n"))
    with pytest.raises(bridge.SystemdBridgeError, match="inactive"):
        bridge.cleanup(cfg)


def test_collected_unit_is_clean_but_bus_failure_is_not(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    monkeypatch.setattr(bridge.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(returncode=0, stdout="LoadState=not-found\nActiveState=inactive\nControlGroup=\n"))
    bridge.cleanup(cfg)
    monkeypatch.setattr(bridge.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(returncode=1, stdout=""))
    with pytest.raises(bridge.SystemdBridgeError):
        bridge.cleanup(cfg)


def test_request_constructs_resident_run_and_preserves_selected_log(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    request = {
        "schema": "lanectl.resident-admission/v1", "wake_id": "owner-wake-1", "generation": 3,
        "work_ref": "stories#1", "context": str(inbox / "context.json"),
        "context_sha256": "a" * 64, "source_recheck": str(inbox / "recheck.json"),
        "source_recheck_sha256": "b" * 64,
    }
    cfg = {"python_executable": "/nix/store/python/bin/python", "profile": "/etc/lanectl/resident/profile.json",
           "admission_dir": str(inbox), "event_state_dir": str(tmp_path / "existing-log")}
    command, env = bridge.episode_command(cfg, request)
    assert command[:6] == [cfg["python_executable"], "-I", "-m", "lanectl.cli", "resident", "run"]
    assert "--source-recheck-sha256" in command
    assert command[command.index("--generation") + 1] == "3"
    assert env["LANECTL_STATE"] == cfg["event_state_dir"]
    assert not any("fence" == item or "recover" == item for item in command)
    request["context"] = str(tmp_path / "outside.json")
    with pytest.raises(bridge.SystemdBridgeError, match="admission"):
        bridge.episode_command(cfg, request)


def test_unknown_admission_fields_do_not_become_flags(tmp_path):
    cfg = {"admission_dir": str(tmp_path)}
    with pytest.raises(bridge.SystemdBridgeError, match="fields"):
        bridge.episode_command(cfg, {"schema": "lanectl.resident-admission/v1", "argv": ["/bin/sh"]})


def test_worker_must_not_be_regular_account_or_docker_member(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    user = SimpleNamespace(pw_uid=999, pw_gid=999, pw_name="resident-worker", pw_shell="/bin/nologin")
    monkeypatch.setattr(bridge.pwd, "getpwnam", lambda name: user)
    monkeypatch.setattr(bridge.grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=999))
    monkeypatch.setattr(bridge.os, "getgrouplist", lambda *args: [999])
    assert bridge._identity(cfg) == (999, 999)
    user.pw_shell = "/bin/bash"
    with pytest.raises(bridge.SystemdBridgeError, match="non-login"):
        bridge._identity(cfg)
    user.pw_shell = "/bin/nologin"
    monkeypatch.setattr(bridge.os, "getgrouplist", lambda *args: [999, 998])
    with pytest.raises(bridge.SystemdBridgeError, match="private group"):
        bridge._identity(cfg)


def test_isolated_module_start_ignores_workspace_python_shadow(tmp_path):
    malicious = tmp_path / "lanectl"
    malicious.mkdir()
    (malicious / "__init__.py").write_text("raise RuntimeError('workspace module was imported')\n")
    (tmp_path / "sitecustomize.py").write_text("raise RuntimeError('workspace sitecustomize was imported')\n")
    result = subprocess.run([sys.executable, "-I", "-m", "lanectl.resident_systemd", "--help"],
                            cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert "workspace module was imported" not in result.stderr


def test_nixos_module_keeps_execution_and_gateway_distinct():
    module = Path(__file__).resolve().parents[2] / "contrib/resident/nixos/module.nix"
    text = module.read_text()
    assert "LoadCredential" in text
    assert 'credential_name = "upstream-token"' in text
    assert "meta skuid" in text
    assert "listen_socket = gatewaySocket" in text
    assert "resident_systemd episode" in text
    assert "cleanup_executable_sha256" in text
    assert "systemd.sockets.lanectl-resident-model" in text
    assert "networking.nftables.enable = true" not in text
