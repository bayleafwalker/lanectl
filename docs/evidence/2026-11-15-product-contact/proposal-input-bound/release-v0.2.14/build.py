from pathlib import Path
import subprocess
import tarfile
import json
import hashlib
import zipfile
import os

r = Path('/tmp/lanectl-v014-release-assets-20261115')
repo = Path('/projects/dev/lanectl')
commit = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'v0.2.14^{commit}'], text=True).strip()
epoch = subprocess.check_output(['git', '-C', str(repo), 'show', '-s', '--format=%ct', commit], text=True).strip()
archive = r / 'source.tar'
with archive.open('wb') as out:
    subprocess.run(['git', '-C', str(repo), 'archive', commit], stdout=out, check=True)
env = dict(os.environ, SOURCE_DATE_EPOCH=epoch)
for number in (1, 2):
    context = r / f'context{number}'
    context.mkdir()
    with tarfile.open(archive) as tar:
        tar.extractall(context, filter='data')
    with (r / f'build{number}.log').open('w') as log:
        result = subprocess.run(['uv', 'build', '--offline', '--wheel', '--out-dir', str(r / f'build{number}')],
                                cwd=context, env=env, stdout=log, stderr=subprocess.STDOUT)
    assert result.returncode == 0, f'build{number} failed; output retained'
wheel = r / 'build1/lanectl-0.2.14-py3-none-any.whl'
repeat = r / 'build2' / wheel.name
assert wheel.read_bytes() == repeat.read_bytes()
target = r / wheel.name
target.write_bytes(wheel.read_bytes())
files = subprocess.check_output(['git', '-C', str(repo), 'ls-tree', '-r', '--name-only', commit, 'src/lanectl'], text=True).splitlines()
source_hashes = {}
with zipfile.ZipFile(target) as zipped:
    for name in files:
        source = subprocess.check_output(['git', '-C', str(repo), 'show', f'{commit}:{name}'])
        assert zipped.read(name.removeprefix('src/')) == source, name
        source_hashes[name] = hashlib.sha256(source).hexdigest()
    assert len([n for n in zipped.namelist() if n.startswith('lanectl/') and not n.endswith('/')]) == len(files)
manifest = {'distribution': 'lanectl', 'version': '0.2.14', 'tag': 'v0.2.14',
            'source_commit': commit, 'wheel': target.name, 'size_bytes': target.stat().st_size,
            'wheel_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
            'two_clean_offline_builds_byte_identical': True, 'source_date_epoch': epoch,
            'runtime_files_equal': len(files), 'runtime_source_sha256': source_hashes,
            'scope': 'Exact-source wheel byte equivalence under this cached build environment; not a general build-tool reproducibility guarantee.'}
(r / 'lanectl-0.2.14-artifact.json').write_text(json.dumps(manifest, indent=2) + '\n')
assets = [target, r / 'lanectl-0.2.14-artifact.json']
(r / 'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n' for p in assets))
(r / 'release-notes.md').write_text('Trusted specification-review inputs now have a separate 256 KiB encoded-byte limit checked before dispatch. Reviewer output remains limited to 64 KiB. Proposal files are checked unchanged through bounded regular-file descriptors, rejecting mutation, symlinks, directories and FIFOs.\n\nValidation: 1,140 tests passed on the integrated release source, test-first regression and adversarial descriptor cases, independent native Sonnet review. Two clean offline wheel builds were byte-identical; all 62 runtime files match tagged source.\n\nNo governance, autonomy, attempt-budget, credentials, hosted deployment or event-authority change. Product acceptance for the larger HLA review is separate.\n')
print(json.dumps({k: v for k, v in manifest.items() if k != 'runtime_source_sha256'}), flush=True)
