"""Exercise the lane adapter through the real Vuoro ASGI/auth/schema shell."""
import argparse
import asyncio
from pathlib import Path
import sys
import tempfile
import uuid

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--vuoro-root', type=Path, required=True)
a = p.parse_args()
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'src'),
    str(a.vuoro_root / 'packages/vuoro-adapter-kit/src'),
    str(a.vuoro_root / 'packages/vuoro-service/src')]
import httpx
from lanectl.contracts import make_event
from lanectl.stream_store import StreamStore, initialize
from lanectl.vuoro_adapter import register_lane_catalog
from vuoro_service.app import create_app, ServiceSettings
from vuoro_service.catalog import CatalogRegistry
from vuoro_service.identity import Identity, StaticBearerIdentityResolver

async def verify(path):
    initialize(path)
    store = StreamStore(path)
    registry = CatalogRegistry()
    register_lane_catalog(registry, store)
    identities = {
        'writer': Identity(actor='lane', environment='test', authorities=frozenset({'work:read','work:evidence'}),
            repo_ids=frozenset({'repo-a'}), workspace_id='ws', principal_id='fixture:writer:1'),
        'reader': Identity(actor='reader', environment='test', authorities=frozenset({'work:read'}),
            repo_ids=frozenset({'repo-a'}), workspace_id='ws', principal_id='fixture:reader:1'),
        'other': Identity(actor='other', environment='test', authorities=frozenset({'work:read','work:evidence'}),
            repo_ids=frozenset({'repo-b'}), workspace_id='ws', principal_id='fixture:other:1'),
    }
    app = create_app(settings=ServiceSettings(environment_name='test', compatibility_state='compatible'),
        registry=registry, identity_resolver=StaticBearerIdentityResolver(identities))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
        headers = {'X-Vuoro-Client-Protocol': '1', 'Authorization': 'Bearer writer'}
        catalog = (await client.get('/api/catalog/v1', headers=headers)).json()
        async def call(op, args, token='writer', repo='repo-a'):
            return await client.post('/api/invoke/v1', headers={**headers, 'Authorization': 'Bearer ' + token}, json={
                'schema_version':'invocation/v1','request_id':str(uuid.uuid4()),'operation':op,
                'arguments':args,'catalog_revision':catalog['revision'],'basis_revision':None,
                'idempotency_key':None,'repo_id':repo})
        event = make_event('release.published', {'release_id':'release-x','revision':1}, item_id='release-x')
        batch = {'stream':'control','expected_revision':0,'events':[event],'idempotency_key':'batch-0001'}
        response = await call('lane.stream.append-v1', batch)
        assert response.status_code == 200, response.text
        assert response.json()['result']['revision'] == 1
        replay = await call('lane.stream.append-v1', batch)
        assert replay.status_code == 200 and replay.json()['result']['replayed']
        for token in ['reader','other']:
            denied = await call('lane.stream.append-v1', batch, token=token)
            assert denied.status_code == 403, denied.text
        denied = await call('lane.stream.read-v1', {'stream':'control'}, repo='repo-b')
        assert denied.status_code == 403, denied.text
        changed = dict(batch, events=[dict(event, ts='different')])
        conflict = await call('lane.stream.append-v1', changed)
        assert conflict.status_code == 409 and conflict.json()['error']['code'] == 'idempotency-conflict', conflict.text
        stale = await call('lane.stream.append-v1', dict(batch, idempotency_key='batch-0002'))
        assert stale.status_code == 409 and stale.json()['error']['code'] == 'revision-conflict', stale.text
        bad = await call('lane.stream.append-v1', dict(batch, idempotency_key='batch-0003',expected_revision=1,
            events=[event, {'type':'unknown'}]))
        assert bad.status_code == 409 and bad.json()['error']['code'] == 'invalid-event', bad.text
        read = await call('lane.stream.read-v1', {'stream':'control'}, token='reader')
        assert read.status_code == 200 and len(read.json()['result']['events']) == 1, read.text
        other = await call('lane.stream.read-v1', {'stream':'control'}, token='other',repo='repo-b')
        assert other.status_code == 200 and other.json()['result']['events'] == [], other.text
    print('Real Vuoro ASGI: append/replay/read pass; unauthorized repo/authority, payload mismatch, stale revision and invalid batch refuse')

with tempfile.TemporaryDirectory(prefix='lanectl-service-contract-') as tmp:
    asyncio.run(verify(Path(tmp)/'stream.sqlite'))
