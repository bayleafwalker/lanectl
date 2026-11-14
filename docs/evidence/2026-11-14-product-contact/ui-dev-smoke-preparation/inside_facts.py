"""Run from stdin inside verified API container; HTTP checked against bound SQL."""
import json, urllib.request, http.cookiejar
import psycopg
from psycopg.rows import dict_row
from apps.api.routes.report_routes import (TRANSACTION_ANOMALIES_ROW_MODEL, CONTRACT_REVIEW_CANDIDATES_ROW_MODEL, CONTRACT_RENEWAL_WATCHLIST_ROW_MODEL, UPCOMING_FIXED_COSTS_ROW_MODEL)
# injected http_verify.py above this script
models={'anomaly':TRANSACTION_ANOMALIES_ROW_MODEL,'contract_review':CONTRACT_REVIEW_CANDIDATES_ROW_MODEL,'contract_renewal':CONTRACT_RENEWAL_WATCHLIST_ROW_MODEL,'upcoming_cost':UPCOMING_FIXED_COSTS_ROW_MODEL}
jar=http.cookiejar.CookieJar(); client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)); plain=urllib.request.build_opener()
def fetch(opener,path):
 from urllib.error import HTTPError
 try:
  with opener.open('http://127.0.0.1:8080'+path) as r:return r.status,json.load(r)
 except HTTPError as e:return e.code,json.load(e)
req=urllib.request.Request('http://127.0.0.1:8080/auth/login',data=json.dumps({'username':'admin','password':'replace-me-local-admin-password'}).encode(),headers={'Content-Type':'application/json'},method='POST')
with client.open(req) as response:
 if response.status!=200: raise RuntimeError('example local API auth failed')
with psycopg.connect('postgresql://homelab:homelab@postgres:5432/homelab',row_factory=dict_row) as db:
 items=db.execute('select * from reporting.mart_open_attention_items').fetchall()
 verify(db,items,lambda p:fetch(client,p),lambda p:fetch(plain,p),models)
 status,feed=fetch(client,'/reports/attention-items')
 if status!=200:raise RuntimeError('feed unavailable')
 records={}
 for item in feed['rows']:
  kind=item['item_type']; key=item['item_id']
  status,body=fetch(client,'/reports/'+SEGMENTS[kind]+'/records/'+quote(key,safe=''))
  if status!=200 or body['item_id']!=key:raise RuntimeError('record changed during collection')
  expected=[models[kind].model_validate(jsonable(row)).model_dump(mode='json') for row in sql_rows(db,kind,key)]
  if canon(expected)!=canon(body['rows']):raise RuntimeError('record changed vs independent SQL')
  records[key]={'kind':kind,'item_id':key,'rows':body['rows']}
 print(json.dumps({'feed':feed['rows'],'records':records},default=str))
