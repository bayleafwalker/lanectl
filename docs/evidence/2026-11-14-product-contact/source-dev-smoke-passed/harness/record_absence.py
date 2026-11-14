#!/usr/bin/env python3
"""Record an actual Docker volume-list observation before any train deploy."""
import argparse, datetime, json, os, pathlib, re, subprocess
p=argparse.ArgumentParser()
for key in ('project','train-id','sha','source-path','volume','output'): p.add_argument('--'+key,required=True)
a=p.parse_args()
if a.project!='lane-dev-'+a.train_id or not re.fullmatch(r'[0-9a-f]{40}',a.sha): p.error('invalid project/train/SHA')
if not pathlib.Path(a.output).is_absolute() or not pathlib.Path(a.output).is_relative_to('/tmp'): p.error('output must be an absolute /tmp path')
info=subprocess.run(['docker','info','--format','{{.ID}}'],text=True,capture_output=True,check=True).stdout.strip()
proc=subprocess.run(['docker','volume','ls','--format','{{.Name}}'],text=True,capture_output=True,check=True)
observed=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
names=proc.stdout.splitlines()
if not info or a.volume in names: raise SystemExit('REFUSED: Docker server unknown or volume already exists')
proof={'schema':'hla-volume-absence/v1','project':a.project,'train_id':a.train_id,'sha':a.sha,'source_path':a.source_path,'volume':a.volume,'docker_server_id':info,'command':'docker volume ls --format {{.Name}}','exit_code':proc.returncode,'volume_names':names,'observed_at':observed}
fd=os.open(a.output,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
with os.fdopen(fd,'w') as f: json.dump(proof,f,indent=2); f.write('\n')
print('Recorded predeploy absence proof:',a.output)
