"""Intent drafts stay isolated, independently reviewed and unpublished."""
import json
import os
from pathlib import Path

import pytest

from lanectl import cli, specification as spec
from lanectl.adapters import AdapterResult
from lanectl.config import load_release

ACC = 'from calc import sub\n\ndef test_sub():\n    assert sub(5, 3) == 2\n'


def fake_adapter(*, worktree, prompt, **kwargs):
    payload = ({'verdict': 'accept', 'reason': 'Checks both changed behaviour and inputs',
                'trivial_pass': 'Constant returns fail the second case', 'checks': ['constant-return', 'ignored-input']}
               if 'adversarial reviewer' in prompt else
               {'outcome': 'Add subtraction', 'tests': {'tests/test_acc_spec.py': ACC}})
    (Path(worktree) / '.lanectl-spec' / 'response.json').write_text(json.dumps(payload))
    return AdapterResult('done', 0, 'written', None, {'output_tokens': 10})


def make(estate, **kwargs):
    adapter = kwargs.pop('adapter_fn_override', fake_adapter)
    return spec.draft_intent('spec-sub', repo_name='target', title='Subtraction',
        intent='Support sub(a,b) for positive and negative values', scope=['src/**'],
        author_model='scripted/author', reviewer_model='scripted/reviewer',
        adapter_fn=adapter, **kwargs)


def test_draft_has_independent_review_and_fails_on_real_base(estate):
    repo, _, _ = estate
    d = make(estate)
    rel = load_release(d)
    assert rel.draft and rel.outcome == 'Add subtraction'
    assert rel.acceptance.files == ('tests/test_acc_spec.py',)
    assert spec.validate_for_publish(d) == []
    assert not (repo / '.lanectl-spec').exists()
    assert not (repo / 'tests/test_acc_spec.py').exists()
    assert json.loads((d / 'specification.json').read_text())['review']['verdict'] == 'accept'


def test_base_lint_preserves_runner_credential_file_fence(estate, tmp_path, monkeypatch):
    from dataclasses import replace
    from lanectl.config import load_lane, load_repos
    repo, release, _ = estate
    credential = tmp_path / 'synthetic-credentials' / 'runner'
    credential.parent.mkdir()
    credential.write_text('synthetic-only')
    observed = tmp_path / 'observed-lint-boundary'
    monkeypatch.setenv('CREDENTIALS_DIRECTORY', str(credential.parent))
    acceptance = (
        'from pathlib import Path\n'
        f'try: Path({str(credential)!r}).read_bytes()\n'
        f'except (PermissionError, FileNotFoundError): Path({str(observed)!r}).write_text("blocked")\n'
        f'else: Path({str(observed)!r}).write_text("leaked")\n' + ACC)
    release('lint-secret-fence', acceptance)
    path = Path(os.environ['LANECTL_HOME']) / 'backlog/lint-secret-fence'
    assert spec._base_lint(path, load_repos()['target'], load_lane('implement'), 30) == []
    assert observed.read_text() == 'blocked'
    real = spec.from_lane
    monkeypatch.setattr(spec, 'from_lane', lambda *a, **k: replace(real(*a, **k), inaccessible=()))
    assert spec._base_lint(path, load_repos()['target'], load_lane('implement'), 30) == []
    assert observed.read_text() == 'leaked'


def test_planner_alone_publishes_and_edits_invalidate_review(estate, capsys):
    d = make(estate)
    f = d / 'files/tests/test_acc_spec.py'
    f.write_text(f.read_text() + '\n# planner changed the test\n')
    assert cli.main(['backlog', 'publish', 'spec-sub']) == 1
    assert 'changed' in capsys.readouterr().out
    assert load_release(d).draft


def test_valid_review_does_not_automatically_publish(estate):
    d = make(estate)
    assert load_release(d).draft
    assert cli.main(['backlog', 'publish', 'spec-sub']) == 0
    assert not load_release(d).draft
    assert spec.validate_for_publish(d) == []


@pytest.mark.parametrize('author,reviewer', [('scripted/model','scripted/reviewer'),
                                            ('scripted/author','scripted/author')])
def test_model_independence_before_dispatch(estate, author, reviewer):
    calls=[]
    with pytest.raises(ValueError, match='different|implement'):
        spec.draft_intent('spec-sub',repo_name='target', title='Sub',intent='Sub',scope=['src/**'],
          author_model=author,reviewer_model=reviewer,adapter_fn=lambda **k:calls.append(k))
    assert calls == []


def test_reviewer_rejects_a_trivial_test_and_publish_cannot_override(estate, capsys):
    def adapter(**kw):
        result=fake_adapter(**kw)
        if 'adversarial reviewer' in kw['prompt']:
            (kw['worktree']/'.lanectl-spec/response.json').write_text(json.dumps(
              {'verdict':'revise','reason':'A constant passes','trivial_pass':'return 2','checks':['constant-return']}))
        return result
    d=make(estate, adapter_fn_override=adapter)
    assert spec.validate_for_publish(d)
    p=d/'release.toml';p.write_text(p.read_text()+'\n[lint]\noverride="planner override"\n')
    assert cli.main(['backlog','publish','spec-sub'])==1
    assert load_release(d).draft


@pytest.mark.parametrize('path', ['../escape.py','/tmp/test_escape.py','tests/conftest.py','src/code.py','tests/../escape.py'])
def test_generated_paths_never_escape_or_replace_support_files(estate,path):
    def adapter(**kw):
        (kw['worktree']/'.lanectl-spec/response.json').write_text(json.dumps(
           {'outcome':'Add subtraction','tests':{path:ACC}}))
        return AdapterResult('done',0,'',None)
    with pytest.raises(ValueError,match='acceptance|path'):
        make(estate,adapter_fn_override=adapter)
    assert not (Path(os.environ['LANECTL_HOME'])/'backlog/spec-sub').exists()


