"""Vuoro protocol and restart tests against an HTTP owner, never a live tracker."""
import hashlib
import json
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from lanectl.coordination import Coordinator, CoordinationError, VuoroClient

OPS = ['run.register', 'lease.acquire', 'lease.heartbeat', 'evidence.tail',
       'evidence.append', 'lease.report-outcome', 'public.item']


def expires(seconds=3600):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


@contextmanager
def owner():
    state = {'calls': [], 'effects': {}, 'tail': None, 'deny': None, 'drop': None, 'user_agents': [],
             'environment': 'test', 'correlation': None, 'work_list_state': 'ok', 'completion': {'authority':'sprintctl','state':'ok',
             'as_of':'2026-11-10T00:00:00Z','item':{'work_id':123,'status':'active','resolution':None}}, 'lease': {'lease_id': 'lease_test', 'state': 'active',
             'generation': 1, 'expires_at': expires(), 'heartbeat_interval_seconds': 20}}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, value, status=200):
            data = json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            state['user_agents'].append(self.headers['User-Agent'])
            assert self.headers['Authorization'] == 'Bearer synthetic-runner'
            if self.path == '/api/meta/v1/handshake':
                return self.respond({'client_protocol': {'minimum': 1, 'maximum': 1},
                    'environment': {'name': state['environment']}})
            assert self.path == '/api/catalog/v1'
            operations = [{'name': 'work.' + op + '-v1'} for op in OPS]
            operations.append({'name': 'lane.stream.read-v1'})
            operations.append({'name': 'work.public.list-v1', 'execution_semantics': 'read',
                               'repo_scoped': True, 'result_schema': {'type': 'object'}})
            self.respond({'revision': 'catalog-a', 'operations': operations})

        def do_POST(self):
            state['user_agents'].append(self.headers['User-Agent'])
            assert self.path == '/api/invoke/v1'
            assert self.headers['Authorization'] == 'Bearer synthetic-runner'
            p = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert p['schema_version'] == 'invocation/v1'
            assert p['idempotency_key'] is None
            assert p['catalog_revision'] == 'catalog-a' and p['repo_id'] == 'repo-a'
            assert p['request_id'] == self.headers['X-Request-ID']
            state['calls'].append(p)
            op, args = p['operation'], p['arguments']
            if state.get('drop_before_effect') == op:
                state['drop_before_effect'] = None
                self.connection.shutdown(2)
                self.connection.close()
                return
            if state['deny']:
                return self.respond({'status': 'rejected', 'error': {'code': state['deny'],
                                     'message': 'owner refusal'}}, 403)
            key = (op, args.get('idempotency_key'))
            if key in state['effects'] and not op.endswith(('acquire-v1', 'heartbeat-v1', 'tail-v1', 'item-v1')):
                result = state['effects'][key]
            elif op.endswith('run.register-v1'):
                result = {'run': {'run_id': state.get('run_id', 'run_test')}}
            elif op.endswith(('lease.acquire-v1', 'lease.heartbeat-v1')):
                result = {'lease': dict(state['lease'])}
                if op.endswith('lease.acquire-v1') and state.get('took_over'):
                    result['took_over'] = state['took_over']
            elif op.endswith('public.item-v1'):
                result = state['completion']
            elif op == 'work.public.list-v1':
                result = {'authority': 'sprintctl', 'state': state['work_list_state'], 'items': []}
            elif op == 'lane.stream.read-v1':
                result = {'revision': 0, 'head_revision': 0, 'events': [],
                          'next_after': 0, 'has_more': False}
            elif op.endswith('evidence.tail-v1'):
                result = {'item': state['tail']}
            elif op.endswith('evidence.append-v1'):
                assert args['chain_seq'] == (0 if state['tail'] is None else state['tail']['chain_seq'] + 1)
                assert args['digest'] == 'sha256:' + hashlib.sha256(json.dumps(
                    args['claims'][0]['detail'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                result = {'item': dict(args)}
                state['tail'] = dict(args)
            else:
                assert op.endswith('lease.report-outcome-v1')
                result = {'settled': False, 'settlement_effect': 'awaiting-verification'}
            state['effects'][key] = result
            if state['drop'] == op:
                state['drop'] = None
                self.connection.shutdown(2)
                self.connection.close()
                return
            response = {'schema_version': 'invocation-result/v1', 'request_id': p['request_id'],
                        'operation': op, 'catalog_revision': p['catalog_revision'],
                        'status': 'accepted', 'result': result}
            if state['correlation']:
                response[state['correlation']] = 'wrong'
            self.respond(response)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def coord(url, tmp_path):
    client = VuoroClient(url, 'repo-a', lambda: 'synthetic-runner', expected_environment='test')
    return Coordinator(client, tmp_path / 'coordination.sqlite')


def start(c):
    return c.start('release-a1', 123, 'scripted/model', 'sha256:' + 'a' * 64)


def test_takeover_receipt_survives_acquire_replays_without_receipt(tmp_path):
    with owner() as (url, state):
        state['took_over'] = 'lease_predecessor'
        assert start(coord(url, tmp_path))['took_over'] == 'lease_predecessor'
        state['took_over'] = None
        for _ in range(2):
            replacement = coord(url, tmp_path)
            assert start(replacement)['took_over'] == 'lease_predecessor'
            assert replacement.recorded_binding('release-a1')['took_over'] == 'lease_predecessor'
        state['lease']['lease_id'] = 'lease_other'
        assert 'took_over' not in start(coord(url, tmp_path))


def test_takeover_requires_exact_predecessor_and_distinct_run(tmp_path):
    with owner() as (url, state):
        coordinator = coord(url, tmp_path)
        original = start(coordinator)
        state['lease']['lease_id'] = 'lease_replacement'
        state['took_over'] = original['lease']['lease_id']
        state['run_id'] = 'run_replacement'
        coordinator.start('release-a2', 123, 'scripted/model', 'sha256:' + 'a' * 64)
        restarted = coord(url, tmp_path)
        restarted.assert_takeover('release-a1', 'release-a2')
        for invalid in ('release-a2', 'unknown'):
            with pytest.raises(CoordinationError):
                restarted.assert_takeover(invalid, 'release-a2')


def test_uncertain_predecessor_report_replays_exactly_and_owner_refuses_after_takeover(tmp_path):
    with owner() as (url, state):
        coordinator = coord(url, tmp_path)
        original = start(coordinator)
        operation = 'work.lease.report-outcome-v1'
        state['drop_before_effect'] = operation
        with pytest.raises(CoordinationError):
            coordinator.report_outcome('release-a1', 'succeeded', 'old result')
        pending = coordinator.saved_request('release-a1:outcome')
        assert pending[2] is None

        state['run_id'] = 'run_replacement'
        state['lease']['lease_id'] = 'lease_replacement'
        state['took_over'] = original['lease']['lease_id']
        restarted = coord(url, tmp_path)
        restarted.start('release-a2', 123, 'scripted/model', 'sha256:' + 'a' * 64)
        restarted.assert_takeover('release-a1', 'release-a2')
        state['deny'] = 'lease-superseded'
        with pytest.raises(CoordinationError, match='lease-superseded'):
            restarted.report_outcome('release-a1', 'succeeded', 'old result')
        reports = [call for call in state['calls'] if call['operation'] == operation]
        assert reports == [pending[1], pending[1]]
        assert restarted.saved_request('release-a1:outcome')[2] is None


def test_full_protocol_and_owner_retains_settlement(tmp_path):
    with owner() as (url, s):
        c = coord(url, tmp_path)
        binding = start(c)
        assert binding['run_id'] == 'run_test' and binding['lease']['generation'] == 1
        c.heartbeat('release-a1')
        c.append_evidence('release-a1', 'gates', 'test', {'passed': True})
        c.append_evidence('release-a1', 'review', 'review', {'passed': True})
        result = c.report_outcome('release-a1', 'succeeded', 'candidate ready', checks=[])
        assert result['settled'] is False
        ops = [p['operation'] for p in s['calls']]
        assert ops[0:3] == ['work.run.register-v1', 'work.lease.acquire-v1', 'work.lease.heartbeat-v1']
        assert ops[-1] == 'work.lease.report-outcome-v1'
        acquire = s['calls'][1]['arguments']
        assert 'ttl_seconds' not in acquire
        assert s['tail']['chain_seq'] == 1 and s['tail']['chain_prev_digest'].startswith('sha256:')
        from lanectl import __version__
        assert s['user_agents'] and set(s['user_agents']) == {f'lanectl/{__version__}'}


def test_restart_revalidates_lease_without_new_registration(tmp_path):
    with owner() as (url, s):
        start(coord(url, tmp_path))
        start(coord(url, tmp_path))
        ops = [p['operation'] for p in s['calls']]
        assert ops.count('work.run.register-v1') == 1
        assert ops.count('work.lease.acquire-v1') == 2
        calls = [p for p in s['calls'] if 'lease.acquire' in p['operation']]
        assert calls[0] == calls[1]


def test_lost_evidence_ack_replays_exact_request_after_restart(tmp_path):
    with owner() as (url, s):
        c = coord(url, tmp_path)
        start(c)
        s['drop'] = 'work.evidence.append-v1'
        with pytest.raises(CoordinationError):
            c.append_evidence('release-a1', 'gates', 'test', {'passed': True})
        c = coord(url, tmp_path)
        c.append_evidence('release-a1', 'gates', 'test', {'passed': True})
        requests = [p for p in s['calls'] if p['operation'] == 'work.evidence.append-v1']
        assert requests[0] == requests[1] and s['tail']['chain_seq'] == 0
        with pytest.raises(CoordinationError, match='different'):
            c.append_evidence('release-a1', 'gates', 'test', {'passed': False})


def test_restart_cannot_rebind_attempt_to_another_item(tmp_path):
    with owner() as (url, _):
        c = coord(url, tmp_path)
        start(c)
        with pytest.raises(CoordinationError, match='different'):
            c.start('release-a1', 124, 'scripted/model', 'sha256:' + 'a' * 64)


@pytest.mark.parametrize('code', ['token-revoked', 'lease-expired', 'lease-superseded'])
def test_owner_refusal_stops_guard_and_cannot_report_success(tmp_path, code):
    with owner() as (url, s):
        c = coord(url, tmp_path)
        start(c)
        s['deny'] = code
        lost = []
        with pytest.raises(CoordinationError, match=code):
            with c.guard('release-a1', on_lost=lambda: lost.append(True)):
                pytest.fail('worker must not start')
        assert lost == [True]
        with pytest.raises(CoordinationError):
            c.report_outcome('release-a1', 'succeeded', 'unsafe')
        assert not any(p['operation'].endswith('report-outcome-v1') for p in s['calls'])


def test_expired_lease_cannot_start_worker(tmp_path):
    with owner() as (url, s):
        s['lease']['expires_at'] = expires(-1)
        with pytest.raises(CoordinationError, match='expired'):
            start(coord(url, tmp_path))


def test_environment_mismatch_refuses_before_write(tmp_path):
    with owner() as (url, s):
        s['environment'] = 'wrong'
        with pytest.raises(CoordinationError, match='environment'):
            start(coord(url, tmp_path))
        assert s['calls'] == []


def test_client_refuses_remote_cleartext_and_url_credentials():
    for url in ['http://example.com', 'https://user:password@example.com', 'https://example.com/path']:
        with pytest.raises(ValueError):
            VuoroClient(url, 'repo-a', lambda: 'secret')


def test_lost_registration_ack_recovers_without_duplicate_run(tmp_path):
    with owner() as (url, s):
        s['drop'] = 'work.run.register-v1'
        with pytest.raises(CoordinationError):
            start(coord(url, tmp_path))
        start(coord(url, tmp_path))
        registrations = [p for p in s['calls'] if p['operation'] == 'work.run.register-v1']
        assert registrations[0] == registrations[1]


def test_lost_report_ack_recovers_exact_outcome_without_new_heartbeat(tmp_path):
    with owner() as (url, s):
        c = coord(url, tmp_path)
        start(c)
        s['drop'] = 'work.lease.report-outcome-v1'
        with pytest.raises(CoordinationError):
            c.report_outcome('release-a1', 'succeeded', 'ready')
        beats = sum(p['operation'].endswith('heartbeat-v1') for p in s['calls'])
        result = coord(url, tmp_path).report_outcome('release-a1', 'succeeded', 'ready')
        assert result['settlement_effect'] == 'awaiting-verification'
        assert sum(p['operation'].endswith('heartbeat-v1') for p in s['calls']) == beats
        reports = [p for p in s['calls'] if p['operation'].endswith('report-outcome-v1')]
        assert reports[0] == reports[1]


def test_guard_cancels_running_worker_when_next_heartbeat_is_refused(tmp_path):
    with owner() as (url, s):
        s['lease']['heartbeat_interval_seconds'] = 1
        c = coord(url, tmp_path)
        start(c)
        cancelled = threading.Event()
        with pytest.raises(CoordinationError, match='token-revoked'):
            with c.guard('release-a1', on_lost=cancelled.set) as guard:
                guard.assert_active()
                s['deny'] = 'token-revoked'
                assert cancelled.wait(3), 'running worker cancellation never arrived'
        assert not guard._thread.is_alive()


def test_journal_cannot_be_reused_against_another_owner(tmp_path):
    with owner() as (url, _):
        coord(url, tmp_path)
        with pytest.raises(CoordinationError, match='different owner'):
            Coordinator(VuoroClient(url, 'other-repo', lambda: 'synthetic-runner'),
                        tmp_path / 'coordination.sqlite')


@pytest.mark.parametrize('field', ['schema_version', 'request_id', 'operation', 'catalog_revision'])
def test_mismatched_response_correlation_refuses_binding(tmp_path, field):
    with owner() as (url, s):
        s['correlation'] = field
        with pytest.raises(CoordinationError, match='correlation'):
            start(coord(url, tmp_path))


def test_config_is_opt_in_and_credentials_never_enter_journal(tmp_path, monkeypatch):
    from lanectl.coordination import configured
    assert configured('repo', root=tmp_path, journal_path=tmp_path / 'j.sqlite') is None
    (tmp_path / 'governance').mkdir()
    with owner() as (url, _):
        (tmp_path / 'governance/vuoro.toml').write_text(
            '[repos.repo]\nendpoint = "' + url + '"\nrepo_id = "repo-a"\n'
            'expected_environment = "test"\ntoken_env = "TEST_LANE_RUNNER"\n')
        monkeypatch.setenv('TEST_LANE_RUNNER', 'synthetic-runner')
        c = configured('repo', root=tmp_path, journal_path=tmp_path / 'j.sqlite')
        start(c)
        assert b'synthetic-runner' not in (tmp_path / 'j.sqlite').read_bytes()
        monkeypatch.setenv('TEST_LANE_RUNNER', 'rotated-token')
        assert c.client.token_resolver() == 'rotated-token'


def test_new_principal_cannot_resume_cached_registration(tmp_path):
    with owner() as (url, s):
        start(coord(url, tmp_path))
        s['deny'] = 'run-principal-mismatch'
        with pytest.raises(CoordinationError, match='run-principal-mismatch'):
            start(coord(url, tmp_path))
        assert s['calls'][-1]['operation'] == 'work.lease.acquire-v1'


@pytest.mark.parametrize('status,resolution,closed', [('active',None,False),('done',None,False),
    ('done','rejected',False),('done','withdrawn',False),('done','accepted',True)])
def test_completion_requires_current_accepted_owner_fact(tmp_path,status,resolution,closed):
    with owner() as (url,s):
        c = coord(url,tmp_path)
        start(c)
        s['completion']['item'].update(status=status,resolution=resolution)
        assert c.completion('release-a1')['closed'] is closed
        assert s['calls'][-1]['arguments'] == {'work_id':123}


def test_completion_refuses_unavailable_owner_facts(tmp_path):
    with owner() as (url,s):
        c = coord(url,tmp_path)
        start(c)
        s['completion']['state'] = 'unavailable'
        with pytest.raises(CoordinationError,match='unavailable'):
            c.completion('release-a1')


@pytest.mark.parametrize('denial', [None, 'identity-required', 'repo-scope-mismatch'])
def test_coordinate_requires_scoped_stream_read(tmp_path, monkeypatch, capsys, denial):
    from lanectl.cli import main

    with owner() as (endpoint, state):
        governance = tmp_path / 'governance'
        governance.mkdir()
        (governance / 'vuoro.toml').write_text(
            f'[repos.example]\nendpoint = "{endpoint}"\nrepo_id = "repo-a"\n'
            'expected_environment = "test"\ntoken_env = "TEST_RUNNER_TOKEN"\n'
        )
        local_state = tmp_path / 'state'
        monkeypatch.setenv('LANECTL_HOME', str(tmp_path))
        monkeypatch.setenv('LANECTL_STATE', str(local_state))
        monkeypatch.setenv('TEST_RUNNER_TOKEN', 'synthetic-runner')
        state['deny'] = denial

        assert main(['coordinate', 'example', '--require-stream-read']) == (1 if denial else 0)
        output = capsys.readouterr().out
        assert (denial or 'repository-scoped stream read accepted') in output
        assert [(call['operation'], call['arguments']) for call in state['calls']] == [
            ('lane.stream.read-v1', {'stream': 'control', 'after': 0, 'limit': 1})
        ]
        assert not local_state.exists()


@pytest.mark.parametrize("status,reported,denial,expected", [
    ("pending", 123, None, "Work item 123 is pending"),
    ("active", 123, None, "is not pending"),
    ("pending", 124, None, "is not work 123"),
    ("pending", 123, "item-not-found", "item-not-found"),
])
def test_coordinate_work_item_preflight(tmp_path, monkeypatch, capsys,
                                        status, reported, denial, expected):
    from lanectl.cli import main

    with owner() as (endpoint, state):
        governance = tmp_path / "governance"
        governance.mkdir()
        (governance / "vuoro.toml").write_text(
            f'[repos.example]\nendpoint = "{endpoint}"\nrepo_id = "repo-a"\n'
            'expected_environment = "test"\ntoken_env = "TEST_RUNNER_TOKEN"\n'
        )
        local_state = tmp_path / "state"
        monkeypatch.setenv("LANECTL_HOME", str(tmp_path))
        monkeypatch.setenv("LANECTL_STATE", str(local_state))
        monkeypatch.setenv("TEST_RUNNER_TOKEN", "synthetic-runner")
        state["completion"]["item"].update(status=status, work_id=reported)
        state["deny"] = denial

        success = status == "pending" and reported == 123 and denial is None
        assert main(["coordinate", "example", "--work-item", "123"]) == (0 if success else 1)
        assert expected in capsys.readouterr().out
        assert [(call["operation"], call["arguments"]) for call in state["calls"]] == [
            ("work.public.item-v1", {"work_id": 123})
        ]
        assert not local_state.exists()


@pytest.mark.parametrize('status,denial,expected', [
    ('ok', None, 'repository-scoped Work read accepted'),
    ('ok', 'repo-unauthorized', 'repo-unauthorized'),
    ('unavailable', None, 'owner reports unavailable work state'),
])
def test_coordinate_requires_scoped_work_read(tmp_path, monkeypatch, capsys, status, denial, expected):
    from lanectl.cli import main

    with owner() as (endpoint, state):
        governance = tmp_path / 'governance'
        governance.mkdir()
        (governance / 'vuoro.toml').write_text(
            f'[repos.example]\nendpoint = "{endpoint}"\nrepo_id = "repo-a"\n'
            'expected_environment = "test"\ntoken_env = "TEST_RUNNER_TOKEN"\n'
        )
        local_state = tmp_path / 'state'
        monkeypatch.setenv('LANECTL_HOME', str(tmp_path))
        monkeypatch.setenv('LANECTL_STATE', str(local_state))
        monkeypatch.setenv('TEST_RUNNER_TOKEN', 'synthetic-runner')
        state['deny'] = denial
        state['work_list_state'] = status

        assert main(['coordinate', 'example', '--require-work-read']) == (0 if status == 'ok' and not denial else 1)
        assert expected in capsys.readouterr().out
        assert [(call['operation'], call['arguments']) for call in state['calls']] == [
            ('work.public.list-v1', {})
        ]
        assert not local_state.exists()
