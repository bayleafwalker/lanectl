"""Extra coverage for the report section registry."""
from lanectl import report


def test_sections_format_in_name_order_and_json_only_sections_are_built():
    report.register_section("zz_second", lambda events: "B", lambda value: [f"second={value}"])
    report.register_section("zz_first", lambda events: "A", lambda value: [f"first={value}"])
    report.register_section("zz_json", lambda events: len(events))
    try:
        built = report.build_report([])
        assert built["zz_first"] == "A"
        assert built["zz_second"] == "B"
        assert built["zz_json"] == 0
        lines = report.format_report(built).splitlines()
        assert lines.index("first=A") < lines.index("second=B")
        assert not any("zz_json" in line for line in lines)
    finally:
        for name in ("zz_first", "zz_second", "zz_json"):
            report._SECTIONS.pop(name, None)
