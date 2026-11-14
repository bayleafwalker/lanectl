#!/usr/bin/env python3
"""PATH-scoped Docker observer: preserves output/exit; never records environment."""
import hashlib, json, os, pathlib, stat, subprocess, sys, threading, uuid
from datetime import datetime, timezone

def context_digest(root):
 root=pathlib.Path(root).resolve(); h=hashlib.sha256()
 def add(tag, value):
  b=os.fsencode(value); h.update(tag+b' '+str(len(b)).encode()+b':'+b)
 def walk(path):
  for p in sorted(path.iterdir(),key=lambda x:os.fsencode(x.name)):
   rel=p.relative_to(root).as_posix()
   if rel=='.git': continue  # excluded by the checked .dockerignore
   st=p.lstat(); mode=st.st_mode
   add(b'path',rel); add(b'mode',oct(stat.S_IMODE(mode)))
   if stat.S_ISLNK(mode): add(b'link',os.readlink(p))
   elif stat.S_ISDIR(mode): add(b'dir',''); walk(p)
   elif stat.S_ISREG(mode):
    add(b'file',str(st.st_size))
    with p.open('rb') as f:
     while True:
      data=f.read(1024*1024)
      if not data: break
      h.update(data)
    s2=p.lstat()
    if (st.st_ino,st.st_size,st.st_mtime_ns,st.st_mode)!=(s2.st_ino,s2.st_size,s2.st_mtime_ns,s2.st_mode): raise ValueError('context changed while hashing')
   else: raise ValueError('special file in context: '+rel)
 walk(root); return h.hexdigest()

def invoke(real, logdir, source, args):
 if not args or args[0]!='build': os.execv(real,[real,*args])
 # All records belong to a single private, newly created observer directory.
 log=pathlib.Path(logdir); root=pathlib.Path(source).resolve(); cwd=pathlib.Path.cwd().resolve()
 if cwd!=root: raise ValueError('unexpected build context working directory')
 before=context_digest(root)
 started=datetime.now(timezone.utc).isoformat()
 proc=subprocess.Popen([real,*args],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 streams=[bytearray(),bytearray()]
 def copy(src,dst,storage):
  while True:
   block=src.read(65536)
   if not block: break
   storage.extend(block); dst.buffer.write(block); dst.buffer.flush()
 threads=[threading.Thread(target=copy,args=(proc.stdout,sys.stdout,streams[0])),threading.Thread(target=copy,args=(proc.stderr,sys.stderr,streams[1]))]
 for t in threads:t.start()
 rc=proc.wait()
 for t in threads:t.join()
 try:
  after=context_digest(root)
  obj={'started_at':started,'finished_at':datetime.now(timezone.utc).isoformat(),'argv':args,'cwd':str(cwd),'context_before':before,'context_after':after,'exit_code':rc,'stdout':streams[0].decode('utf8','replace'),'stderr':streams[1].decode('utf8','replace')}
  path=log/('build-'+uuid.uuid4().hex+'.json')
  fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
  with os.fdopen(fd,'w') as f:
   json.dump(obj,f,sort_keys=True);f.flush();os.fsync(f.fileno())
 except Exception as e:
  # Preserve Docker's result; missing/failed evidence is always rejected later.
  print('Docker observer could not record evidence: '+str(e),file=sys.stderr)
 return rc

if __name__=='__main__':
 try: sys.exit(invoke(sys.argv[1],sys.argv[2],sys.argv[3],sys.argv[4:]))
 except Exception as e: print('Docker observer refused: '+str(e),file=sys.stderr);sys.exit(125)
