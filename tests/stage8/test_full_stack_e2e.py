"""An independently specified change lands using the served lane owner stream.

Models are scripted, but acceptance/gates, Git train checks, disposable deploy,
transactional StreamStore and restart replay execute their real implementations.
"""
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from lanectl import backlog, deploy, runner, specification
from lanectl.adapters import AdapterResult
from lanectl.config import load_release
from lanectl.coordination import CoordinationError
from lanectl.events import project_items
from lanectl.remote_events import RemoteEventLog
from lanectl.stream_store import StreamStore, initialize
from tests.stage9.test_remote_events import Client

ACCEPTANCE = '''from calc import sub

def test_subtraction_uses_both_inputs():
    assert sub(5, 3) == 2
    assert sub(1, 2) == -1
    assert sub(-2, -2) == 0
'''


def _head(repo):
    return subprocess.run(['git', '-C', str(repo), 'rev-parse', 'main'],
                          check=True, capture_output=True, text=True).stdout.strip()


def _spec_model(*, worktree, model, prompt, **kwargs):
    if model == 'scripted/spec-author':
        payload = {'outcome': 'Provide subtraction using both supplied arguments.',
                   'tests': {'tests/test_acc_stack_sub.py': ACCEPTANCE}}
    else:
        assert model == 'scripted/spec-reviewer'
        proposed = json.loads((worktree/'.lanectl-spec/proposal.json').read_text())
        assert proposed['tests']['tests/test_acc_stack_sub.py'] == ACCEPTANCE
        payload = {'verdict': 'accept', 'reason': 'Independent subtraction outcomes cover signs.',
                   'trivial_pass': 'Constant answers and ignored arguments fail the three cases.',
                   'checks': ['constant-return', 'ignored-input', 'negative-operands']}
    (worktree/'.lanectl-spec/response.json').write_text(json.dumps(payload))
    return AdapterResult('done', 0, 'synthetic specification', None)


def _implement(*, worktree, **kwargs):
    (worktree/'src/calc.py').write_text(
        'def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n')
    (worktree/'tests/test_stack_extra.py').write_text(
        'from calc import sub\n\ndef test_zero_identity():\n    assert sub(9, 0) == 9\n')
    return AdapterResult('done', 0, 'synthetic implementation', None)


def test_intent_to_deployed_landing_replays_lost_ack_on_real_owner(estate, tmp_path, monkeypatch):
    repo, _, _ = estate
    base = _head(repo)
    target = tmp_path/'disposable-deploy'
    target.mkdir()
    monkeypatch.setenv('PRIVATE_TEST_SENTINEL', 'must-not-reach-deploy')
    governance = Path(os.environ['LANECTL_HOME'])/'governance/repos.toml'
    governance.write_text(governance.read_text() + f'''
[repos.target.deploy]
cmd = "test -z ${{PRIVATE_TEST_SENTINEL:-}} && echo $LANE_NAMESPACE >> {target}/started && touch {target}/live"
health_cmd = "test -f {target}/live"
teardown_cmd = "rm -f {target}/live; echo down >> {target}/stopped"
ttl_s = 300
env_allow = ["PATH"]
''')
    database = tmp_path/'owner.sqlite'
    initialize(database)
    client = Client(StreamStore(database))
    pending = tmp_path/'pending-lane-batch.json'
    log = RemoteEventLog(client, pending)

    draft = specification.draft_intent('stack-sub', repo_name='target', title='Subtraction',
        intent='Implement sub(a,b), preserving both arguments and their signs.',
        scope=['src/**', 'tests/**'], author_model='scripted/spec-author',
        reviewer_model='scripted/spec-reviewer', adapter_fn=_spec_model)
    assert load_release(draft).draft
    refused = runner.admit('implement', log)
    assert isinstance(refused, str) and 'draft' in refused
    assert not [e for e in log.read() if e['type']=='item.claimed']
    assert backlog._publish(SimpleNamespace(id='stack-sub')) == 0

    claim = runner.admit('implement', log)
    assert claim.model == 'scripted/model'
    assert '-> candidate' in runner.execute(claim, log, adapter_fn=_implement)
    assert _head(repo) == base
    gates = [e['data'] for e in log.read() if e['type']=='gate.result']
    assert gates and all(g['passed'] for g in gates)
    assert {'acceptance', 'acceptance-on-base', 'diff-policy', 'fail-on-base'} <= {g['gate'] for g in gates}

    assert 'PASSED' in runner.build_train(log, 'target')
    train = [e['data'] for e in log.read() if e['type']=='train.built'][-1]
    train_id = train['train_id']
    # A formerly successful train is not an authority after a failure record.
    log.append('train.built', dict(train, passed=False))
    assert 'failed train' in runner.land(log, train_id)
    assert 'not deploying' in deploy.deploy_train(log, train_id)
    assert _head(repo) == base
    assert not [e for e in log.read() if e['type']=='item.landed']
    log.append('train.built', train)
    assert 'pass its health check' in runner.land(log, train_id)

    # The deploy effect and owner receipt occur, but their acknowledgement is lost.
    # Restart must replay the receipt, not perform the deployment a second time.
    client.drop = True
    with pytest.raises(CoordinationError, match='connection lost after commit'):
        deploy.deploy_train(log, train_id)
    assert pending.exists() and (target/'live').exists()
    assert len((target/'started').read_text().splitlines()) == 1
    restarted = RemoteEventLog(Client(StreamStore(database)), pending)
    recovered = restarted.read()
    assert not pending.exists()
    assert len([e for e in recovered if e['type']=='train.deployed']) == 1
    assert runner.land(restarted, train_id).startswith('landed')
    assert _head(repo) == train['checked_sha']
    assert not (target/'live').exists()
    assert (target/'stopped').read_text().splitlines() == ['down']
    assert project_items(restarted.read())['stack-sub'].state == 'landed'

    another_host = RemoteEventLog(Client(StreamStore(database)), tmp_path/'other-host-pending.json')
    assert runner.land(another_host, train_id).startswith('landed')
    records = another_host.read()
    assert len([e for e in records if e['type']=='item.landed']) == 1
    assert len([e for e in records if e['type']=='train.deployed']) == 1
    assert client.store.read('ws','repo-a','control')['events'] == records
    assert not client.store.read('ws','other-repo','control')['events']
    assert len((target/'started').read_text().splitlines()) == 1
    assert (target/'stopped').read_text().splitlines() == ['down']
