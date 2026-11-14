import json, os, pathlib, subprocess, sys, tempfile, unittest
HERE=pathlib.Path(__file__).parent
class ObserverTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=HERE);self.root=pathlib.Path(self.tmp.name);self.src=self.root/'source';self.src.mkdir();(self.src/'file').write_text('input');self.log=self.root/'log';self.log.mkdir();self.fake=self.root/'docker'
  self.fake.write_text('#!/usr/bin/env python3\nimport json,os,sys\nprint(json.dumps({"args":sys.argv[1:],"cwd":os.getcwd()}))\nprint("fake stderr",file=sys.stderr)\nsys.exit(7 if "fail" in sys.argv else 0)\n');self.fake.chmod(0o755)
 def tearDown(self):self.tmp.cleanup()
 def run_observer(self,*args,log=None):
  return subprocess.run([sys.executable,str(HERE/'docker_observe.py'),str(self.fake),str(log or self.log),str(self.src),*args],cwd=self.src,text=True,capture_output=True)
 def test_success_and_arg_cwd_stream(self):
  p=self.run_observer('build','-q','--flag=x y','.');self.assertEqual(p.returncode,0);data=json.loads(p.stdout);self.assertEqual(data,{'args':['build','-q','--flag=x y','.'],'cwd':str(self.src)});self.assertEqual(p.stderr,'fake stderr\n');record=json.loads(next(self.log.iterdir()).read_text());self.assertEqual(record['argv'],data['args']);self.assertEqual(record['context_before'],record['context_after']);self.assertEqual(record['stdout'],p.stdout)
 def test_nonzero_preserved(self):
  p=self.run_observer('build','fail');self.assertEqual(p.returncode,7);self.assertEqual(json.loads(next(self.log.iterdir()).read_text())['exit_code'],7)
 def test_record_failure_preserves_exit_but_no_evidence(self):
  p=self.run_observer('build','x',log=self.root/'absent');self.assertEqual(p.returncode,0);self.assertIn('could not record',p.stderr);self.assertEqual(list(self.log.iterdir()),[])
 def test_changed_context_digest(self):
  sys.path.insert(0,str(HERE));from docker_observe import context_digest
  a=context_digest(self.src);(self.src/'untracked').write_text('new');self.assertNotEqual(a,context_digest(self.src))
 def test_other_docker_passthrough(self):
  p=self.run_observer('ps','--quiet');self.assertEqual(p.returncode,0);self.assertEqual(json.loads(p.stdout)['args'],['ps','--quiet']);self.assertEqual(list(self.log.iterdir()),[])
 def test_wrong_working_directory_refused(self):
  p=subprocess.run([sys.executable,str(HERE/'docker_observe.py'),str(self.fake),str(self.log),str(self.src),'build','.'],cwd=self.root,text=True,capture_output=True);self.assertEqual(p.returncode,125)
if __name__=='__main__':unittest.main()
