import copy
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import quote
import http_verify as h
import orchestrate

class Model:
 @classmethod
 def model_validate(cls,row): return cls(row)
 def __init__(self,row): self.row=row
 def model_dump(self,mode): return self.row

class DB:
 def __init__(self, groups): self.groups=groups; self.calls=[]
 def execute(self, sql, params):
  self.calls.append((sql,params)); self.result=self.groups.get(params[0], []); return self
 def fetchall(self): return self.result

class HttpTests(unittest.TestCase):
 def setUp(self):
  self.items=[{'item_type':k,'item_id': ('key/one' if n==0 else 'key'+str(n))} for n,k in enumerate(h.SOURCES)]
  self.groups={i['item_id']:[{'amount':Decimal('1.20'),'day':date(2026,11,14),'identity':i['item_id']}, {'amount':Decimal('2.00'),'day':date(2026,11,15),'identity':i['item_id']}] for i in self.items}
  self.db=DB(self.groups); self.models={k:Model for k in h.SOURCES}; self.responses={}
  self.responses['/reports/attention-items']=(200,{'rows':copy.deepcopy(self.items)})
  for item in self.items:
   path=self.path(item); self.responses[path]=(200,{'item_id':item['item_id'],'rows':h.jsonable(self.groups[item['item_id']])})
  for kind,segment in h.SEGMENTS.items(): self.responses['/reports/'+segment+'/records/__hla_smoke_provably_unknown_7f937b01__']=(404,{'detail':'not found'})
 def path(self,item): return '/reports/'+h.SEGMENTS[item['item_type']]+'/records/'+quote(item['item_id'],safe='')
 def run_verify(self): return h.verify(self.db,self.items,lambda p:self.responses.get(p,(404,{'detail':'no'})),lambda p:(401,{'detail':'auth'}),self.models)
 def test_correct_and_parameter_binding(self):
  result=self.run_verify(); self.assertEqual(len(result['http_groups']),4); self.assertEqual(len(result['slash_groups']),1); self.assertEqual(len(result['multirow_groups']),4)
  self.assertTrue(all('%s' in sql and len(params)==1 and params[0] not in sql for sql,params in self.db.calls))
  self.assertIn('%2F',self.path(self.items[0]))
 def test_wrong_rows(self):
  self.responses[self.path(self.items[0])][1]['rows'][0]['amount']='99'
  with self.assertRaises(AssertionError): self.run_verify()
 def test_missing_rows(self):
  self.responses[self.path(self.items[0])][1]['rows'].pop()
  with self.assertRaises(AssertionError): self.run_verify()
 def test_wrong_item_id(self):
  self.responses[self.path(self.items[0])][1]['item_id']='wrong'
  with self.assertRaises(AssertionError): self.run_verify()
 def test_wrong_kind_path(self):
  path=self.path(self.items[0]); self.responses['/reports/wrong/records/key%2Fone']=self.responses.pop(path)
  with self.assertRaises(AssertionError): self.run_verify()
 def test_error_status(self):
  self.responses[self.path(self.items[0])]=(503,{'detail':'unavailable'})
  with self.assertRaises(AssertionError): self.run_verify()
 def test_missing_kind_fixture(self):
  self.items.pop()
  with self.assertRaisesRegex(AssertionError,'missing kind'): self.run_verify()
 def test_feed_ids_wrong(self):
  self.responses['/reports/attention-items'][1]['rows'].pop()
  with self.assertRaisesRegex(AssertionError,'feed ids'): self.run_verify()
 def test_unknown_control_fails(self):
  self.responses['/reports/transaction-anomalies/records/__hla_smoke_provably_unknown_7f937b01__']=(200,{'rows':[]})
  with self.assertRaises(AssertionError): self.run_verify()
 def test_no_http_write_control(self):
  with patch.object(orchestrate,'snapshot',return_value={'rows':{'a':['changed']}}):
   with self.assertRaisesRegex(ValueError,'changed during verification'): orchestrate.verify_unchanged({}, {'rows':{'a':['original']}})
  with patch.object(orchestrate,'snapshot',return_value={'rows':{'a':['original']}}):
   orchestrate.verify_unchanged({}, {'rows':{'a':['original']}})
if __name__=='__main__': unittest.main()
