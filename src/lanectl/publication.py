"""Resolve append-only publication evidence without rewriting operational history."""
import hashlib
import subprocess

from .config import home
from .contracts import parse_evidence_ref

from .stream_store import encode


def fingerprint(event):
    return hashlib.sha256(encode(event).encode()).hexdigest()


def _validate_target(event, preceding):
    from .contracts import validate_event
    validate_event(event)
    d = event['data']
    target = preceding.get(d['target_event_sha256'])
    if (target is None or target.get('data', {}).get('release_id') != d['release_id']
            or target.get('data', {}).get('revision') != d['revision']):
        raise ValueError('invalidation target must be a preceding matching publication')


def _resolve(events):
    preceding, invalid, publications = {}, set(), []
    for n, event in enumerate(events, 1):
        if event.get('type') == 'release.published':
            digest = fingerprint(event)
            preceding[digest] = event
            publications.append((n, event, digest))
        elif event.get('type') == 'release.publication.invalidated':
            _validate_target(event, preceding)
            invalid.add(event['data']['target_event_sha256'])
    return preceding, [(n, event) for n, event, digest in publications if digest not in invalid]


def publication_evidence(events):
    """Validate history context and return publications not explicitly invalidated."""
    return _resolve(events)[1]


def validate_invalidation(event, events):
    if event['type'] != 'release.publication.invalidated':
        return
    preceding, _ = _resolve(events)
    _validate_target(event, preceding)
    validate_evidence_ref(event['data']['evidence_ref'])


def validate_evidence_ref(ref):
    """Verify a committed regular blob in LANECTL_HOME, without reading its contents."""
    commit, path = parse_evidence_ref(ref)
    def git(*args):
        result = subprocess.run(["git", "--literal-pathspecs", "-C", str(home()), *args], capture_output=True, text=True)
        if result.returncode:
            raise ValueError("evidence_ref commit or file is unavailable")
        return result.stdout
    if git("cat-file", "-t", commit).strip() != "commit":
        raise ValueError("evidence_ref must name a commit")
    listing = git("ls-tree", "--full-tree", commit, "--", path).splitlines()
    if len(listing) != 1 or not listing[0].startswith(("100644 blob ", "100755 blob ")):
        raise ValueError("evidence_ref must name a committed regular file")
    if listing[0].split("\t", 1)[-1] != path:
        raise ValueError("evidence_ref path mismatch")
