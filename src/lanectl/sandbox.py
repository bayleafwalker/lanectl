"""Write sandbox for worker harnesses and for running worker-written code.

Governance path. Enforces the lane EffectGrant on the filesystem: everything
under `readonly` roots is mounted read-only except the attempt's own checkout.
Seed implementation: `systemd-run --user` (mount namespaces, command deadlines).
Added 2026-11-08 after OpenCode workers wrote into the main checkout.
"""
from __future__ import annotations

import os
from contextlib import ExitStack
import hashlib
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

PASS_ENV = ("PATH", "HOME", "USER", "LANG", "TERM", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
            "XDG_CACHE_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR", "UV_CACHE_DIR",
            "SSL_CERT_FILE", "NIX_SSL_CERT_FILE")


@dataclass(frozen=True)
class Sandbox:
    mode: str                         # "systemd-run" | "appservice" | "none"
    readonly: tuple[str, ...]         # roots mounted read-only (e.g. /projects)
    writable: tuple[str, ...]         # exceptions: the attempt checkout, scratch dirs
    timeout_s: int
    unit: str | None = None
    inaccessible: tuple[str, ...] = ()
    clean_environment: bool = False
    environment: tuple[tuple[str, str], ...] | None = None
    guard_completion: bool = False

    def prefix(self, cwd: Path, env_path: str | None = None) -> list[str]:
        if self.mode == "none":
            return []
        if self.mode != "systemd-run":
            raise ValueError(f"unknown sandbox mode {self.mode!r}")
        exe = shutil.which("systemd-run")
        if not exe:
            raise RuntimeError("sandbox mode systemd-run but systemd-run is not on PATH")
        argv = [exe, "--user", "--quiet", "--pipe", "--wait", "--collect"]
        if self.guard_completion:
            # Uncaught termination during startup must fail too. For oneshot,
            # the command deadline is its start deadline, not RuntimeMaxSec.
            argv += ["-p", "Type=oneshot", "-p", f"TimeoutStartSec={self.timeout_s}",
                     "-p", "TimeoutStopSec=15"]
        else:
            argv += ["-p", f"RuntimeMaxSec={self.timeout_s}"]
        argv.append(f"--working-directory={cwd}")
        if self.unit:
            argv.append(f"--unit={self.unit}")
        argv += [f"-pReadOnlyPaths={p}" for p in self.readonly]
        argv += [f"-pReadWritePaths={p}" for p in self.writable]
        for path in self.inaccessible:
            if any(char.isspace() or char in "'\"\\\0" for char in path):
                raise ValueError('credential paths with whitespace or quoting are unsupported')
            argv.append(f"-pInaccessiblePaths=-{path}")
        source = dict(self.environment) if self.environment is not None else os.environ
        for name in PASS_ENV:
            val = env_path if (name == "PATH" and env_path) else source.get(name)
            if val:
                argv.append(f"--setenv={name}={val}")
        return argv

    def cancel(self) -> bool:
        """Stop only this attempt's named transient service after authority loss."""
        if self.mode in ("none", "appservice"):
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
        if self.guard_completion:
            # Keep a parent outside the candidate shell: a child handling TERM
            # with exit 0 must not turn an interrupted check into a pass.
            # Pass cmd as one argument, never interpolate it into this script.
            payload = ["/bin/sh", "-c",
                       'trap "exit 125" HUP INT TERM; /bin/sh -c "$1"; rc=$?; exit "$rc"',
                       "lanectl-command", cmd]
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
                   guard_completion=True,
                   environment=tuple((name, source[name]) for name in PASS_ENV if source.get(name)))


def appservice_opencode_config() -> Path:
    value = os.environ.get("LANECTL_APPSERVICE_OPENCODE_CONFIG")
    if not value:
        raise ValueError("LANECTL_APPSERVICE_OPENCODE_CONFIG is required")
    return _image_opencode_config(Path(value))


def _image_opencode_config(path: Path) -> Path:
    config = path.resolve(strict=True)
    if not config.is_relative_to("/nix/store") or not config.is_file():
        raise ValueError("appservice OpenCode configuration must come from the Nix image")
    return config


def probe_appservice() -> None:
    """Prove the worker image can launch and deny reads outside the checkout."""
    config = appservice_opencode_config()
    opencode = shutil.which("opencode")
    shell = shutil.which("bash")
    if opencode is None or shell is None:
        raise RuntimeError("appservice isolation requires image-provided OpenCode and Bash")
    executable = Path(opencode).resolve(strict=True)
    if not executable.is_relative_to("/nix/store"):
        raise ValueError("appservice OpenCode executable must come from the Nix image")
    with tempfile.TemporaryDirectory(prefix="lanectl-appservice-probe-") as temp:
        root = Path(temp)
        checkout = root / "checkout"
        checkout.mkdir()
        marker = root / "coordinator-marker"
        marker.write_text("appservice isolation probe")
        result = run_appservice_command(
            checkout, [shell, "-c",
                       'test ! -e "$1" && test -z "${CREDENTIALS_DIRECTORY:-}" && exec "$2" --version',
                       "lanectl-appservice-probe", str(marker), str(executable)],
            10, opencode_config=config,
        )
        if result.returncode or not result.stdout.strip():
            raise RuntimeError("appservice isolation or OpenCode launch probe failed")


