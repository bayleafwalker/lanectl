from unittest.mock import patch

from lanectl.steering import effective_weights
from lanectl.steering import admission
from lanectl.capacity import AllocationPolicy
from lanectl.contracts import make_event
from datetime import datetime, timezone
import pytest


def test_static_until_class_is_authorized():
    assert effective_weights([], {"a": .75, "b": .25}, "glue", {}) == {"a": .75, "b": .25}


def test_insufficient_evidence_preserves_reviewed_weights():
    policy = dict(adaptive_classes=["glue"], min_evidence=5, min_weight=.05,
                  max_weight=1., prior=[1, 1])
    with patch("lanectl.steering.learning.posterior", return_value={}):
        assert effective_weights([], {"a": .75, "b": .25}, "glue", policy) == {"a": .75, "b": .25}


def test_learning_cannot_add_model_and_changes_are_bounded():
    policy = dict(adaptive_classes=["glue"], min_evidence=5, min_weight=.05,
                  max_weight=1., prior=[1, 1], max_relative_change=.2)
    evidence = {(m, "glue"): {"ruled": 10} for m in ["a", "b"]}
    with patch("lanectl.steering.learning.posterior", return_value=evidence), \
         patch("lanectl.steering.learning.suggest", return_value={"a": .1, "b": 1., "evil": 1.}):
        assert effective_weights([], {"a": .75, "b": .25}, "glue", policy) == {"a": .6, "b": .3}


def test_invalid_policy_cannot_change_routing():
    for value in [-1, float("nan"), 2]:
        try:
            effective_weights([], {"a": 1.}, "glue", {"adaptive_classes": ["glue"], "max_relative_change": value})
        except ValueError:
            pass
        else:
            raise AssertionError("invalid policy accepted")


NOW = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)


def allocation():
    return AllocationPolicy.from_dict({"revision": 1, "providers": {"p": {
        "unit": "output_tokens", "pool": "account", "freshness_s": 3600,
        "estimates": {"S": 10}, "windows": [{"name": "day", "budget": 100,
        "length_s": 86400, "anchor": "2026-11-10T00:00:00Z", "budget_basis": "verified"},
        {"name": "model", "budget": 20, "length_s": 86400,
         "anchor": "2026-11-10T00:00:00Z", "budget_basis": "verified", "models": ["a"]}]}}})


def observation(value=15, **overrides):
    return make_event("capacity.observed", {"provider": "p", "pool": "account",
        "unit": "output_tokens", "basis": "measured", "source": "provider",
        "scope": "account", "value_kind": "cumulative", "value": value,
        "observed_at": "2026-11-10T11:59:00Z", "window_start": "2026-11-10T00:00:00Z",
        **overrides}, ts="2026-11-10T12:00:00Z")


def test_model_limit_blocks_only_applicable_model_when_enforced():
    events = [observation()]
    assert admission(events, allocation(), NOW, "p", "S", "a", enforce=True)["decision"] == "block"
    assert admission(events, allocation(), NOW, "p", "S", "b", enforce=True)["decision"] == "admit"
    assert admission(events, allocation(), NOW, "p", "S", "a")["decision"] == "admit"


def test_unqualified_observations_never_create_measured_headroom():
    for changes in [{"scope": "host"}, {"basis": "estimated"}, {"unit": "requests"},
                    {"observed_at": "2026-11-10T13:00:00Z"},
                    {"observed_at": "2026-11-10T09:00:00Z"}, {"value": -1}, {"model": "a"}]:
        result = admission([observation(**changes)], allocation(), NOW, "p", "S", "a", enforce=True)
        assert result["decision"] == "admit" and result["basis"] == "unknown"


def test_inflight_reservations_prevent_concurrent_overspend():
    held = make_event("capacity.reserved", {"reservation_id": "r", "provider": "p",
        "pool": "account", "unit": "output_tokens", "amount": 10, "attempt_id": "aa"})
    result = admission([observation(5), held], allocation(), NOW, "p", "S", "a", enforce=True)
    assert result["decision"] == "block"


def test_denial_blocks_without_capacity_until_observed_reset():
    deny = observation(value_kind="denial", value=None, reset_at="2026-11-10T13:00:00Z")
    assert admission([deny], allocation(), NOW, "p", "S", "a", enforce=True)["decision"] == "block"
    deny["data"]["reset_at"] = "2026-11-10T11:59:30Z"
    assert admission([deny], allocation(), NOW, "p", "S", "a", enforce=True)["decision"] == "admit"


def test_pool_reservations_shared_across_provider_aliases_and_deduplicated():
    held = make_event("capacity.reserved", {"reservation_id": "r", "provider": "alias",
        "pool": "account", "unit": "output_tokens", "amount": 10, "attempt_id": "aa"})
    assert admission([observation(5), held], allocation(), NOW, "p", "S", "a", enforce=True)["decision"] == "block"
    assert admission([observation(0), held, held], allocation(), NOW, "p", "S", "a", enforce=True)["decision"] == "admit"
    reconciled = make_event("capacity.reconciled", {"reservation_id": "r", "provider": "alias",
        "attempt_id": "aa", "actual": 0, "outcome": "completed"})
    assert admission([observation(5), held, reconciled], allocation(), NOW, "p", "S", "a", enforce=True)["decision"] == "admit"


def test_admission_modes_are_explicit_and_default_shadow():
    from lanectl.capacity import ProviderPolicy, PolicyError
    assert allocation().providers["p"].admission_mode == "shadow"
    assert ProviderPolicy("p", "tokens", False, (), admission_mode="enforce").admission_mode == "enforce"
    with pytest.raises(PolicyError):
        ProviderPolicy("p", "tokens", False, (), admission_mode="yes")


def test_reviewed_routing_policy_keeps_opt_in(tmp_path):
    from lanectl.learning import load_limits
    path = tmp_path / "routing.toml"
    path.write_text('min_weight=.05\nmax_weight=1.0\nmin_evidence=5\nprior=[1,1]\nadaptive_classes=["glue"]\nmax_relative_change=.1\n'.replace('=.','=0.'))
    assert load_limits(path)["adaptive_classes"] == ["glue"]
    assert load_limits(path)["max_relative_change"] == .1
