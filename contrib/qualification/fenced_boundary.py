"""Actual read/write boundary probes; never read credential bytes or truncate files."""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import secrets
import shlex
import subprocess
import sys
import tempfile

from lanectl.config import load_repos, home
from lanectl.events import state_dir
from lanectl.runner import _train_command
from lanectl.fenced_train import TRAIN_ROOT, RESULT_ROOT


def program(denied, canary, readonly, create_targets):
    return '''import errno,json,os,pathlib,sys
def attempt(path, flags, create=False):
    try:
        fd=os.open(path,flags|os.O_NONBLOCK,0o600)
    except OSError as error:
        return errno.errorcode.get(error.errno,str(error.errno))
    os.close(fd)
    if create:
        try: os.unlink(path)
        except OSError as error:
            cleanup_errors.append({"path":path,"errno":errno.errorcode.get(error.errno,str(error.errno))})
    return "OPENED"
cleanup_errors=[]
rows=[]
for path in '''+repr([str(p) for p in denied])+''':
    rows.append({"path":path,"read":attempt(path,os.O_RDONLY),"write":attempt(path,os.O_WRONLY)})
allowed=[]
for path in '''+repr([str(p) for p in readonly])+''':
    allowed.append({"path":path,"read":attempt(path,os.O_RDONLY),"write":attempt(path,os.O_WRONLY)})
creates=[{"path":path,"write":attempt(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,True)} for path in '''+repr([str(p) for p in create_targets])+''']
canary={"path":'''+repr(str(canary))+''',"read":attempt('''+repr(str(canary))+''',os.O_RDONLY)}
env=[key for key in ("FJ_TOKEN","LANECTL_TEST_API_KEY","CREDENTIALS_DIRECTORY") if key in os.environ]
pathlib.Path(".lanectl-boundary-writable").write_text("synthetic")
record={"denied":rows,"readonly":allowed,"create_denied":creates,"cleanup_errors":cleanup_errors,"public_unbound_canary":canary,"secret_env_names":env,
        "uid":os.getuid(),"root_uid":os.stat("/").st_uid,"nix_uid":os.stat("/nix").st_uid,
        "home":os.environ.get("HOME"),"checkout_writable":True}
record["ok"]=(not env and not cleanup_errors and record["uid"]==1120 and record["root_uid"]==record["nix_uid"]==0
              and all(row[key]!="OPENED" for row in rows for key in ("read","write"))
              and all(row["read"]=="OPENED" and row["write"]!="OPENED" for row in allowed)
              and all(row["write"]!="OPENED" for row in creates) and canary["read"]!="OPENED")
print("LANECTL_COMPLETE_BOUNDARY_V1="+json.dumps(record,sort_keys=True),flush=True)
sys.exit(0 if record["ok"] else 1)
'''


def extract(stdout):
    for line in stdout.splitlines():
        if line.startswith('LANECTL_COMPLETE_BOUNDARY_V1='):
            return json.loads(line.partition('=')[2])
    raise RuntimeError('complete boundary observation missing')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',default='sovite')
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    repo=replace(load_repos()[args.repo],setup_cmd='',train_isolation='systemd')
    nonce=secrets.token_hex(8)
    runtime=Path(f'/run/user/{os.getuid()}')
    canary=next((p for p in map(Path,('/etc/issue','/etc/services','/etc/protocols')) if p.is_file()),None)
    if canary is None:
        raise RuntimeError('no public host canary exists outside the declared input manifest')
    with (tempfile.TemporaryDirectory(prefix='lanectl-boundary-home-',dir=Path.home()/'.cache') as folder,
          tempfile.TemporaryDirectory(prefix='lanectl-boundary-runtime-',dir=runtime) as run,
          tempfile.TemporaryDirectory(prefix='probe-sibling-',dir=TRAIN_ROOT) as sibling):
        lab=Path(folder)
        names=['.config/vuoro/credentials/runner','.config/forgejo/token','.local/share/forgejo-cli/keys.json',
               '.local/share/opencode/auth.json','.claude/.credentials.json','.codex/auth.json','.ssh/key',
               '.local/state/lanectl/synthetic-state']
        denied=[lab/name for name in names]+[Path(run)/'synthetic-credential',Path(sibling)/'synthetic-checkout']
        for path in denied:
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text('SYNTHETIC-NOT-A-CREDENTIAL')
        Path(sibling).chmod(0o755)
        (Path(sibling)/'synthetic-checkout').chmod(0o666)
        denied += [Path(repo.path)/'pyproject.toml',home()/'governance/repos.toml',state_dir()/'events.jsonl']
        readonly=[Path('/run/current-system/sw/bin/python3').resolve(),Path('/etc/hosts')]
        creates=[Path('/nix')/('.lanectl-ro-'+nonce),Path('/etc')/('.lanectl-ro-'+nonce),RESULT_ROOT/('probe-'+nonce+'.json')]
        code=program(denied,canary,readonly,creates)
        fake={'FJ_TOKEN':'synthetic-only','LANECTL_TEST_API_KEY':'synthetic-only','CREDENTIALS_DIRECTORY':run}
        outside=subprocess.run([sys.executable,'-c',code],cwd=lab,env=dict(os.environ,**fake),capture_output=True,text=True,timeout=30)
        control=extract(outside.stdout)
        assert outside.returncode==1 and len(control['secret_env_names'])==3
        assert all(row[key]=='OPENED' for row in control['denied'] for key in ('read','write'))
        assert control['public_unbound_canary']['read']=='OPENED'
        previous={key:os.environ.get(key) for key in fake}
        try:
            os.environ.update(fake)
            inside=_train_command(repo,Path(repo.path),shlex.join(['/run/current-system/sw/bin/python3','-c',code]))
        finally:
            for key,value in previous.items():
                if value is None:os.environ.pop(key,None)
                else:os.environ[key]=value
        observed=extract(inside.stdout)
        manifest=subprocess.run(['systemctl','show','lanectl-train@qualification.service','-p','RootDirectory','-p','User'],capture_output=True,text=True,check=True).stdout
        result={'repo':repo.name,'outside_control_exit':outside.returncode,'outside_control':control,
                'inside_exit':inside.returncode,'inside':observed,'template_configuration_snapshot':manifest}
        args.output.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({'inside_exit':inside.returncode,'ok':observed['ok'],'unit':manifest}),flush=True)
        return int(inside.returncode!=0 or not observed['ok'])


if __name__=='__main__':
    raise SystemExit(main())
