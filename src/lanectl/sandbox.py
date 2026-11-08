"""Write sandbox for worker harnesses and for running worker-written code.

Governance path. Enforces the lane EffectGrant on the filesystem: everything
under `readonly` roots is mounted read-only except the attempt's own checkout.
Seed implementation: `systemd-run --user` (mount namespaces, RuntimeMaxSec).
Added 2026-11-08 after OpenCode workers wrote into the main checkout.
"""
from __future__ import annotations

import os
import shlex
import shutil
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
        argv += [f"-pReadOnlyPaths={p}" for p in self.readonly]
        argv += [f"-pReadWritePaths={p}" for p in self.writable]
        for name in PASS_ENV:
            val = env_path if (name == "PATH" and env_path) else os.environ.get(name)
            if val:
                argv.append(f"--setenv={name}={val}")
        return argv

    def wrap_shell(self, cmd: str, cwd: Path) -> str:
        """A shell command string that runs `cmd` inside the sandbox."""
        if self.mode == "none":
            return cmd
        return " ".join(shlex.quote(a) for a in self.prefix(cwd)) + " /bin/sh -c " + shlex.quote(cmd)

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


def from_lane(raw: dict, writable: tuple[str, ...], timeout_s: int) -> Sandbox:
    return Sandbox(mode=raw.get("mode", "none"), readonly=tuple(raw.get("readonly", ())),
                   writable=writable + tuple(raw.get("writable", ())), timeout_s=timeout_s)
