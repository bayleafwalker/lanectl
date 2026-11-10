"""Check generated requests against the actual owner schemas (dev dependencies only).

Run with Vuoro's development Python and --sprintctl-root /path/to/sprintctl
--vuoro-root /path/to/vuoro. Nothing connects to a service or changes owner state.
"""
import argparse
from pathlib import Path
import sys
import tempfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--sprintctl-root', type=Path, required=True)
p.add_argument('--vuoro-root', type=Path, required=True)
a = p.parse_args()
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'src'), str(a.sprintctl_root),
    str(a.vuoro_root / 'packages/vuoro-adapter-kit/src'),
    str(a.vuoro_root / 'packages/vuoro-service/src')]
from sprintctl.vuoro_adapter import WORK_OPERATION_CONTRACTS
from vuoro_service.contracts import InvocationRequest
from jsonschema import Draft202012Validator
from lanectl.coordination import VuoroClient, Coordinator

contracts = {c.name: c for c in WORK_OPERATION_CONTRACTS}
validated = []
class ContractOwner(VuoroClient):
    def discover(self):
        self._catalog = {'revision': 'fixture', 'operations': [{'name': name, 'idempotency': contracts[name].idempotency} for name in contracts]}
        return self._catalog

    def invoke(self, envelope):
        InvocationRequest.model_validate(envelope)
        contract = contracts[envelope['operation']]
        if contract.idempotency == 'not-allowed':
            assert envelope['idempotency_key'] is None, 'service refuses transport key on owner-idempotent operation'
        Draft202012Validator(contract.input_schema).validate(envelope['arguments'])
        validated.append(envelope)
        op = envelope['operation']
        if op.endswith('register-v1'):
            return {'run': {'run_id': 'run_' + '0' * 26}}
        if op.endswith(('acquire-v1', 'heartbeat-v1')):
            return {'lease': {'lease_id': 'lease_' + '0' * 26, 'generation': 1,
                'state': 'active', 'expires_at': '2099-01-01T00:00:00+00:00',
                'heartbeat_interval_seconds': 20}}
        if op.endswith(('append-v1', 'tail-v1')):
            return {'item': None}
        return {'settled': False, 'settlement_effect': 'awaiting-verification'}

with tempfile.TemporaryDirectory(prefix='lanectl-owner-contract-') as tmp:
    client = ContractOwner('https://owner.example.invalid', 'fixture', lambda: 'unused')
    c = Coordinator(client, Path(tmp) / 'journal.sqlite')
    c.start('contract-a1', 1, 'fixture/model', 'sha256:' + 'a' * 64)
    c.heartbeat('contract-a1')
    c.append_evidence('contract-a1', 'gates', 'test', {'passed': True})
    c.report_outcome('contract-a1', 'succeeded', 'fixture', checks=[])

# Prove both validators reject realistic incompatible requests.
from jsonschema.exceptions import ValidationError
claim = next(e for e in validated if e['operation'].endswith('acquire-v1'))
invalid = dict(claim['arguments'], ttl_seconds=60)
try:
    Draft202012Validator(contracts[claim['operation']].input_schema).validate(invalid)
except ValidationError:
    pass
else:
    raise AssertionError('owner schema accepted caller-selected TTL')
try:
    InvocationRequest.model_validate(dict(claim, schema_version='unknown/v9'))
except ValueError:
    pass
else:
    raise AssertionError('service envelope accepted unknown schema')
print(f'{len(validated)} owner-schema requests validated; owner and service falsifiers rejected')
