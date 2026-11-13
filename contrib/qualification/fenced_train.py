"""Real-host #2889 qualification; emits observations, never credential bytes."""
import argparse
from dataclasses import replace
import errno
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time


def probe_program(paths):
    return '''import errno,json,os,pathlib,sys
rows=[]
for path in ''' + repr([str(p) for p in paths]) + ''':
    row={"path":path}
    for name,flags in (("read",os.O_RDONLY),("write",os.O_WRONLY)):
        try:
            fd=os.open(path,flags|os.O_NONBLOCK);os.close(fd);row[name]="OPENED"
        except OSError as exc:
            row[name]=errno.errorcode.get(exc.errno,str(exc.errno))
    rows.append(row)
env=[name for name in ("FJ_TOKEN","LANECTL_TEST_API_KEY","CREDENTIALS_DIRECTORY") if name in os.environ]
pathlib.Path(".lanectl-probe-writable").write_text("synthetic writable probe")
result={"rows":rows,"inherited_secret_names":env,"checkout_writable":True,"root_uid":os.stat("/").st_uid,"nix_uid":os.stat("/nix").st_uid,"uid":os.getuid()}
print("LANECTL_FENCE_PROBE_V1="+json.dumps(result,sort_keys=True),flush=True)
sys.exit(int(bool(env) or any(r[k]=="OPENED" for r in rows for k in ("read","write"))))
'''


def extract(stdout):
    for line in stdout.splitlines():
        if line.startswith('LANECTL_FENCE_PROBE_V1='):
            return json.loads(line.partition('=')[2])
    raise RuntimeError('probe did not emit its complete observation')


def probes(repo):
    from lanectl import runner
    with (tempfile.TemporaryDirectory(prefix='lanectl-fence-home-', dir=Path.home()/'.cache') as home,
          tempfile.TemporaryDirectory(prefix='lanectl-fence-project-', dir='/projects/dev') as project):
        h = Path(home)
        names = ['.config/vuoro/credentials/runner', '.config/forgejo/token',
                 '.local/share/forgejo-cli/keys.json', '.local/share/opencode/auth.json',
                 '.codex/auth.json', '.claude/.credentials.json', '.ssh/key',
                 'runtime/credentials/runner', '.local/state/lanectl/synthetic-state']
        paths = [h/name for name in names]
        separate = Path(project)/'other-repo-marker'
        paths.append(separate)
        for path in paths:
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text('SYNTHETIC-NOT-A-CREDENTIAL')
        Path(project).chmod(0o755)
        separate.chmod(0o666)
        # Existing public canonical/governance inputs: open and close only.
        paths += [Path(repo.path)/'pyproject.toml',
                  Path(__import__('lanectl.config',fromlist=['home']).home())/'governance/repos.toml']
        program = probe_program(paths)
        env = dict(os.environ, FJ_TOKEN='synthetic-only', LANECTL_TEST_API_KEY='synthetic-only',
                   CREDENTIALS_DIRECTORY=str(h/'runtime/credentials'))
        outside = subprocess.run([sys.executable,'-c',program],cwd=project,env=env,
                                 capture_output=True,text=True,timeout=30)
        control = extract(outside.stdout)
        assert outside.returncode == 1 and control['inherited_secret_names']
        assert all(row['read']=='OPENED' and row['write']=='OPENED' for row in control['rows'])
        prior = {name:os.environ.get(name) for name in ('FJ_TOKEN','LANECTL_TEST_API_KEY','CREDENTIALS_DIRECTORY')}
        try:
            for name in prior:
                os.environ[name]=env[name]
            inside = runner._train_command(replace(repo,setup_cmd='',train_isolation='systemd'),
                Path(repo.path), shlex.join(['/run/current-system/sw/bin/python3','-c',program]))
        finally:
            for name,value in prior.items():
                if value is None:os.environ.pop(name,None)
                else:os.environ[name]=value
        if inside.returncode:
            raise RuntimeError('fenced probe failed: '+inside.stderr+'\n'+inside.stdout[-4000:])
        observed=extract(inside.stdout)
        assert not observed['inherited_secret_names'] and observed['checkout_writable']
        assert observed['root_uid']==observed['nix_uid']==0 and observed['uid']==1120
        assert all(row[k]!='OPENED' for row in observed['rows'] for k in ('read','write'))
        return {'outside_control_exit':outside.returncode,'outside_control':control,'fenced_exit':inside.returncode,'fenced':observed}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',default='sovite')
    parser.add_argument('--mode',choices=['probes','commands'],required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    from lanectl import runner
    from lanectl.config import load_repos
    repo=load_repos()[args.repo]
    start=time.monotonic()
    if args.mode=='probes':
        result=probes(repo)
    else:
        result={}
        repo=replace(repo,train_isolation='systemd')
        for phase,command in [('setup',repo.setup_cmd),('check',repo.check_cmd)]:
            if not command:continue
            completed=runner._train_command(repo,Path(repo.path),command)
            result[phase]={'command':command,'returncode':completed.returncode,
                           'stdout':completed.stdout,'stderr':completed.stderr}
            if completed.returncode:break
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps({'repo':args.repo,'mode':args.mode,'elapsed_s':round(time.monotonic()-start,2),'result':result},indent=2)+'\n')
    if args.mode=='commands':return int(any(v['returncode'] for v in result.values()))
    return 0


if __name__=='__main__':raise SystemExit(main())
