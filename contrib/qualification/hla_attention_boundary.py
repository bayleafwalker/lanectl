#!/usr/bin/env python3
"""Synthetic HTTP/store boundary probes; expected negatives for rejected revisions.

Requires the checked-out source's frozen tests/test_attention_record_api helpers.
Assertions cover only the observed source-row shape; opaque 'None' contract IDs
are intentionally not classified or rejected by this probe.
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

parser=argparse.ArgumentParser()
parser.add_argument('--source-root',type=Path,required=True)
parser.add_argument('--expected-source-commit',required=True)
parser.add_argument('--output-root',type=Path,required=True)
parser.add_argument('--require-fixed',action='store_true')
a=parser.parse_args()
source=a.source_root.resolve(); root=a.output_root.resolve()
if not source.is_relative_to('/tmp') or not root.is_relative_to('/tmp') or source==Path('/tmp') or root==Path('/tmp'):
    parser.error('source and output roots must be dedicated directories under /tmp')
if root.is_relative_to(source) or source.is_relative_to(root):
    parser.error('source and output roots must not overlap')
if root.exists() and any(root.iterdir()): parser.error('output root must be empty')
if not re.fullmatch('[0-9a-f]{40}',a.expected_source_commit): parser.error('expected source commit must be 40 lowercase hexadecimal characters')
head=subprocess.run(['git','-C',str(source),'rev-parse','HEAD'],check=True,capture_output=True,text=True).stdout.strip()
if head!=a.expected_source_commit: parser.error('source HEAD does not match expected commit')
status=subprocess.run(['git','-C',str(source),'status','--porcelain','--untracked-files=no'],check=True,capture_output=True,text=True).stdout
if status: parser.error('source has tracked modifications')
root.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(source))

from fastapi.testclient import TestClient
import packages.pipelines.reporting_service as report_module
import tests.test_attention_record_api as fixtures
from apps.api.routes.report_routes import UPCOMING_FIXED_COSTS_ROW_MODEL
from apps.api.support import to_jsonable
from packages.domains.finance.pipelines.subscription_models import MART_UPCOMING_FIXED_COSTS_30D_COLUMNS
from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService
from packages.pipelines.transformation_service import TransformationService
from packages.storage.duckdb_store import DuckDBStore
from packages.storage.postgres_reporting import PostgresReportingStore
from tests.postgres_test_support import running_postgres_container

for module in (report_module,fixtures):
    if not Path(module.__file__).resolve().is_relative_to(source):
        raise RuntimeError(f'import escaped source root: {module.__file__}')

ts=TransformationService(DuckDBStore.memory())
facts=fixtures.seed(ts)
fixtures.refresh(ts)
row=ts.store.fetchall_dicts('SELECT * FROM mart_upcoming_fixed_costs_30d ORDER BY charge_id')[0]
key=f"upcoming_{row['charge_id']}_{row['expected_date']}"
path=fixtures.record_path('upcoming_cost',key)
@contextmanager
def observe_warehouse():
    reads=[]
    old_one=DuckDBStore.fetchall
    old_many=DuckDBStore.fetchall_dicts
    def fetchall(store,statement,*args,**kwargs):
        reads.append({'method':'fetchall','sql':str(statement)})
        return old_one(store,statement,*args,**kwargs)
    def fetchall_dicts(store,statement,*args,**kwargs):
        reads.append({'method':'fetchall_dicts','sql':str(statement)})
        return old_many(store,statement,*args,**kwargs)
    with patch.object(DuckDBStore,'fetchall',fetchall), patch.object(DuckDBStore,'fetchall_dicts',fetchall_dicts):
        yield reads

def http_client(client): return TestClient(client.app,raise_server_exceptions=False)
def exception_name(client,url):
    try: client.get(url)
    except Exception as exc: return type(exc).__module__+'.'+type(exc).__name__
    return None
strict=ReportingService(ts,access_mode=ReportingAccessMode.PUBLISHED,publication_store=None)
c1=fixtures.make_client(root,ts,strict,name='strict-none')
assert strict._access_mode==ReportingAccessMode.PUBLISHED and strict._publication_store is None
with observe_warehouse() as reads:
    response=http_client(c1).get(path)
case1={'http_status':response.status_code,'warehouse_reads':reads,'route_item_id':key,
       'matched_rows':len(response.json().get('rows',[])),
       'required_behavior':response.status_code==503 and not reads}
calls=[]; real_run=subprocess.run
def docker_observer(args,*pa,**kw):
    if isinstance(args,list) and args and args[0]=='docker': calls.append(list(args))
    return real_run(args,*pa,**kw)
with patch('tests.postgres_test_support.subprocess.run',side_effect=docker_observer):
    with running_postgres_container() as dsn:
        pg=PostgresReportingStore(dsn,schema='synthetic_probe')
        fixtures.publish(ts,pg)
        reporting=ReportingService(ts,publication_store=pg,access_mode=ReportingAccessMode.PUBLISHED)
        c2=fixtures.make_client(root,ts,reporting,name='published-old-schema')
        before=http_client(c2).get(path)
        assert before.status_code==200
        pg.execute_statements([('ALTER TABLE mart_upcoming_fixed_costs_30d DROP COLUMN charge_id',[])])
        unknown_path=fixtures.record_path('upcoming_cost',f"upcoming_ffffffffffffffff_{row['expected_date']}")
        with observe_warehouse() as reads:
            known=http_client(c2).get(path); known_error=exception_name(c2,path)
            unknown=http_client(c2).get(unknown_path); unknown_error=exception_name(c2,unknown_path)
        case2={'known_before_column_removal_status':before.status_code,'known_after_status':known.status_code,
               'known_exception':known_error,'unknown_item_id':f"upcoming_ffffffffffffffff_{row['expected_date']}",'unknown_after_status':unknown.status_code,
               'unknown_exception':unknown_error,'warehouse_reads':reads,
               'required_behavior':known.status_code==503 and unknown.status_code==503 and not reads}
        fixtures.publish(ts,pg)
        rows=ts.store.fetchall_dicts('SELECT * FROM mart_upcoming_fixed_costs_30d ORDER BY charge_id')
        target=dict(rows[0],charge_id=''); rows[0]=target
        try:
            UPCOMING_FIXED_COSTS_ROW_MODEL.model_validate(to_jsonable(target))
            model_accepts=True
        except Exception:
            model_accepts=False
        try:
            pg.replace_rows('mart_upcoming_fixed_costs_30d',MART_UPCOMING_FIXED_COSTS_30D_COLUMNS,rows)
            store_accepts=True
        except Exception:
            store_accepts=False
        forged=f"upcoming__{target['expected_date']}"
        with observe_warehouse() as reads:
            response=http_client(c2).get(fixtures.record_path('upcoming_cost',forged))
        try:
            data=response.json()
        except ValueError:
            data={}
        case3={'public_row_model_accepts_empty':model_accepts,'publication_store_accepts_empty':store_accepts,
               'forged_item_id':forged,'http_status':response.status_code,
               'response_charge_ids':[r.get('charge_id') for r in data.get('rows',[])],
               'response_detail_only':isinstance(data,dict) and set(data)=={'detail'},
               'warehouse_reads':reads,'required_behavior':response.status_code in (400,404,422,503)
               and isinstance(data,dict) and set(data)=={'detail'} and not reads,
               'input_provenance':'explicit boundary mutation of a loader-generated row; no claim source ingestion generates empty IDs'}
container=next(cmd[cmd.index('--name')+1] for cmd in calls if len(cmd)>1 and cmd[1]=='run')
removed=any(cmd[1:3]==['rm','-f'] and cmd[-1]==container for cmd in calls)
inspection=real_run(['docker','inspect',container],capture_output=True,text=True)
assert removed and inspection.returncode!=0
fixed=all(c['required_behavior'] for c in (case1,case2,case3))
result={'source_commit':head,'source_root':str(source),'service_module':report_module.__file__,
        'fixture_module':fixtures.__file__,
        'reference_date':str(facts['today']),'case1_strict_no_store':case1,
        'case2_published_missing_charge_column':case2,'case3_empty_identity':case3,
        'all_required_behaviors':fixed,'require_fixed':a.require_fixed,
        'owned_container':container,'fixture_rm_f_seen':removed,'container_absent_after_cleanup':True,
        'limitations':['requires compatible frozen attention test fixture helpers',
        'only these three scenarios are checked','warehouse reads tracked through DuckDBStore fetchall/fetchall_dicts',
        'no inference about literal None in opaque contract IDs']}
(root/'observations.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
if a.require_fixed and not fixed: sys.exit(1)
