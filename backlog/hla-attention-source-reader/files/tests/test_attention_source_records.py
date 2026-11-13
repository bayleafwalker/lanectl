from __future__ import annotations

from datetime import date
from decimal import Decimal

import psycopg
import pytest
from pydantic import ValidationError

from apps.api.routes.report_routes import (
    CONTRACT_RENEWAL_WATCHLIST_ROW_MODEL,
    CONTRACT_REVIEW_CANDIDATES_ROW_MODEL,
    TRANSACTION_ANOMALIES_ROW_MODEL,
    UPCOMING_FIXED_COSTS_ROW_MODEL,
)
from packages.domains.finance.pipelines.subscription_models import MART_UPCOMING_FIXED_COSTS_30D_COLUMNS
from packages.domains.finance.pipelines.transaction_models import MART_TRANSACTION_ANOMALIES_CURRENT_COLUMNS
from packages.domains.utilities.pipelines.utility_models import (
    MART_CONTRACT_RENEWAL_WATCHLIST_COLUMNS,
    MART_CONTRACT_REVIEW_CANDIDATES_COLUMNS,
)
from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService
from packages.pipelines.transformation_service import TransformationService
from packages.storage.duckdb_store import DuckDBStore, WarehouseBusyError
from packages.storage.postgres_reporting import PostgresReportingStore
from tests.postgres_test_support import running_postgres_container


TABLES = {
    "anomaly": ("mart_transaction_anomalies_current", MART_TRANSACTION_ANOMALIES_CURRENT_COLUMNS),
    "contract_review": ("mart_contract_review_candidates", MART_CONTRACT_REVIEW_CANDIDATES_COLUMNS),
    "contract_renewal": ("mart_contract_renewal_watchlist", MART_CONTRACT_RENEWAL_WATCHLIST_COLUMNS),
    "upcoming_cost": ("mart_upcoming_fixed_costs_30d", MART_UPCOMING_FIXED_COSTS_30D_COLUMNS),
}
DAY = date(2026, 4, 10)


def rows():
    anomaly = {"transaction_id": "target/with_under", "booking_date": DAY,
               "counterparty_name": "", "amount": Decimal("10"), "direction": "expense",
               "anomaly_type": "large", "anomaly_reason": "reason"}
    review = {"contract_id": "None/utility", "provider": "", "utility_type": "electricity",
              "reason": "price_high", "score": 3, "current_price": Decimal("1"),
              "market_reference": None, "currency": "EUR"}
    renewal = {"contract_id": "None/utility", "contract_name": "", "provider": "P",
               "utility_type": "electricity", "renewal_date": DAY,
               "days_until_renewal": 5, "current_price": Decimal("1"), "currency": "EUR",
               "contract_duration_days": None}
    upcoming = {"charge_id": "charge/one_x", "contract_name": "Same", "provider": "P",
                "frequency": "monthly", "expected_amount": Decimal("10"), "currency": "EUR",
                "expected_date": DAY, "confidence": "high"}
    return {
        "anomaly": [{**anomaly, "transaction_id": f"first-{i:04}"} for i in range(1200)] + [anomaly],
        "contract_review": [review, {**review, "score": 7, "current_price": Decimal("2")},
                            {**review, "reason": "price_low"},
                            {**review, "contract_id": "other"}],
        "contract_renewal": [renewal, {**renewal, "current_price": Decimal("2")},
                             {**renewal, "renewal_date": date(2026, 4, 11)},
                             {**renewal, "contract_id": "other"}],
        "upcoming_cost": [upcoming, {**upcoming, "charge_id": "charge/two_x"},
                          {**upcoming, "expected_date": date(2026, 4, 11)}],
    }


KEYS = {
    "anomaly": "anomaly_target/with_under",
    "contract_review": "review_None/utility_price_high",
    "contract_renewal": "renewal_None/utility_2026-04-10",
    "upcoming_cost": "upcoming_charge/one_x_2026-04-10",
}


