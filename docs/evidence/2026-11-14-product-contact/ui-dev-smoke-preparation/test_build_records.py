import copy,unittest
from build_records import validate
class BuildRecords(unittest.TestCase):
 def setUp(self):
  self.c={'source_path':'/tmp/checked','project':'lane-dev-train-x'};self.r=[]
  for service,df,tag in [('api','infra/docker/Dockerfile','homelab-analytics:'),('web','infra/docker/web.Dockerfile','homelab-analytics-web:')]:
   self.r.append({'argv':['build','-q','-f',df,'-t',tag+self.c['project'],'--label','lanectl.namespace='+self.c['project'],'.'],'cwd':'/tmp/checked','context_before':'ctx','context_after':'ctx','exit_code':0,'stdout':'sha256:'+'a'*64+'\n'})
 def test_positive(self):self.assertEqual(set(validate(self.r,self.c,'ctx')),{'api','web'})
 def bad(self,which,key,value):
  r=copy.deepcopy(self.r);r[which][key]=value
  with self.assertRaises(ValueError):validate(r,self.c,'ctx')
 def test_wrong_context(self):self.bad(1,'context_after','bad')
 def test_wrong_command(self):self.bad(1,'argv',['build','-q','.'])
 def test_wrong_cwd(self):self.bad(1,'cwd','/tmp/other')
 def test_bad_output(self):self.bad(1,'stdout','sha256:abcd')
 def test_failure(self):self.bad(1,'exit_code',1)
 def test_missing(self):
  with self.assertRaises(ValueError):validate(self.r[:1],self.c,'ctx')
 def test_extra(self):
  with self.assertRaises(ValueError):validate(self.r+self.r[:1],self.c,'ctx')
 def test_receipt_window_rejects_stale(self):
  c=dict(self.c,built_ts='2026-01-01T12:00:00Z',deploy_ts='2026-01-01T12:10:00Z')
  r=copy.deepcopy(self.r)
  for item in r:item.update(started_at='2026-01-01T11:00:00+00:00',finished_at='2026-01-01T11:01:00+00:00')
  with self.assertRaisesRegex(ValueError,'outside receipt window'):validate(r,c,'ctx')
 def test_receipt_window_accepts(self):
  c=dict(self.c,built_ts='2026-01-01T12:00:00Z',deploy_ts='2026-01-01T12:10:00Z')
  r=copy.deepcopy(self.r)
  for item in r:item.update(started_at='2026-01-01T12:01:00+00:00',finished_at='2026-01-01T12:02:00+00:00')
  self.assertEqual(len(validate(r,c,'ctx')),2)
if __name__=='__main__':unittest.main()
