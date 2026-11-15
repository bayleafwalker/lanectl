"""Controlled Docker post-creation timeout; synthetic engine, not a candidate result."""
import importlib.util, os, subprocess, tempfile
from pathlib import Path
p=Path('/tmp/hla-onboarding-acceptance-portability-r2-20261114/test_onboarding_expand_acceptance.py');spec=importlib.util.spec_from_file_location('acceptance',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
state={'created':False,'removed':False,'owner':None,'name':None};ident='a'*64
class Result:
 def __init__(self,rc=0,out='',err=''):self.returncode=rc;self.stdout=out;self.stderr=err
def fake(args,**kwargs):
 if args[0]==m.NODE:return Result(1,'','synthetic local unavailable')
 assert args[0]=='docker'
 if args[1:3]==['image','inspect']:return Result()
 if args[1]=='run':
  state['created']=True;state['name']=args[args.index('--name')+1];state['owner']=args[args.index('--label')+1].split('=',1)[1]
  raise subprocess.TimeoutExpired(args,45,output=b'synthetic partial id',stderr=b'timeout')
 if args[1]=='inspect':return Result(0,ident+' '+state['owner']+'\n')
 if args[1]=='rm': assert args[-1]==ident;state['removed']=True;return Result(0,ident+'\n')
 if args[1]=='ps':return Result(0,'')
 raise AssertionError(args)
with tempfile.TemporaryDirectory(prefix='hla-docker-timeout-') as d:
 m.OUT=Path(d);m.subprocess.run=fake;os.environ.pop('HLA_ONBOARDING_PLAYWRIGHT_WS',None);os.environ.pop('HLA_CHROMIUM',None)
 try:m.select_browser(Path('/tmp'),{});raise AssertionError('timeout not surfaced')
 except subprocess.TimeoutExpired:pass
 assert state['created'] and state['removed'];assert 'synthetic partial id' in (m.OUT/'browser-launch.log').read_text()
print('controlled post-creation launch timeout surfaced; owned labeled container removed and partial output retained')
