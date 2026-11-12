from lanectl.lifecycle import lifecycle
from tests.stage9.test_acc_ui_integration import RealOwner


def test_owner_reported_unavailability_is_unknown_after_successful_rpc():
    owner = RealOwner()
    assert lifecycle(owner, item_id=2895)["facts"]["work.public.item-v1"]["state"] == "observed"
    invoke = owner.invoke
    owner.invoke = lambda envelope: (dict(authority="sprintctl", state="unavailable", item=None)
        if envelope["operation"] == "work.public.item-v1" else invoke(envelope))
    assert lifecycle(owner, item_id=2895)["facts"]["work.public.item-v1"]["state"] == "unknown"
