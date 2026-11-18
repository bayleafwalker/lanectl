from pathlib import Path


def test_quickstart_distinguishes_work_from_lane_stream():
    readme = (Path(__file__).resolve().parents[2] / "README.md").read_text()
    assert "lanectl coordinate example --work-item 123" in readme
    assert "lanectl coordinate example --require-stream-read" in readme
    assert "claim-run" in readme
