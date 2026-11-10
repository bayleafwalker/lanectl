"""Turn recurring planner/gate flags into reviewed maintenance drafts.

Reuse triage.proposed for durable intake; scans are deterministic, model-free
and deduplicated by the relevant owner evidence, not by the whole log tail.
Telemetry-derived intents remain restricted and never publish themselves.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
from pathlib import Path

from . import specification
from .config import home, load_release
from .ready import _first_party
from .report import attribution

RULE = 'closure-flags/v1'
SOURCE = 'closure'


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def proposals(events):
    """Latest durable state per closure proposal, ordered by fingerprint."""
    rows = {}
    for event in events:
        data = event.get('data') or {}
        if event.get('type') == 'triage.proposed' and data.get('source') == SOURCE:
            rows[data['fingerprint']] = dict(data)
    return [rows[k] for k in sorted(rows)]


def from_flags(events, *, min_recurrence=2):
    """Propose maintenance for at least two distinct ruled gap-bearing attempts."""
    if min_recurrence < 2:
        raise ValueError('recurrence must require at least two distinct ruled attempts')
    ruled = attribution(events)['ruled']
    classes = {e['data']['attempt_id']: e['data']['task_class'] for e in events
               if e['type'] == 'experiment.recorded'}
    landed = {e.get('item_id') for e in events if e['type'] == 'item.landed'}
    active = set()
    consumed = set()
    for row in proposals(events):
        if row.get('action') != 'drafted':
            continue
        if row.get('release_id') in landed:
            consumed.update(row.get('evidence_refs', []))
        else:
            active.add((row['kind'], row['task_class']))
    groups = {}
    for event in events:
        if event['type'] != 'integrator.fix':
            continue
        data = event['data']
        kind = {'spec-gap': 'planner', 'gate-gap': 'gate'}.get(data.get('fix_class'))
        aid = data.get('attempt_id')
        task_class = classes.get(aid)
        if not kind or aid not in ruled or not task_class:
            continue
        key = (kind, task_class)
        if key in active:
            continue
        evidence = dict(attempt_id=aid, commit=data.get('commit'), fix_class=data['fix_class'])
        ref = _digest(evidence)
        if ref not in consumed:
            groups.setdefault(key, {})[ref] = aid
    rows = []
    for (kind, task_class), refs in sorted(groups.items()):
        recurrence = len(set(refs.values()))
        if recurrence < min_recurrence:
            continue
        source_revision = _digest(dict(rule=RULE, kind=kind, task_class=task_class,
                                       evidence_refs=sorted(refs)))
        fp = _digest(dict(source=SOURCE, source_revision=source_revision))
        rows.append(dict(source=SOURCE, fingerprint=fp, source_revision=source_revision,
            rule_revision=RULE, kind=kind, task_class=task_class, repo='lanectl',
            summary=f'Recurring {kind} gaps in task class {task_class}',
            recurrence=recurrence, evidence_refs=sorted(refs), data_class='restricted',
            action='proposed'))
    return rows


def scan(log, *, record=False):
    """Inspect or append only newly evidenced proposals, without model calls."""
    def pending(events):
        seen = {row['fingerprint'] for row in proposals(events)}
        return [row for row in from_flags(events) if row['fingerprint'] not in seen]
    if not record:
        return pending(log.read())
    with log.locked():
        rows = pending(log.read())
        for row in rows:
            log.append('triage.proposed', row)
        return rows


def _intent(row):
    subject = ('release specification and acceptance criteria' if row['kind'] == 'planner'
               else 'regression detection at the lane gates')
    return (f'Investigate and improve {subject} for task class {row["task_class"]}. '
            'Add regression evidence for the underlying failure mode, preserving existing '
            'owner authority and protected-path review. This is maintenance intake, not '
            'permission to weaken tests, change policy or publish. '
            f'Source evidence revision {row["source_revision"]}; proposal {row["fingerprint"]}.')


def draft(log, fingerprint, *, author_model, reviewer_model, scope,
          lane_name='restricted', draft_fn=None):
    """Link one independently reviewed draft; retry safely after process failure."""
    if not _first_party(author_model) or not _first_party(reviewer_model):
        raise ValueError('telemetry-derived maintenance intents are restricted')
    # Validate identity before using it in a lock path.
    if not isinstance(fingerprint, str) or len(fingerprint) != 64 or any(
            c not in '0123456789abcdef' for c in fingerprint):
        raise ValueError('unknown closure proposal')
    lock_path = log.path.parent / f'closure-{fingerprint}.lock'
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('closure proposal is already being drafted') from exc
        row = next((r for r in proposals(log.read()) if r['fingerprint'] == fingerprint), None)
        if row is None:
            raise ValueError('unknown closure proposal')
        if row.get('action') == 'drafted':
            return row
        release_id = f'closure-{fingerprint[:20]}'
        intent = _intent(row)
        destination = home() / 'backlog' / release_id
        if destination.exists():
            # A crash may have happened after atomic draft creation but before
            # linking it into the log. Never overwrite a different planner draft.
            evidence = json.loads((destination / specification.EVIDENCE_FILE).read_text())
            if (evidence.get('intent_digest') != hashlib.sha256(intent.encode()).hexdigest()
                    or evidence.get('release_digest') != specification.release_digest(destination)
                    or load_release(destination).id != release_id):
                raise ValueError('existing draft does not match closure source evidence')
            path = destination
        else:
            path = (draft_fn or specification.draft_intent)(release_id,
                repo_name=row['repo'], title=row['summary'], intent=intent, scope=scope,
                author_model=author_model, reviewer_model=reviewer_model,
                lane_name=lane_name, data_class='restricted', task_class='tooling')
        result = dict(row, action='drafted', release_id=release_id, draft_path=str(path))
        with log.locked():
            log.append('triage.proposed', result)
        return result


def register(sub):
    parser = sub.add_parser('closure', help='turn recurring owner flags into unpublished maintenance drafts')
    commands = parser.add_subparsers(dest='closure_command', required=True)
    commands.add_parser('list', help='inspect previously recorded maintenance intake')
    scan_cmd = commands.add_parser('scan', help='derive new intake without model calls')
    scan_cmd.add_argument('--record', action='store_true')
    draft_cmd = commands.add_parser('draft', help='author and review one restricted maintenance draft')
    draft_cmd.add_argument('fingerprint')
    draft_cmd.add_argument('--author-model', required=True)
    draft_cmd.add_argument('--reviewer-model', required=True)
    draft_cmd.add_argument('--scope', action='append', required=True)
    draft_cmd.add_argument('--lane', default='restricted')
    return {'closure': _cmd}


def _cmd(args, log):
    try:
        if args.closure_command == 'scan':
            rows = scan(log, record=args.record)
        elif args.closure_command == 'list':
            rows = proposals(log.read())
        else:
            rows = [draft(log, args.fingerprint, author_model=args.author_model,
                reviewer_model=args.reviewer_model, scope=args.scope, lane_name=args.lane)]
        print(json.dumps(rows, indent=2))
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f'closure: {exc}')
        return 2
