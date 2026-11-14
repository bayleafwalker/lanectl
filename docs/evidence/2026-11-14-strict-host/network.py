from dataclasses import replace
from pathlib import Path
import json, shlex
from lanectl.config import load_repos
from lanectl.runner import _train_command
repo=replace(load_repos()['sovite'],setup_cmd='',train_isolation='systemd')
code='import socket,ssl; print("DNS", socket.getaddrinfo("pypi.org",443, type=socket.SOCK_STREAM)[0][4][0]); s=socket.create_connection(("pypi.org",443),timeout=15); t=ssl.create_default_context().wrap_socket(s,server_hostname="pypi.org"); print("TLS",t.version(),t.getpeercert()["subjectAltName"][:2]); t.close()'
r=_train_command(repo,Path(repo.path),shlex.join(['/run/current-system/sw/bin/python3','-c',code]))
Path('/tmp/lanectl-strict-qualification-20261114/network.json').write_text(json.dumps({'command':code,'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr},indent=2))
print(r.returncode,r.stdout[-1000:],r.stderr)
raise SystemExit(r.returncode)