def reader(service):
    # This assertion makes the canonical failure identify the missing public feature.
    assert callable(getattr(service, "get_attention_record", None)), "missing attention source reader"
    return service.get_attention_record


def errors():
    from packages.domains.overview.pipelines.attention_records import (
        AttentionRecordNotFoundError, AttentionRecordUnavailableError,
    )
    return AttentionRecordNotFoundError, AttentionRecordUnavailableError


def make_warehouse():
    store = DuckDBStore.memory()
    ts = TransformationService(store)
    data = rows()
    for kind, (table, columns) in TABLES.items():
        store.execute(f"DELETE FROM {table}")
        names = [name for name, _ in columns]
        placeholders = ", ".join("?" for _ in names)
        for row in data[kind]:
            store.execute(f"INSERT INTO {table} ({', '.join(names)}) VALUES ({placeholders})",
                          [row[name] for name in names])
    return ts


def expected(ts, kind, key):
    table, _ = TABLES[kind]
    expressions = {
        "anomaly": "'anomaly_' || transaction_id",
        "contract_review": "'review_' || contract_id || '_' || reason",
        "contract_renewal": "'renewal_' || contract_id || '_' || CAST(renewal_date AS VARCHAR)",
        "upcoming_cost": "'upcoming_' || charge_id || '_' || CAST(expected_date AS VARCHAR)",
    }
    return ts.store.fetchall_dicts(f"SELECT * FROM {table} WHERE {expressions[kind]} = ?", [key])


def equal_group(actual, want):
    assert len(actual) == len(want)
    assert sorted((repr(sorted(row.items())) for row in actual)) == sorted(
        repr(sorted(row.items())) for row in want
    )


@pytest.fixture
def warehouse():
    ts = make_warehouse()
    try:
        yield ts
    finally:
        ts.store.close()


def test_exact_groups_and_source_mode(warehouse):
    service = ReportingService(warehouse, access_mode=ReportingAccessMode.WAREHOUSE)
    get = reader(service)
    not_found, _ = errors()
    for kind, key in KEYS.items():
        want = expected(warehouse, kind, key)
        assert want
        equal_group(get(kind, key), want)
        with pytest.raises(not_found):
            get(kind, key + "_missing")
    assert len(get("contract_review", KEYS["contract_review"])) == 2
    assert len(get("contract_renewal", KEYS["contract_renewal"])) == 2
    equal_group(get("contract_review", "review_None/utility_price_low"),
                expected(warehouse, "contract_review", "review_None/utility_price_low"))
    equal_group(get("upcoming_cost", "upcoming_charge/two_x_2026-04-10"),
                expected(warehouse, "upcoming_cost", "upcoming_charge/two_x_2026-04-10"))
    assert get("anomaly", KEYS["anomaly"])[0]["transaction_id"] == "target/with_under"


@pytest.mark.parametrize("kind,column,forged,model", [
    ("anomaly", "transaction_id", "anomaly_", TRANSACTION_ANOMALIES_ROW_MODEL),
    ("contract_review", "contract_id", "review__price_high", CONTRACT_REVIEW_CANDIDATES_ROW_MODEL),
    ("contract_review", "reason", "review_None/utility_", CONTRACT_REVIEW_CANDIDATES_ROW_MODEL),
    ("contract_renewal", "contract_id", "renewal__2026-04-10", CONTRACT_RENEWAL_WATCHLIST_ROW_MODEL),
    ("upcoming_cost", "charge_id", "upcoming__2026-04-10", UPCOMING_FIXED_COSTS_ROW_MODEL),
])
def test_empty_identity_invalidates_only_absence(warehouse, kind, column, forged, model):
    get = reader(ReportingService(warehouse, access_mode=ReportingAccessMode.WAREHOUSE))
    not_found, unavailable = errors()
    unknown = KEYS[kind] + "_absent"
    want = expected(warehouse, kind, KEYS[kind])
    with pytest.raises(not_found):
        get(kind, unknown)
    mutated = {**rows()[kind][0], column: ""}
    model.model_validate(mutated)
    table, columns = TABLES[kind]
    names = [name for name, _ in columns]
    warehouse.store.execute(f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
                            [mutated[name] for name in names])
    equal_group(get(kind, KEYS[kind]), want)
    for key in (forged, unknown):
        with pytest.raises(unavailable):
            get(kind, key)


