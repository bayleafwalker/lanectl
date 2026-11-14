from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import duckdb, psycopg
from fastapi.testclient import TestClient
from packages.pipelines.warehouse_session import WarehouseSessionManager, WarehouseSessionTransformationService, _ReadOnlyTransformationService
from packages.pipelines.transformation_service import TransformationService
from packages.pipelines.reporting_service import ReportingService, ReportingAccessMode
from packages.storage.duckdb_store import DuckDBStore, WarehouseBusyError
from packages.storage.postgres_reporting import PostgresReportingStore
from tests.postgres_test_support import running_postgres_container
from tests.test_attention_record_api import seed, refresh, source_key, record_path, make_client, publish
with TemporaryDirectory(prefix='hla-a7-boundary-') as td:
    root=Path(td); path=root/'warehouse.duckdb'; store=DuckDBStore.open(str(path)); ts=TransformationService(store)
    seed(ts); refresh(ts); row=store.fetchall_dicts('SELECT * FROM mart_upcoming_fixed_costs_30d')[0]
    key=source_key('upcoming_cost',row); uri=record_path('upcoming_cost',key); store.close()
    manager=WarehouseSessionManager(path,lambda store,read_only: _ReadOnlyTransformationService(store) if read_only else TransformationService(store),idle_timeout_seconds=0)
    try:
        proxy=WarehouseSessionTransformationService(manager); service=ReportingService(proxy,access_mode=ReportingAccessMode.WAREHOUSE)
        client=TestClient(make_client(root,proxy,service).app,raise_server_exceptions=False)
        initial=client.get(uri); assert initial.status_code==200; result={}
        for label,exc in [('driver',duckdb.IOException('synthetic-lease-marker')),('busy',WarehouseBusyError('synthetic',1,RuntimeError('held'))),('program',RuntimeError('synthetic-program-marker'))]:
            assert manager.mode is None
            with patch('packages.storage.duckdb_store.connect_with_lock_retry',side_effect=exc) as mock:
                resp=client.get(uri)
            assert mock.call_count==1 and manager.mode is None
            if label=='driver': assert resp.status_code==503 and set(resp.json())=={'detail'} and 'synthetic-lease-marker' not in resp.text
            if label=='busy': assert resp.status_code==503 and resp.headers['Retry-After']=='5' and resp.json()['retry_after_seconds']==5
            if label=='program': assert resp.status_code==500 and 'synthetic-program-marker' not in resp.text
            after=client.get(uri); assert after.status_code==200 and after.json()==initial.json()
            result[label]={'status':resp.status_code,'factory_calls':mock.call_count,'before_after_exact':True,'retry_after':resp.headers.get('Retry-After')}
        print('warehouse',json.dumps(result,sort_keys=True))
    finally: manager.stop()
    warehouse=DuckDBStore.memory(); ts=TransformationService(warehouse); seed(ts); refresh(ts)
    try:
        with running_postgres_container() as dsn:
            pg=PostgresReportingStore(dsn); publish(ts,pg); service=ReportingService(ts,publication_store=pg,access_mode=ReportingAccessMode.PUBLISHED)
            client=TestClient(make_client(root,ts,service,name='pg').app,raise_server_exceptions=False)
            before=client.get(uri); assert before.status_code==200
            with patch.object(pg,'_connect',side_effect=psycopg.OperationalError('synthetic-pg-marker')) as mock:
                with patch.object(warehouse,'fetchall_dicts',side_effect=AssertionError('warehouse fallback')):
                    resp=client.get(uri)
            assert mock.call_count and resp.status_code==503 and set(resp.json())=={'detail'} and 'synthetic-pg-marker' not in resp.text
            failure=RuntimeError('synthetic-pg-program')
            with patch.object(pg,'_connect',side_effect=failure) as mock:
                resp2=client.get(uri)
            assert mock.call_count and resp2.status_code==500 and 'synthetic-pg-program' not in resp2.text
            after=client.get(uri); assert after.status_code==200 and after.json()==before.json()
            print('postgres',json.dumps({'driver_status':resp.status_code,'program_status':resp2.status_code,'before_after_exact':True,'warehouse_fallback_forbidden':True},sort_keys=True))
    finally: warehouse.close()