def test_lint_failure_is_recorded_and_blocks_publication(estate):
    d=make(estate,lint_fn=lambda *_:['passes-on-base'])
    assert 'passes-on-base' in str(spec.validate_for_publish(d))
    assert cli.main(['backlog','publish','spec-sub'])==1


def test_worker_edit_to_existing_code_is_rejected(estate):
    def adapter(**kw):
        (kw['worktree']/'src/calc.py').write_text('broken')
        return fake_adapter(**kw)
    with pytest.raises(ValueError,match='outside'):
        make(estate,adapter_fn_override=adapter)


def test_generated_response_has_size_bound(estate):
    def adapter(**kw):
        (kw['worktree']/'.lanectl-spec/response.json').write_text('x'*(spec.MAX_RESPONSE_BYTES+1))
        return AdapterResult('done',0,'',None)
    with pytest.raises(ValueError,match='bound'):
        make(estate,adapter_fn_override=adapter)


def test_restricted_repo_refuses_external_models_before_dispatch(estate):
    p=Path(os.environ['LANECTL_HOME'])/'governance/repos.toml'
    p.write_text(p.read_text()+'\ndata_class_floor="restricted"\n')
    with pytest.raises(ValueError,match='restricted'):
        spec.draft_intent('spec-sub',repo_name='target',title='Sub',intent='Sub',scope=['src/**'],
          author_model='opencode-go/deepseek-v4-pro',reviewer_model='claude-sonnet-5-5',
          adapter_fn=fake_adapter)


def test_author_is_excluded_even_after_routing_changes(estate):
    rel=load_release(make(estate))
    assert spec.implementation_models(rel,{'scripted/author':1,'scripted/model':1}) == {'scripted/model':1}


def test_reviewer_cannot_rewrite_proposal(estate):
    def adapter(**kw):
        result = fake_adapter(**kw)
        proposal = kw['worktree']/'.lanectl-spec/proposal.json'
        if proposal.exists():
            proposal.write_text('{}')
        return result
    with pytest.raises(ValueError,match='modified'):
        make(estate,adapter_fn_override=adapter)


def test_existing_acceptance_file_cannot_be_replaced(estate):
    def adapter(**kw):
        (kw['worktree']/'.lanectl-spec/response.json').write_text(json.dumps(
           {'outcome':'Subtraction','tests':{'tests/test_calc.py':ACC}}))
        return AdapterResult('done',0,'',None)
    with pytest.raises(ValueError,match='already exists'):
        make(estate,adapter_fn_override=adapter)


def test_rebase_invalidates_review(estate):
    d=make(estate)
    p=d/'release.toml'
    p.write_text(p.read_text().replace('revision = 1','revision = 2'))
    assert 'changed' in str(spec.validate_for_publish(d))


def test_model_failure_is_not_a_draft(estate):
    with pytest.raises(ValueError,match='failed or escalated'):
        make(estate,adapter_fn_override=lambda **kw:AdapterResult('escalated',0,'',None))
    assert not (Path(os.environ['LANECTL_HOME'])/'backlog/spec-sub').exists()


def test_native_shim_denies_source_checkout_write(estate,tmp_path,monkeypatch):
    import subprocess
    repo,_,_=estate
    bin_dir=tmp_path/'bin';bin_dir.mkdir()
    worker=bin_dir/'claude'
    worker.write_text('#!/bin/sh\n'
       f'touch {repo}/outside-attempt 2>/dev/null && exit 7\n'
       'printf \'{"outcome":"sub","tests":{"tests/test_sub.py":"assert False"}}\' > .lanectl-spec/response.json\n')
    worker.chmod(0o755)
    monkeypatch.setenv('PATH',str(bin_dir)+os.pathsep+os.environ['PATH'])
    def adapter(**kw):
        p=subprocess.run(['claude'],cwd=kw['worktree'],env=kw['env'],capture_output=True,text=True)
        assert p.returncode==0,p.stderr
        return AdapterResult('done',0,'',None)
    lane=spec.load_lane('implement');r=spec.load_repos()['target']
    result,_=spec._invoke(r,lane,backlog_head(repo),'claude-sonnet-5-5','test',adapter_fn=adapter)
    assert result['outcome']=='sub'
    assert not (repo/'outside-attempt').exists()


def backlog_head(repo):
    import subprocess
    return subprocess.run(['git','-C',str(repo),'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()


def test_work_completion_intent_is_frozen_before_review(estate):
    d=make(estate,work='target#7',work_complete=True)
    rel=load_release(d)
    assert rel.work=='target#7' and rel.work_complete
    assert spec.validate_for_publish(d)==[]


def test_generated_base_test_cannot_write_to_source_checkout(estate):
    repo,_,_=estate
    source=f'''from pathlib import Path
from calc import add

def test_protection():
    p = Path({str(repo / 'leaked')!r})
    try:
        p.write_text('leak')
    except OSError:
        pass
    assert add(1, 2) == 4
'''
    def adapter(**kw):
        result=fake_adapter(**kw)
        if 'adversarial reviewer' not in kw['prompt']:
            (kw['worktree']/'.lanectl-spec/response.json').write_text(json.dumps(
                {'outcome':'New result','tests':{'tests/test_acc_spec.py':source}}))
        return result
    d=make(estate,adapter_fn_override=adapter)
    assert spec.validate_for_publish(d)==[]
    assert not (repo/'leaked').exists()
    assert cli.main(['backlog','publish','spec-sub'])==0
    assert not (repo/'leaked').exists()
