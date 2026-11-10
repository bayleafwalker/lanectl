from unittest.mock import patch

from lanectl.steering import effective_weights


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
