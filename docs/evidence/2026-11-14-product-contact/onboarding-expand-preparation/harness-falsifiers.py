import importlib.util, pathlib, subprocess, sys, tempfile, time
p=pathlib.Path('/tmp/hla-onboarding-acceptance-draft-20261114/base/tests/test_onboarding_expand_acceptance.py');spec=importlib.util.spec_from_file_location('acceptance',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
out=pathlib.Path('/tmp/hla-onboarding-acceptance-draft-20261114/falsifiers');out.mkdir(exist_ok=True)
# A leader which exits while a child remains in its process group.
proc=subprocess.Popen([sys.executable,'-c','import subprocess,sys; subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]); print("spawned",flush=True)'],stdout=subprocess.PIPE,text=True,start_new_session=True);proc.wait();assert proc.stdout.readline().strip()=='spawned'
try: m.stop(proc)
except AssertionError as e: (out/'lingering.log').write_text('guard rejected lingering group: '+str(e)+'\n');raise
(out/'lingering.log').write_text('leader exited; owned lingering group stopped and absence verified\n')
with (out/'timeout.stdout').open('w') as stdout,(out/'timeout.stderr').open('w') as stderr:
 proc=subprocess.Popen([sys.executable,'-c','import time; print("partial marker",flush=True);time.sleep(60)'],stdout=stdout,stderr=stderr,start_new_session=True)
 try:proc.wait(timeout=.5);raise AssertionError('timeout did not fail')
 except subprocess.TimeoutExpired:(out/'timeout.log').write_text('expected timeout detected\n')
 finally:m.stop(proc)
assert 'partial marker' in (out/'timeout.stdout').read_text()
before=m.snapshot();file=m.ROOT/'README.md';data=file.read_bytes()
try:
 file.write_bytes(data+b'\nqualification falsifier\n');after=m.snapshot();assert after!=before
 (out/'invariance.log').write_text('tracked mutation detected\n')
finally:file.write_bytes(data)
assert m.snapshot()==before
print('all forced failure controls observed')
