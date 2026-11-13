"""Actual service lifecycle qualification in an isolated synthetic repository."""
from dataclasses import replace
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import tempfile
import threading
from unittest.mock import patch

from lanectl import fenced_train as ft, runner
from lanectl.config import RepoSpec
from lanectl.events import EventLog


def main():
    results = {}
    with tempfile.TemporaryDirectory(prefix='lanectl-fence-lifecycle-', dir=Path.home()/'.cache') as folder:
        lab = Path(folder)
        canonical = lab/'canonical'
        canonical.mkdir()
        secret = lab/'synthetic-secret'
        secret.write_text('SYNTHETIC-NOT-A-CREDENTIAL')
        code = '''import os,pathlib,sys
assert os.getuid()==1120
assert os.stat('/').st_uid==os.stat('/nix').st_uid==0
assert not any(k in os.environ for k in ('FJ_TOKEN','LANECTL_TEST_API_KEY','CREDENTIALS_DIRECTORY'))
for path in ''' + repr([str(secret), str(lab/'state/events.jsonl'), '/projects/dev/lanectl/governance/repos.toml']) + ''':
    for flags in (os.O_RDONLY,os.O_WRONLY):
        try: fd=os.open(path,flags|os.O_NONBLOCK)
        except OSError: pass
        else:
            os.close(fd)
            raise AssertionError('boundary opened '+path)
pathlib.Path('.probe-writable').write_text('synthetic')
print('LIFECYCLE_BOUNDARY_OK '+sys.argv[1],flush=True)
'''
        (canonical/'probe.py').write_text(code)
        (canonical/'value.txt').write_text('base\n')
        def git(*args):
            return subprocess.check_output(['git','-C',str(canonical),'-c','user.name=qualification','-c','user.email=qualification@localhost',*args],text=True).strip()
        git('init','-q','-b','main')
        git('add','.')
        git('commit','-qm','synthetic qualification base')
        git('checkout','-qb','lane/proof-a1')
        (canonical/'value.txt').write_text('candidate\n')
        git('add','.')
        git('commit','-qm','synthetic qualification candidate')
        git('checkout','-q','main')
        repo = RepoSpec(name='qualification',path=canonical,main='main',
                        test_cmd='python3 probe.py test',check_cmd='test -f .setup-complete && python3 probe.py check',
                        worktree_root=lab/'wt',setup_cmd='python3 probe.py setup && touch .setup-complete',
                        train_isolation='systemd')
        log = EventLog(lab/'state/events.jsonl')
        candidate = {'attempt_id':'proof-a1','branch':'lane/proof-a1','title':'synthetic lifecycle qualification'}
        # Config/candidate inputs are synthetic; production train functions,
        # the command boundary, systemd, root receipts and cleanup are real.
        with patch.object(runner,'load_repos',return_value={'qualification':repo}), patch.object(runner,'load_releases',return_value=[]), patch.object(runner,'candidates',return_value=[candidate]):
            output = runner.build_train(log,'qualification')
            assert ': PASSED ' in output, output
            built = [e['data'] for e in log.read() if e['type']=='train.built'][-1]
            assert 'LIFECYCLE_BOUNDARY_OK check' in built['check_tail']
            results['build_train'] = {'passed':True,'checked_sha':built['checked_sha']}
            output = runner.recheck_train(log,built['train_id'])
            assert ': PASSED ' in output,output
            results['recheck'] = {'passed':True}
            # Historical recovery after an already-canonical train and lost
            # worktree. No synthetic attempt is claimed or settled in Work.
            git('merge','--ff-only','-q','train/'+built['train_id'])
            runner._discard(repo,Path(built['worktree']))
            historical = dict(built,attempts=[],checked_sha=None)
            log.append('train.built',historical)
            output = runner.land(log,built['train_id'])
            assert output.startswith('landed []'),output
            latest = [e['data'] for e in log.read() if e['type']=='train.built'][-1]
            assert latest['checked_sha']==git('rev-parse','main')
            results['historical_land'] = {'passed':True,'checked_sha':latest['checked_sha']}
        # Real root-owned timeout, including receipt and ownership handback.
        timeout = ft.run_command(replace(repo,setup_cmd=''),canonical,'python3 -c '+shlex.quote('import time; time.sleep(120)'),timeout_s=1)
        assert timeout.returncode!=0,timeout
        results['host_timeout'] = {'returncode':timeout.returncode,'stderr':timeout.stderr}
        original_start, original_stop = ft._start, ft._stop_terminal
        for lose_stop in (False,True):
            observed = {}
            timers=[]
            def start(tool,unit):
                original_start(tool,unit)
                observed['unit']=unit
                timer=threading.Timer(0.5,lambda:os.kill(os.getpid(),signal.SIGINT))
                timers.append(timer)
                timer.start()
            def stop(tool,unit):
                observed['stop_calls']=observed.get('stop_calls',0)+1
                result=False if lose_stop else original_stop(tool,unit)
                observed['stop_acknowledged']=result
                return result
            try:
                with patch.object(ft,'_start',side_effect=start),patch.object(ft,'_stop_terminal',side_effect=stop):
                    try:
                        ft.run_command(replace(repo,setup_cmd=''),canonical,'python3 -c '+shlex.quote('import time; time.sleep(120)'),timeout_s=180)
                    except KeyboardInterrupt as exc:
                        observed['interrupted']=True
                        observed['named_orphan']='orphan' in str(exc)
                    else:
                        raise AssertionError('interrupt was not observed')
            finally:
                for timer in timers:
                    timer.cancel()
                    timer.join()
            unit=observed['unit']
            tid=unit.split('@',1)[1].removesuffix('.service')
            directory=ft.TRAIN_ROOT/tid
            assert observed['stop_calls']==1
            if lose_stop:
                assert observed['named_orphan'] and directory.exists()
                assert original_stop('systemctl',unit), 'manual recovery could not prove stop'
                ft._remove(directory)
                observed['manual_recovery_after_ack']=True
            else:
                assert observed['stop_acknowledged'] and not directory.exists()
                assert ft._active('systemctl',unit) in ft.TERMINAL
            results['injected_stop_loss' if lose_stop else 'keyboard_interrupt']=observed
        results['canonical_preserved'] = canonical.is_dir() and git('rev-parse','main')==latest['checked_sha']
        assert results['canonical_preserved']
    Path('/tmp/lanectl-fence-lifecycle-v025.json').write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps(results),flush=True)


if __name__=='__main__':
    main()
