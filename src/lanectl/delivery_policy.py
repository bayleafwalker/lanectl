"""Immutable delivery-policy evidence and historical provenance resolution."""
from dataclasses import asdict
import hashlib
import subprocess
import tomllib

from .config import home, lane_from_raw
from .contracts import LaneRevision

SCHEMA = 'lanectl.delivery-policy/v1'
MODES = ('legacy', 'review-progress')


def snapshot(lane):
    if lane.delivery_policy not in MODES:
        raise ValueError('unknown delivery policy')
    return {'schema': SCHEMA, 'lane': asdict(lane)}


def from_binding(binding):
    if not isinstance(binding, dict) or binding.get('schema') != SCHEMA:
        raise ValueError('unresolved delivery policy')
    raw = dict(binding['lane'])
    for name in ('protected_paths', 'dependency_manifests', 'test_globs',
                 'forbidden_added_patterns', 'external_models'):
        raw[name] = tuple(raw[name])
    lane = LaneRevision(**raw)
    if lane.delivery_policy not in MODES:
        raise ValueError('unknown delivery policy')
    return lane


def historical(claim):
    """Resolve exact recorded lane bytes from retained Git, never current defaults."""
    name, digest, revision = claim.get('lane'), claim.get('lane_digest'), claim.get('lane_revision')
    if not name or not digest or revision is None or '/' in name or '..' in name:
        return None
    path = f'governance/lanes/{name}.toml'
    proc = subprocess.run(['git', '-C', str(home()), 'log', '--all', '--format=%H', '--', path],
                          capture_output=True, text=True)
    if proc.returncode:
        return None
    for commit in proc.stdout.splitlines():
        blob = subprocess.run(['git', '-C', str(home()), 'show', f'{commit}:{path}'], capture_output=True)
        if blob.returncode or 'sha256:' + hashlib.sha256(blob.stdout).hexdigest()[:16] != digest:
            continue
        try:
            lane = lane_from_raw(tomllib.loads(blob.stdout.decode()), digest)
            if lane.revision == revision and lane.delivery_policy == "legacy":
                return snapshot(lane)
        except (ValueError, KeyError, UnicodeError):
            return None
    return None


def resolve(events, item_id):
    """First publication fixes an outcome; old outcomes require claim evidence."""
    relevant = [e for e in events if e.get('item_id') == item_id]
    for e in relevant:
        if e['type'] == 'release.published':
            binding = e['data'].get('effective_policy')
            if binding is not None:
                from_binding(binding)
                return binding
            break
    else:
        return None
    claim = next((e['data'] for e in relevant if e['type'] == 'item.claimed'), None)
    return historical(claim) if claim else None


def publication_binding(events, item_id, lane):
    if any(e.get('item_id') == item_id and e['type'] in ('release.published', 'item.claimed')
           for e in events):
        return resolve(events, item_id)
    return snapshot(lane)


def effective_lane(binding, current):
    """Freeze quality rules without restoring a superseded authority grant.

    Incomparable sandbox/effect changes fail closed. Other boundaries intersect;
    counters and timeouts take the more restrictive value.
    """
    from dataclasses import replace
    bound = from_binding(binding)
    if bound.lane != current.lane:
        raise ValueError('bound lane does not match current lane')
    if bound.effects != current.effects or bound.sandbox != current.sandbox:
        raise ValueError('lane effect or sandbox policy changed; review required')
    order = {'S': 0, 'M': 1, 'L': 2}
    if bound.size_max not in order or current.size_max not in order:
        raise ValueError('unknown eligibility size')
    combine = lambda left, right: tuple(dict.fromkeys((*left, *right)))
    return replace(bound,
        size_max=min((bound.size_max, current.size_max), key=order.get),
        routing={m: w for m, w in current.routing.items() if m in bound.routing},
        caps={k: min(v, current.caps[k]) for k, v in bound.caps.items()},
        protected_paths=combine(bound.protected_paths, current.protected_paths),
        dependency_manifests=combine(bound.dependency_manifests, current.dependency_manifests),
        test_globs=combine(bound.test_globs, current.test_globs),
        forbidden_added_patterns=combine(bound.forbidden_added_patterns, current.forbidden_added_patterns),
        external_models=combine(bound.external_models, current.external_models),
        timeout_s=min(bound.timeout_s, current.timeout_s),
        allow_restricted=bound.allow_restricted and current.allow_restricted)


def claim_binding(events, item_id, claim):
    """A claim can repeat, but never override, the outcome's first binding."""
    publication = next((e for e in events if e.get('item_id') == item_id
                        and e.get('type') == 'release.published'), None)
    if publication is None:
        return None
    # An unbound historical outcome predates frozen policy: each attempt is
    # governed by the lane bytes it actually recorded, not the first claim's.
    if 'effective_policy' not in publication['data']:
        binding = historical(claim)
    else:
        binding = resolve(events, item_id)
    repeated = claim.get('effective_policy')
    if binding is None or (repeated is not None and repeated != binding):
        return None
    return binding
