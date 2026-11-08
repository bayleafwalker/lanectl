"""Acceptance: report sections registry (planner-owned)."""
from lanectl import report


def test_stage_modules_do_not_import_report():
    import inspect
    from lanectl import capacity, evaluator, landing
    for mod in (capacity, evaluator, landing):
        assert "from .report" not in inspect.getsource(mod) and hasattr(mod, "report_section")


def test_registered_section_is_built_and_formatted():
    report.register_section("zz_probe", lambda events: len(events), lambda v: [f"zz_probe: n={v}"])
    try:
        r = report.build_report([])
        assert r["zz_probe"] == 0
        assert "zz_probe: n=0" in report.format_report(r).splitlines()
    finally:
        report._SECTIONS.pop("zz_probe", None)


def test_stage_sections_are_registered_and_keys_kept():
    r = report.build_report([])
    for name in ("evaluator", "landing_shadow", "shadow_admission"):
        assert name in report._SECTIONS
    assert r["shadow_admission"] == {"recorded": 0, "agreed": 0, "agreement": None}
    text = report.format_report(r)
    assert "shadow_admission: recorded=0 agreed=0" in text
    assert "landing_shadow: trains=0" in text
