"""Acceptance: repos declare how they land (planner-owned contract)."""
import pytest

from lanectl.config import ContractError, _landing, load_repos


def test_landing_values():
    assert _landing("r", "local") == "local" and _landing("r", "pr") == "pr"
    with pytest.raises(ContractError):
        _landing("r", "merge")


def test_governance_homelab_lands_by_pr():
    repos = load_repos()
    assert repos["homelab-analytics"].landing == "pr"
    assert repos["lanectl"].landing == "local"
