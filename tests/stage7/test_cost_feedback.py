"""Unit tests for cost feedback: quota consumed versus landed work."""
from lanectl import report
from lanectl.contracts import make_event
from lanectl.feedback import cost_feedback

M1 = "opencode-go/deepseek-v4.1-flash"
M2 = "opencode-go/glm-5"


def _claim(aid, model):
    return make_event("item.claimed", {"attempt_id": aid, "lane": "implement",
                                      "model": model, "worker": "opencode"},
                      item_id=aid.rsplit("-", 1)[0])


def _use(n, aid=None, provider="opencode"):
    data = {"provider": provider, "source": "adapter", "units": {"output_tokens": n}}
    if aid:
        data["attempt_id"] = aid
    return make_event("usage.recorded", data)


def _landed(aid):
    return make_event("item.landed", {"attempt_id": aid, "train_id": "t", "fix_commits": []},
                      item_id=aid.rsplit("-", 1)[0])


def _fix(aid, cls):
    return make_event("integrator.fix", {"attempt_id": aid, "commit": "c1", "fix_class": cls})


def test_unattributed_usage_is_provider_scoped():
    fb = cost_feedback([_use(700, provider="opencode"), _use(900, provider="other-cli")])
    assert fb["_unattributed"] == {"output_tokens": 700}
    assert all(m.startswith("_") for m in fb)   # no claim -> no model rows


def test_fixes_count_only_on_landed_attempts():
    ev = [_claim("aa-a1", M1), _use(1000, "aa-a1"), _use(1000, "aa-a2"),
          _landed("aa-a1"), _fix("aa-a1", "model-error"), _fix("aa-a2", "model-error")]
    row = cost_feedback(ev)[M1]
    assert row["attempts"] == 1 and row["landed"] == 1
    assert row["fixes"] == 1 and row["model_error_fixes"] == 1
    assert row["output_tokens"] == 1000     # usage for an unclaimed attempt is not attributed
    assert row["tokens_per_landed"] == 1000


def test_models_are_separate_and_formatted_in_sorted_order():
    ev = [_claim("bb-a1", M2), _use(4000, "bb-a1"),
          _claim("aa-a1", M1), _use(1000, "aa-a1"), _use(500),
          _fix("aa-a1", "spec-gap")]
    fb = cost_feedback(ev)
    assert fb[M1]["tokens_per_landed"] is None and fb[M1]["fixes"] == 0
    assert fb[M2]["output_tokens"] == 4000

    lines = [ln for ln in report.format_report(report.build_report(ev)).splitlines()
             if "cost_feedback" in ln or "attempts=" in ln or "unattributed" in ln]
    assert lines[0] == "cost_feedback:"
    assert lines[1] == (f"  {M1}: attempts=1 landed=0 output_tokens=1000 "
                        "tokens_per_landed=- fixes=0 model_error_fixes=0")
    assert lines[2] == (f"  {M2}: attempts=1 landed=0 output_tokens=4000 "
                        "tokens_per_landed=- fixes=0 model_error_fixes=0")
    assert lines[3] == "  unattributed opencode output_tokens=500"
