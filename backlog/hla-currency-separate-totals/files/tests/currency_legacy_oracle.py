"""Read-only legacy fact inventory and equality oracle; never repairs stores."""
import re
from datetime import date, datetime, timezone
from decimal import Decimal

FACTS = {
    "fact_transaction": "transaction_id",
    "fact_bill": "bill_id",
    "fact_utility_usage": "usage_id",
}


def canonical(value):
    if value is None:
        return {"type": "null", "value": None}
    if isinstance(value, datetime):
        instant = value.astimezone(timezone.utc) if value.utcoffset() is not None else value
        return {"type": "datetime", "value": instant.isoformat()}
    if isinstance(value, date):
        return {"type": "date", "value": value.isoformat()}
    if isinstance(value, Decimal):
        return {"type": "decimal", "value": format(value.normalize(), "f")}
    if isinstance(value, bool):
        return {"type": "boolean", "value": value}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": repr(value)}
    if isinstance(value, str):
        return {"type": "string", "value": value}
    if isinstance(value, bytes):
        return {"type": "bytes", "value": value.hex()}
    raise TypeError(f"unsupported fact scalar type: {type(value).__name__}")


def snapshot_legacy_facts(store, baseline=None):
    """Capture all original columns and rows, with primary-key order and no writes.

    When checking a candidate, project the recorded legacy columns so added
    columns do not change the inventory. A supported equivalent read-only
    projection may be needed if the implementation replaces these relations.
    """
    result = {}
    for relation, key in FACTS.items():
        metadata = store.fetchall(f"PRAGMA table_info('{relation}')")
        available = {row[1]: row[2] for row in metadata}
        columns = list(available) if baseline is None else baseline[relation]["columns"]
        assert columns and key in columns and set(columns) <= set(available), (relation, columns, available)
        assert all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", c) for c in columns)
        projection = ", ".join(f'"{column}"' for column in columns)
        rows = store.fetchall_dicts(f'SELECT {projection} FROM "{relation}" ORDER BY "{key}"')
        result[relation] = {
            "columns": columns,
            "column_types": [available[column] for column in columns],
            "rows": [[canonical(row[column]) for column in columns] for row in rows],
        }
    return result


def assert_inventory_unchanged(expected, observed):
    """Require the exact baseline relations, source columns and fact rows."""
    assert observed == expected, "legacy fact inventory changed"
