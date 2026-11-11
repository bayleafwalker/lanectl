"""Write sandbox for worker harnesses and for running worker-written code.

Governance path. Enforces the lane EffectGrant on the filesystem: everything
under `readonly` roots is mounted read-only except the attempt's own checkout.
Seed implementation: `systemd-run --user` (mount namespaces, RuntimeMaxSec).
Added 2026-11-08 after OpenCode workers wrote into the main checkout.
"""
from __future__ import annotations

import os
import hashlib
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

PASS_ENV = ("PATH", "HOME", "USER", "LANG", "TERM", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
            "XDG_CACHE_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR", "UV_CACHE_DIR",
            "SSL_CERT_FILE", "NIX_SSL_CERT_FILE")


@dataclass(frozen=True)
class Sandbox:
    mode: str                         # "systemd-run" | "none"
    readonly: tuple[str, ...]         # roots mounted read-only (e.g. /projects)
    writable: tuple[str, ...]         # exceptions: the attempt checkout, scratch dirs
    timeout_s: int
    unit: str | None = None
    inaccessible: tuple[str, ...] = ()
    clean_environment: bool = False
    environment: tuple[tuple[str, str], ...] | None = None

    def prefix(self, cwd: Path, env_path: str | None = None) -> list[str]:
        if self.mode == "none":
            return []
        if self.mode != "systemd-run":
            raise ValueError(f"unknown sandbox mode {self.mode!r}")
        exe = shutil.which("systemd-run")
        if not exe:
            raise RuntimeError("sandbox mode systemd-run but systemd-run is not on PATH")
        argv = [exe, "--user", "--quiet", "--pipe", "--wait", "--collect",
                "-p", f"RuntimeMaxSec={self.timeout_s}", f"--working-directory={cwd}"]
        if self.unit:
            argv.append(f"--unit={self.unit}")
        argv += [f"-pReadOnlyPaths={p}" for p in self.readonly]
        argv += [f"-pReadWritePaths={p}" for p in self.writable]
        argv += [f"-pInaccessiblePaths=-{shlex.quote(p)}" for p in self.inaccessible]
        source = dict(self.environment) if self.environment is not None else os.environ
        for name in PASS_ENV:
            val = env_path if (name == "PATH" and env_path) else source.get(name)
            if val:
                argv.append(f"--setenv={name}={val}")
        return argv

    def cancel(self) -> bool:
        """Stop only this attempt's named transient service after authority loss."""
        if self.mode == "none":
            return True
        if not self.unit:
            return False
        try:
            result = subprocess.run(["systemctl", "--user", "stop", self.unit],
                                    capture_output=True, timeout=15)
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def wrap_shell(self, cmd: str, cwd: Path) -> str:
        """A shell command string that runs `cmd` inside the sandbox."""
        if self.mode == "none":
            return cmd
        payload = ["/bin/sh", "-c", cmd]
        if self.clean_environment:
            source = dict(self.environment) if self.environment is not None else os.environ
            env_exe = shutil.which("env", path=os.defpath)
            if env_exe is None:
                raise RuntimeError("clean train environment requires env on the system path")
            payload = [env_exe, "-i", *[f"{name}={source[name]}" for name in PASS_ENV if source.get(name)], *payload]
        return " ".join(shlex.quote(a) for a in [*self.prefix(cwd), *payload])

    def shim_dir(self, dest: Path, tools: tuple[str, ...]) -> Path | None:
        """Write PATH shims so a launcher (agentops dispatch run) starts sandboxed tools."""
        if self.mode == "none":
            return None
        dest.mkdir(parents=True, exist_ok=True)
        clean_path = os.environ.get("PATH", "")
        for tool in tools:
            real = shutil.which(tool)
            if not real:
                continue
            pre = " ".join(shlex.quote(a) for a in self.prefix(Path("/"), env_path=clean_path))
            pre = pre.replace(shlex.quote("--working-directory=/"), '"--working-directory=$PWD"')
            shim = dest / tool
            # OpenCode's shared background service runs sessions outside the sandbox
            # and maps every clone to one project directory: force a private server.
            fix = ('if [ "$1" = run ] && [ "$2" != --help ]; then shift; set -- run --standalone "$@"; fi\n'
                   if tool == "opencode" else "")
            shim.write_text(f'#!/bin/sh\n{fix}exec {pre} {shlex.quote(real)} "$@"\n')
            shim.chmod(0o755)
        return dest


def from_lane(raw: dict, writable: tuple[str, ...], timeout_s: int, *, attempt_id=None) -> Sandbox:
    unit = ("lanectl-attempt-" + hashlib.sha256(attempt_id.encode()).hexdigest()[:24] + ".service"
            if attempt_id is not None else None)
    return Sandbox(mode=raw.get("mode", "none"), readonly=tuple(raw.get("readonly", ())),
                   writable=writable + tuple(raw.get("writable", ())), timeout_s=timeout_s, unit=unit,
                   inaccessible=runner_credential_paths(os.environ))


def transport_environment():
    """Only runtime/transport basics reach the trusted systemd launcher."""
    return {name: os.environ[name] for name in PASS_ENV if os.environ.get(name)}


def runner_credential_paths(source):
    """Coordinator credentials only; native harness provider auth stays usable."""
    home = Path(source.get("HOME", str(Path.home()))).resolve()
    config = Path(source.get("XDG_CONFIG_HOME") or home / '.config').resolve()
    runtime = Path(source.get("XDG_RUNTIME_DIR") or f'/run/user/{os.getuid()}').resolve()
    paths = [home / '.config/vuoro/credentials', config / 'vuoro/credentials', runtime / 'credentials']
    if source.get('CREDENTIALS_DIRECTORY'):
        paths.append(Path(source['CREDENTIALS_DIRECTORY']).resolve())
    return tuple(dict.fromkeys(str(p) for p in paths))


def for_train(*, readonly, writable, timeout_s=1800, env=None):
    """Mandatory direct-file and environment credential fence for train code.

    This namespace is independent of the worker harness policy. Network behavior
    is unchanged; it is not full isolation against arbitrary hostile same-UID code.
    Missing credential paths are optional mounts and never need to be opened here.
    """
    source = dict(os.environ if env is None else env)
    home = Path(source.get("HOME", str(Path.home()))).resolve()
    config = Path(source.get("XDG_CONFIG_HOME") or home / '.config').resolve()
    data = Path(source.get("XDG_DATA_HOME") or home / '.local/share').resolve()
    paths = [*runner_credential_paths(source),
             home / '.config/forgejo', config / 'forgejo',
             home / '.local/share/forgejo-cli', data / 'forgejo-cli',
             home / '.ssh', home / '.config/sops', config / 'sops',
             home / '.local/share/opencode/auth.json', data / 'opencode/auth.json',
             home / '.codex/auth.json', home / '.claude/.credentials.json']
    return Sandbox(mode='systemd-run', readonly=tuple(readonly), writable=tuple(writable),
                   timeout_s=timeout_s, inaccessible=tuple(dict.fromkeys(str(p) for p in paths)),
                   clean_environment=True,
                   environment=tuple((name, source[name]) for name in PASS_ENV if source.get(name)))
