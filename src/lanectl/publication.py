"""Resolve append-only publication evidence without rewriting operational history."""
import hashlib
import re
import subprocess

from .config import home

from .stream_store import encode


def fingerprint(event):
    return hashlib.sha256(encode(event).encode()).hexdigest()


def publication_evidence(events):
    """Return (checkpoint, event) pairs for publications not explicitly invalidated."""
    invalid = {e['data']['target_event_sha256'] for e in events
               if e.get('type') == 'release.publication.invalidated'}
    return [(n, e) for n, e in enumerate(events, 1)
            if e.get('type') == 'release.published' and fingerprint(e) not in invalid]


def validate_invalidation(event, events):
    if event['type'] != 'release.publication.invalidated':
        return
    d = event['data']
    if not any(e.get('type') == 'release.published'
               and e.get('data', {}).get('release_id') == d['release_id']
               and e.get('data', {}).get('revision') == d['revision']
               and fingerprint(e) == d['target_event_sha256'] for e in events):
        raise ValueError('invalidation target must be a preceding matching publication')
    validate_evidence_ref(d['evidence_ref'])


def validate_evidence_ref(ref):
    """Verify a committed regular blob in LANECTL_HOME, without reading its contents."""
    match = re.fullmatch(r"git:([0-9a-f]{40}):(.+)", ref)
    if not match:
        raise ValueError("evidence_ref must be git:<full commit>:<relative path>")
    commit, path = match.groups()
    parts = path.split("/")
    if path.startswith("/") or any(ord(ch) < 32 or ord(ch) == 127 for ch in path) or any(part in ("", ".", "..") for part in parts):
        raise ValueError("evidence_ref path must be a safe relative path")
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
