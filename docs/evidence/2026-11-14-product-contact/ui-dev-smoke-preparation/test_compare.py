import copy, unittest
from compare import check

def fixture():
 rows={
 'anomaly':{'counterparty_name':'Alpha','booking_date':'2026-01-02','amount':'12.3400','direction':'debit','anomaly_reason':'unusual'},
 'upcoming_cost':{'contract_name':'Broadband','provider':'Beta','expected_amount':'30.00','currency':'EUR','frequency':'monthly','expected_date':'2026-01-03','confidence':'high'},
 'contract_review':{'provider':'Gamma','utility_type':'electricity','reason':'review','current_price':'12.00','currency':'EUR','market_reference':None},
 'contract_renewal':{'contract_name':'Power','provider':'Delta','renewal_date':'2026-01-04','days_until_renewal':2,'current_price':'20','currency':'EUR'}}
 kinds=list(rows); feed=[]; records={}; queue=[]; details={}
 for idx,k in enumerate(kinds):
  key=k+'/opaque'; title='Unique '+k; href='/details/'+k
  components=[rows[k]]; texts=[' '.join('Unknown' if v is None else str(v) for v in rows[k].values())]
  if k=='contract_review':
   other=dict(rows[k],provider='Other',current_price='19'); components.append(other); texts.append(' '.join('Unknown' if v is None else str(v) for v in other.values()))
  feed.append({'item_id':key,'item_type':k,'title':title,'severity':3-idx%3})
  records[key]={'item_id':key,'kind':k,'rows':components}
  queue.append({'title':title,'href':href,'label':{3:'urgent',2:'soon',1:'watch'}[3-idx%3]})
  details[key]={'click_url':href,'direct_url':href,'current_report':True,'text':'Current report','components':texts}
 # stable sorted feed and corresponding rendered queue
 order=sorted(range(len(feed)),key=lambda i:-feed[i]['severity'])
 return feed,records,{'queue':[queue[i] for i in order],'details':details,'queue_current_report':True,'cashflow_distinct':True}

class Controls(unittest.TestCase):
 def setUp(self): self.feed,self.records,self.obs=fixture()
 def test_baseline(self): self.assertEqual(check(self.feed,self.records,self.obs)['checked'],4)
 def reject(self,mutate):
  f,r,o=copy.deepcopy((self.feed,self.records,self.obs)); mutate(f,r,o)
  with self.assertRaises(ValueError): check(f,r,o)
 def test_wrong_rank(self): self.reject(lambda f,r,o:o['queue'].reverse())
 def test_stale(self): self.reject(lambda f,r,o:o['details']['anomaly/opaque']['components'].__setitem__(0,'stale'))
 def test_missing(self): self.reject(lambda f,r,o:o['details']['contract_review/opaque']['components'].pop())
 def test_disjoint(self): self.reject(lambda f,r,o:o['details']['contract_review/opaque']['components'].__setitem__(1,o['details']['contract_review/opaque']['components'][0]))
 def test_collapsed(self): self.reject(lambda f,r,o:o['details']['contract_review/opaque'].__setitem__('components',[' '.join(o['details']['contract_review/opaque']['components'])]))
 def test_wrong_link(self): self.reject(lambda f,r,o:o['details']['anomaly/opaque'].__setitem__('direct_url','/wrong'))
 def test_invented_currency(self): self.reject(lambda f,r,o:o['details']['anomaly/opaque'].__setitem__('text','Current report EUR'))
 def test_false_history(self): self.reject(lambda f,r,o:o['details']['anomaly/opaque'].__setitem__('text','Current report deleted'))
 def test_bad_label(self): self.reject(lambda f,r,o:o['queue'][0].__setitem__('label','watch'))
 def test_missing_current(self): self.reject(lambda f,r,o:o.__setitem__('cashflow_distinct',False))
if __name__=='__main__': unittest.main()

class NumericControls(unittest.TestCase):
 def test_numeric_requires_whole_token(self):
  from compare import value_present
  for expected,rendered in [('7.1','17.1'),('1','10'),('7.10','7.1001'),('1','-1'),('3','13'),('1','1,000')]:
   with self.subTest(expected=expected,rendered=rendered):self.assertFalse(value_present(expected,rendered))
 def test_decimal_equivalence_and_non_numeric(self):
  from compare import value_present
  self.assertTrue(value_present('7.1000','Amount 7.1 EUR'))
  self.assertTrue(value_present('2026-01-04','Date 2026-01-04'))
  self.assertTrue(value_present('Delta','Provider Delta'))
 def test_wrong_precise_row_cannot_pass(self):
  from compare import disjoint_match
  with self.assertRaises(ValueError):disjoint_match([['7.1']],['amount 17.1'])
