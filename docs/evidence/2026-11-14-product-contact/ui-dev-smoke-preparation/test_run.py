import copy, unittest
from unittest.mock import patch
import run
class RuntimeGuards(unittest.TestCase):
 def setUp(self):
  self.cfg={'web_id':'w','api_id':'a','project':'lane-dev-train-x'}
  self.img={'web':'sha256:web','api':'sha256:api'}
  self.web={'Id':'w','Image':'sha256:web','State':{'Running':True},'Config':{'Labels':{'com.docker.compose.project':'lane-dev-train-x','com.docker.compose.service':'web'},'Env':['HOMELAB_ANALYTICS_API_BASE_URL=http://api:8080']},'NetworkSettings':{'Ports':{'8081/tcp':[{'HostIp':'127.0.0.1','HostPort':'1234'}]}}}
  self.api={'Id':'a','Image':'sha256:api'};self.net={'Containers':{'a':{},'w':{}}}
 def test_bound_url(self):self.assertEqual(run.get_web_url(self.cfg,self.web,self.api,self.net,self.img),'http://127.0.0.1:1234/')
 def bad(self,change):
  c,w,a,n,i=copy.deepcopy((self.cfg,self.web,self.api,self.net,self.img));change(c,w,a,n,i)
  with self.assertRaises(ValueError):run.get_web_url(c,w,a,n,i)
 def test_wrong_image(self):self.bad(lambda c,w,a,n,i:w.update(Image='sha256:other'))
 def test_wrong_port(self):self.bad(lambda c,w,a,n,i:w['NetworkSettings']['Ports']['8081/tcp'][0].update(HostIp='0.0.0.0'))
 def test_wrong_backend(self):self.bad(lambda c,w,a,n,i:w['Config'].update(Env=['HOMELAB_ANALYTICS_API_BASE_URL=http://other:8080']))
 def test_wrong_project(self):self.bad(lambda c,w,a,n,i:w['Config']['Labels'].update({'com.docker.compose.project':'other'}))
 def test_wrong_network(self):self.bad(lambda c,w,a,n,i:n['Containers'].pop('a'))
 def test_browser_bad_id_never_cleanup(self):
  with patch.object(run,'cmd',side_effect=['a'*64+'\n','invalid-id']):
   with self.assertRaises(ValueError):run.run_browser('/docker','image','/tmp','http://127.0.0.1:1234/',{},'x',run.pathlib.Path('/tmp'))
 def test_facts_collector_has_no_publisher_call(self):
  from pathlib import Path
  text=Path(run.__file__).with_name('inside_facts.py').read_text()
  self.assertNotIn('inside_publish',text)
if __name__=='__main__':unittest.main()

class OrchestrationControls(unittest.TestCase):
 def test_wrong_web_image_stops_before_browser_or_publication(self):
  import json, os, tempfile
  from pathlib import Path
  from unittest.mock import patch
  with tempfile.TemporaryDirectory(dir=Path(run.__file__).parent) as t:
   config=Path(t)/'context.json';config.write_text(json.dumps({'source_path':t,'api_id':'a','web_id':'w','network_id':'n','project':'lane-dev-train-x'}))
   sel=Path(t)/'selectors.json';sel.write_text('{}')
   fake=Path(t)/'docker';fake.write_text('');fake.chmod(0o755)
   web={'Id':'w','Image':'wrong','State':{'Running':True},'Config':{'Labels':{},'Env':[]},'NetworkSettings':{'Ports':{}}}
   calls=[]
   def command(argv,**kwargs):
    calls.append(argv)
    if 'guard.py' in argv[1]:return '{}'
    raise AssertionError('unexpected subprocess')
   def inspected(d,kind,name):
    if kind=='image':return {'Id':name}
    if kind=='network':return {'Containers':{}}
    return web if name=='w' else {'Id':'a','Image':'sha256:api'}
   with patch.object(run.sys,'argv',['run.py',str(config),'--observer-dir',t,'--selectors',str(sel),'--browser-image','sha256:'+'b'*64,'--docker',str(fake)]),patch.object(run.shutil,'which',return_value=str(fake)),patch.object(run,'cmd',side_effect=command),patch.object(run,'inspect',side_effect=inspected),patch.object(run,'check_context',return_value={'web':'sha256:web','api':'sha256:api'}),patch.object(run,'run_browser') as browser:
    with self.assertRaisesRegex(ValueError,'wrong web'):run.main()
    browser.assert_not_called()
    self.assertTrue(all('publish' not in ' '.join(c) for c in calls))

class BrowserCleanupControls(unittest.TestCase):
 def exercise(self, *, fail_inspect=False, fail_log=False, fail_remove=False, fail_inventory=False, primary=False, still_present=False):
  import json, subprocess, tempfile
  from pathlib import Path
  cid='a'*64;calls=[];inventories=0
  with tempfile.TemporaryDirectory(dir=Path(run.__file__).parent) as directory:
   artifact=Path(directory);(artifact/'observation.json').write_text('{}')
   def command(argv, **kwargs):
    nonlocal inventories
    calls.append(argv)
    if argv[1]=='ps':
     inventories+=1
     if inventories==2 and fail_inventory:raise RuntimeError('injected inventory failure')
     return cid+'\n' if inventories==2 and still_present else ''
    if argv[1]=='create':return cid+'\n'
    if argv[1:3]==['container','inspect']:
     if fail_inspect:raise RuntimeError('injected inspect failure')
     return '{}'
    if argv[1]=='rm':
     if fail_remove:raise RuntimeError('injected removal failure')
     return cid+'\n'
    raise AssertionError(argv)
   original=Path.write_text
   def write_text(path,*args,**kwargs):
    if path.name=='browser.log' and fail_log:raise OSError('injected log write failure')
    return original(path,*args,**kwargs)
   proc=subprocess.CompletedProcess([],1 if primary else 0,stdout='browser output',stderr='')
   with patch.object(run,'cmd',side_effect=command),patch.object(run.subprocess,'run',return_value=proc),patch.object(Path,'write_text',write_text):
    with self.assertRaises(Exception) as error:
     run.run_browser('/docker','image','/tmp','http://127.0.0.1:1234/',{},'x',artifact)
   self.assertIn(['/docker','rm',cid],calls)
   self.assertEqual(inventories,2)
   return error.exception
 def test_inspect_failure_removes_and_inventories(self):
  self.assertIn('inspect/log failed',str(self.exercise(fail_inspect=True)))
 def test_log_write_failure_removes_and_inventories(self):
  self.assertIn('injected log write failure',str(self.exercise(fail_log=True)))
 def test_removal_failure_remains_failure(self):
  self.assertIn('removal failed',str(self.exercise(fail_remove=True)))
 def test_inventory_failure_never_claims_absence(self):
  self.assertIn('absence inventory failed',str(self.exercise(fail_inventory=True)))
 def test_still_present_never_claims_absence(self):
  self.assertIn('still present',str(self.exercise(still_present=True)))
 def test_primary_error_preserved_with_cleanup_diagnostics(self):
  err=self.exercise(primary=True,fail_inspect=True,fail_remove=True,fail_inventory=True)
  self.assertIn('browser execution failed',str(err))
  notes=' '.join(err.__notes__)
  self.assertIn('inspect/log failed',notes);self.assertIn('removal failed',notes);self.assertIn('absence inventory failed',notes)
