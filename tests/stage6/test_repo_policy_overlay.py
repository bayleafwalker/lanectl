"""Runner-side coverage for the per-repo policy overlay."""
from lanectl import runner
from lanectl.config import RepoSpec
from lanectl.contracts import Acceptance, LaneRevision, WorkRelease
from lanectl.events import ItemView
from lanectl.gates import diffpolicy

SHA = "a" * 40


def _repo(tmp_path, **kw):
    return RepoSpec(name="target", path=tmp_path, main="main", test_cmd="true",
                    check_cmd="true", worktree_root=tmp_path / "wt", **kw)


def _lane(**kw):
    base = dict(lane="implement", revision=1, size_max="M",
                routing={"lane/model": 1.0}, max_attempts=2,
                retry="same_model", caps={}, size_budget_lines={"S": 250},
                protected_paths=("governance/**",), dependency_manifests=(),
                test_globs=(), forbidden_added_patterns=(), external_models=("ext/model",))
    base.update(kw)
    return LaneRevision(**base)


def _rel(**kw):
    base = dict(id="item-1", repo="target", base_sha=SHA, title="t", outcome="o",
                task_class="glue", size="S", data_class="public",
                scope_paths=("src/**",), acceptance=Acceptance(exec=("true",)))
    base.update(kw)
    return WorkRelease(**base)


def test_pick_model_uses_repo_routing_and_floor(tmp_path):
    view = ItemView("item-1")
    lane = _lane()
    repo = _repo(tmp_path, routing={"repo/model": 1.0})
    assert runner.pick_model(_rel(), lane, view, repo) == "repo/model"
    # A repo floor restricted drops the external lane route.
    ext = _lane(routing={"ext/model": 1.0})
    assert runner.pick_model(_rel(), ext, view) == "ext/model"
    assert runner.pick_model(_rel(), ext, view, _repo(tmp_path, data_class_floor="restricted")) is None


def test_worker_prompt_lists_repo_protected_paths(tmp_path):
    prompt = runner.render_prompt(_rel(), _lane(), _repo(tmp_path, protected_paths=("infra/**",)))
    do_not_touch = next(line for line in prompt.splitlines() if line.startswith("- Do not touch:"))
    assert "governance/**" in do_not_touch and "infra/**" in do_not_touch


def test_run_gates_treats_repo_protected_paths_as_protected(tmp_path, monkeypatch):
    repo = _repo(tmp_path, protected_paths=("infra/**",))
    claim = runner.Claim(_rel(), repo, _lane(protected_paths=()), "item-1-a1", "lane/model", "w")
    monkeypatch.setattr(diffpolicy, "collect",
                        lambda *a, **k: [diffpolicy.FileChange("M", "infra/main.tf", 1, 0, ["x"])])
    gates = runner.run_gates(claim, tmp_path, SHA, "b" * 40, {}, "done")
    assert gates["diff-policy"] == ["protected-path: infra/main.tf"]
