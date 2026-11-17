"""Exercise receipt validation with synthetic candidates and real pytest results."""
import os, pathlib, shutil, subprocess, tempfile, sys
source = pathlib.Path(__file__).resolve().parent
if len(sys.argv) != 2 or not pathlib.Path(sys.argv[1]).is_absolute():
    sys.exit('Usage: python test-qualification-runner.py /absolute/path/to/python-with-pytest')
python = sys.argv[1]
with tempfile.TemporaryDirectory(prefix='backup-harness-controls-') as d:
    root = pathlib.Path(d)
    candidate = root/'candidate'; candidate.mkdir()
    subprocess.run(['git','init','-q',str(candidate)],check=True)
    subprocess.run(['git','-C',str(candidate),'config','user.email','test@example.invalid'],check=True)
    subprocess.run(['git','-C',str(candidate),'config','user.name','Acceptance control'],check=True)
    p=candidate/'packages/storage/postgres_reporting.py'; p.parent.mkdir(parents=True); p.write_text('# synthetic candidate\n')
    subprocess.run(['git','-C',str(candidate),'add','.'],check=True)
    subprocess.run(['git','-C',str(candidate),'commit','-qm','fixture'],check=True)
    venv=candidate/'.venv/bin'; venv.mkdir(parents=True)
    (candidate/'.git/info/exclude').write_text('.venv\n')
    p=venv/'python'; p.write_text('#!/bin/sh\necho 170010\n'); p.chmod(0o755)
    criterion=root/'criterion'; shutil.copytree(source,criterion,ignore=shutil.ignore_patterns('__pycache__'))
    testdir=criterion/'files/tests'
    (testdir/'backup_published_qualification.py').write_text('import os, pytest\n@pytest.mark.skipif(os.environ.get("CONTROL_SKIP") == "1", reason="skip control")\ndef test_published_backups_survive_warehouse_clear_and_do_not_fallback():\n    pass\n')
    make=root/'fake-make'
    make.write_text('#!/bin/sh\nargs="$2"\njunit="${args##*--junitxml=}"\n'+python+' -m pytest -q -p no:cacheprovider "'+str(testdir/'backup_published_qualification.py')+'" "--junitxml=$junit"\nresult=$?\nif [ "$CONTROL_MUTATE" = 1 ]; then printf "\\n# mutation\\n" >> "'+str(testdir/'test_acc_observed_backup_visibility.py')+'"; fi\nexit "$result"\n')
    make.chmod(0o755)
    for name, extra, expected in [('pass',{},0),('collect',{'PYTEST_ADDOPTS':'--collect-only'},1),('skip',{'CONTROL_SKIP':'1'},1),('changed',{'CONTROL_MUTATE':'1'},1)]:
        receipt=root/(name+'.json')
        env=os.environ.copy(); env.pop('PYTEST_ADDOPTS',None); env.update({'BACKUP_ACCEPTANCE_POSTGRES_DSN':'synthetic-only','BACKUP_ACCEPTANCE_MAKE':str(make),**extra})
        run=subprocess.run(['python',str(criterion/'qualify-published.py'),str(receipt)],cwd=candidate,env=env,text=True,capture_output=True)
        print(name,'exit=',run.returncode,'receipt=',receipt.exists(),'message=',(run.stdout+run.stderr).strip().splitlines()[-1])
        assert (run.returncode == 0)==(expected==0)
        assert receipt.exists()==(expected==0)
