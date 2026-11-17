"""Independent controls for the legacy fact-inventory equality oracle."""
import copy
from decimal import Decimal

import pytest
from currency_legacy_oracle import assert_inventory_unchanged, canonical


def test_inventory_oracle_rejects_dropped_added_mutated_and_duplicate_facts():
    expected = {
        "fact_transaction": {"columns": ["transaction_id", "amount", "currency"],
                             "rows": [["t1", "170.0000", "EUR"], ["t2", "80.0000", "USD"]]},
        "fact_bill": {"columns": ["bill_id", "billed_amount", "currency"],
                      "rows": [["b1", "200.0000", "EUR"], ["b2", "100.0000", "USD"]]},
        "fact_utility_usage": {"columns": ["usage_id", "usage_quantity"], "rows": [["u1", "100.0000"]]},
    }
    assert_inventory_unchanged(expected, copy.deepcopy(expected))
    bad = []
    dropped = copy.deepcopy(expected)
    dropped["fact_transaction"]["rows"].pop()
    bad.append(dropped)
    added = copy.deepcopy(expected)
    added["fact_bill"]["rows"].append(["b3", "1.0000", "USD"])
    bad.append(added)
    relabelled = copy.deepcopy(expected)
    relabelled["fact_bill"]["rows"][0][2] = "USD"
    bad.append(relabelled)
    changed_identity = copy.deepcopy(expected)
    changed_identity["fact_transaction"]["rows"][0][0] = "different-id"
    bad.append(changed_identity)
    changed_amount = copy.deepcopy(expected)
    changed_amount["fact_transaction"]["rows"][0][1] = "171.0000"
    bad.append(changed_amount)
    duplicated = copy.deepcopy(expected)
    duplicated["fact_utility_usage"]["rows"].append(["u1", "100.0000"])
    bad.append(duplicated)
    dropped_column = copy.deepcopy(expected)
    dropped_column["fact_transaction"]["columns"].remove("currency")
    bad.append(dropped_column)
    for mutation in bad:
        with pytest.raises(AssertionError):
            assert_inventory_unchanged(expected, mutation)


def test_inventory_numeric_comparison_is_independent_of_decimal_scale():
    assert canonical(Decimal("170.0000")) == canonical(Decimal("170.00")) == "170"
