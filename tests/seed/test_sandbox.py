"""Seed: the sandbox makes everything but the attempt checkout read-only."""
import os
import subprocess

from lanectl.sandbox import Sandbox


def test_systemd_sandbox_blocks_writes_outside_checkout(tmp_path):
    ro, rw = tmp_path / "estate", tmp_path / "estate" / "attempt"
    rw.mkdir(parents=True)
    sb = Sandbox("systemd-run", readonly=(str(ro),), writable=(str(rw),), timeout_s=60)
    cmd = sb.wrap_shell("touch inside && (touch ../outside 2>/dev/null && echo LEAK || echo BLOCKED)", rw)
    out = subprocess.run(cmd, shell=True, cwd=rw, capture_output=True, text=True)
    assert "BLOCKED" in out.stdout, out
    assert (rw / "inside").exists() and not (ro / "outside").exists()


def test_shim_runs_tool_inside_sandbox(tmp_path):
    ro, rw = tmp_path / "estate", tmp_path / "estate" / "attempt"
    rw.mkdir(parents=True)
    sb = Sandbox("systemd-run", readonly=(str(ro),), writable=(str(rw),), timeout_s=60)
    shims = sb.shim_dir(tmp_path / "shims", ("sh",))
    out = subprocess.run([str(shims / "sh"), "-c", "pwd; touch ../x 2>/dev/null && echo LEAK || echo BLOCKED"],
                         cwd=rw, capture_output=True, text=True)
    assert out.stdout.split() == [str(rw), "BLOCKED"], out


def test_none_mode_is_transparent(tmp_path):
    sb = Sandbox("none", (), (), 1)
    assert sb.wrap_shell("echo hi", tmp_path) == "echo hi" and sb.shim_dir(tmp_path, ("sh",)) is None


def test_opencode_shim_forces_private_server(tmp_path):
    import stat
    fake = tmp_path / "bin" / "opencode"
    fake.parent.mkdir()
    fake.write_text('#!/bin/sh\necho "$@"\n')
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    rw = tmp_path / "w"
    rw.mkdir()
    os.environ["PATH"] = f"{fake.parent}{os.pathsep}{os.environ['PATH']}"
    sb = Sandbox("systemd-run", readonly=(), writable=(str(rw),), timeout_s=60)
    shims = sb.shim_dir(tmp_path / "shims", ("opencode",))
    run = subprocess.run([str(shims / "opencode"), "run", "--format", "json", "hi"], cwd=rw,
                         capture_output=True, text=True).stdout.split()
    assert run == ["run", "--standalone", "--format", "json", "hi"]
    helped = subprocess.run([str(shims / "opencode"), "run", "--help"], cwd=rw,
                            capture_output=True, text=True).stdout.split()
    assert helped == ["run", "--help"]
