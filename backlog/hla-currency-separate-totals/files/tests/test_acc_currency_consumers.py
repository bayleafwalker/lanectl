"""Independent currency and monetary-evidence checks for report consumers."""
from decimal import Decimal

import pytest

from test_acc_currency_separate_totals import MONTH, api, bill, by_currency, load, rows, usage


OVERLAP_PUBLICATIONS = ["mart_utility_cost_summary", "mart_utility_cost_trend_monthly"]


def load_utility_overlap(ts):
    invoices, observations = [], []
    for meter in ("one-invoice", "two-invoices", "overlapping-invoices"):
        first = bill(1, "EUR", 200, meter)
        first["billing_period_end"] = first["billing_period_start"][:8] + "28"
        if meter == "overlapping-invoices":
            first["billing_period_end"] = first["billing_period_start"][:8] + "20"
        invoices.append(first)
        if meter in ("two-invoices", "overlapping-invoices"):
            second = dict(first, billed_amount="60", provider="another-synthetic-provider",
                          invoice_date=first["billing_period_end"])
            if meter == "overlapping-invoices":
                second["billing_period_start"] = first["billing_period_start"][:8] + "10"
                second["billing_period_end"] = first["billing_period_start"][:8] + "28"
            invoices.append(second)
        days = (15, 17) if meter == "overlapping-invoices" else (4, 5)
        observations.extend(dict(usage(day, meter), usage_quantity="50") for day in days)
    assert ts.load_bills(invoices, run_id="many-invoices") == 5
    assert ts.load_utility_usage(observations, run_id="many-observations") == 6
    ts.refresh_publications(OVERLAP_PUBLICATIONS)


def assert_utility_overlap_summary(client):
    summary = rows(client, "/reports/utility-cost-summary")
    assert len(summary) == 3, summary
    by_meter = {row["meter_id"]: row for row in summary}
    assert set(by_meter) == {"one-invoice", "two-invoices", "overlapping-invoices"}
    for meter, total, bill_count in (("one-invoice", "200", 1), ("two-invoices", "260", 2),
                                     ("overlapping-invoices", "260", 2)):
        row = by_meter[meter]
        assert row["currency"] == "EUR" and row["coverage_status"] == "matched", row
        assert Decimal(str(row["billed_amount"])) == Decimal(total), row
        assert Decimal(str(row["usage_quantity"])) == Decimal("100"), row
        assert Decimal(str(row["unit_cost"])) == Decimal(total) / Decimal("100"), row
        assert row["bill_count"] == bill_count and row["usage_record_count"] == 2, row


def assert_utility_overlap_windows(client):
    for start, end, billed, bills in ((1, 20, 200, 1), (10, 28, 60, 1), (1, 28, 260, 2)):
        window = {"meter_id": "overlapping-invoices",
                  "from_period": f"{MONTH}-{start:02}", "to_period": f"{MONTH}-{end:02}"}
        response = client.get("/reports/utility-cost-summary", params=window)
        assert response.status_code == 200, (window, response.text)
        observed = response.json()["rows"]
        assert len(observed) == 1, (window, observed)
        row = observed[0]
        assert row["currency"] == "EUR" and row["coverage_status"] == "matched", (window, row)
        assert Decimal(str(row["billed_amount"])) == Decimal(billed), (window, row)
        assert Decimal(str(row["usage_quantity"])) == Decimal(100), (window, row)
        assert Decimal(str(row["unit_cost"])) == Decimal(billed) / Decimal(100), (window, row)
        assert row["bill_count"] == bills and row["usage_record_count"] == 2, (window, row)


def assert_utility_overlap_trend(client):
    trend = rows(client, "/reports/utility-cost-trend")
    by_currency(trend, "total_cost", {"EUR": 720})
    by_currency(trend, "usage_amount", {"EUR": 300})
    by_currency(trend, "unit_price_effective", {"EUR": "2.4"})


def test_utility_cost_summary_does_not_multiply_bills_or_usage(tmp_path):
    with api(tmp_path) as (ts, client):
        load_utility_overlap(ts)
        assert_utility_overlap_summary(client)


def test_utility_summary_filters_keep_each_periods_observations(tmp_path):
    with api(tmp_path) as (ts, client):
        load_utility_overlap(ts)
        assert_utility_overlap_windows(client)


