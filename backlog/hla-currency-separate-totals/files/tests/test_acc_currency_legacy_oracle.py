"""Independent controls for the legacy typed fact-inventory equality oracle."""
import copy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from currency_legacy_oracle import assert_inventory_unchanged, canonical


def test_inventory_oracle_rejects_dropped_added_mutated_and_duplicate_facts():
    expected = {
        "fact_transaction": {"columns": ["transaction_id", "amount", "currency"],
                             "column_types": ["VARCHAR", "DECIMAL(18,4)", "VARCHAR"],
                             "rows": [[canonical("170"), canonical(Decimal("170")), canonical("EUR")],
                                      [canonical("t2"), canonical(Decimal("80")), canonical("USD")]]},
        "fact_bill": {"columns": ["bill_id", "billed_amount", "currency"],
                      "column_types": ["VARCHAR", "DECIMAL(18,4)", "VARCHAR"],
                      "rows": [[canonical("b1"), canonical(Decimal("200")), canonical("EUR")],
                               [canonical("b2"), canonical(Decimal("100")), canonical("USD")]]},
        "fact_utility_usage": {"columns": ["usage_id", "usage_quantity"],
                               "column_types": ["VARCHAR", "DECIMAL(18,4)"],
                               "rows": [[canonical("u1"), canonical(Decimal("100"))]]},
    }
    assert_inventory_unchanged(expected, copy.deepcopy(expected))
    bad = []
    dropped = copy.deepcopy(expected)
    dropped["fact_transaction"]["rows"].pop()
    bad.append(dropped)
    added = copy.deepcopy(expected)
    added["fact_bill"]["rows"].append([canonical("b3"), canonical(Decimal("1")), canonical("USD")])
    bad.append(added)
    relabelled = copy.deepcopy(expected)
    relabelled["fact_bill"]["rows"][0][2] = canonical("USD")
    bad.append(relabelled)
    changed_identity = copy.deepcopy(expected)
    changed_identity["fact_transaction"]["rows"][0][0] = canonical(170)
    bad.append(changed_identity)
    amount_type_changed = copy.deepcopy(expected)
    amount_type_changed["fact_transaction"]["rows"][0][1] = canonical("170")
    bad.append(amount_type_changed)
    changed_amount = copy.deepcopy(expected)
    changed_amount["fact_transaction"]["rows"][0][1] = canonical(Decimal("171"))
    bad.append(changed_amount)
    duplicated = copy.deepcopy(expected)
    duplicated["fact_utility_usage"]["rows"].append(copy.deepcopy(expected["fact_utility_usage"]["rows"][0]))
    bad.append(duplicated)
    dropped_column = copy.deepcopy(expected)
    dropped_column["fact_transaction"]["columns"].remove("currency")
    bad.append(dropped_column)
    changed_type = copy.deepcopy(expected)
    changed_type["fact_transaction"]["column_types"][1] = "VARCHAR"
    bad.append(changed_type)
    for mutation in bad:
        with pytest.raises(AssertionError):
            assert_inventory_unchanged(expected, mutation)


def test_scalar_types_remain_distinct_while_decimal_scale_is_normalized():
    assert canonical(Decimal("170.0000")) == canonical(Decimal("170.00"))
    assert canonical("170") != canonical(Decimal("170.00"))
    assert canonical("170") != canonical(170)
    assert canonical(True) != canonical(1)
    assert canonical(date(2026, 1, 1)) != canonical("2026-01-01")
    assert canonical(datetime(2026, 1, 1, tzinfo=timezone.utc)) != canonical("2026-01-01T00:00:00+00:00")
    assert canonical(datetime(2026, 1, 1, 2, tzinfo=timezone(timedelta(hours=2)))) == canonical(datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert canonical(None) != canonical("null")
