from pathlib import Path
import json
import socket
import threading
import time
import httpx
import uvicorn
from apps.api.app import create_app
from packages.domains.finance.pipelines.account_transaction_service import AccountTransactionService
from packages.domains.overview.pipelines.transformation_overview import refresh_open_attention_items, get_open_attention_items
from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService
from packages.pipelines.transformation_service import TransformationService
from packages.storage.duckdb_store import DuckDBStore
from packages.storage.run_metadata import RunMetadataRepository
from packages.pipelines.reporting_snapshots import PublicationSnapshot, PublicationSnapshotStore
from tests.test_attention_record_api import DuckPublicationStore

root = Path('/tmp/hla-overview-priority-prerequisite-20261115')
ts = TransformationService(DuckDBStore.memory())
s = ts.store
s.execute("INSERT INTO mart_transaction_anomalies_current VALUES ('probe-anomaly', CURRENT_DATE, 'Probe Shop', -42, 'debit', 'unusual', 'Synthetic anomaly')")
s.execute("INSERT INTO mart_contract_review_candidates VALUES ('probe-review', 'Probe Utility', 'electricity', 'expired_contract', 3, 1.5, NULL, 'EUR')")
s.execute("INSERT INTO mart_contract_renewal_watchlist VALUES ('probe-soon', 'Probe Soon', 'Probe Utility', 'electricity', CURRENT_DATE + 7, 7, 1.5, 'EUR', NULL)")
s.execute("INSERT INTO mart_contract_renewal_watchlist VALUES ('probe-later', 'Probe Later', 'Probe Utility', 'electricity', CURRENT_DATE + 20, 20, 1.5, 'EUR', NULL)")
s.execute("INSERT INTO mart_contract_renewal_watchlist VALUES ('probe-outside', 'Probe Outside', 'Probe Utility', 'electricity', CURRENT_DATE + 31, 31, 1.5, 'EUR', NULL)")
s.execute("INSERT INTO mart_upcoming_fixed_costs_30d VALUES ('probe-charge', 'Probe Payment', 'Probe Co', 'monthly', 10, 'EUR', CURRENT_DATE + 2, 'high')")
count = refresh_open_attention_items(s)
raw = get_open_attention_items(s)
warehouse = ReportingService(ts, access_mode=ReportingAccessMode.WAREHOUSE)
pub = DuckPublicationStore()
published = ReportingService(ts, publication_store=pub, access_mode=ReportingAccessMode.PUBLISHED)
published.publish_publications(['mart_open_attention_items'])
wr = warehouse.get_open_attention_items()
pr = published.get_open_attention_items()
history = PublicationSnapshot('mart_open_attention_items', '2020-02', '2020-03-01T00:00:00Z', 'synthetic-run', [wr[-1], wr[0], wr[2]])
PublicationSnapshotStore.for_duckdb(s).write(history, retention_months=1200)
PublicationSnapshotStore.for_postgres(pub).write(history, retention_months=1200)
print(json.dumps({'stage':'reporting','producer_count':count,'producer':raw,'warehouse':wr,'published_duckdb_adapter':pr},default=str),flush=True)


def serve(mode,reporting):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    d=root/('http-'+mode);d.mkdir(exist_ok=True)
    source=AccountTransactionService(landing_root=d/'landing',metadata_repository=RunMetadataRepository(d/'runs.db'))
    app=create_app(source,transformation_service=ts,reporting_service=reporting,auth_mode='disabled')
    config=uvicorn.Config(app,host='127.0.0.1',port=port,log_level='warning')
    server=uvicorn.Server(config)
    thread=threading.Thread(target=server.run,daemon=False);thread.start()
    try:
        for _ in range(100):
            if server.started:break
            if not thread.is_alive():raise RuntimeError('server exited before startup')
            time.sleep(.05)
        assert server.started
        response=httpx.get(f'http://127.0.0.1:{port}/reports/attention-items',timeout=10,trust_env=False)
        print(json.dumps({'stage':'http','mode':mode,'status':response.status_code,'body':response.json()},default=str),flush=True)
        assert response.status_code==200
        historical=httpx.get(f'http://127.0.0.1:{port}/reports/attention-items',params={'as_of':'2020-02'},timeout=10,trust_env=False)
        absent=httpx.get(f'http://127.0.0.1:{port}/reports/attention-items',params={'as_of':'2020-01'},timeout=10,trust_env=False)
        print(json.dumps({'stage':'history','mode':mode,'status':historical.status_code,'body':historical.json(),'absent_status':absent.status_code,'absent_body':absent.json()},default=str),flush=True)
        assert historical.status_code==200 and [x['severity'] for x in historical.json()['rows']]==[1,3,2]
        assert absent.status_code==200 and absent.json()['as_of_status']=='no_history' and absent.json()['rows']==[]
    finally:
        server.should_exit=True;thread.join(10);assert not thread.is_alive()
serve('warehouse',warehouse)
serve('published-duckdb-adapter',published)
assert count==5
assert [x['severity'] for x in wr]==[3,3,2,2,1]
assert [x['severity'] for x in pr]==[1,2,2,3,3]
print(json.dumps({'stage':'complete','ok':True,'limitations':'Synthetic seeded source marts; published backend uses the repository DuckDB SQL adapter, not real PostgreSQL; auth disabled, not an auth test.'}),flush=True)
