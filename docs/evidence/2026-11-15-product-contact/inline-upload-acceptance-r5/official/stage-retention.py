from pathlib import Path
import hashlib,json,os,shutil,stat,subprocess
repo=Path('/projects/dev/homelab-analytics')
base='b2d0fe393ac0971e906cce275e91f45e94422593'
listing=subprocess.check_output(['git','-C',str(repo),'ls-tree','-r','-z',base])
tracked={}
for item in listing.split(b'\0'):
 if item:
  meta,name=item.split(b'\t',1);mode,kind,oid=meta.decode().split()
  if kind=='blob':tracked[name.decode()]={'mode':mode,'blob':oid}
stage=Path('/tmp/hla-inline-upload-r5-retention-stage');stage.mkdir()
kept={};omitted={};special={}
for revision in (3,4,5):
 root=Path(f'/tmp/hla-inline-upload-acceptance-r{revision}-20261115')
 for p in sorted(root.rglob('*')):
  rel=p.relative_to(root);name=f'r{revision}/{rel}'
  meta=p.lstat()
  if stat.S_ISDIR(meta.st_mode):continue
  if not stat.S_ISREG(meta.st_mode):
   special[name]={'mode':stat.S_IMODE(meta.st_mode),'link':os.readlink(p) if p.is_symlink() else None}
   continue
  data=p.read_bytes();digest=hashlib.sha256(data).hexdigest()
  entry={'bytes':len(data),'sha256':digest}
  if '__pycache__' in rel.parts or '.pytest_cache' in rel.parts or p.suffix=='.pyc':
   omitted[name]=dict(entry,reason='Generated Python/pytest cache; not acceptance source or raw execution evidence')
   continue
  original=None
  if rel.parts and rel.parts[0]=='source':original='/'.join(rel.parts[1:])
  elif 'frontend' in rel.parts:
   index=rel.parts.index('frontend');original='apps/web/frontend/'+'/'.join(rel.parts[index+1:])
  blob=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
  if original in tracked and blob==tracked[original]['blob']:
   omitted[name]=dict(entry,reason='Exact canonical Git source bytes, reconstructible from fixed base',base=base,git_path=original,git_blob=blob)
   continue
  target=stage/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
  kept[name]=entry
inventory={'included':kept,'omitted_reconstructible_or_cache':omitted,'nonregular_metadata_only':special,'base':base,'exclusion_rule':'Only exact canonical Git-byte matches or generated Python/pytest caches; all other regular files retained.'}
(stage/'RETENTION-INVENTORY.json').write_text(json.dumps(inventory,indent=2)+'\n')
print(json.dumps({'retained_files':len(kept),'retained_bytes':sum(x['bytes'] for x in kept.values()),'omitted_files':len(omitted),'nonregular':len(special),'stage':str(stage)}),flush=True)
