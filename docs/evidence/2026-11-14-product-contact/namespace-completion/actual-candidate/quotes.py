import os,pathlib,json,dataclasses,shlex
from lanectl import runner
from lanectl.config import RepoSpec
r=pathlib.Path('/tmp/lanectl-candidate-7842494-20261114'); os.environ['LANECTL_HOME']=str(r/'home'); os.environ['LANECTL_STATE']=str(r/'state'); p=RepoSpec('synthetic',r/'canonical','main','','',r/'repo',train_isolation='namespace'); orig=runner.sandboxing.for_train
runner.sandboxing.for_train=lambda **kw:dataclasses.replace(orig(**kw),unit='lanectl-audit-candidate-quotes2-7842494.service')
values=['a $b "quoted"',"second 'line'",'literal $HOME','backtick `echo unsafe`']; cmd='\n'.join('printf "%s\\n" '+shlex.quote(s) for s in values); expected=''.join(s+'\n' for s in values)
x=runner._train_command(p,r/'repo',cmd); print(json.dumps({'source':runner.__file__,'case':'exact_multiline_quotes','unit':'lanectl-audit-candidate-quotes2-7842494.service','command':cmd,'returncode':x.returncode,'stdout':x.stdout,'stderr':x.stderr,'expected':expected,'matches':x.stdout==expected}))
