"""Claude lane attempts reserve and record against the anthropic provider.

The ``estate`` fixture comes from tests/stage8/conftest.py and routes the
implement lane at ``scripted/model``.  These tests re-route it at a Claude model
(the vuoro-cloud route) and install an ``anthropic`` allocation policy, so they
exercise the same paths the planner-owned acceptance file covers without
duplicating it.
"""
import os
import textwrap
from pathlib import Path

from lanectl import runner
from lanectl.adapters import AdapterResult
from tests.seed.test_end_to_end import SUB_TEST


def _route_claude():
    p = Path(os.environ["LANECTL_HOME"]) / "governance" / "lanes" / "implement.toml"
    p.write_text(p.read_text().replace(
        'weights = { "scripted/model" = 1.0 }',
        'weights = { "claude-sonnet-5-5" = 1.0 }'))


def _anthropic_policy():
    gov = Path(os.environ["LANECTL_HOME"]) / "governance"
    (gov / "allocation.toml").write_text(textwrap.dedent("""
        revision = 9
        [providers.anthropic]
        unit = "output_tokens"
        expiring = true
        pool = "anthropic:default"
        freshness_s = 3600
        [[providers.anthropic.windows]]
        name = "week"
        length_s = 604800
        budget = 1000000
        [providers.anthropic.estimates]
        S = 15000
        """))


def _of(log, etype):
    return [e["data"] for e in log.read() if e["type"] == etype]


def _good_with_usage(n):
    def fn(*, worktree, **_):
        wt = Path(worktree)
        (wt / "src" / "calc.py").write_text(
            "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n")
        (wt / "tests" / "test_sub_extra.py").write_text(
            "from calc import sub\n\ndef test_neg():\n    assert sub(1, 2) == -1\n")
        return AdapterResult("done", 0, "ok", None, {"output_tokens": n})
    return fn


def test_claude_attempt_reserves_against_anthropic(estate):
    repo, release, log = estate
    _route_claude()
    _anthropic_policy()
    release("claude-work", SUB_TEST)
    c = runner.admit("implement", log)
    assert not isinstance(c, str), c
    reserved = _of(log, "capacity.reserved")
    assert reserved == [{
        "reservation_id": f"res-{c.attempt_id}", "provider": "anthropic",
        "pool": "anthropic:default", "unit": "output_tokens", "amount": 15000,
        "attempt_id": c.attempt_id}]


def test_claude_usage_is_recorded_under_anthropic(estate):
    repo, release, log = estate
    _route_claude()
    _anthropic_policy()
    release("claude-work", SUB_TEST)
    c = runner.admit("implement", log)
    assert not isinstance(c, str), c
    runner.execute(c, log, adapter_fn=_good_with_usage(12345))
    usage = _of(log, "usage.recorded")
    assert usage and usage[-1]["provider"] == "anthropic"
    assert usage[-1]["model"] == "claude-sonnet-5-5"
    assert usage[-1]["attempt_id"] == c.attempt_id
