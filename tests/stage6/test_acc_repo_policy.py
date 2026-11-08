"""Acceptance: per-repo policy overlay (planner-owned)."""
import dataclasses
import textwrap

from lanectl.config import load_lane, load_release, load_repos
from lanectl.gates.diffpolicy import FileChange, evaluate
from lanectl.ready import eligible_models, readiness

SHA = "a" * 40


def _home(tmp_path, monkeypatch, data_class="public"):
    gov = tmp_path / "governance"
    gov.mkdir()
    (gov / "repos.toml").write_text(textwrap.dedent(f"""
        [repos.open]
        path = "{tmp_path}/open"
        test_cmd = "true"
        check_cmd = "true"
        worktree_root = "{tmp_path}/wt"

        [repos.closed]
        path = "{tmp_path}/closed"
        test_cmd = "true"
        check_cmd = "true"
        worktree_root = "{tmp_path}/wt"
        protected_paths = ["deploy/**", "infra/**"]
        data_class_floor = "restricted"

        [repos.closed.routing]
        "claude-sonnet-5-5" = 1.0
        """))
    rels = {}
    for repo in ("open", "closed"):
        d = tmp_path / "backlog" / f"it-{repo}"
        d.mkdir(parents=True)
        (d / "release.toml").write_text(textwrap.dedent(f"""
            id = "it-{repo}"
            repo = "{repo}"
            base_sha = "{SHA}"
            title = "t"
            outcome = "o"
            task_class = "glue"
            size = "S"
            data_class = "{data_class}"
            [scope]
            paths = ["src/**", "deploy/values.yaml"]
            [acceptance]
            exec = ["true"]
            """))
        rels[repo] = load_release(d)
    lane = dataclasses.replace(load_lane("implement"),
                               routing={"opencode-go/deepseek-v4.1-flash": 1.0, "claude-sonnet-5-5": 0.0},
                               external_models=("opencode-go/deepseek-v4.1-flash",))
    return load_repos(tmp_path), rels, lane


def test_repo_policy_fields_and_defaults(tmp_path, monkeypatch):
    repos, _, _ = _home(tmp_path, monkeypatch)
    o, c = repos["open"], repos["closed"]
    assert (o.protected_paths, o.data_class_floor, o.routing) == ((), "public", {})
    assert c.protected_paths == ("deploy/**", "infra/**") and c.data_class_floor == "restricted"
    assert c.routing == {"claude-sonnet-5-5": 1.0}


def test_eligible_models_apply_override_and_floor(tmp_path, monkeypatch):
    repos, rels, lane = _home(tmp_path, monkeypatch)
    assert eligible_models(rels["open"], lane) == lane.routing                 # unchanged without repo
    assert eligible_models(rels["open"], lane, repos["open"]) == lane.routing
    assert eligible_models(rels["closed"], lane, repos["closed"]) == {"claude-sonnet-5-5": 1.0}


def test_floor_without_first_party_route_blocks(tmp_path, monkeypatch):
    repos, rels, lane = _home(tmp_path, monkeypatch)
    no_route = dataclasses.replace(repos["closed"], routing={})
    assert eligible_models(rels["closed"], lane, no_route) == {"claude-sonnet-5-5": 0.0}
    reasons = readiness(rels["closed"], lane, {**repos, "closed": no_route})
    assert any("no eligible model" in r for r in reasons)
    assert not any("no eligible model" in r for r in readiness(rels["closed"], lane, repos))


def test_repo_protected_paths_in_diff_policy(tmp_path, monkeypatch):
    repos, rels, lane = _home(tmp_path, monkeypatch)
    changes = [FileChange("M", "deploy/values.yaml", 1, 0, ["x: 1"]), FileChange("A", "infra/main.tf", 1, 0, ["y"])]
    v = evaluate(changes, rels["closed"], lane, (), repos["closed"].protected_paths)
    assert "protected-review: deploy/values.yaml" in v and "protected-path: infra/main.tf" in v
    assert not any(x.startswith("protected") for x in evaluate(changes, rels["open"], lane, ()))
