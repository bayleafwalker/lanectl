"""Report polish: full class/model names and infra-stopped attempt labels."""
from lanectl import report
from lanectl.contracts import make_event
from lanectl.feedback import cost_feedback

M1 = "opencode-go/deepseek-v4.1-flash"
M2 = "opencode-go/glm-5"
LONG_CLASS = "test-generation"


def _exp(aid, cls=LONG_CLASS, model=M1, elapsed=10.0):
    return make_event("experiment.recorded",
                      {"attempt_id": aid, "model": model, "worker": "opencode",
                       "task_class": cls, "decision": "candidate", "elapsed_s": elapsed},
                      item_id=aid.rsplit("-", 1)[0])


def _claim(aid, model=M1):
    return make_event("item.claimed",
                      {"attempt_id": aid, "lane": "implement", "model": model,
                       "worker": "opencode"},
                      item_id=aid.rsplit("-", 1)[0])


def _decide(aid, reasons, decision="rejected"):
    return make_event("decision.recorded",
                      {"attempt_id": aid, "decision": decision, "reasons": reasons,
                       "rules_revision": 1}, item_id=aid.rsplit("-", 1)[0])


def test_names_are_printed_in_full():
    text = report.format_report(report.build_report([_claim("aa-a1"), _exp("aa-a1")]))
    lines = text.splitlines()
    assert any(line.startswith(LONG_CLASS + " ") for line in lines), lines
    assert any(line.startswith(M1 + " ") for line in lines), lines


def test_numeric_columns_stay_right_aligned_under_the_header():
    ev = [_claim("aa-a1"), _exp("aa-a1", elapsed=10.0),
          _claim("bb-a1", M2), _exp("bb-a1", cls="glue", model=M2, elapsed=20.0)]
    lines = report.format_report(report.build_report(ev)).splitlines()
    header = next(line for line in lines if line.startswith("CLASS"))
    att_end = header.index("ATT") + len("ATT")
    rows = [line for line in lines if line.startswith((LONG_CLASS + " ", "glue "))]
    assert len(rows) == 2, lines
    mean_end = header.index("MEAN_S") + len("MEAN_S")
    for row, mean in zip(rows, (f"{20.0:>8.1f}", f"{10.0:>8.1f}")):
        assert row[att_end - 4:att_end] == "   1", rows       # ATT right aligned in 4
        assert row[mean_end - 8:mean_end] == mean, rows       # MEAN_S keeps its width
    assert header[att_end - 4:att_end] == " ATT"


def test_short_names_use_the_title_width():
    ev = [_claim("aa-a1"), _exp("aa-a1", cls="glue", elapsed=1.0)]
    lines = report.format_report(report.build_report(ev)).splitlines()
    header = next(line for line in lines if line.startswith("CLASS"))
    row = next(line for line in lines if line.startswith("glue "))
    # "CLASS" (5) is wider than "glue" (4), so the name column stays 5 wide.
    assert header.index("ATT") == 7, header
    assert row[:5] == "glue " and row[5] == " " and row[9] == "1", row



def test_infra_stopped_attempts_are_counted_per_model():
    ev = [_claim("aa-a1"), _decide("aa-a1", ["infra: stopped during isolation breach"]),
          _claim("aa-a2"), _decide("aa-a2", ["gate: scope"]),
          _claim("aa-a3"), _decide("aa-a3", ["gate: scope", "infra: mentioned late"]),
          _claim("aa-a4"),                       # claimed, never decided
          _claim("bb-a1", M2), _decide("bb-a1", ["infra: runner died before gates"]),
          _decide("zz-a1", ["infra: unclaimed attempt"])]
    fb = cost_feedback(ev)
    assert fb[M1]["attempts"] == 4 and fb[M1]["infra_attempts"] == 1
    assert fb[M2]["attempts"] == 1 and fb[M2]["infra_attempts"] == 1
    assert all(not m.startswith("zz") for m in fb)     # no row without a claim


def test_infra_label_follows_attempts_in_the_formatted_line():
    ev = [_claim("aa-a1"), _decide("aa-a1", ["infra: runner died before gates"]),
          _claim("aa-a2"), _decide("aa-a2", ["infra: isolation breach"]),
          _claim("aa-a3"), _decide("aa-a3", ["gate: scope"])]
    text = report.format_report(report.build_report(ev))
    line = next(ln for ln in text.splitlines() if ln.strip().startswith(M1 + ":"))
    assert "attempts=3 infra=2 landed=" in line, line