def test_null_charge_and_missing_identity_column(warehouse):
    get = reader(ReportingService(warehouse, access_mode=ReportingAccessMode.WAREHOUSE))
    _, unavailable = errors()
    table = TABLES["upcoming_cost"][0]
    warehouse.store.execute(f"UPDATE {table} SET charge_id = NULL WHERE charge_id = ?", ["charge/two_x"])
    equal_group(get("upcoming_cost", KEYS["upcoming_cost"]),
                expected(warehouse, "upcoming_cost", KEYS["upcoming_cost"]))
    for key in ("upcoming_None_2026-04-10", "upcoming_missing_2026-04-10"):
        with pytest.raises(unavailable):
            get("upcoming_cost", key)
    warehouse.store.execute(f"ALTER TABLE {table} DROP COLUMN charge_id")
    with pytest.raises(unavailable):
        get("upcoming_cost", KEYS["upcoming_cost"])


def test_published_missing_store_and_prefer_fallback(warehouse):
    missing = ReportingService(warehouse, access_mode=ReportingAccessMode.PUBLISHED)
    get = reader(missing)
    _, unavailable = errors()
    with pytest.raises(unavailable):
        get("anomaly", KEYS["anomaly"])
    prefer = reader(ReportingService(warehouse, access_mode=ReportingAccessMode.PREFER_PUBLISHED))
    equal_group(prefer("anomaly", KEYS["anomaly"]), expected(warehouse, "anomaly", KEYS["anomaly"]))


