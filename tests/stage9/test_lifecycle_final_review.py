def test_web_commit_details_and_unattempted_release_train_scope():
    from lanectl.contracts import make_event
    from lanectl.lifecycle import lifecycle_rows
    from lanectl.lifecycle_web import render_lifecycle
    from tests.stage9.test_acc_verification import row
    from tests.stage9.test_acc_ui_integration import RealOwner
    page = render_lifecycle("lanectl", row())
    assert all(value in page for value in ("checked_sha", "landed_sha", "abc"))
    assert "secret raw output" not in page and "token=secret" not in page
    foreign = make_event("train.built", dict(train_id="foreign", base_sha="base", attempts=["bb-a1"], passed=True))
    result = lifecycle_rows(RealOwner(), [foreign], item_id="aa", work_ids={"aa": 2895})[0]
    assert result.get("train_id") is None and result["facts"]["local.train"]["state"] == "unknown"