def test_utility_trend_does_not_multiply_overlapping_usage(tmp_path):
    with api(tmp_path) as (ts, client):
        load_utility_overlap(ts)
        assert_utility_overlap_trend(client)


def test_unbilled_usage_does_not_dilute_billed_currency_unit_price(tmp_path):
    with api(tmp_path) as (ts, client):
        load(ts, [], [bill(1, "EUR", 100, "billed")], [usage(1, "billed"), usage(1, "unbilled")])
        trend = rows(client, "/reports/utility-cost-trend")
        eur = [row for row in trend if row.get("currency") == "EUR"]
        assert len(eur) == 1, trend
        assert Decimal(str(eur[0]["total_cost"])) == Decimal(100), trend
        assert Decimal(str(eur[0]["usage_amount"])) == Decimal(100), trend
        assert Decimal(str(eur[0]["unit_price_effective"])) == Decimal(1), trend



def test_billed_usage_unit_price_control(tmp_path):
    with api(tmp_path) as (ts, client):
        load(ts, [], [bill(1, "EUR", 100, "billed")], [usage(1, "billed")])
        trend = rows(client, "/reports/utility-cost-trend")
        assert len(trend) == 1 and trend[0]["currency"] == "EUR", trend
        assert Decimal(str(trend[0]["usage_amount"])) == Decimal(100), trend
        assert Decimal(str(trend[0]["unit_price_effective"])) == Decimal(1), trend


def tariff_response(client):
    return client.post("/api/scenarios/tariff-shock", json={"tariff_pct_delta": "0.10", "utility_type": "electricity"})