@pytest.mark.integration
@pytest.mark.slow
def test_postgres_current_publication_filtering_and_identity(warehouse, monkeypatch):
    get = reader(ReportingService(warehouse, access_mode=ReportingAccessMode.WAREHOUSE))
    not_found, unavailable = errors()
    with running_postgres_container() as dsn:
        pg = PostgresReportingStore(dsn)
        published_rows = rows()
        published_rows["upcoming_cost"][0]["provider"] = "Published only"
        for kind, (table, columns) in TABLES.items():
            pg.replace_rows(table, columns, published_rows[kind])
        service = ReportingService(warehouse, publication_store=pg, access_mode=ReportingAccessMode.PUBLISHED)
        get = reader(service)
        recorded = []
        original = pg.fetchall_dicts
        def observe(sql, params=None):
            result = original(sql, params)
            recorded.append((sql, params, result))
            return result
        monkeypatch.setattr(pg, "fetchall_dicts", observe)
        # The warehouse cannot supply either the record or absence evidence.
        monkeypatch.setattr(warehouse.store, "fetchall_dicts", lambda *a, **k: pytest.fail("warehouse read"))
        monkeypatch.setattr(warehouse.store, "execute", lambda *a, **k: pytest.fail("warehouse read"))
        for kind, key in KEYS.items():
            table, _ = TABLES[kind]
            want = [r for r in published_rows[kind] if (
                ("anomaly_" + r["transaction_id"] if kind == "anomaly" else
                 "review_" + r["contract_id"] + "_" + r["reason"] if kind == "contract_review" else
                 "renewal_" + r["contract_id"] + "_" + str(r["renewal_date"]) if kind == "contract_renewal" else
                 "upcoming_" + r["charge_id"] + "_" + str(r["expected_date"])) == key)]
            recorded.clear()
            equal_group(get(kind, key), want)
            fact_queries = [(sql, params, result) for sql, params, result in recorded
                            if table in str(sql).lower() and result
                            and set(want[0]).issubset(result[0])]
            assert fact_queries, "must observe the source fact query"
            for sql, params, result in fact_queries:
                assert params and key in params
                equal_group(result, want)
            with pytest.raises(not_found):
                get(kind, key + "_unknown")
        # Public models and fresh Postgres tables both admit empty identity strings.
        for kind, column, forged, model in [
            ("anomaly", "transaction_id", "anomaly_", TRANSACTION_ANOMALIES_ROW_MODEL),
            ("contract_review", "contract_id", "review__price_high", CONTRACT_REVIEW_CANDIDATES_ROW_MODEL),
            ("contract_review", "reason", "review_None/utility_", CONTRACT_REVIEW_CANDIDATES_ROW_MODEL),
            ("contract_renewal", "contract_id", "renewal__2026-04-10", CONTRACT_RENEWAL_WATCHLIST_ROW_MODEL),
            ("upcoming_cost", "charge_id", "upcoming__2026-04-10", UPCOMING_FIXED_COSTS_ROW_MODEL),
        ]:
            table, columns = TABLES[kind]
            with pytest.raises(not_found):
                get(kind, forged)
            before = get(kind, KEYS[kind])
            mutated = {**published_rows[kind][0], column: ""}
            model.model_validate(mutated)
            names = [name for name, _ in columns]
            pg.execute_statements([(f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join('%s' for _ in names)})",
                                    [mutated[name] for name in names])])
            with pytest.raises(unavailable):
                get(kind, KEYS[kind] + "_unknown")
            with pytest.raises(unavailable):
                get(kind, forged)
            equal_group(get(kind, KEYS[kind]), before)
            pg.execute_statements([(f"DELETE FROM {table} WHERE {column} = %s", [""])])
        pg.execute_statements([("UPDATE mart_upcoming_fixed_costs_30d SET charge_id = NULL WHERE charge_id = %s", ["charge/two_x"])])
        with pytest.raises(unavailable):
            get("upcoming_cost", "upcoming_None_2026-04-10")
        assert get("upcoming_cost", KEYS["upcoming_cost"])
        pg.execute_statements([("ALTER TABLE mart_upcoming_fixed_costs_30d DROP COLUMN charge_id", [])])
        with pytest.raises(unavailable):
            get("upcoming_cost", KEYS["upcoming_cost"])
        with pytest.raises(ValidationError):
            UPCOMING_FIXED_COSTS_ROW_MODEL.model_validate({**rows()["upcoming_cost"][0], "expected_date": None})
        pg.execute_statements([("DROP TABLE mart_transaction_anomalies_current", [])])
        with pytest.raises(unavailable):
            get("anomaly", KEYS["anomaly"])


@pytest.mark.integration
@pytest.mark.slow
def test_postgres_driver_failure_is_sanitized_and_other_errors_propagate(warehouse, monkeypatch):
    reader(ReportingService(warehouse))
    _, unavailable = errors()
    with running_postgres_container() as dsn:
        pg = PostgresReportingStore(dsn)
        service = ReportingService(warehouse, publication_store=pg, access_mode=ReportingAccessMode.PUBLISHED)
        get = reader(service)
        marker = "synthetic-private-driver-marker"
        def fail_driver(**kwargs):
            raise psycopg.OperationalError(marker)
        monkeypatch.setattr(pg, "_connect", fail_driver)
        with pytest.raises(unavailable) as exc:
            get("anomaly", KEYS["anomaly"])
        assert marker not in str(exc.value)
        def fail_programming(**kwargs):
            raise RuntimeError("programming defect")
        monkeypatch.setattr(pg, "_connect", fail_programming)
        with pytest.raises(RuntimeError, match="programming defect"):
            get("anomaly", KEYS["anomaly"])
        def fail_busy(**kwargs):
            raise WarehouseBusyError("test", 1, RuntimeError("locked"))
        monkeypatch.setattr(pg, "_connect", fail_busy)
        with pytest.raises(WarehouseBusyError):
            get("anomaly", KEYS["anomaly"])
