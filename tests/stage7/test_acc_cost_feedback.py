"""Acceptance: cost feedback (planner-owned)."""
from lanectl import report
from lanectl.contracts import make_event
from lanectl.feedback import cost_feedback

M = "opencode-go/deepseek-v4.1-flash"


def _claim(aid, model=M):
    return make_event("item.claimed", {"attempt_id": aid, "lane": "implement", "model": model, "worker": "opencode"},
                      item_id=aid.rsplit("-", 1)[0])


def _use(n, aid=None):
    data = {"provider": "opencode", "source": "adapter", "units": {"output_tokens": n}}
    if aid:
        data["attempt_id"] = aid
    return make_event("usage.recorded", data)


def test_tokens_per_landed_and_fixes():
    ev = [_claim("aa-a1"), _use(10000, "aa-a1"), _claim("bb-a1"), _use(30000, "bb-a1"),
          _claim("bb-a2"), _use(20000, "bb-a2"), _use(5000),
          make_event("item.landed", {"attempt_id": "aa-a1", "train_id": "tt", "fix_commits": ["c1"]}, item_id="aa"),
          make_event("integrator.fix", {"attempt_id": "aa-a1", "commit": "c1", "fix_class": "spec-gap"}),
          make_event("item.landed", {"attempt_id": "bb-a2", "train_id": "tt", "fix_commits": []}, item_id="bb")]
    fb = cost_feedback(ev)
    row = fb[M]
    assert row["attempts"] == 3 and row["landed"] == 2 and row["output_tokens"] == 60000
    assert row["tokens_per_landed"] == 30000 and row["fixes"] == 1 and row["model_error_fixes"] == 0
    assert fb["_unattributed"] == {"output_tokens": 5000}


def test_nothing_landed_is_none_not_zero():
    fb = cost_feedback([_claim("aa-a1"), _use(9000, "aa-a1")])
    assert fb[M]["landed"] == 0 and fb[M]["tokens_per_landed"] is None


def test_report_section():
    text = report.format_report(report.build_report([_claim("aa-a1"), _use(9000, "aa-a1")]))
    assert "cost_feedback:" in text
    assert f"  {M}: attempts=1 landed=0 output_tokens=9000 tokens_per_landed=- fixes=0 model_error_fixes=0" in text
