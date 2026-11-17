"""Read-only legacy fact inventory and equality oracle; never repairs stores."""
import re
from datetime import date, datetime
from decimal import Decimal

FACTS = {
    "fact_transaction": "transaction_id",
    "fact_bill": "bill_id",
    "fact_utility_usage": "usage_id",
}


def canonical(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    return value


def snapshot_legacy_facts(store, baseline=None):
    """Capture all original columns and rows, with primary-key order and no writes.

    When checking a candidate, project the recorded legacy columns so added
    columns do not change the inventory. A supported equivalent read-only
    projection may be needed if the implementation replaces these relations.
    """
    result = {}
    for relation, key in FACTS.items():
        available = [row[1] for row in store.fetchall(f"PRAGMA table_info('{relation}')")]
        columns = available if baseline is None else baseline[relation]["columns"]
        assert columns and key in columns and set(columns) <= set(available), (relation, columns, available)
        assert all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", c) for c in columns)
        projection = ", ".join(f'"{column}"' for column in columns)
        rows = store.fetchall_dicts(f'SELECT {projection} FROM "{relation}" ORDER BY "{key}"')
        result[relation] = {
            "columns": columns,
            "rows": [[canonical(row[column]) for column in columns] for row in rows],
        }
    return result


def assert_inventory_unchanged(expected, observed):
    """Require the exact baseline relations, source columns and fact rows."""
    assert observed == expected, "legacy fact inventory changed"
