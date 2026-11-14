#!/usr/bin/env python3
"""Create a private PATH shim, without invoking Docker, lanectl or deployment."""
import argparse, os, pathlib, shlex, sys
p=argparse.ArgumentParser();p.add_argument('--directory',required=True);p.add_argument('--docker',required=True);p.add_argument('--source',required=True);a=p.parse_args()
root=pathlib.Path(a.directory); real=pathlib.Path(a.docker).resolve(strict=True); source=pathlib.Path(a.source).resolve(strict=True)
if not root.is_absolute() or root.parent.resolve()!=pathlib.Path(__file__).resolve().parent or root.exists(): p.error('directory must be a new direct child of the preparation directory')
if not real.is_file() or not os.access(real,os.X_OK) or not source.is_dir():p.error('invalid binary or source')
root.mkdir(mode=0o700);(root/'bin').mkdir(mode=0o700);(root/'logs').mkdir(mode=0o700)
observer=pathlib.Path(__file__).with_name('docker_observe.py').resolve(strict=True)
cmd=[sys.executable,str(observer),str(real),str(root/'logs'),str(source)]
launcher='#!/bin/sh\nexec '+shlex.join(cmd)+' "$@"\n'
path=root/'bin'/'docker';path.write_text(launcher);path.chmod(0o700)
print('Created private shim '+str(path)+'; no deployment invoked.')
