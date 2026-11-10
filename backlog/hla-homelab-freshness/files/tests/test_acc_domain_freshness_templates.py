"""Acceptance: freshness templates cover every pack's real source datasets (planner-owned)."""
from types import SimpleNamespace

from packages.domains.finance.manifest import FINANCE_PACK
from packages.domains.homelab.manifest import HOMELAB_PACK
from packages.domains.utilities.manifest import UTILITIES_PACK
from packages.pipelines.source_freshness_bootstrap import (
    DOMAIN_FRESHNESS_CONFIGS,
    ensure_domain_freshness_configs,
)

PACKS = (FINANCE_PACK, UTILITIES_PACK, HOMELAB_PACK)
FREQUENCIES = {"ad_hoc", "weekly", "monthly", "quarterly", "annual"}


def test_every_pack_source_has_a_template():
    for pack in PACKS:
        templates = DOMAIN_FRESHNESS_CONFIGS.get(pack.name, {})
        missing = [s.dataset_name for s in pack.sources if s.dataset_name not in templates]
        assert not missing, f"{pack.name}: no freshness template for {missing}"


def test_templates_use_known_frequencies():
    for domain, templates in DOMAIN_FRESHNESS_CONFIGS.items():
        for name, t in templates.items():
            assert t["expected_frequency"] in FREQUENCIES, (domain, name)


def test_homelab_backup_runs_template():
    t = DOMAIN_FRESHNESS_CONFIGS["homelab"]["ha_backup_runs"]
    assert t["expected_frequency"] == "weekly" and t["freshness_sla_days"] == 8


class FakeControlPlane:
    def __init__(self, asset_ids):
        self.assets = [SimpleNamespace(source_asset_id=a) for a in asset_ids]
        self.created = []

    def list_source_assets(self):
        return self.assets

    def list_source_freshness_configs(self):
        return []

    def create_source_freshness_config(self, cfg):
        self.created.append(cfg)


def test_bootstrap_creates_configs_for_two_non_finance_domains():
    cp = FakeControlPlane(["hass_ha_service_states", "hass_ha_backup_runs",
                           "nordpool_utility_rates", "bank_account_transactions"])
    counts = ensure_domain_freshness_configs(cp, PACKS)
    assert counts.get("homelab", 0) >= 2
    assert counts.get("utilities", 0) >= 1
    by_id = {c.source_asset_id: c for c in cp.created}
    assert by_id["hass_ha_backup_runs"].freshness_sla_days == 8
