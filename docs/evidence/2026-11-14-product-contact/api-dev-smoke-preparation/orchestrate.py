#!/usr/bin/env python3
"""Bounded, single-attempt qualification against a root-identified lane deployment."""
import argparse, json, os, pathlib, re, subprocess, sys, tempfile, uuid
HERE=pathlib.Path(__file__).resolve().parent
DIAGNOSTICS=None
STAGE=0

def call(argv, *, input=None, ok=True):
 global STAGE
 p=subprocess.run(argv,input=input,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 if DIAGNOSTICS is not None:
  STAGE+=1
  path=DIAGNOSTICS / ('stage-%03d.json' % STAGE)
  fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
  with os.fdopen(fd,'w') as f: json.dump({'argv':argv,'stdout':p.stdout,'stderr':p.stderr,'exit_code':p.returncode},f,indent=2)
 if ok and p.returncode: raise RuntimeError('command failed: '+argv[0]+' (see exit status '+str(p.returncode)+')')
 return p

def guard(path,*options):
 return call([sys.executable,str(HERE/'guard.py'),str(path),*options],ok=False)

def snapshot(cfg):
 code='''import json,psycopg\nfrom psycopg.rows import dict_row\nfrom psycopg import sql\nwith psycopg.connect('postgresql://homelab:homelab@postgres:5432/homelab',row_factory=dict_row) as c:\n objs=c.execute("select c.relname,c.relkind from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='reporting' order by 1,2").fetchall()\n tables={}\n for o in objs:\n  if o['relkind'] in ('r','p','v','m','f'):\n   rows=c.execute(sql.SQL('select * from reporting.{}').format(sql.Identifier(o['relname']))).fetchall()\n   tables[o['relname']]=sorted(json.dumps(r,sort_keys=True,default=str) for r in rows)\n print(json.dumps({'objects':objs,'rows':tables},sort_keys=True))\n'''
 return json.loads(call(['docker','exec',cfg['api_id'],'python','-c',code]).stdout)

def demand_guard(path,*options):
 p=guard(path,*options)
 if p.returncode: raise ValueError('preflight refused: '+p.stderr.strip())
 return json.loads(p.stdout)

def wrong_image_falsifier(path,cfg):
 demand_guard(path)
 before=snapshot(cfg)
 bad=dict(cfg); bad['api_image']='sha256:'+('0'*64 if cfg['api_image']!='sha256:'+'0'*64 else '1'*64)
 fd,name=tempfile.mkstemp(prefix='hla-wrong-image-',suffix='.json',dir='/tmp')
 try:
  with os.fdopen(fd,'w') as f: json.dump(bad,f)
  refused=guard(name)
 finally: os.unlink(name)
 if refused.returncode==0 or 'API image identity mismatch' not in refused.stderr: raise ValueError('wrong-image falsifier did not refuse at intended guard')
 after=snapshot(cfg)
 if before!=after: raise ValueError('schema changed during wrong-image falsifier')
 return {'wrong_image_refused':True,'before':before,'after':after}

def verify_unchanged(cfg, before):
 after=snapshot(cfg)
 if before!=after: raise ValueError('schema or data changed during verification')
 return after

def main():
 global DIAGNOSTICS
 DIAGNOSTICS=pathlib.Path(tempfile.mkdtemp(prefix='hla-source-diagnostics-',dir='/tmp'))
 print('Restricted diagnostics: '+str(DIAGNOSTICS),file=sys.stderr,flush=True)
 p=argparse.ArgumentParser(); p.add_argument('mode',choices=['preflight','falsify-image','run']); p.add_argument('config'); args=p.parse_args()
 config=pathlib.Path(args.config).resolve(); cfg=json.loads(config.read_text())
 assert re.fullmatch(r'train-[a-zA-Z0-9-]+',cfg['train_id'])
 assert cfg['no_concurrent_operator_writes'] is True
 if args.mode=='preflight': print(json.dumps(demand_guard(config),indent=2)); return
 if args.mode=='falsify-image': print(json.dumps(wrong_image_falsifier(config,cfg),indent=2)); return
 pre=demand_guard(config); falsifier=wrong_image_falsifier(config,cfg)
 # A persistent per-container marker is created before any writes and is never
 # deleted by this harness; even an empty-schema failure must not be retried.
 attempt=pathlib.Path('/tmp')/('hla-source-attempt-'+cfg['api_id'])
 attempt.mkdir(mode=0o700)
 print('Attempt evidence: '+str(attempt),file=sys.stderr,flush=True)
 (attempt/'preflight.json').write_text(json.dumps(pre,indent=2))
 (attempt/'wrong-image.json').write_text(json.dumps(falsifier,indent=2))
 token=uuid.uuid4().hex; staging='/tmp/hla-source-harness-'+token; root='/tmp/hla-source-qualification-'+token
 helper=HERE/'seed.py'
 # Only the owned container is written. Never alter environment or recreate it.
 call(['docker','exec',cfg['api_id'],'mkdir',staging])
 for src,name in ((helper,'seed.py'),(HERE/'inside_publish.py','publish.py'),(HERE/'inside_verify.py','verify.py'),(HERE/'http_verify.py','http_verify.py')):
  call(['docker','cp',str(src),cfg['api_id']+':'+staging+'/'+name])
 seed=call(['docker','exec',cfg['api_id'],'python',staging+'/seed.py','--root',root,'--source-commit',cfg['sha']]); (attempt/'seed.json').write_text(seed.stdout)
 demand_guard(config) # repeat immediately before publication
 # On any error leave marker, schema, and container untouched for investigation.
 published=call(['docker','exec',cfg['api_id'],'python',staging+'/publish.py',root,staging+'/seed.py']); (attempt/'publication.json').write_text(published.stdout)
 before=snapshot(cfg); (attempt/'published-before-http.json').write_text(json.dumps(before,indent=2))
 if not before['objects']: raise ValueError('publication left empty schema')
 refused=guard(config)
 if refused.returncode==0 or 'reporting namespace is nonempty' not in refused.stderr: raise ValueError('nonempty falsifier did not refuse at intended guard')
 after=snapshot(cfg)
 if before!=after: raise ValueError('nonempty preflight changed schema or rows')
 (attempt/'nonempty-falsifier.json').write_text(json.dumps({'refused':True,'unchanged':True},indent=2))
 post=demand_guard(config,'--allow-nonempty')
 for k in ('project','sha','api_id','pg_id','api_image','network_id','volume'):
  if pre[k]!=post[k]: raise ValueError('identity changed: '+k)
 try:
  verified=call(['docker','exec',cfg['api_id'],'python',staging+'/verify.py']); (attempt/'verification.json').write_text(verified.stdout)
 finally:
  final=verify_unchanged(cfg,after); (attempt/'published-after-http.json').write_text(json.dumps(final,indent=2))
 (attempt/'complete.json').write_text(json.dumps({'result':'pass','context':post,'staging':staging,'synthetic_root':root,'assumption':'no concurrent operator writes'},indent=2))
 print(json.dumps({'result':'pass','observations':str(attempt),'cleanup':'Only root may remove the exact receipt-owned train resources; preserve failed attempts.'},indent=2))

if __name__=='__main__':
 try: main()
 except Exception as e: print('REFUSED OR FAILED: '+str(e),file=sys.stderr); sys.exit(1)
