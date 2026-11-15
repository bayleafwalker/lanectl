from pathlib import Path
from unittest.mock import patch
from contextlib import ExitStack
import hashlib,importlib.util,json,subprocess,tempfile
root=Path('/projects/dev/_wt/hla1597-unit-20261115');path=root/'tests/test_onboarding_auto_collapse_unit.py'
before=hashlib.sha256(path.read_bytes()).hexdigest()
spec=importlib.util.spec_from_file_location('hla1597_wrapper_under_test',path);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
node='/projects/dev/homelab-analytics/.tooling/node-v20.20.1-linux-x64/bin/node'
results=[]
def rejected(label,configure,expected):
 with ExitStack() as stack:
  configure(stack)
  try:mod.test_onboarding_checklist_auto_collapses_when_core_sources_active()
  except BaseException as e:
   assert expected in str(e),(label,type(e).__name__,str(e))
   results.append({'guard':label,'raised':type(e).__name__,'message':str(e),'expected_failure':True})
  else:raise AssertionError(label+' did not reject')
rejected('missing-node',lambda s:s.enter_context(patch.object(mod.shutil,'which',return_value=None)),'node is required on PATH')
with tempfile.TemporaryDirectory(prefix='hla1597-missing-deps-') as tmp:
 def missing(s):
  s.enter_context(patch.object(mod.shutil,'which',return_value=node));s.enter_context(patch.object(mod,'FRONTEND',Path(tmp)))
 rejected('missing-dependency',missing,'missing frontend dependency esbuild')
def timeout(s):
 s.enter_context(patch.object(mod.shutil,'which',return_value=node))
 def run(*a,**kw):
  assert kw['timeout']==120
  raise subprocess.TimeoutExpired(a[0],kw['timeout'])
 s.enter_context(patch.object(mod.subprocess,'run',side_effect=run))
rejected('timeout',timeout,'timed out after 120s')
def nonzero(s):
 s.enter_context(patch.object(mod.shutil,'which',return_value=node))
 s.enter_context(patch.object(mod.subprocess,'run',return_value=subprocess.CompletedProcess(['synthetic'],7,'guard-stdout','guard-stderr')))
rejected('node-nonzero',nonzero,'guard-stdoutguard-stderr')
assert len(results)==4 and hashlib.sha256(path.read_bytes()).hexdigest()==before
print(json.dumps({'head':'57a7785c17ae76ba2169ca6af5bd4af62564a188','wrapper_sha256':before,'guards':results,'source_unchanged':True},indent=2))
