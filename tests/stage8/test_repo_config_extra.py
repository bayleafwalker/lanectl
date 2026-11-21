"""Lane tests: gate jobs and deploy spec parsing in config.load_repos (s3-repo-config)."""
import dataclasses

import pytest

from lanectl import config
from lanectl.contracts import ContractError

BASE = '''
[repos.target]
path = "/tmp/target"
main = "main"
test_cmd = "pytest {files}"
check_cmd = "pytest"
worktree_root = "/tmp/wt"
'''


def _load(tmp_path, extra=""):
    (tmp_path / "governance").mkdir(exist_ok=True)
    (tmp_path / "governance" / "repos.toml").write_text(BASE + extra)
    return config.load_repos(tmp_path)["target"]


def test_dataclasses_are_frozen_with_documented_defaults():
    job = config.GateJob("ruff", "ruff check .")
    deploy = config.DeploySpec("up", "health", "down")
    assert (job.timeout_s, deploy.ttl_s, deploy.env_allow) == (600, 3600, ())
    with pytest.raises(dataclasses.FrozenInstanceError):
        job.name = "other"
    with pytest.raises(dataclasses.FrozenInstanceError):
        deploy.cmd = "other"


def test_repo_without_tables_keeps_other_fields(tmp_path):
    spec = _load(tmp_path)
    assert (spec.name, spec.main, spec.setup_cmd) == ("target", "main", "")
    assert spec.gate_jobs == () and spec.deploy is None


def test_gate_jobs_keep_listed_order_and_accept_digits(tmp_path):
    spec = _load(tmp_path, '''
[[repos.target.gate_jobs]]
name = "2-lint"
cmd = "a"
[[repos.target.gate_jobs]]
name = "types"
cmd = "b"
timeout_s = 30
[[repos.target.gate_jobs]]
name = "z"
cmd = "c"
''')
    assert [j.name for j in spec.gate_jobs] == ["2-lint", "types", "z"]
    assert [j.timeout_s for j in spec.gate_jobs] == [600, 30, 600]


def test_deploy_env_allow_defaults_to_empty_tuple(tmp_path):
    spec = _load(tmp_path, '''
[repos.target.deploy]
cmd = "up"
health_cmd = "ok"
teardown_cmd = "down"
''')
    assert spec.deploy == config.DeploySpec("up", "ok", "down", 3600, ())
    assert isinstance(spec.deploy.env_allow, tuple)


@pytest.mark.parametrize("extra", [
    '[[repos.target.gate_jobs]]\nname = "a b"\ncmd = "x"\n',
    '[[repos.target.gate_jobs]]\nname = "Lint"\ncmd = "x"\n',
    '[[repos.target.gate_jobs]]\nname = "9"\ncmd = "x"\n[[repos.target.gate_jobs]]\nname = "9"\ncmd = "y"\n',
    '[[repos.target.gate_jobs]]\nname = "lint"\ncmd = "x"\ntimeout_s = -1\n',
    '[[repos.target.gate_jobs]]\nname = "lint"\ncmd = ""\n',
    '[repos.target.deploy]\ncmd = "a"\nhealth_cmd = "b"\nteardown_cmd = "c"\nttl_s = 0\n',
    '[repos.target.deploy]\ncmd = "a"\nhealth_cmd = "b"\nteardown_cmd = "c"\nenv_allow = ["LANE_TRAIN_ID"]\n',
])
def test_more_invalid_tables_name_the_repo(tmp_path, extra):
    with pytest.raises(ContractError) as excinfo:
        _load(tmp_path, extra)
    assert "target" in str(excinfo.value)


def test_appservice_deployment_profile_preserves_existing_governance(tmp_path, monkeypatch):
    profile = tmp_path / "preview.toml"
    profile.write_text("""
[target]
namespace = "lanectl-train-preview"
cmd = "request-preview deploy"
health_cmd = "request-preview health"
teardown_cmd = "request-preview teardown"
""")
    monkeypatch.setenv("LANECTL_APPSERVICE_DEPLOY_PROFILE", str(profile))
    with pytest.raises(ContractError, match="existing appservice repo"):
        _load(tmp_path)
    appservice = 'train_isolation = "appservice"\n'
    repo = _load(tmp_path, appservice)
    assert repo.deploy.namespace == "lanectl-train-preview"
    assert repo.path.as_posix() == "/tmp/target"
    with pytest.raises(ContractError, match="already declared"):
        _load(tmp_path, appservice + """
[repos.target.deploy]
cmd = "up"
health_cmd = "ok"
teardown_cmd = "down"
""")
    profile.write_text(profile.read_text().replace("[target]", "[unregistered]"))
    with pytest.raises(ContractError, match="unregistered"):
        _load(tmp_path, appservice)


def test_publication_command_is_limited_to_appservice_pr_landing(tmp_path):
    command = 'publication_cmd = "/protected/submit"\n'
    with pytest.raises(ContractError, match="Appservice PR landing"):
        _load(tmp_path, command)
    spec = _load(tmp_path, command + 'train_isolation = "appservice"\nlanding = "pr"\n')
    assert spec.publication_cmd == "/protected/submit"


def test_mounted_publication_hook_selects_canonical_pr_landing(tmp_path, monkeypatch):
    profile = tmp_path / "preview.toml"
    profile.write_text("""
[target]
cmd = "request-preview deploy"
health_cmd = "request-preview health"
teardown_cmd = "request-preview teardown"
publication_cmd = "/protected/submit"
""")
    monkeypatch.setenv("LANECTL_APPSERVICE_DEPLOY_PROFILE", str(profile))
    spec = _load(tmp_path, 'train_isolation = "appservice"\nlanding = "local"\n')
    assert spec.landing == "pr"
    assert spec.publication_cmd == "/protected/submit"
    assert spec.deploy.health_cmd == "request-preview health"
