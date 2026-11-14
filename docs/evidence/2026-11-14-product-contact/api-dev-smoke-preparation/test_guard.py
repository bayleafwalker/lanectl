import copy, unittest
from guard import check_fresh_volume, check_dns, check_sessions
from guard import check_identity
class GuardTests(unittest.TestCase):
 def setUp(self):
  self.c=dict(sha='a'*40,train_id='train-x',project='lane-dev-train-x',api_id='b'*64,pg_id='c'*64,api_image='sha256:'+'d'*64,network_id='e'*64,volume='lane_pg',network_members=['b'*64,'c'*64])
  def container(s,i): return {'Id':i,'Image':self.c['api_image'],'State':{'Running':True},'Mounts':[], 'Config':{'Labels':{'com.docker.compose.project':self.c['project'],'com.docker.compose.service':s},'Env':[]}}
  self.api=container('api',self.c['api_id']); self.pg=container('postgres',self.c['pg_id']); self.pg['Mounts']=[{'Name':'lane_pg','Destination':'/var/lib/postgresql/data'}]
  self.api['Config']['Env']=['HOMELAB_ANALYTICS_REPORTING_BACKEND=postgres','HOMELAB_ANALYTICS_REPORTING_POSTGRES_DSN=postgresql://homelab:homelab@postgres:5432/homelab']
  self.net={'Id':self.c['network_id'],'Labels':{'com.docker.compose.project':self.c['project']}}; self.vol={'Name':'lane_pg','Labels':{'com.docker.compose.project':self.c['project']}}
 def test_valid(self): self.assertTrue(check_identity(self.c,self.api,self.pg,self.net,self.vol,self.c['network_members']))
 def test_wrong_image_refuses(self):
  self.c['api_image']='sha256:'+'f'*64
  with self.assertRaisesRegex(ValueError,'image identity'): check_identity(self.c,self.api,self.pg,self.net,self.vol,self.c['network_members'])
 def test_schema_override_refuses(self):
  self.api['Config']['Env'].append('HOMELAB_ANALYTICS_REPORTING_SCHEMA=other')
  with self.assertRaisesRegex(ValueError,'schema mismatch'): check_identity(self.c,self.api,self.pg,self.net,self.vol,self.c['network_members'])
 def test_unexpected_network_member_refuses(self):
  with self.assertRaisesRegex(ValueError,'unexpected network'): check_identity(self.c,self.api,self.pg,self.net,self.vol,self.c['network_members']+['f'*64])
class GuardEvidenceTests(unittest.TestCase):
 def setUp(self):
  self.c={'project':'lane-dev-train-x','train_id':'train-x','sha':'a'*40,'source_path':'/tmp/tree','volume':'lane_pg','pg_id':'c'*64,'network_id':'e'*64}
  self.proof={**{k:self.c[k] for k in ('project','train_id','sha','source_path','volume')},'schema':'hla-volume-absence/v1','docker_server_id':'server','command':'docker volume ls --format {{.Name}}','exit_code':0,'volume_names':['unrelated'],'observed_at':'2026-11-14T10:00:00.000001Z'}
  self.vol={'CreatedAt':'2026-11-14T10:00:00.999999999Z'}; self.deploy={'ts':'2026-11-14T10:00:01Z'}
  self.net={'Containers':{self.c['pg_id']:{'IPv4Address':'172.1.0.3/16'}}}
  self.pg={'Id':self.c['pg_id'],'NetworkSettings':{'Networks':{'net':{'NetworkID':self.c['network_id'],'IPAddress':'172.1.0.3','Aliases':['postgres']}}}}
 def test_fresh_volume(self): check_fresh_volume(self.c,self.vol,self.deploy,self.proof,'server')
 def test_old_empty_volume_rejected(self):
  self.vol['CreatedAt']='2026-11-14T09:59:59Z'
  with self.assertRaisesRegex(ValueError,'predates'): check_fresh_volume(self.c,self.vol,self.deploy,self.proof,'server')
 def test_volume_in_inventory_rejected(self):
  self.proof['volume_names'].append('lane_pg')
  with self.assertRaisesRegex(ValueError,'existed'): check_fresh_volume(self.c,self.vol,self.deploy,self.proof,'server')
 def test_volume_after_receipt_rejected(self):
  self.vol['CreatedAt']='2026-11-14T10:00:02Z'
  with self.assertRaisesRegex(ValueError,'after deploy'): check_fresh_volume(self.c,self.vol,self.deploy,self.proof,'server')
 def test_valid_dns(self): self.assertEqual(check_dns(self.c,{},self.pg,self.net,['172.1.0.3'],[self.pg]),'172.1.0.3')
 def test_wrong_dns_rejected(self):
  with self.assertRaisesRegex(ValueError,'DNS'): check_dns(self.c,{},self.pg,self.net,['172.1.0.4'],[self.pg])
 def test_duplicate_alias_rejected(self):
  impostor={'Id':'d'*64,'NetworkSettings':{'Networks':{'net':{'NetworkID':self.c['network_id'],'Aliases':['postgres']}}}}
  with self.assertRaisesRegex(ValueError,'claimed'): check_dns(self.c,{},self.pg,self.net,['172.1.0.3'],[self.pg,impostor])
 def test_api_client_allowed(self): check_sessions([['172.1.0.2','','homelab']],'172.1.0.2')
 def test_unexpected_local_client_rejected(self):
  for addr in ('local','127.0.0.1','::1'):
   with self.subTest(addr=addr), self.assertRaisesRegex(ValueError,'unexpected database client'): check_sessions([[addr,'','homelab']],'172.1.0.2')
if __name__=='__main__': unittest.main()
