"""HLA1597: run the OnboardingChecklist auto-collapse node:test unit suite."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[1] / "apps" / "web" / "frontend"
SUITE = FRONTEND / "unit" / "onboarding-auto-collapse.test.cjs"


def test_onboarding_checklist_auto_collapses_when_core_sources_active() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.fail("node is required on PATH for the onboarding unit suite")
    for dep in ("esbuild", "react", "react-dom", "next"):
        if not (FRONTEND / "node_modules" / dep).is_dir():
            pytest.fail(f"missing frontend dependency {dep}; run npm ci in {FRONTEND}")
    try:
        result = subprocess.run(
            [node, "--test", str(SUITE)],
            cwd=FRONTEND,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"node unit suite timed out after {exc.timeout}s")
    assert result.returncode == 0, result.stdout + result.stderr
