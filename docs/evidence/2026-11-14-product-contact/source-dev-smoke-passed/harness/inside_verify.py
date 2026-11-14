"""Post-publication verification run only inside the verified API container."""
import collections, json, urllib.request, http.cookiejar
import psycopg
from psycopg.rows import dict_row
from packages.pipelines.reporting_service import ReportingService, ReportingAccessMode
from packages.storage.postgres_reporting import PostgresReportingStore

DSN='postgresql://homelab:homelab@postgres:5432/homelab'
RELATIONS=('mart_subscription_summary','mart_upcoming_fixed_costs_30d','mart_contract_price_current','mart_contract_review_candidates','mart_contract_renewal_watchlist','mart_transaction_anomalies_current','mart_open_attention_items')
# Independently specified parameter-bound SQL expressions, not imported from reader.
SOURCES={'anomaly':('mart_transaction_anomalies_current',"'anomaly_' || transaction_id"),'contract_review':('mart_contract_review_candidates',"'review_' || contract_id || '_' || reason"),'contract_renewal':('mart_contract_renewal_watchlist',"'renewal_' || contract_id || '_' || CAST(renewal_date AS VARCHAR)"),'upcoming_cost':('mart_upcoming_fixed_costs_30d',"'upcoming_' || charge_id || '_' || CAST(expected_date AS VARCHAR)")}
class FailClosedWarehouse:
 @property
 def store(self): raise AssertionError('warehouse fallback attempted')

def normalize(rows): return collections.Counter(json.dumps(row,sort_keys=True,default=str) for row in rows)
with psycopg.connect(DSN,row_factory=dict_row) as db:
 objects=db.execute("select c.relname from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='reporting' and c.relkind in ('r','p','v','m','S','f') order by 1").fetchall()
 names={r['relname'] for r in objects}
 assert names==set(RELATIONS), (names,RELATIONS)
 snapshots={name:db.execute('select * from reporting.'+name).fetchall() for name in RELATIONS}
 items=snapshots['mart_open_attention_items']
 assert len({r['item_id'] for r in items})==len(items)
 assert {r['item_type'] for r in items}==set(SOURCES)
 service=ReportingService(FailClosedWarehouse(),publication_store=PostgresReportingStore(DSN,schema='reporting'),access_mode=ReportingAccessMode.PUBLISHED)
 groups=[]
 for item in items:
  kind,key=item['item_type'],item['item_id']; table,expr=SOURCES[kind]
  expected=db.execute('select * from reporting.'+table+' where '+expr+' = %s',(key,)).fetchall()
  actual=service.get_attention_record(kind,key)
  assert expected and normalize(expected)==normalize(actual), (kind,key)
  groups.append({'type':kind,'id':key,'rows':len(expected)})
jar=http.cookiejar.CookieJar(); opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
req=urllib.request.Request('http://127.0.0.1:8080/auth/login',data=json.dumps({'username':'admin','password':'replace-me-local-admin-password'}).encode(),headers={'Content-Type':'application/json'},method='POST')
with opener.open(req) as r: assert r.status==200
with opener.open('http://127.0.0.1:8080/reports/attention-items') as r: response=json.load(r)
assert {r['item_id'] for r in response['rows']}=={r['item_id'] for r in items}
print(json.dumps({'relations':{k:len(v) for k,v in snapshots.items()},'source_groups':groups,'snapshot_items':items,'http_ids':sorted(r['item_id'] for r in response['rows'])},default=str,indent=2))
