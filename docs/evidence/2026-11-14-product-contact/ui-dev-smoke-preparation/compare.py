"""Offline comparator for synthetic controls or a separately captured real browser observation.
No fixture is a runtime qualification; caller must bind expected API rows to independent SQL.
"""
import re
from decimal import Decimal, InvalidOperation

FIELDS = {
 'anomaly': ('counterparty_name','booking_date','amount','direction','anomaly_reason'),
 'upcoming_cost': ('contract_name','provider','expected_amount','currency','frequency','expected_date','confidence'),
 'contract_review': ('provider','utility_type','reason','current_price','currency','market_reference'),
 'contract_renewal': ('contract_name','provider','renewal_date','days_until_renewal','current_price','currency'),
}

def require(ok, why):
 if not ok: raise ValueError(why)

def value_present(value, text):
 text=' '.join(text.split()).casefold()
 if value is None: return bool(re.search(r'\bunknown\b',text))
 value=str(value).strip().casefold()
 # Numeric expectations must match a complete decimal token, never a substring.
 # String and ISO-date expectations retain exact case-insensitive text matching.
 try: expected=Decimal(value)
 except InvalidOperation: return value in text
 if not expected.is_finite(): return False
 for token in re.findall(r'(?<![\w.])(?<!\d,)-?\d+(?:\.\d+)?(?![\w.]|,\d)',text):
  try:
   if Decimal(token)==expected: return True
  except InvalidOperation: pass
 return False

def disjoint_match(expected, actual):
 # Every record must match a distinct UI component; repeats retain multiplicity.
 require(len(expected)==len(actual), 'component row count mismatch')
 edges=[[j for j,t in enumerate(actual) if all(value_present(v,t) for v in row)] for row in expected]
 def visit(i,used):
  if i==len(edges): return True
  return any(visit(i+1,used|{j}) for j in edges[i] if j not in used)
 require(visit(0,set()), 'missing, wrong, stale or combined component facts')

def check(feed, records, observation):
 require(isinstance(feed,list) and feed, 'empty feed')
 require(all(i.get('item_type') in FIELDS for i in feed), 'unsupported kind')
 require(len({i['item_id'] for i in feed})==len(feed), 'duplicate feed identity')
 def rank(x):
  v=x.get('severity'); return -v if type(v) in (int,float) and v in (1,2,3) else 0
 ordered=sorted(feed,key=rank)[:8]
 require(set(x['item_type'] for x in ordered)==set(FIELDS), 'top eight lacks a kind')
 rows=observation['queue']
 require(len(rows)==len(ordered), 'queue length mismatch')
 require(observation['queue_current_report'], 'queue lacks Current report')
 require(observation['cashflow_distinct'], 'cashflow context not separate')
 links=set()
 for item,ui in zip(ordered,rows):
  require(ui['title']==item['title'], 'wrong rank/title')
  sev=item.get('severity'); label={3:'urgent',2:'soon',1:'watch'}.get(sev,'unknown') if type(sev) in (int,float) else 'unknown'
  require(ui['label'].casefold()==label, 'wrong urgency label')
  require(ui['href'] and ui['href'] not in links, 'missing/duplicate detail link'); links.add(ui['href'])
  key=item['item_id']; kind=item['item_type']; record=records[key]
  require(record['item_id']==key and record['kind']==kind, 'wrong record identity')
  detail=observation['details'][key]
  require(detail['click_url']==ui['href'] and detail['direct_url']==ui['href'], 'click/deep link mismatch')
  require(detail['current_report'], 'detail lacks Current report')
  require(not re.search(r'\b(observed today|deleted|history|historical|saved you|recommend(?:ed|ation)?)\b',detail['text'],re.I), 'unsupported history or recommendation')
  if kind=='anomaly': require(not re.search(r'(?:[€£$]|\b(?:EUR|USD|GBP)\b)',detail['text'],re.I),'fabricated anomaly currency')
  disjoint_match([[row.get(f) for f in FIELDS[kind]] for row in record['rows']],detail['components'])
 require(any('/' in i['item_id'] for i in ordered), 'no slash identity')
 require(any(len(records[i['item_id']]['rows'])>1 for i in ordered), 'no multirow identity')
 require(any(records[i['item_id']]['kind']=='contract_review' and any(r.get('market_reference') is None for r in records[i['item_id']]['rows']) for i in ordered),'no null market reference')
 return {'checked':len(rows),'kinds':sorted(FIELDS),'slash_and_multirow_and_null':True}