def run_appservice_train(checkout: Path, command: str, timeout_s: int = 1800, *, cancel_event=None):
    """Run a shell check with only its checkout and the image's tools mounted."""
    shell = shutil.which("bash")
    if shell is None:
        raise RuntimeError("appservice train isolation requires Bash")
    return run_appservice_command(checkout, [shell, "-c", command], timeout_s,
                                  cancel_event=cancel_event)


def run_appservice_command(checkout: Path, command: list[str], timeout_s: int, *, cancel_event=None,
                           opencode_config: Path | None = None):
    """Launch an image executable inside the same boundary used for train checks."""
    from .child_process import communicate

    if cancel_event is not None and cancel_event.is_set():
        return subprocess.CompletedProcess(command, 130, "", "appservice train cancelled")

    workspace = checkout.resolve(strict=True)
    launcher = shutil.which("bwrap")
    executable = Path(command[0]).resolve(strict=True)
    if launcher is None or not executable.is_relative_to("/nix/store"):
        raise RuntimeError("appservice isolation requires Bubblewrap and a Nix image executable")

    argv = [
        launcher, "--unshare-user", "--unshare-pid", "--disable-userns",
        "--die-with-parent", "--clearenv",
        "--ro-bind", "/nix/store", "/nix/store",
        "--ro-bind", "/bin", "/bin",
        "--dev", "/dev", "--tmpfs", "/tmp", "--dir", "/tmp/home",
        "--bind", str(workspace), "/checkout", "--chdir", "/checkout",
        "--setenv", "PATH", "/bin", "--setenv", "HOME", "/tmp/home",
    ]
    metadata = workspace / ".git"
    if metadata.exists():
        argv.extend(["--ro-bind", str(metadata), "/checkout/.git"])
    if opencode_config is not None:
        config = _image_opencode_config(opencode_config)
        # Bun needs procfs at startup. Mount a fresh view inside --unshare-pid.
        argv.extend([
            "--proc", "/proc",
            "--setenv", "OPENCODE_CONFIG", str(config),
            "--setenv", "OPENCODE_DISABLE_PROJECT_CONFIG", "1",
            "--setenv", "OPENCODE_CONFIG_PROJECT_DISABLE", "1",
            "--setenv", "OPENCODE_DISABLE_CLAUDE_CODE", "1",
            "--setenv", "OPENCODE_DISABLE_MODELS_FETCH", "1",
            "--setenv", "OPENCODE_DISABLE_AUTOUPDATE", "1",
            "--setenv", "OPENCODE_DISABLE_FREE_MODELS", "1",
        ])
    with ExitStack() as stack:
        if metadata.is_file():
            clone = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="lanectl-train-git-"))) / "clone"
            subprocess.run(
                ["git", "clone", "--quiet", "--no-local", "--no-checkout",
                 "--single-branch", "--no-tags", str(workspace), str(clone)],
                check=True, capture_output=True, timeout=timeout_s,
            )
            subprocess.run(
                ["git", "-C", str(clone), "read-tree", "HEAD"],
                check=True, capture_output=True, timeout=timeout_s,
            )
            subprocess.run(
                ["git", "-C", str(clone), "remote", "remove", "origin"],
                check=True, capture_output=True, timeout=timeout_s,
            )
            argv.extend([
                "--ro-bind", str(clone / ".git"), "/git-metadata",
                "--setenv", "GIT_DIR", "/git-metadata",
                "--setenv", "GIT_WORK_TREE", "/checkout",
            ])
        argv.extend([str(executable), *command[1:]])
        status = stack.enter_context(tempfile.TemporaryFile())
        argv[1:1] = ["--json-status-fd", str(status.fileno())]
        process = stack.enter_context(subprocess.Popen(
            argv, start_new_session=True, text=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={}, pass_fds=(status.fileno(),),
        ))
        out, err, stopped = communicate(process, timeout_s, cancel_event)
        if stopped == "cancelled":
            return subprocess.CompletedProcess(command, 130, out, err + "appservice train cancelled")
        if stopped == "timeout":
            return subprocess.CompletedProcess(command, 124, out, err + "appservice train timed out")
        status.seek(0)
        if b'"exit-code"' not in status.read() or err.startswith("bwrap:"):
            return subprocess.CompletedProcess(command, 125, out, err + "appservice sandbox launch failed")
        return subprocess.CompletedProcess(command, process.returncode, out, err)
