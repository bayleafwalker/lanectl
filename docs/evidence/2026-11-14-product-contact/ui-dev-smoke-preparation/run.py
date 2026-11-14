#!/usr/bin/env python3
"""Read-only post-publication observer; never executes the seed or publisher."""
import argparse, importlib.util, json, os, pathlib, re, shutil, stat, subprocess, sys, uuid
from build_records import validate
from compare import check
from docker_observe import context_digest
HERE=pathlib.Path(__file__).resolve().parent
API=pathlib.Path('/projects/dev/lanectl/docs/evidence/2026-11-14-product-contact/api-dev-smoke-preparation')

def cmd(args, *, data=None):
 p=subprocess.run(args,input=data,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 if p.returncode: raise RuntimeError('command failed: '+args[0]+': '+p.stderr[-1000:])
 return p.stdout

def check_context(cfg, recorddir, docker):
 root=pathlib.Path(cfg['source_path']).resolve(strict=True)
 if cmd(['git','-C',str(root),'rev-parse','HEAD']).strip()!=cfg['sha']:raise ValueError('source HEAD mismatch')
 if cmd(['git','-C',str(root),'status','--porcelain','--untracked-files=all']).strip():raise ValueError('source not clean')
 for x in ('infra/docker/web.Dockerfile','infra/docker/Dockerfile','.dockerignore'):
  if not (root/x).is_file():raise ValueError('build input missing '+x)
 folder=pathlib.Path(recorddir).resolve(strict=True)
 st=folder.stat()
 if st.st_uid!=os.getuid() or stat.S_IMODE(st.st_mode)!=0o700:raise ValueError('observer directory not private')
 logs=folder/'logs'; files=list(logs.iterdir())
 if any(p.is_symlink() or not p.is_file() or p.stat().st_uid!=os.getuid() or stat.S_IMODE(p.stat().st_mode)!=0o600 or not re.fullmatch(r'build-[0-9a-f]{32}\.json',p.name) for p in files):raise ValueError('invalid build record file')
 events=[json.loads(line) for line in pathlib.Path(cfg['event_log']).read_text().splitlines() if line.strip()]
 relevant=[e for e in events if (e.get('data') or {}).get('train_id')==cfg['train_id']]
 built=[e for e in relevant if e.get('type')=='train.built']
 deployed=[e for e in relevant if e.get('type')=='train.deployed']
 if not built or not deployed:raise ValueError('missing receipt timestamps')
 window={**cfg,'built_ts':built[-1]['ts'],'deploy_ts':deployed[-1]['ts']}
 return validate([json.loads(p.read_text()) for p in files],window,context_digest(root))

def inspect(docker,kind,identifier):
 data=json.loads(cmd([docker,kind,'inspect',identifier]));
 if len(data)!=1:raise ValueError('inspect mismatch')
 return data[0]

def get_web_url(cfg,web,api,network,images):
 labels=web['Config'].get('Labels') or {};state=web['State']
 if web['Id']!=cfg['web_id'] or web['Image']!=images['web'] or not state['Running'] or labels.get('com.docker.compose.project')!=cfg['project'] or labels.get('com.docker.compose.service')!='web':raise ValueError('wrong web container/image')
 if api['Id']!=cfg['api_id'] or api['Image']!=images['api']:raise ValueError('wrong API image')
 if web['Id'] not in (network.get('Containers') or {}) or api['Id'] not in (network.get('Containers') or {}):raise ValueError('network mismatch')
 env=dict(x.split('=',1) for x in web['Config']['Env'] if '=' in x)
 if env.get('HOMELAB_ANALYTICS_API_BASE_URL')!='http://api:8080':raise ValueError('web API audience mismatch')
 ports=web['NetworkSettings']['Ports'].get('8081/tcp') or []
 if len(ports)!=1 or ports[0]['HostIp']!='127.0.0.1' or not ports[0]['HostPort'].isdigit():raise ValueError('web port not unique loopback')
 return 'http://127.0.0.1:'+ports[0]['HostPort']+'/'

def run_browser(docker,image,root,url,facts,selectors,artifact):
 # Unique, retained logs, cleanup only exact captured ID. Host networking reaches
 # only the inspected loopback URL; expected image pinned by immutable image ID.
 before=set(cmd([docker,'ps','-a','--no-trunc','-q']).split()); name='hla-ui-smoke-'+uuid.uuid4().hex
 args=[docker,'create','--name',name,'--network','host','--mount',f'type=bind,src={HERE},dst=/smoke,readonly','--mount',f'type=bind,src={root}/apps/web/frontend/node_modules,dst=/deps,readonly','--mount',f'type=bind,src={artifact},dst=/out','-e','NODE_PATH=/deps',image,'node','/smoke/observe.cjs',url,'/out/facts.json','/out/selectors.json','/out/observation.json']
 cid=cmd(args).strip()
 if not re.fullmatch(r'[0-9a-f]{64}',cid) or cid in before:raise ValueError('browser ownership identity not established')
 result=None; primary=None; cleanup_errors=[]
 try:
  (artifact/'browser-id').write_text(cid+'\n')
  proc=subprocess.run([docker,'start','-a',cid],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  (artifact/'browser.log').write_text(proc.stdout+proc.stderr)
  if proc.returncode:raise RuntimeError('browser execution failed; see browser.log')
  result=json.loads((artifact/'observation.json').read_text())
 except BaseException as exc:
  primary=exc
 finally:
  # Diagnostic failure must never skip removal or the independent inventory.
  try:
   diagnostic=cmd([docker,'container','inspect',cid])
   (artifact/'browser-inspect.json').write_text(diagnostic)
  except Exception as exc:cleanup_errors.append('browser inspect/log failed: '+str(exc))
  try:cmd([docker,'rm',cid])
  except Exception as exc:cleanup_errors.append('browser removal failed: '+str(exc))
  try:
   after=set(cmd([docker,'ps','-a','--no-trunc','-q']).split())
   (artifact/'browser-inventory.json').write_text(json.dumps({'before':sorted(before),'after':sorted(after),'created_id':cid},indent=2))
   if cid in after:cleanup_errors.append('owned browser still present in daemon inventory')
  except Exception as exc:cleanup_errors.append('browser absence inventory failed: '+str(exc))
 if primary is not None:
  for error in cleanup_errors: primary.add_note(error)
  raise primary
 if cleanup_errors:raise RuntimeError('; '.join(cleanup_errors))
 return result

def main():
 p=argparse.ArgumentParser();p.add_argument('config');p.add_argument('--observer-dir',required=True);p.add_argument('--selectors',required=True);p.add_argument('--browser-image',required=True);p.add_argument('--docker',required=True);a=p.parse_args()
 docker=str(pathlib.Path(a.docker).resolve(strict=True));cfg=json.loads(pathlib.Path(a.config).read_text());root=pathlib.Path(cfg['source_path']).resolve()
 if not re.fullmatch(r'sha256:[0-9a-f]{64}',a.browser_image):raise ValueError('browser image must be immutable ID')
 if not shutil.which('docker') or pathlib.Path(shutil.which('docker')).resolve()!=pathlib.Path(docker):raise ValueError('guard Docker path does not match measured binary')
 if inspect(docker,'image',a.browser_image)['Id']!=a.browser_image:raise ValueError('browser image inspection mismatch')
 artifact=HERE/('run-'+uuid.uuid4().hex);artifact.mkdir(mode=0o700);print('evidence:',artifact,flush=True)
 # Original guard checks checked/deployed receipt, source/API image, topology,
 # volume provenance and publication state; no publisher is called.
 def guard():return cmd([sys.executable,str(API/'guard.py'),a.config,'--allow-nonempty'])
 (artifact/'api-guard-before.json').write_text(guard())
 images=check_context(cfg,a.observer_dir,docker)
 web=inspect(docker,'container',cfg['web_id']);api=inspect(docker,'container',cfg['api_id']);net=inspect(docker,'network',cfg['network_id']);url=get_web_url(cfg,web,api,net,images)
 api_ip=(net.get('Containers') or {}).get(cfg['api_id'],{}).get('IPv4Address','').split('/')[0]
 dns=cmd([docker,'exec',cfg['web_id'],'node','-e',"require('dns').lookup('api',{all:true},(e,a)=>{if(e)process.exit(1);console.log(JSON.stringify(a.map(x=>x.address)))})"])
 if set(json.loads(dns))!={api_ip}:raise ValueError('web DNS not bound solely to API')
 # Import snapshot helper only; it performs a read-only SQL snapshot.
 spec=importlib.util.spec_from_file_location('api_orchestrate',API/'orchestrate.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 original_call=mod.call
 def bound_call(argv, **kwargs):
  if argv[0]=='docker': argv=[docker,*argv[1:]]
  return original_call(argv, **kwargs)
 mod.call=bound_call
 before=mod.snapshot(cfg);(artifact/'snapshot-before.json').write_text(json.dumps(before))
 try:
  code=(API/'http_verify.py').read_text()+'\n'+(HERE/'inside_facts.py').read_text()
  facts=json.loads(cmd([docker,'exec','-i',cfg['api_id'],'python','-'],data=code))
  (artifact/'facts.json').write_text(json.dumps(facts,indent=2));(artifact/'selectors.json').write_text(pathlib.Path(a.selectors).read_text())
  observation=run_browser(docker,a.browser_image,root,url,facts,a.selectors,artifact)
  result=check(facts['feed'],facts['records'],observation)
  (artifact/'comparison.json').write_text(json.dumps(result,indent=2))
 finally:
  after=mod.snapshot(cfg);(artifact/'snapshot-after.json').write_text(json.dumps(after))
  if before!=after:raise ValueError('reporting snapshots changed')
  (artifact/'api-guard-after.json').write_text(guard())
  if check_context(cfg,a.observer_dir,docker)!=images:raise ValueError('build/source context changed')
 print('UI observation complete; review evidence and scope:',artifact)
if __name__=='__main__':
 try:main()
 except Exception as e:
  print('REFUSED OR FAILED:',e,file=sys.stderr)
  for note in getattr(e,'__notes__',[]):print('ADDITIONAL CLEANUP FAILURE:',note,file=sys.stderr)
  sys.exit(1)
