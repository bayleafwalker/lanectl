"""Read-only enrolled-runner qualification. Never emits credential values."""
import json
import os
from pathlib import Path
import re

from lanectl.coordination import CoordinationError, VuoroClient
from lanectl.lifecycle import ready_work

credential=Path(os.environ['CREDENTIALS_DIRECTORY'])/'lanectl-runner'
endpoint='https://vuoro-shared.apps.kotona.app'
client=VuoroClient(endpoint,'homelab-analytics',lambda:credential.read_text().strip())
def safe_reason(value):
    found=re.search(r'owner refused: ([a-z][a-z0-9-]{0,63}) \(HTTP ([0-9]{3})\)',str(value))
    return {'code':found[1],'http':int(found[2])} if found else {'code':'unavailable-or-incompatible'}
try:
    handshake=client._request('/api/meta/v1/handshake')
    environment=handshake.get('environment',{}).get('name')
    if not isinstance(environment,str) or not re.fullmatch('[A-Za-z0-9_-]{1,80}',environment):
        raise CoordinationError('unrecognized owner environment')
    client.expected_environment=environment
    catalog=client.discover()
    fact=ready_work(client)
    value=fact.get('value')
    rows=value.get('items') if isinstance(value,dict) else None
    result={'endpoint':endpoint,'environment':environment,'catalog_revision':catalog['revision'],
            'advertised_work_reads':[op['name'] for op in catalog['operations'] if op.get('name','').startswith('work.public.')],
            'ready_state':fact['state'],'ready_count':len(rows) if fact['state']=='observed' and isinstance(rows,list) else None,
            'ready_work_ids':[row.get('work_id') for row in rows if isinstance(row,dict)] if fact['state']=='observed' and isinstance(rows,list) else None}
    if fact['state']!='observed':result['refusal']=safe_reason(fact.get('reason'))
    print(json.dumps(result,sort_keys=True))
except CoordinationError as error:
    print(json.dumps({'endpoint':endpoint,'discovery':'unknown','refusal':safe_reason(error)},sort_keys=True))
    raise SystemExit(1)
