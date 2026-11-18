"""Independent domain-card acceptance through supported source loaders and HTTP."""
from datetime import datetime
from decimal import Decimal

import pytest
from domain_cards_fixture import FIRST, SECOND, domain_world, finance_points, utility_points
from fastapi.testclient import TestClient

DOMAINS = {"finance", "utilities", "homelab"}


def domain_cards(client):
    response = client.get("/reports/domain-cards")
    assert response.status_code == 200, (response.status_code, response.text)
    rows = response.json()["cards"]
    assert len(rows) == len(DOMAINS)
    cards = {row["domain_key"]: row for row in rows}
    assert cards.keys() == DOMAINS
    return cards


def attention(card, *, state="available", label=None, priority=None):
    assert card["attention_state"] == state, card
    if label is None:
        assert card["attention"] is None, card
    else:
        item = card["attention"]
        assert item["label"] == label and item["priority"] == priority, item
        assert isinstance(item["key"], str) and item["key"], item


def monetary_points(rows):
    return [(row["unit"], row["period"], Decimal(str(row["value"]))) for row in rows]


def check_monetary(card, points):
    assert card["metric_state"] == "available", card
    assert card["trend_state"] == "available", card
    expected = sorted((unit, day.strftime("%Y-%m"), Decimal(amount)) for day, unit, amount in points)
    observed = monetary_points(card["trend"])
    assert sorted(observed) == expected, card
    newest = {}
    for row in expected:
        newest[row[0]] = row
    assert sorted(monetary_points(card["headline"])) == sorted(newest.values()), card
    for unit in newest:
        periods = [period for observed_unit, period, _ in observed if observed_unit == unit]
        assert periods == sorted(periods), card


def observation_points(rows):
    return [(row["run_id"], datetime.fromisoformat(row["period"]), row["value"], row["unit"]) for row in rows]


def assert_homelab_comparable(card, *, first_value, second_value, known_count):
    first = ("irregular-first", datetime.fromisoformat(FIRST), first_value, "services")
    second = ("irregular-second", datetime.fromisoformat(SECOND), second_value, "services")
    assert card["metric_state"] == "available", card
    assert card["trend_state"] == "available", card
    assert observation_points(card["trend"]) == [first, second], card
    [headline] = card["headline"]
    # The current observation may omit the run label; compare the observed timestamp and count.
    assert datetime.fromisoformat(headline["period"]) == second[1], headline
    assert headline["value"] == second_value and headline["unit"] == "services", headline
    assert headline["known_count"] == known_count, headline


def assert_data_rich_cards(client, today):
    cards = domain_cards(client)
    finance = [(day, unit, value - 120 if day.year == today.year and day.month == today.month else value)
               for day, unit, value in finance_points(today)]
    check_monetary(cards["finance"], finance)
    check_monetary(cards["utilities"], utility_points(today))
    assert_homelab_comparable(cards["homelab"], first_value=1, second_value=4, known_count=4)
    attention(cards["finance"], label="Unusual transaction: Anchor Books", priority=2)
    attention(cards["utilities"], label="Upcoming renewal: Harbor Utility", priority=3)
    # The current critical services tie, but source ID orders Zeta relay before Alpha proxy.
    homelab = cards["homelab"]
    assert homelab["attention_state"] == "available"
    assert homelab["attention"]["priority"] == 3 and "Zeta relay" in homelab["attention"]["label"]
    assert homelab["attention"]["key"] == "a-critical"
    source = client.get("/reports/attention-items")
    assert source.status_code == 200, source.text
    for key in ("finance", "utilities"):
        top = cards[key]["attention"]
        assert any(row["item_id"] == top["key"] and row["source_domain"] == key
                   and row["title"] == top["label"] and row["severity"] == top["priority"]
                   for row in source.json()["rows"]), top
    assert domain_cards(client) == cards, "identical source should keep deterministic focus and ordering"


def test_domain_cards_observed_values_and_top_attention(tmp_path):
    with domain_world(tmp_path, "normal") as (app, today), TestClient(app) as client:
        assert_data_rich_cards(client, today)


@pytest.mark.parametrize("scenario", ["empty", "usage-only"])
def test_domain_cards_keep_active_domain_membership_on_genuine_empty(tmp_path, scenario):
    with domain_world(tmp_path, scenario) as (app, _), TestClient(app) as client:
        for card in domain_cards(client).values():
            assert card["metric_state"] == "empty" and card["headline"] == [], card
            assert card["trend_state"] == "insufficient_history" and card["trend"] == [], card
            attention(card, state="empty")


def test_homelab_running_cohort_is_observed_zero_with_recovery(tmp_path):
    with domain_world(tmp_path, "recovery") as (app, _), TestClient(app) as client:
        card = domain_cards(client)["homelab"]
        assert_homelab_comparable(card, first_value=1, second_value=0, known_count=2)
        attention(card, state="empty")


@pytest.mark.parametrize("scenario", ["one", "changed"])
def test_homelab_requires_comparable_observed_service_ids(tmp_path, scenario):
    with domain_world(tmp_path, scenario) as (app, _), TestClient(app) as client:
        card = domain_cards(client)["homelab"]
        assert card["metric_state"] == "available", card
        assert card["trend_state"] == "insufficient_history", card
        assert len(card["trend"]) <= 1, card


