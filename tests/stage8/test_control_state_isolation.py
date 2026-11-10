"""The actual native tool namespace cannot rewrite its coordinator's state."""
from pathlib import Path
import os
import shlex
import subprocess

from lanectl import adapters, runner
from lanectl.adapters import AdapterResult
from lanectl.events import state_dir, project_items


def test_worker_cannot_overwrite_log_or_journal_but_can_write_attempt(estate,tmp_path,monkeypatch):
    _,release,log=estate
    release('state-proof','from calc import sub\n\ndef test_sub():\n    assert sub(5,3)==2\n')
    journal=state_dir()/'coordination.sqlite';journal.write_text('coordinator-journal\n')
    native=tmp_path/'native-bin';native.mkdir()
    tool=native/'claude'
    tool.write_text('#!/bin/sh\n'+
        f'if (printf corrupt > {shlex.quote(str(log.path))}) 2>/dev/null; then echo LOG_LEAK; else echo LOG_BLOCKED; fi\n'+
        f'if (printf corrupt > {shlex.quote(str(journal))}) 2>/dev/null; then echo JOURNAL_LEAK; else echo JOURNAL_BLOCKED; fi\n'+
        'printf %s '+shlex.quote('def add(a,b):\n    return a+b\n\ndef sub(a,b):\n    return a-b\n')+' > src/calc.py\n'+
        'printf %s '+shlex.quote('from calc import sub\n\ndef test_negative():\n    assert sub(1,2)==-1\n')+' > tests/test_extra.py\n'+
        'echo ATTEMPT_WRITTEN\n')
    tool.chmod(0o755)
    monkeypatch.setenv('PATH',str(native)+os.pathsep+os.environ['PATH'])
    def probe(*,worktree,env,**kwargs):
        shim=Path(env['PATH'].split(os.pathsep)[0])/'claude'
        p=subprocess.run([str(shim)],cwd=worktree,env=env,capture_output=True,text=True)
        assert p.returncode==0,p.stderr
        assert p.stdout.split()==['LOG_BLOCKED','JOURNAL_BLOCKED','ATTEMPT_WRITTEN'],p.stdout
        return AdapterResult('done',0,'isolated',None)
    monkeypatch.setitem(adapters.ADAPTERS,'scripted',probe)
    out=runner.execute(runner.admit('implement',log),log)
    assert 'candidate' in out,out
    assert project_items(log.read())['state-proof'].state=='candidate'
    assert journal.read_text()=='coordinator-journal\n'
    log.append('usage.recorded',{'provider':'test','source':'coordinator','units':{}})
    assert log.read()[-1]['data']['source']=='coordinator'
