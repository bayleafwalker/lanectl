#!/usr/bin/env python3
"""Synthetic published-store connection error probe, not an actual outage."""
import argparse
import json
import re
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

p=argparse.ArgumentParser()
p.add_argument('--source-root',type=Path,required=True)
p.add_argument('--expected-source-commit',required=True)
p.add_argument('--output-root',type=Path,required=True)
p.add_argument('--require-fixed',action='store_true')
a=p.parse_args(); source=a.source_root.resolve(); root=a.output_root.resolve()
if not source.is_relative_to('/tmp') or not root.is_relative_to('/tmp') or source==Path('/tmp') or root==Path('/tmp'):
    p.error('source and output roots must be dedicated directories under /tmp')
if root.is_relative_to(source) or source.is_relative_to(root): p.error('source and output roots must not overlap')
if root.exists() and any(root.iterdir()): p.error('output root must be empty')
if not re.fullmatch('[0-9a-f]{40}',a.expected_source_commit): p.error('expected source commit must be 40 lowercase hexadecimal characters')
head=subprocess.run(['git','-C',str(source),'rev-parse','HEAD'],check=True,capture_output=True,text=True).stdout.strip()
if head!=a.expected_source_commit: p.error('source HEAD does not match expected commit')
if subprocess.run(['git','-C',str(source),'status','--porcelain','--untracked-files=no'],check=True,capture_output=True,text=True).stdout: p.error('source has tracked modifications')
root.mkdir(parents=True,exist_ok=True); sys.path.insert(0,str(source))

import psycopg
from fastapi.testclient import TestClient
from apps.api.support import to_jsonable
import packages.pipelines.reporting_service as reporting_module
import tests.test_attention_record_api as fixtures
from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService
from packages.pipelines.transformation_service import TransformationService
from packages.storage.duckdb_store import DuckDBStore
from packages.storage.postgres_reporting import PostgresReportingStore
from tests.postgres_test_support import running_postgres_container
for module in (reporting_module,fixtures):
    if not Path(module.__file__).resolve().is_relative_to(source): raise RuntimeError('import escaped source root')

def canonical(rows): return sorted(json.dumps(r,sort_keys=True) for r in to_jsonable(rows))
def exact(response,key,expected):
    body=response.json()
    return (response.status_code==200 and set(body)=={'item_id','rows'} and body['item_id']==key
            and canonical(body['rows'])==canonical(expected))
@contextmanager
def observe():
    reads=[]; old1=DuckDBStore.fetchall; old2=DuckDBStore.fetchall_dicts
    def f1(store,statement,*args,**kwargs): reads.append(str(statement)); return old1(store,statement,*args,**kwargs)
    def f2(store,statement,*args,**kwargs): reads.append(str(statement)); return old2(store,statement,*args,**kwargs)
    with patch.object(DuckDBStore,'fetchall',f1),patch.object(DuckDBStore,'fetchall_dicts',f2): yield reads

ts=TransformationService(DuckDBStore.memory()); facts=fixtures.seed(ts); fixtures.refresh(ts)
all_calls=[]; real_run=subprocess.run
def track(args,*pa,**kw):
    if isinstance(args,list) and args and args[0]=='docker': all_calls.append(list(args))
    return real_run(args,*pa,**kw)
marker='synthetic-driver-connect-marker-42'
with patch('tests.postgres_test_support.subprocess.run',side_effect=track):
    with running_postgres_container() as dsn:
        pg=PostgresReportingStore(dsn,schema='synthetic_discovery'); fixtures.publish(ts,pg)
        reporting=ReportingService(ts,publication_store=pg,access_mode=ReportingAccessMode.PUBLISHED)
        original_client=fixtures.make_client(root,ts,reporting,name='published')
        client=TestClient(original_client.app,raise_server_exceptions=False)
        rows=pg.fetchall_dicts('SELECT * FROM mart_upcoming_fixed_costs_30d ORDER BY charge_id')
        key=fixtures.source_key('upcoming_cost',rows[0]); expected=[r for r in rows if fixtures.source_key('upcoming_cost',r)==key]
        path=fixtures.record_path('upcoming_cost',key)
        with observe() as before_reads: before=client.get(path)
        before_ok=exact(before,key,expected) and not before_reads
        calls=[]
        def inject(*args,**kwargs):
            calls.append('connect')
            raise psycopg.OperationalError(marker)
        with patch.object(pg,'_connect',side_effect=inject),observe() as reads:
            failed=client.get(path)
            qualifying_attempts=len(calls)
            try: original_client.get(path); raised=None
            except Exception as exc: raised=type(exc).__module__+'.'+type(exc).__name__
            diagnostic_attempts=len(calls)-qualifying_attempts
        try: body=failed.json()
        except ValueError: body=None
        detail_only=isinstance(body,dict) and set(body)=={'detail'}
        no_marker=marker not in failed.text
        no_facts=not any(str(rows[0].get(k)) in failed.text for k in ('charge_id','contract_name','provider') if rows[0].get(k))
        with observe() as after_reads: after=client.get(path)
        after_ok=exact(after,key,expected) and not after_reads
        required=(before_ok and after_ok and failed.status_code==503 and detail_only and no_marker and no_facts and not reads and qualifying_attempts>=1)
        result={'source_commit':head,'source_root':str(source),'service_module':reporting_module.__file__,
            'fixture_module':fixtures.__file__,'reference_date':str(facts['today']),
            'source':'real published Postgres; only _connect patched on actual store object',
            'injected_error_type':'psycopg.OperationalError','qualifying_connection_attempts':qualifying_attempts,
            'diagnostic_connection_attempts':diagnostic_attempts,
            'item_id':key,'expected_group_size':len(expected),'before_status':before.status_code,
            'before_exact_group':before_ok,'before_warehouse_reads':before_reads,
            'fault_http_status':failed.status_code,'fault_body_is_detail_only':detail_only,
            'fault_marker_absent_from_http':no_marker,'fault_source_facts_absent_from_http':no_facts,
            'fault_warehouse_reads':reads,'raised_exception_type':raised,
            'after_status':after.status_code,'after_exact_group':after_ok,'after_warehouse_reads':after_reads,
            'required_behavior':required,'require_fixed':a.require_fixed}
container=next(cmd[cmd.index('--name')+1] for cmd in all_calls if len(cmd)>1 and cmd[1]=='run')
removed=any(cmd[1:3]==['rm','-f'] and cmd[-1]==container for cmd in all_calls)
absent=real_run(['docker','inspect',container],capture_output=True,text=True).returncode!=0
assert removed and absent
result.update(owned_container=container,fixture_rm_f_seen=removed,container_absent_after_cleanup=absent,
              limitations=['synthetic injected connection error, not an actual outage','DuckDBStore fetchall/fetchall_dicts traced; raw connection reads not traced','WarehouseBusyError not exercised'])
(root/'observations.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
if a.require_fixed and not required: sys.exit(1)