def contains_unavailability(value):
    if isinstance(value, dict):
        return any(contains_unavailability(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_unavailability(item) for item in value)
    return isinstance(value, str) and ("unavailable" in value.lower() or "insufficient" in value.lower())


def scenario_inventory(client):
    response = client.get("/api/scenarios?include_archived=true")
    assert response.status_code == 200, (response.status_code, response.text)
    body = response.json()
    assert isinstance(body, dict) and isinstance(body.get("rows"), list), body
    identifiers = []
    for row in body["rows"]:
        assert isinstance(row, dict) and isinstance(row.get("scenario_id"), str) and row["scenario_id"], row
        identifiers.append(row["scenario_id"])
    assert len(identifiers) == len(set(identifiers)), body
    return set(identifiers)


def test_income_projection_refuses_a_delta_in_a_different_currency(tmp_path):
    with api(tmp_path) as (ts, client):
        load(ts, [(1, "USD", "100.37")])
        endpoint = "/api/scenarios/income-change"
        payload = {"monthly_income_delta": "10.00", "projection_months": 1}
        before = scenario_inventory(client)
        relations = ("dim_scenario", "fact_scenario_assumption", "proj_income_cashflow")
        old_counts = [ts.store.fetchall(f"SELECT count(*) FROM {relation}") for relation in relations]
        incompatible = client.post(endpoint, json={**payload, "currency": "EUR"})
        assert scenario_inventory(client) == before, incompatible.text
        assert [ts.store.fetchall(f"SELECT count(*) FROM {relation}") for relation in relations] == old_counts
        assert incompatible.status_code in (409, 422, 503), incompatible.text
        assert "currenc" in incompatible.text.lower(), incompatible.text

        compatible = client.post(endpoint, json={**payload, "currency": "USD"})
        assert compatible.status_code == 200, compatible.text
        scenario_id = compatible.json()["scenario_id"]
        assert scenario_inventory(client) == before | {scenario_id}
        assert Decimal(compatible.json()["new_monthly_income"]) == Decimal("110.37")
        result = client.get(f"/api/scenarios/{scenario_id}/cashflow")
        assert result.status_code == 200, result.text
        body = result.json()
        assumptions = [row for row in body["assumptions"] if row["assumption_key"] == "monthly_income_delta"]
        assert len(assumptions) == 1 and assumptions[0]["unit"] == "USD", body
        assert len(body["cashflow_rows"]) == 1, body
        projection = body["cashflow_rows"][0]
        assert Decimal(str(projection["baseline_income"])) == Decimal("100.37"), projection
        assert Decimal(str(projection["scenario_income"])) == Decimal("110.37"), projection


SAVED_CASHFLOW_FIELDS = ("currency", "projection_currency", "cashflow_currency", "unit", "currency_unit")
SAVED_CASHFLOW_ASSUMPTIONS = {
    "income-change": {"cashflow_currency", "projection_currency"},
    "expense-shock": {"baseline_monthly_expense", "baseline_expense", "cashflow_currency", "projection_currency"},
}


def saved_cashflow_currency(body, kind):
    declarations = [entry[field] for entry in (body, *body["cashflow_rows"])
                    for field in SAVED_CASHFLOW_FIELDS if entry.get(field) is not None]
    declarations.extend(assumption["unit"] for assumption in body["assumptions"]
                        if assumption["assumption_key"] in SAVED_CASHFLOW_ASSUMPTIONS[kind]
                        and assumption.get("unit") is not None)
    if declarations and kind == "income-change":
        declarations.extend(row["unit"] for row in body["assumptions"]
                            if row["assumption_key"] == "monthly_income_delta" and row.get("unit") is not None)
    return set(declarations)


@pytest.mark.parametrize("currency", ["EUR", "USD"])
@pytest.mark.parametrize("kind", ["income-change", "expense-shock"])
def test_saved_cashflow_keeps_its_currency_after_baseline_changes(tmp_path, kind, currency):
    warehouse = tmp_path / "saved-projections.duckdb"
    with api(tmp_path, warehouse=warehouse) as (ts, client):
        load(ts, [(1, currency, 1000), (2, currency, -100)])
        change = {"monthly_income_delta": "20", "currency": currency} if kind == "income-change" else {"expense_pct_delta": "0.10"}
        created = client.post(f"/api/scenarios/{kind}", json={**change, "projection_months": 1})
        assert created.status_code == 200, created.text
        scenario_id = created.json()["scenario_id"]

    with api(tmp_path / "reopened", warehouse=warehouse) as (ts, client):
        # Replace the fixture's current source denomination after saving.
        other_currency = "USD" if currency == "EUR" else "EUR"
        ts.store.execute("DELETE FROM fact_transaction")
        ts.store.execute("DELETE FROM fact_transaction_current")
        load(ts, [(1, other_currency, 2200), (2, other_currency, -300)])
        by_currency(rows(client, "/reports/monthly-cashflow"), "net", {other_currency: 1900})

        response = client.get(f"/api/scenarios/{scenario_id}/cashflow")
        assert response.status_code == 200, response.text
        body = response.json()
        assert saved_cashflow_currency(body, kind) == {currency}, body
        assert len(body["cashflow_rows"]) == 1, body
        projection = body["cashflow_rows"][0]
        expected = {
            "baseline_income": 1000, "baseline_expense": 100,
            "scenario_income": 1020 if kind == "income-change" else 1000,
            "scenario_expense": 100 if kind == "income-change" else 110,
        }
        assert {key: Decimal(str(projection[key])) for key in expected} == expected, projection


def assert_no_household_projection(client, response, before):
    after = scenario_inventory(client)
    body = response.json()
    assert isinstance(body, dict), body
    returned_id = body.get("scenario_id")
    assert returned_id is None or (isinstance(returned_id, str) and returned_id), body
    identifiers = after - before
    if returned_id is not None:
        identifiers.add(returned_id)
    # Fetch both public views before evaluating either, even on a refused POST.
    probes = [(scenario_id, endpoint, row_keys, client.get(f"/api/scenarios/{scenario_id}/{endpoint}"))
              for scenario_id in sorted(identifiers)
              for endpoint, row_keys in (("comparison", ("scenario_rows", "variance_rows")), ("cashflow", ("cashflow_rows",)))]
    for scenario_id, endpoint, row_keys, result in probes:
        if result.status_code in (404, 409, 422, 503):
            continue
        assert result.status_code == 200, (scenario_id, endpoint, result.status_code, result.text)
        details = result.json()
        assert all(key in details and details[key] in (None, []) for key in row_keys), (scenario_id, endpoint, details)
        assert contains_unavailability(details), (scenario_id, endpoint, details)
    if response.status_code in (409, 422, 503):
        return
    assert response.status_code == 200, (response.status_code, response.text)
    assert "months_until_deficit" in body and body["months_until_deficit"] is None, body
    assert contains_unavailability(body), body


def assert_no_unrepresentable_tariff_scalar(client, response, before):
    assert_no_household_projection(client, response, before)
    if response.status_code in (409, 422, 503):
        return
    body = response.json()
    fields = ("baseline_monthly_utility_cost", "new_monthly_utility_cost", "annual_additional_cost")
    assert all(field in body and body[field] is None for field in fields), body


def test_tariff_shock_cannot_combine_eur_cashflow_with_usd_utility(tmp_path):
    with api(tmp_path) as (ts, client):
        load(ts, [(1, "EUR", 500)], [bill(1, "USD", 100)], [usage(1)])
        before = scenario_inventory(client)
        response = tariff_response(client)
        assert_no_household_projection(client, response, before)
        if response.status_code == 200 and response.json().get("baseline_monthly_utility_cost") is not None:
            body = response.json()
            assert Decimal(str(body["baseline_monthly_utility_cost"])) == Decimal(100), body
            assert Decimal(str(body["new_monthly_utility_cost"])) == Decimal(110), body
            assert_utility_assumption_unit(client, body, "USD")


def test_tariff_shock_cannot_drop_or_blend_utility_currencies(tmp_path):
    with api(tmp_path) as (ts, client):
        load(ts, [(1, "EUR", 500)], [bill(1, "EUR", 100, "eur"), bill(2, "USD", 200, "usd")],
             [usage(1, "eur"), usage(2, "usd")])
        before = scenario_inventory(client)
        assert_no_unrepresentable_tariff_scalar(client, tariff_response(client), before)


def test_tariff_shock_usage_only_is_not_a_zero_bill(tmp_path):
    with api(tmp_path) as (ts, client):
        load(ts, [(1, "EUR", 500)], [], [usage(1)])
        before = scenario_inventory(client)
        assert_no_unrepresentable_tariff_scalar(client, tariff_response(client), before)


def test_tariff_shock_same_currency_and_observed_zero_controls(tmp_path):
    for amount in (100, 0):
        with api(tmp_path / str(amount)) as (ts, client):
            load(ts, [(1, "EUR", 500)], [bill(1, "EUR", amount)], [usage(1)])
            response = tariff_response(client)
            assert response.status_code == 200, response.text
            body = response.json()
            assert Decimal(str(body["baseline_monthly_utility_cost"])) == Decimal(amount)
            assert Decimal(str(body["new_monthly_utility_cost"])) == Decimal(amount) * Decimal("1.10")
            assert Decimal(str(body["annual_additional_cost"])) == Decimal(amount) * Decimal("1.20")


def assert_utility_assumption_unit(client, body, currency):
    assumptions = client.get(f"/api/scenarios/{body['scenario_id']}/assumptions")
    assert assumptions.status_code == 200, assumptions.text
    monetary = [row for row in assumptions.json()["rows"] if row.get("assumption_key") == "baseline_utility_cost"]
    assert len(monetary) == 1 and monetary[0]["unit"] == currency, assumptions.json()


def test_tariff_shock_single_usd_has_truthful_monetary_unit(tmp_path):
    with api(tmp_path) as (ts, client):
        load(ts, [(1, "USD", 500)], [bill(1, "USD", 100)], [usage(1)])
        response = tariff_response(client)
        assert response.status_code == 200, response.text
        body = response.json()
        assert Decimal(str(body["baseline_monthly_utility_cost"])) == Decimal(100)
        assert Decimal(str(body["new_monthly_utility_cost"])) == Decimal(110)
        assert_utility_assumption_unit(client, body, "USD")


def price(contract, component, currency, amount):
    return {"contract_id": contract, "contract_name": contract, "provider": "Synthetic",
            "contract_type": "electricity", "price_component": component,
            "billing_cycle": "per_kwh" if component == "energy" else "monthly",
            "unit_price": amount, "currency": currency,
            "quantity_unit": "kWh" if component == "energy" else None,
            "valid_from": "2025-01-01", "valid_to": None}


def energy_assessment(tmp_path, energy_currency, base_currency):
    with api(tmp_path) as (ts, client):
        prices = [price("current", "energy", energy_currency, "0.0825"),
                  price("current", "base_fee", base_currency, "5.99"),
                  price("quote", "energy", energy_currency, "0.06"),
                  price("quote", "base_fee", energy_currency, "3.99")]
        ts.load_contract_prices(prices, run_id="synthetic-prices")
        bills, usages = [], []
        for month in range(1, 13):
            start = f"2025-{month:02d}-01"
            b = bill(1, energy_currency, 60, "year")
            b.update(billing_period_start=start, billing_period_end=start, billed_quantity="400", invoice_date=start)
            u = usage(1, "year")
            u.update(usage_start=start, usage_end=start, usage_quantity="400")
            bills.append(b)
            usages.append(u)
        ts.load_bills(bills, run_id="synthetic-bills")
        ts.load_utility_usage(usages, run_id="synthetic-usage")
        ts.refresh_publications(["mart_contract_price_current", "mart_utility_cost_summary", "mart_utility_cost_trend_monthly"])
        response = client.get("/control/decisions/definitions/electricity_contract_keep_or_switch/subjects", params={"period": "current"})
        assert response.status_code == 200, response.text
        subjects = response.json()["subjects"]
        assert len(subjects) == 1, subjects
        return subjects[0]


def test_energy_decision_refuses_mixed_contract_components(tmp_path):
    result = energy_assessment(tmp_path, "EUR", "USD")["snapshot"]["assessment"]
    assert result["verdict"] == "insufficient_evidence", result
    assert all(value is None for key, value in result.items() if key.startswith("estimated_annual_")), result


def assert_usd_energy_subject(subject):
    result = subject["snapshot"]["assessment"]
    assert result["currency"] == "USD", result
    expected = {
        "estimated_annual_cost_current_eur": Decimal("467.88"),
        "estimated_annual_cost_best_alternative_eur": Decimal("335.88"),
        "estimated_annual_difference_eur": Decimal("132"),
    }
    amounts = {key: Decimal(str(value)) for key, value in result.items()
               if key.startswith("estimated_annual_") and value is not None}
    assert amounts == expected, result
    annual = {key: value for key, value in subject["baseline"].items()
              if "annual" in key and isinstance(value, dict) and value.get("value") is not None}
    assert {key: Decimal(str(value["value"])) for key, value in annual.items()} == expected, annual
    assert all(value.get("unit") in ("USD/year", "US$/year", "$/year") for value in annual.values()), annual


def test_energy_decision_single_usd_is_never_labelled_eur(tmp_path):
    assert_usd_energy_subject(energy_assessment(tmp_path, "USD", "USD"))


def test_usd_energy_oracle_accepts_legacy_keys_but_rejects_wrong_units_and_values():
    import copy

    import pytest

    values = {"estimated_annual_cost_current_eur": "467.88",
              "estimated_annual_cost_best_alternative_eur": "335.88",
              "estimated_annual_difference_eur": "132"}
    subject = {"snapshot": {"assessment": {"currency": "USD", **values}},
               "baseline": {key: {"value": value, "unit": "USD/year"} for key, value in values.items()}}
    assert_usd_energy_subject(subject)
    wrong_unit = copy.deepcopy(subject)
    wrong_unit["baseline"]["estimated_annual_cost_current_eur"]["unit"] = "EUR/year"
    with pytest.raises(AssertionError):
        assert_usd_energy_subject(wrong_unit)
    wrong_value = copy.deepcopy(subject)
    wrong_value["snapshot"]["assessment"]["estimated_annual_cost_current_eur"] = "468.88"
    with pytest.raises(AssertionError):
        assert_usd_energy_subject(wrong_value)
    current, alternative, _ = values
    for field in ("assessment", "baseline"):
        swapped = copy.deepcopy(subject)
        observed = swapped["snapshot"]["assessment"] if field == "assessment" else swapped["baseline"]
        observed[current], observed[alternative] = observed[alternative], observed[current]
        with pytest.raises(AssertionError):
            assert_usd_energy_subject(swapped)


def test_energy_decision_same_eur_control(tmp_path):
    result = energy_assessment(tmp_path, "EUR", "EUR")["snapshot"]["assessment"]
    assert result["verdict"] == "alternative_estimated_cheaper", result
    assert Decimal(str(result["estimated_annual_cost_current_eur"])) == Decimal("467.88"), result
    assert Decimal(str(result["estimated_annual_cost_best_alternative_eur"])) == Decimal("335.88"), result


def test_tariff_unavailability_oracle_rejects_exposed_and_persisted_blends():
    import httpx
    import pytest

    class Comparisons:
        def __init__(self, comparison, cashflow, rows=()):
            self.comparison, self.cashflow, self.rows = comparison, cashflow, rows
            self.calls = []

        def get(self, path):
            self.calls.append(path)
            if path == "/api/scenarios?include_archived=true":
                return httpx.Response(200, json={"rows": list(self.rows)})
            return self.comparison if path.endswith("/comparison") else self.cashflow

    unavailable = Comparisons(httpx.Response(409, json={"error": "unavailable"}),
                              httpx.Response(404, json={"detail": "unavailable"}))
    refusal = httpx.Response(422, json={"detail": "unavailable"})
    assert scenario_inventory(unavailable) == set()
    assert_no_household_projection(unavailable, refusal, set())
    safe_usd = httpx.Response(200, json={"scenario_id": "usd-only", "months_until_deficit": None,
                                         "baseline_monthly_utility_cost": 100, "new_monthly_utility_cost": 110,
                                         "annual_additional_cost": 120, "currency": "USD", "projection_status": "unavailable"})
    assert_no_household_projection(unavailable, safe_usd, set())
    explicit = Comparisons(httpx.Response(200, json={"status": "unavailable", "scenario_rows": [], "variance_rows": []}),
                           httpx.Response(200, json={"status": "unavailable", "cashflow_rows": []}))
    assert_no_household_projection(explicit, safe_usd, set())
    ambiguous = Comparisons(httpx.Response(200, json={"scenario_rows": [], "variance_rows": []}),
                            httpx.Response(200, json={"cashflow_rows": []}))
    with pytest.raises(AssertionError):
        assert_no_household_projection(ambiguous, safe_usd, set())
    fields = ("baseline_monthly_utility_cost", "new_monthly_utility_cost", "annual_additional_cost")
    null_header = {key: None for key in fields}
    null_header.update(scenario_id="persisted-blend", months_until_deficit=1)
    with pytest.raises(AssertionError):
        assert_no_household_projection(unavailable, httpx.Response(200, json=null_header), set())
    persisted = Comparisons(httpx.Response(200, json={"scenario_rows": [{"expense": 110}], "variance_rows": []}),
                            httpx.Response(200, json={"cashflow_rows": [{"expense": 110}]}),
                            rows=[{"scenario_id": "persisted-blend"}])
    hidden_header = httpx.Response(200, json={**null_header, "months_until_deficit": None, "projection_status": "unavailable"})
    with pytest.raises(AssertionError):
        assert_no_unrepresentable_tariff_scalar(persisted, hidden_header, set())
    # Refusal or missing returned ID cannot hide a newly discoverable projection.
    for result in (refusal, httpx.Response(200, json={"months_until_deficit": None, "projection_status": "unavailable"})):
        persisted.calls.clear()
        with pytest.raises(AssertionError):
            assert_no_household_projection(persisted, result, set())
        assert "/api/scenarios/persisted-blend/comparison" in persisted.calls
        assert "/api/scenarios/persisted-blend/cashflow" in persisted.calls
    metadata = Comparisons(httpx.Response(404, json={"detail": "not found"}),
                           httpx.Response(409, json={"error": "unavailable"}),
                           rows=[{"scenario_id": "existing"}])
    before = scenario_inventory(metadata)
    assert before == {"existing"}
    metadata.rows = [{"scenario_id": "existing"}, {"scenario_id": "metadata-only"}]
    assert_no_household_projection(metadata, refusal, before)
    assert "/api/scenarios/metadata-only/comparison" in metadata.calls
    assert "/api/scenarios/metadata-only/cashflow" in metadata.calls
    assert "/api/scenarios/existing/comparison" not in metadata.calls
    # A failed or malformed catalogue never means an empty inventory.
    class BrokenCatalogue:
        def __init__(self, result):
            self.result = result

        def get(self, path):
            return self.result

    for bad in (httpx.Response(503, json={"error": "unavailable"}), httpx.Response(200, json={}),
                httpx.Response(200, json={"rows": [{"label": "missing id"}]}),
                httpx.Response(200, json={"rows": [{"scenario_id": "x"}, {"scenario_id": "x"}]})):
        with pytest.raises(AssertionError):
            scenario_inventory(BrokenCatalogue(bad))
    for amounts in ((0, 0, 0), (100, 110, 120), (300, 330, 360)):
        with pytest.raises(AssertionError):
            assert_no_unrepresentable_tariff_scalar(unavailable, httpx.Response(200, json={**dict(zip(fields, amounts, strict=True)), "months_until_deficit": None, "scenario_id": "invalid", "projection_status": "unavailable"}), set())
