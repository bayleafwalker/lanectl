import hashlib
import json
from pathlib import Path
import subprocess
import time

out = Path('/tmp/vuoro-lane-image-publish-20261115/registry-readback')
out.mkdir(exist_ok=False)
receipt = json.loads(Path('/tmp/vuoro-lane-image-publish-20261115/registry-receipt/lane-image-publication.json').read_text())
reference = receipt['image']
digest = reference.split('@')[1]
source = '784c0192b2f89afb1d9239d20f2ae408ee10f8d4'
assert reference == 'ghcr.io/bayleafwalker/vuoro-service@' + digest
assert receipt['source_sha'] == source and receipt['complete'] is True
aliases = ['ghcr.io/bayleafwalker/vuoro-service:lane-main',
           'ghcr.io/bayleafwalker/vuoro-service:lane-sha-' + source]
commands = []

def run(label, argv, data=None):
    start = time.monotonic()
    result = subprocess.run(argv, input=data, capture_output=True, timeout=300)
    (out/(label+'.stdout')).write_bytes(result.stdout)
    (out/(label+'.stderr')).write_bytes(result.stderr)
    commands.append({'label': label, 'argv': argv, 'exit': result.returncode,
                     'elapsed_s': round(time.monotonic()-start, 3)})
    (out/'state.json').write_text(json.dumps({'phase': 'running', 'commands': commands}, indent=2)+'\n')
    if result.returncode:
        raise SystemExit(result.returncode)
    return result.stdout

for index, alias in enumerate(aliases):
    actual = run('alias-'+str(index), ['docker', 'buildx', 'imagetools', 'inspect',
                                      alias, '--format', '{{.Manifest.Digest}}']).decode().strip()
    assert actual == digest, (alias, actual, digest)
run('provenance', ['gh', 'attestation', 'verify', 'oci://'+reference,
                  '--repo', 'bayleafwalker/vuoro', '--signer-workflow',
                  'bayleafwalker/vuoro/.github/workflows/publish-lane-service-image.yaml',
                  '--source-digest', source, '--source-ref', 'refs/heads/main',
                  '--predicate-type', 'https://slsa.dev/provenance/v1', '--deny-self-hosted-runners'])
run('pull', ['docker', 'pull', '--platform', 'linux/amd64', reference])
script = Path('/projects/dev/vuoro/scripts/validate_lane_service_image.py').read_bytes()
actual = json.loads(run('installed-composition', ['docker', 'run', '--rm', '-i',
    '--network', 'none', '--platform', 'linux/amd64', '--entrypoint', 'python',
    reference, '-', receipt['manifest_sha256']], script))
assert actual == receipt['installed_composition'], (actual, receipt['installed_composition'])
summary = {'phase': 'passed', 'observed_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
           'image': reference, 'source_sha': source, 'aliases': aliases,
           'alias_digests_match': True, 'provenance_verified': True,
           'installed_composition': actual, 'verifier_sha256': hashlib.sha256(script).hexdigest(),
           'commands': commands, 'scope': 'public registry artifact only; no hosted deployment or authority cutover'}
(out/'state.json').write_text(json.dumps(summary, indent=2)+'\n')
print(json.dumps(summary, indent=2))
