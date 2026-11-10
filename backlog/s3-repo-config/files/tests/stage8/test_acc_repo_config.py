"""Acceptance: s3-repo-config - gate jobs and deploy spec parsed from repos.toml."""
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


def test_repo_without_tables_has_defaults(tmp_path):
    spec = _load(tmp_path)
    assert spec.gate_jobs == ()
    assert spec.deploy is None


def test_gate_jobs_parsed_in_order_with_default_timeout(tmp_path):
    spec = _load(tmp_path, '''
[[repos.target.gate_jobs]]
name = "ruff"
cmd = "ruff check ."
[[repos.target.gate_jobs]]
name = "type-check"
cmd = "mypy src"
timeout_s = 120
''')
    assert spec.gate_jobs == (config.GateJob("ruff", "ruff check .", 600),
                              config.GateJob("type-check", "mypy src", 120))


def test_deploy_parsed_with_defaults(tmp_path):
    spec = _load(tmp_path, '''
[repos.target.deploy]
cmd = "./deploy.sh"
health_cmd = "./health.sh"
teardown_cmd = "./down.sh"
''')
    assert spec.deploy == config.DeploySpec("./deploy.sh", "./health.sh", "./down.sh", 3600, ())


def test_deploy_parsed_with_values(tmp_path):
    spec = _load(tmp_path, '''
[repos.target.deploy]
cmd = "./deploy.sh"
health_cmd = "./health.sh"
teardown_cmd = "./down.sh"
ttl_s = 900
env_allow = ["PATH", "HOME"]
''')
    assert spec.deploy.ttl_s == 900
    assert spec.deploy.env_allow == ("PATH", "HOME")


@pytest.mark.parametrize("extra", [
    '[[repos.target.gate_jobs]]\ncmd = "x"\n',
    '[[repos.target.gate_jobs]]\nname = "ruff"\n',
    '[[repos.target.gate_jobs]]\nname = "Ruff"\ncmd = "x"\n',
    '[[repos.target.gate_jobs]]\nname = "-ruff"\ncmd = "x"\n',
    '[[repos.target.gate_jobs]]\nname = "ruff"\ncmd = "x"\n[[repos.target.gate_jobs]]\nname = "ruff"\ncmd = "y"\n',
    '[[repos.target.gate_jobs]]\nname = "ruff"\ncmd = "x"\ntimeout_s = 0\n',
    '[repos.target.deploy]\ncmd = "a"\nhealth_cmd = "b"\n',
    '[repos.target.deploy]\ncmd = "a"\nteardown_cmd = "c"\n',
    '[repos.target.deploy]\nhealth_cmd = "b"\nteardown_cmd = "c"\n',
    '[repos.target.deploy]\ncmd = "a"\nhealth_cmd = "b"\nteardown_cmd = "c"\nttl_s = -5\n',
    '[repos.target.deploy]\ncmd = "a"\nhealth_cmd = "b"\nteardown_cmd = "c"\nenv_allow = ["LANE_NAMESPACE"]\n',
])
def test_invalid_tables_raise_contract_error_naming_repo(tmp_path, extra):
    with pytest.raises(ContractError, match="target"):
        _load(tmp_path, extra)
