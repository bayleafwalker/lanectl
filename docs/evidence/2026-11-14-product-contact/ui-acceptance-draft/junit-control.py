import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
p=Path('/tmp/hla-attention-ui-spec/files/tests/test_attention_current_ui_acceptance.py')
s=importlib.util.spec_from_file_location('acceptance',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
names=sorted(m.EXPECTED_CASES)
def case(name,inner=''): return f'<testcase classname="tests.test_attention_current_ui_acceptance" name="{name}">{inner}</testcase>'
def report(body,tests=9,skipped=0,failures=0,errors=0): return f'<testsuites><testsuite tests="{tests}" skipped="{skipped}" failures="{failures}" errors="{errors}">{body}</testsuite></testsuites>'
valid=''.join(map(case,names)); tests={'valid':report(valid),'zero':report('',tests=0),'incomplete':report(''.join(map(case,names[:-1])),tests=8),'skipped':report(case(names[0],'<skipped/>')+''.join(map(case,names[1:])),skipped=1),'failure':report(case(names[0],'<failure/>')+''.join(map(case,names[1:])),failures=1),'error':report(case(names[0],'<error/>')+''.join(map(case,names[1:])),errors=1),'duplicate':report(case(names[0])*2+''.join(map(case,names[2:]))),'wrong-module':report(valid.replace('tests.test_attention_current_ui_acceptance','wrong.module',1)),'summary-mismatch':report(valid,tests=8),'malformed':'<testsuites>', 'missing-count':report(valid).replace(' errors="0"','')}
with TemporaryDirectory() as td:
 path=Path(td)/'report.xml'
 for name,content in tests.items():
  path.write_text(content)
  try: m.validate_report(path); ok=True
  except Exception: ok=False
  assert ok == (name=='valid'),name
  print(name, 'accepted' if ok else 'rejected')
 path.unlink()
 try: m.validate_report(path)
 except FileNotFoundError: print('missing rejected')
 else: raise AssertionError('missing accepted')
