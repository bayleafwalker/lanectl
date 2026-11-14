"""Run fixed supplemental cases against one exact git commit in an isolated archive."""
import argparse
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path('/projects/dev/homelab-analytics')
HERE = Path(__file__).resolve().parent
FROZEN = Path('/tmp/hla-client-boundary-header-repair/files/tests/test_attention_record_boundary_acceptance.py')
FROZEN_SHA = 'c57154ceb6f60f1a01898ace9fa1ab9bfd9e222a6c06498648f6a0bdf09ea038'
def tracked_paths(commit):
    entries = subprocess.check_output(['git', 'ls-tree', '-rz', '--full-tree', commit], cwd=REPO).split(b'\0')
    return [Path(path.decode()) for entry in entries if entry
            for head, path in [entry.split(b'\t', 1)] if head.split()[1] == b'blob']


def fingerprint(root, relative):
    path = root
    for part in relative.parts[:-1]:
        path = path / part
        mode = path.lstat().st_mode
        if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
            raise AssertionError(f'unsafe tracked parent: {relative}')
    path = path / relative.name
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        return ('symlink', os.readlink(path))
    if not stat.S_ISREG(info.st_mode):
        raise AssertionError(f'tracked path is not a file: {relative}')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as handle:
        opened = os.fstat(handle.fileno())
        if (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
            raise AssertionError(f'tracked file replaced while reading: {relative}')
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    return ('file', stat.S_IMODE(info.st_mode), digest)


def snapshot(root, paths):
    return {str(path): fingerprint(root, path) for path in paths}


parser = argparse.ArgumentParser()
parser.add_argument('sha')
parser.add_argument('--mutate-body-first', action='store_true')
parser.add_argument('--output', required=True)
args = parser.parse_args()
sha = subprocess.check_output(['git','rev-parse','--verify',args.sha+'^{commit}'],cwd=REPO,text=True).strip()
assert sha == args.sha and len(sha) == 40, 'provide exact full commit SHA'
assert hashlib.sha256(FROZEN.read_bytes()).hexdigest() == FROZEN_SHA, 'frozen helper bytes changed'
out = Path(args.output);out.mkdir(parents=True,exist_ok=False)
with tempfile.TemporaryDirectory(prefix='hla-statusbody-') as directory:
    checkout=Path(directory)/'checkout';checkout.mkdir()
    archive=subprocess.run(['git','archive',sha],cwd=REPO,stdout=subprocess.PIPE,check=True)
    subprocess.run(['tar','-x','-C',str(checkout)],input=archive.stdout,check=True)
    candidate=checkout/'apps/web/frontend/lib/attention-record.ts'
    assert fingerprint(checkout, candidate.relative_to(checkout))[0] == 'file', 'candidate reader must be regular'
    before=hashlib.sha256(candidate.read_bytes()).hexdigest()
    if args.mutate_body_first:
        source=candidate.read_text(); marker='  if (response.status === 401) {'
        assert source.count(marker)==1,'mutation target absent or ambiguous'
        candidate.write_text(source.replace(marker,'  await response.json(); // qualification-only deliberate fault\n'+marker,1))
    after=hashlib.sha256(candidate.read_bytes()).hexdigest()
    overlay=checkout/'tests/test_attention_record_boundary_acceptance.py'
    if overlay.exists() or overlay.is_symlink():
        assert fingerprint(checkout,overlay.relative_to(checkout))[0]=='file', 'acceptance overlay must be regular'
    else:
        assert not (checkout/'tests').is_symlink(), 'acceptance parent must be a directory'
    shutil.copy2(FROZEN,overlay)
    shutil.copy2(HERE/'test_statusbody_supplement.py',checkout/'tests/test_statusbody_supplement.py')
    env=dict(os.environ,PYTHONPATH=str(checkout)+os.pathsep+os.environ.get('PYTHONPATH',''), HLA_STATUSBODY_ARTIFACTS=str(out.resolve()))
    command=[sys.executable,'-m','pytest','-q','-s','-o','addopts=','tests/test_statusbody_supplement.py','--junitxml',str(out/'junit.xml')]
    print('exact source',sha,'reader sha256 before',before,'after',after,'mutated',args.mutate_body_first,flush=True)
    paths=tracked_paths(sha)
    baseline=snapshot(checkout,paths)
    print('acceptance overlay sha256', FROZEN_SHA, 'supplement sha256', hashlib.sha256((HERE/'test_statusbody_supplement.py').read_bytes()).hexdigest(), flush=True)
    print('snapshot contains',len(paths),'tracked paths after overlay and optional mutation',flush=True)
    try:
        p=subprocess.run(command,cwd=checkout,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        (out/'pytest.log').write_text(p.stdout)
        print(p.stdout,flush=True)
    finally:
        changed=[]
        for path in paths:
            try:
                if fingerprint(checkout,path)!=baseline[str(path)]:
                    changed.append(str(path))
            except (OSError,AssertionError) as exc:
                changed.append(f'{path}: {exc}')
        (out/'source-invariance.txt').write_text('\n'.join(changed) if changed else f'all {len(paths)} tracked paths unchanged\n')
        assert not changed, f'tracked source changed after test: {changed}'
        print('all',len(paths),'tracked paths unchanged after test',flush=True)
    report=ET.parse(out/'junit.xml').getroot(); cases=list(report.iter('testcase'))
    names={f'test_status_before_body[{body}-{status}-{expected}-{retry}]' for body in ('', 'SYNTHETIC_SECRET_invalid_json') for status, expected, retry in ((401,'redirect','None'),(403,'denied','None'),(404,'not_found','None'),(503,'unavailable','12'),(500,'throw','None'))}
    assert len(cases)==10 and {case.get('name') for case in cases}==names, 'incomplete, duplicate or unexpected cases'
    assert not list(report.iter('skipped')) and not list(report.iter('error')), 'skips/errors forbidden'
    failures=len(list(report.iter('failure')))
    if args.mutate_body_first:
        failed_names = {case.get('name') for case in cases if case.find('failure') is not None}
        expected_failures = {name for name in names if '-500-throw-None]' not in name}
        assert p.returncode != 0 and failed_names == expected_failures, 'body-first mutation did not fail the eight mapped-status cases'
        print('body-first mutation rejected:', failures, 'of 10 cases')
    else:
        assert p.returncode == 0 and failures == 0, 'status-body qualification failed'
        print('all 10 cases passed without skips')

assert not checkout.exists(), 'temporary checkout cleanup unverified'
print('owned temporary checkout removed')
