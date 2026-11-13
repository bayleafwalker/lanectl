#!/usr/bin/env python3
"""Synthetic published-row empty-component boundary probes; not ingestion claims.

Requires source's frozen attention record fixture helpers. Exact nonempty opaque
contract IDs containing 'None' are positive controls. Warehouse tracing covers
DuckDBStore.fetchall/fetchall_dicts, not direct raw-connection execution.
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
from contextlib import contextmanager
from datetime import timedelta
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
if root.is_relative_to(source) or source.is_relative_to(root): parser.error('source and output roots must not overlap')
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
from apps.api.routes.report_routes import (
    TRANSACTION_ANOMALIES_ROW_MODEL, CONTRACT_REVIEW_CANDIDATES_ROW_MODEL,
    CONTRACT_RENEWAL_WATCHLIST_ROW_MODEL,
)
from apps.api.support import to_jsonable
from packages.pipelines.household_reporting import PUBLICATION_RELATIONS
from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService
from packages.pipelines.transformation_service import TransformationService
from packages.storage.duckdb_store import DuckDBStore
from packages.storage.postgres_reporting import PostgresReportingStore
from tests.postgres_test_support import running_postgres_container

for module in (report_module,fixtures):
    if not Path(module.__file__).resolve().is_relative_to(source):
        raise RuntimeError(f'import escaped source root: {module.__file__}')

@contextmanager
def observe_warehouse():
    reads=[]; old_one=DuckDBStore.fetchall; old_many=DuckDBStore.fetchall_dicts
    def fetchall(store,statement,*args,**kwargs):
        reads.append({'method':'fetchall','sql':str(statement)})
        return old_one(store,statement,*args,**kwargs)
    def fetchall_dicts(store,statement,*args,**kwargs):
        reads.append({'method':'fetchall_dicts','sql':str(statement)})
        return old_many(store,statement,*args,**kwargs)
    with patch.object(DuckDBStore,'fetchall',fetchall), patch.object(DuckDBStore,'fetchall_dicts',fetchall_dicts):
        yield reads

def json_body(response):
    try: return response.json()
    except ValueError: return None

def canonical(rows):
    return sorted(json.dumps(row, sort_keys=True) for row in to_jsonable(rows))

def resolves_exactly(response,key,expected):
    body=json_body(response)
    return (response.status_code==200 and isinstance(body,dict) and set(body)=={'item_id','rows'}
            and body['item_id']==key and isinstance(body['rows'],list) and bool(body['rows'])
            and canonical(body['rows'])==canonical(expected))

ts=TransformationService(DuckDBStore.memory())
facts=fixtures.seed(ts); today=facts['today']
opaque='opaqueNone/utility'
ts.load_contract_prices([fixtures._price(opaque,component,'1',today+timedelta(days=10),today)
                         for component in ('energy','transfer')],run_id='literal-none-positive')
fixtures.refresh(ts)
calls=[]; real_run=subprocess.run
def docker_observer(args,*pa,**kw):
    if isinstance(args,list) and args and args[0]=='docker': calls.append(list(args))
    return real_run(args,*pa,**kw)
cases=[]; controls=[]
with patch('tests.postgres_test_support.subprocess.run',side_effect=docker_observer):
    with running_postgres_container() as dsn:
        pg=PostgresReportingStore(dsn,schema='synthetic_components')
        fixtures.publish(ts,pg)
        reporting=ReportingService(ts,publication_store=pg,access_mode=ReportingAccessMode.PUBLISHED)
        c=fixtures.make_client(root,ts,reporting,name='published')
        client=TestClient(c.app,raise_server_exceptions=False)
        for kind,relation in [('contract_review','mart_contract_review_candidates'),('contract_renewal','mart_contract_renewal_watchlist')]:
            candidates=pg.fetchall_dicts(f'SELECT * FROM {relation} WHERE contract_id = %s',[opaque])
            assert candidates, (kind,opaque)
            key=fixtures.source_key(kind,candidates[0])
            with observe_warehouse() as reads:
                response=client.get(fixtures.record_path(kind,key))
            grouped=[r for r in candidates if fixtures.source_key(kind,r)==key]
            match=resolves_exactly(response,key,grouped) and not reads
            controls.append({'kind':kind,'opaque_contract_id':opaque,'item_id':key,'http_status':response.status_code,'expected_group_size':len(grouped),'matched_own_rows':bool(match),'warehouse_reads':reads})
        specs=[
            ('anomaly','mart_transaction_anomalies_current','transaction_id',TRANSACTION_ANOMALIES_ROW_MODEL),
            ('contract_review','mart_contract_review_candidates','contract_id',CONTRACT_REVIEW_CANDIDATES_ROW_MODEL),
            ('contract_review','mart_contract_review_candidates','reason',CONTRACT_REVIEW_CANDIDATES_ROW_MODEL),
            ('contract_renewal','mart_contract_renewal_watchlist','contract_id',CONTRACT_RENEWAL_WATCHLIST_ROW_MODEL),
        ]
        for kind,relation,component,model in specs:
            fixtures.publish(ts,pg)
            source_rows=pg.fetchall_dicts(f'SELECT * FROM {relation}',[])
            assert len(source_rows)>=2
            original=dict(source_rows[0]); key_before=fixtures.source_key(kind,original)
            sibling=next(r for r in source_rows[1:] if fixtures.source_key(kind,r)!=key_before)
            sibling_key=fixtures.source_key(kind,sibling)
            sibling_expected=[r for r in source_rows if fixtures.source_key(kind,r)==sibling_key]
            unknown_row=dict(original)
            if kind=='anomaly': unknown_row['transaction_id']='0000000000000000'
            else: unknown_row['contract_id']='qualification-unknown'
            unknown_key=fixtures.source_key(kind,unknown_row)
            assert all(fixtures.source_key(kind,r)!=unknown_key for r in source_rows)
            with observe_warehouse() as before_reads:
                unknown_before=client.get(fixtures.record_path(kind,unknown_key))
            before_body=json_body(unknown_before)
            before_proved=(unknown_before.status_code==404 and isinstance(before_body,dict)
                           and set(before_body)=={'detail'} and not before_reads)
            malformed=dict(original,**{component:''}); source_rows[0]=malformed
            try:
                model.model_validate(to_jsonable(malformed)); model_accepts=True
            except Exception:
                model_accepts=False
            pg.replace_rows(relation,PUBLICATION_RELATIONS[relation].columns,source_rows)
            store_accepts=bool(pg.fetchall_dicts(f'SELECT * FROM {relation} WHERE {component} = %s',['']))
            forged=fixtures.source_key(kind,malformed)
            with observe_warehouse() as reads:
                response=client.get(fixtures.record_path(kind,forged))
                sibling_response=client.get(fixtures.record_path(kind,sibling_key))
                unknown_after=client.get(fixtures.record_path(kind,unknown_key))
            body=json_body(response)
            detail_only=isinstance(body,dict) and set(body)=={'detail'}
            serialized=json.dumps(body,sort_keys=True)
            sensitive=[str(original[field]) for field in ('transaction_id','contract_id','reason','counterparty_name','provider') if original.get(field) is not None and len(str(original[field]))>=5]
            no_facts=not any(value in serialized for value in sensitive)
            safe=response.status_code in (400,404,422,503) and detail_only and no_facts and not reads
            sibling_exact=resolves_exactly(sibling_response,sibling_key,sibling_expected)
            unknown_body=json_body(unknown_after)
            unknown_serialized=json.dumps(unknown_body,sort_keys=True)
            unknown_detail_only=isinstance(unknown_body,dict) and set(unknown_body)=={'detail'}
            unknown_no_facts=not any(value in unknown_serialized for value in sensitive)
            unknown_safe=(unknown_after.status_code==503 and unknown_detail_only
                          and unknown_no_facts and not reads)
            cases.append({'kind':kind,'component':component,'mutation':'empty string in a copied published row',
                'public_row_model_accepts_empty':model_accepts,'publication_store_accepts_empty':store_accepts,
                'forged_item_id':forged,'http_status':response.status_code,'response_detail_only':detail_only,
                'response_source_fields_present':not no_facts,'warehouse_reads':reads,'intact_sibling_item_id':sibling_key,
                'intact_sibling_http_status':sibling_response.status_code,
                'intact_sibling_expected_group_size':len(sibling_expected),'intact_sibling_exact':sibling_exact,
                'unknown_item_id':unknown_key,'unknown_before_http_status':unknown_before.status_code,
                'unknown_before_detail_only':isinstance(before_body,dict) and set(before_body)=={'detail'},
                'unknown_before_warehouse_reads':before_reads,'unknown_before_proved_absent':before_proved,
                'unknown_after_http_status':unknown_after.status_code,'unknown_after_detail_only':unknown_detail_only,
                'unknown_after_source_fields_present':not unknown_no_facts,'unknown_after_required_behavior':unknown_safe,
                'required_behavior':safe and sibling_exact and model_accepts and store_accepts and before_proved and unknown_safe})
container=next(cmd[cmd.index('--name')+1] for cmd in calls if len(cmd)>1 and cmd[1]=='run')
removed=any(cmd[1:3]==['rm','-f'] and cmd[-1]==container for cmd in calls)
inspection=real_run(['docker','inspect',container],capture_output=True,text=True)
assert removed and inspection.returncode!=0
fixed=all(c['required_behavior'] for c in cases) and all(c['matched_own_rows'] for c in controls)
result={'source_commit':head,'source_root':str(source),'service_module':report_module.__file__,
        'fixture_module':fixtures.__file__,'reference_date':str(today),'cases':cases,'literal_none_controls':controls,
        'all_required_behaviors':fixed,'require_fixed':a.require_fixed,'owned_container':container,
        'fixture_rm_f_seen':removed,'container_absent_after_cleanup':True,
        'limitations':['requires compatible frozen attention test fixture helpers',
          'explicit mutations of published rows; no claim ingestion generates empty IDs',
          'warehouse reads traced through DuckDBStore fetchall/fetchall_dicts, not raw connection execution',
          'no general format restrictions or prohibition on literal None']}
(root/'observations.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
if a.require_fixed and not fixed: sys.exit(1)
