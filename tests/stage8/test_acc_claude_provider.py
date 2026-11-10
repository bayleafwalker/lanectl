"""Acceptance: Claude lane attempts use the anthropic provider (planner-owned)."""
from lanectl import runner, windows


def test_provider_for_claude_is_anthropic():
    assert runner.provider_for("claude-sonnet-5-5") == "anthropic"
    assert runner.provider_for("claude-opus-5-5") == "anthropic"


def test_opencode_unchanged_and_consistent_with_windows():
    for model in ("opencode-go/deepseek-v4.1-flash", "opencode-go/deepseek-v4-pro",
                  "claude-sonnet-5-5"):
        assert runner.provider_for(model) == windows.provider_for(model)
    assert runner.provider_for("opencode-go/deepseek-v4.1-flash") == "opencode"


def test_usage_event_uses_the_provider_not_the_worker():
    import inspect
    src = inspect.getsource(runner.execute)
    assert '"provider": c.worker' not in src
    assert "provider_for(c.model)" in src
