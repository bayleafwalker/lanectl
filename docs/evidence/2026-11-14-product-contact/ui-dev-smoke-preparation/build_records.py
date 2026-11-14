"""Validate captured Docker build observations, independently of labels."""
import re
from pathlib import Path
from datetime import datetime, timedelta, timezone

def validate(records, cfg, current_digest):
 if len(records)!=2: raise ValueError('exactly two observed builds required')
 result={}
 for rec in records:
  a=rec.get('argv',[])
  for service,df,tag in [('api','infra/docker/Dockerfile','homelab-analytics:'),('web','infra/docker/web.Dockerfile','homelab-analytics-web:')]:
   expected=['build','-q','-f',df,'-t',tag+cfg['project'],'--label','lanectl.namespace='+cfg['project'],'.']
   if a!=expected: continue
   if service in result: raise ValueError('duplicate build')
   if rec.get('cwd')!=str(Path(cfg['source_path']).resolve()): raise ValueError('wrong build cwd')
   if rec.get('exit_code')!=0: raise ValueError('build failed')
   if 'built_ts' in cfg:
    try:
     parse=lambda x: datetime.fromisoformat(x.replace('Z','+00:00')).astimezone(timezone.utc)
     start,end=parse(rec['started_at']),parse(rec['finished_at'])
     if not parse(cfg['built_ts']) <= start <= end < parse(cfg['deploy_ts'])+timedelta(seconds=1): raise ValueError('build observation outside receipt window')
    except (KeyError,TypeError,AttributeError): raise ValueError('missing build timestamp') from None
   if not current_digest or rec.get('context_before')!=current_digest or rec.get('context_after')!=current_digest: raise ValueError('build context changed')
   image=rec.get('stdout','').strip()
   if not re.fullmatch(r'sha256:[0-9a-f]{64}',image): raise ValueError('invalid build image output')
   result[service]=image
   break
  else: raise ValueError('unexpected build command')
 if set(result)!={'api','web'}: raise ValueError('missing build')
 return result
