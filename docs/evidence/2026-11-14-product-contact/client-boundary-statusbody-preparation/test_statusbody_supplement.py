"""Supplemental status-before-body checks; real temporary Next and candidate reader."""
import json
import os
import shutil
import urllib.parse
from pathlib import Path

import pytest
import tests.test_attention_record_boundary_acceptance as fixture

ROOT = Path(__file__).resolve().parents[1]
assert Path(fixture.__file__).resolve().is_relative_to(ROOT), fixture.__file__

@pytest.fixture(scope='module')
def live(tmp_path_factory):
    with fixture.Lab(tmp_path_factory.mktemp('statusbody-next')) as lab:
        pid = lab.proc.pid
        try:
            yield lab
        finally:
            shutil.copy2(lab.tmp / 'next.log', Path(os.environ['HLA_STATUSBODY_ARTIFACTS']) / 'next.log')
    print(f'owned Next process group {pid} verified absent; no browser launched')

@pytest.mark.parametrize('status,expected,retry', [
    (401, 'redirect', None), (403, 'denied', None), (404, 'not_found', None),
    (503, 'unavailable', '12'), (500, 'throw', None),
])
@pytest.mark.parametrize('body', [b'', b'SYNTHETIC_SECRET_invalid_json'])
def test_status_before_body(live, status, expected, retry, body):
    item_id = 'review_status_body/雪_%_privatekey'
    live.state.update(status=status, body=body, retry=retry)
    live.state['hits'].clear()
    code, headers, payload = fixture.outcome(live, 'contract_review', item_id)
    assert b'SYNTHETIC_SECRET' not in payload and item_id.encode() not in payload
    if expected == 'redirect':
        assert code in (303, 307, 308) and urllib.parse.urlsplit(headers['Location']).path == '/login'
    elif expected == 'throw':
        assert code == 500 and json.loads(payload).get('thrown') is True
    else:
        assert code == 200
        result = json.loads(payload)['result']
        assert result['status'] == expected
        if status == 503:
            assert result['retryAfter'] == '12'
    live.exact_hit('contract_review', item_id)