def test_monetary_single_observation_has_a_headline_without_a_trend(tmp_path):
    with domain_world(tmp_path, "one") as (app, today), TestClient(app) as client:
        cards = domain_cards(client)
        for domain, unit, value in (("finance", "EUR", 42), ("utilities", "USD", 0)):
            card = cards[domain]
            assert card["metric_state"] == "available", card
            assert monetary_points(card["headline"]) == [(unit, today.strftime("%Y-%m"), Decimal(value))]
            assert card["trend_state"] == "insufficient_history" and len(card["trend"]) <= 1, card


def test_homelab_unknown_states_cannot_be_healthy_zero(tmp_path):
    with domain_world(tmp_path, "unknown") as (app, _), TestClient(app) as client:
        card = domain_cards(client)["homelab"]
        assert card["metric_state"] in {"unknown", "unavailable"}, card
        assert card["headline"] == [], card
        assert card["trend_state"] in {"insufficient_history", "unavailable"} and not card["trend"], card
        assert card["attention"] is None, card


def test_homelab_neutral_criticality_does_not_outrank_declared_priorities(tmp_path):
    with domain_world(tmp_path, "ranks") as (app, _), TestClient(app) as client:
        card = domain_cards(client)["homelab"]
        assert card["attention_state"] == "available", card
        assert card["attention"]["priority"] == 2, card
        assert "Standard relay" in card["attention"]["label"], card


def test_domain_cards_strict_publication_is_observed_after_warehouse_clear(tmp_path):
    with domain_world(tmp_path, "normal", access="published") as (app, today), TestClient(app) as client:
        assert_data_rich_cards(client, today)
    with domain_world(tmp_path / "empty", "empty", access="published") as (app, _), TestClient(app) as client:
        for card in domain_cards(client).values():
            assert card["metric_state"] == "empty" and not card["headline"], card
            attention(card, state="empty")


def test_domain_cards_missing_publications_cannot_read_available_warehouse(tmp_path):
    with domain_world(tmp_path, "normal", access="unavailable") as (app, _), TestClient(app) as client:
        for card in domain_cards(client).values():
            assert card["metric_state"] == "unavailable" and not card["headline"], card
            assert card["trend_state"] == "unavailable" and not card["trend"], card
            attention(card, state="unavailable")


def test_domain_cards_missing_publications_do_not_disable_other_domains(tmp_path):
    with domain_world(tmp_path, "normal", access="partial") as (app, today), TestClient(app) as client:
        cards = domain_cards(client)
        assert cards["homelab"]["metric_state"] == "unavailable" and not cards["homelab"]["headline"]
        assert cards["finance"]["metric_state"] == "available"
        assert ("EUR", today.strftime("%Y-%m"), Decimal(180)) in monetary_points(cards["finance"]["headline"])
        assert cards["utilities"]["metric_state"] == "available"
        assert any(unit == "USD" and amount == 0 for unit, _, amount in monetary_points(cards["utilities"]["headline"]))
        attention(cards["finance"], label="Unusual transaction: Anchor Books", priority=2)
        attention(cards["utilities"], label="Upcoming renewal: Harbor Utility", priority=3)


def test_fixture_proves_source_amounts_and_attention_ranks(tmp_path):
    """A baseline-green guard against expected outputs without actual source rows."""
    with domain_world(tmp_path, "normal") as (app, today), TestClient(app) as client:
        response = client.get("/reports/monthly-cashflow")
        assert response.status_code == 200, response.text
        observed = {(row["booking_month"], row["currency"]): Decimal(row["net"]) for row in response.json()["rows"]}
        assert observed[(today.strftime("%Y-%m"), "EUR")] == Decimal(180)

        response = client.get("/reports/utility-cost-trend")
        assert response.status_code == 200, response.text
        assert any(row["currency"] == "USD" and Decimal(row["total_cost"]) == 0 for row in response.json()["rows"])

        response = client.get("/reports/attention-items")
        assert response.status_code == 200, response.text
        observed = {(row["source_domain"], row["title"]): row["severity"] for row in response.json()["rows"]}
        assert observed[("finance", "Unusual transaction: Anchor Books")] == 2
        assert any(domain == "finance" and priority == 1 for (domain, _), priority in observed.items())
        assert observed[("utilities", "Upcoming renewal: Harbor Utility")] == 3
        assert observed[("utilities", "Upcoming renewal: Upland Utility")] == 2


@pytest.mark.parametrize("access", ["warehouse", "published"], ids=["ordinary", "strict_publication"])
@pytest.mark.parametrize("scenario", ["unknown-shared", "unknown-changed"])
def test_homelab_does_not_compare_incomplete_observed_cohorts(tmp_path, access, scenario):
    with domain_world(tmp_path, scenario, access=access) as (app, _), TestClient(app) as client:
        card = domain_cards(client)["homelab"]
        assert card["metric_state"] == "available", card
        [headline] = card["headline"]
        assert headline["known_count"] == 1 and headline["value"] == 0, headline
        assert card["trend_state"] == "insufficient_history" and len(card["trend"]) <= 1, card


@pytest.mark.parametrize("access", ["warehouse", "published"], ids=["ordinary", "strict_publication"])
@pytest.mark.parametrize("invalid_utility_rank", [0, -1])
def test_domain_cards_invalid_priorities_cannot_outrank_known_actions(tmp_path, access, invalid_utility_rank):
    with domain_world(tmp_path, "invalid-priorities", access=access,
                      invalid_utility_rank=invalid_utility_rank) as (app, _), TestClient(app) as client:
        cards = domain_cards(client)
        attention(cards["finance"], label="Unusual transaction: Anchor Books", priority=2)
        attention(cards["utilities"], label="Upcoming renewal: Harbor Utility", priority=3)
