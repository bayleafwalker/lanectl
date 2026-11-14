import copy, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import orchestrate, guard

class FalsifierTests(unittest.TestCase):
 def test_wrong_image_refusal_with_unchanged_snapshot(self):
  cfg={'api_image':'sha256:'+'a'*64}
  refusal=SimpleNamespace(returncode=1,stderr='REFUSED: API image identity mismatch')
  with patch.object(orchestrate,'demand_guard'),patch.object(orchestrate,'snapshot',side_effect=[{'objects':[]},{'objects':[]}]),patch.object(orchestrate,'guard',return_value=refusal):
   self.assertTrue(orchestrate.wrong_image_falsifier('/tmp/x',cfg)['wrong_image_refused'])
 def test_wrong_image_guard_unexpected_success_rejected(self):
  cfg={'api_image':'sha256:'+'a'*64}
  with patch.object(orchestrate,'demand_guard'),patch.object(orchestrate,'snapshot',return_value={}),patch.object(orchestrate,'guard',return_value=SimpleNamespace(returncode=0,stderr='')):
   with self.assertRaisesRegex(ValueError,'falsifier'): orchestrate.wrong_image_falsifier('/tmp/x',cfg)
 def test_changed_data_rejected(self):
  cfg={'api_image':'sha256:'+'a'*64}
  refusal=SimpleNamespace(returncode=1,stderr='API image identity mismatch')
  with patch.object(orchestrate,'demand_guard'),patch.object(orchestrate,'snapshot',side_effect=[{'objects':[]},{'objects':['changed']}]),patch.object(orchestrate,'guard',return_value=refusal):
   with self.assertRaisesRegex(ValueError,'schema changed'): orchestrate.wrong_image_falsifier('/tmp/x',cfg)

class DiagnosticsTests(unittest.TestCase):
 def test_failure_is_persisted_before_raise_with_private_permissions(self):
  import sys, os
  with tempfile.TemporaryDirectory() as d:
   previous=orchestrate.DIAGNOSTICS; orchestrate.DIAGNOSTICS=Path(d)
   try:
    with self.assertRaises(RuntimeError): orchestrate.call([sys.executable,'-c',"import sys;print('output');print('reason',file=sys.stderr);sys.exit(7)"])
    logs=list(Path(d).glob('stage-*.json')); self.assertEqual(len(logs),1)
    data=json.loads(logs[0].read_text()); self.assertEqual(data['exit_code'],7); self.assertEqual(data['stdout'],'output\n'); self.assertEqual(data['stderr'],'reason\n'); self.assertEqual(data['argv'][0],sys.executable)
    self.assertEqual(os.stat(logs[0]).st_mode & 0o777,0o600)
   finally: orchestrate.DIAGNOSTICS=previous

class ReceiptTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(); self.path=Path(self.temp.name)/'events.jsonl'
  self.cfg={'train_id':'train-123','sha':'a'*40,'project':'lane-dev-train-123','repo':'hla','source_path':'/tmp/tree','event_log':str(self.path)}
  self.build={'type':'train.built','data':{'train_id':'train-123','passed':True,'checked_sha':'a'*40,'repo':'hla','worktree':'/tmp/tree'}}
  self.deploy={'type':'train.deployed','data':{'train_id':'train-123','passed':True,'checked_sha':'a'*40,'repo':'hla','namespace':'lane-dev-train-123','expires_at':'2999-01-01T00:00:00Z'}}
 def tearDown(self): self.temp.cleanup()
 def events(self,events): self.path.write_text(''.join(json.dumps(e)+'\n' for e in events))
 def test_matching(self): self.events([self.build,self.deploy]); guard.check_receipt(self.cfg)
 def test_wrong_sha(self):
  bad=copy.deepcopy(self.deploy); bad['data']['checked_sha']='b'*40; self.events([self.build,bad])
  with self.assertRaisesRegex(ValueError,'deploy receipt'): guard.check_receipt(self.cfg)
 def test_torn_down(self):
  self.events([self.build,self.deploy,{'type':'train.torn_down','data':{'train_id':'train-123'}}])
  with self.assertRaisesRegex(ValueError,'torn down'): guard.check_receipt(self.cfg)
if __name__=='__main__': unittest.main()
