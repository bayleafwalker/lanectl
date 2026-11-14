import os,pathlib,shlex,subprocess,json
from lanectl import runner
from lanectl.config import RepoSpec
r=pathlib.Path('/tmp/lanectl-oneshot-prototype-20261114'); os.environ['LANECTL_HOME']=str(r/'home'); os.environ['LANECTL_STATE']=str(r/'state'); p=RepoSpec('synthetic',r/'canonical','main','','',r/'repo',train_isolation='namespace'); orig=runner.sandboxing.for_train
unit='lanectl-audit-oneshot-missing-20261114.service'
class Prototype:
 def __init__(self,s): self.s=s
 def wrap_shell(self,cmd,cwd):
  a=self.s.prefix(cwd); a=[v if not v.startswith('RuntimeMaxSec=') else 'TimeoutStartSec=30' for v in a]; a+=['-p','Type=oneshot','--unit='+unit,'/nonexistent/lanectl-synthetic-missing-executable']; return ' '.join(map(shlex.quote,a))
runner.sandboxing.for_train=lambda **kw:Prototype(orig(**kw))
x=runner._train_command(p,r/'repo','ignored for startup failure'); j=subprocess.run(['journalctl','--user','-u',unit,'--no-pager','-o','short-iso'],capture_output=True,text=True); (r/'startup.journal').write_text(j.stdout)
print(json.dumps({'prototype':True,'case':'missing_service_executable','unit':unit,'returncode':x.returncode,'stdout':x.stdout,'stderr':x.stderr,'journal_rc':j.returncode}))
