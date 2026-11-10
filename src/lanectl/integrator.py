"""Deterministic, policy-bounded integration of already gate-accepted candidates.

This executor never grants authority or changes acceptance. Empty autonomous
classes retain interactive integration. Every external step may be resumed from
owner facts and append-only receipts; uncertainty stops progression.
"""
from __future__ import annotations

import fcntl
import json
import subprocess
from pathlib import Path

from . import deploy, evaluator, landing, runner, work
from .config import home, load_releases, load_repos
from .events import project_items


def _authority():
    try:
        return landing.load_authority()
    except FileNotFoundError:
        return {"autonomous_classes": [], "fix_budget_lines": 0, "allowed_fix_classes": []}


def _run(cmd, cwd, run):
    p = run(cmd, cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if p.returncode:
        raise RuntimeError(f"{' '.join(cmd[:3])}: {(p.stderr or p.stdout)[-500:]}")
    return p.stdout.strip()


def publish(repo, train_id, sha, *, run=subprocess.run):
    """Publish via one stable branch/PR and require its CI before merging.

    An ambiguous response is retried by querying the same head branch. Merge
    success is independently proven against canonical main by work.merged.
    """
    remote = runner.git(repo.path, 'config', '--get', 'claude.canonicalRemote', check=False) or 'origin'
    url = runner.git(repo.path, 'remote', 'get-url', remote)
    if 'github.com' not in url:
        raise RuntimeError('headless PR publication currently requires a GitHub canonical remote')
    slug = url.split('github.com', 1)[1].lstrip(':/').removesuffix('.git')
    branch = f'lanes/{train_id}'
    # Query merged/closed PRs as well: a lost merge acknowledgement must not
    # cause a second PR or an unchecked second merge.
    rows = json.loads(_run(['gh', 'pr', 'list', '-R', slug, '--head', branch,
                            '--state', 'all', '--json', 'number,state,headRefOid'], repo.path, run))
    if len(rows) > 1:
        raise RuntimeError('multiple PRs for train branch; interactive reconciliation required')
    if rows:
        pr = rows[0]
        if pr['headRefOid'] != sha:
            raise RuntimeError('PR head differs from checked train')
        if pr['state'] == 'MERGED':
            if not work.merged(repo, sha, run):
                raise RuntimeError('merged PR is not on canonical main')
            return f'{train_id}: canonical PR merge verified'
        if pr['state'] != 'OPEN':
            raise RuntimeError('train PR was closed without merge')
    else:
        _run(['git', 'push', remote, f'{sha}:refs/heads/{branch}'], repo.path, run)
        _run(['gh', 'pr', 'create', '-R', slug, '--head', branch, '--base', repo.main,
              '--title', f'lanectl: {train_id}', '--body', f'Checked lanectl train {train_id} at {sha}.'], repo.path, run)
        rows = json.loads(_run(['gh', 'pr', 'list', '-R', slug, '--head', branch,
                                '--state', 'open', '--json', 'number,state,headRefOid'], repo.path, run))
        if len(rows) != 1 or rows[0]['headRefOid'] != sha:
            raise RuntimeError('could not verify created train PR')
        pr = rows[0]
    number = str(pr['number'])
    _run(['gh', 'pr', 'checks', number, '-R', slug, '--watch'], repo.path, run)
    checks = json.loads(_run(['gh', 'pr', 'checks', number, '-R', slug, '--required',
                              '--json', 'name,bucket,state'], repo.path, run))
    if not checks or any(c.get('bucket') != 'pass' for c in checks):
        raise RuntimeError('required CI checks are absent or have not all passed')
    # --match-head-commit fences a concurrent PR update between checks and merge.
    _run(['gh', 'pr', 'merge', number, '-R', slug, '--merge', '--match-head-commit', sha], repo.path, run)
    if not work.merged(repo, sha, run):
        raise RuntimeError('merge acknowledgement lacks canonical ancestry proof')
    return f'{train_id}: canonical PR merge verified'


def _fix_warnings(repo, train, events, authority):
    counts = {}
    for e in events:
        if e['type'] != 'integrator.fix' or e['data'].get('train_id') != train['train_id']:
            continue
        commit = e['data']['commit']
        lines = runner.git(repo.path, 'show', '--format=', '--numstat', commit)
        counts[commit] = sum(int(n) for row in lines.splitlines() for n in row.split('\t')[:2] if n.isdigit())
    # Read fixes from the train itself as well; receipts are normally emitted
    # only at land, so relying solely on recorded fixes would miss new ones.
    per_attempt = {}
    total = 0
    for row in runner.git(repo.path, 'log', '--format=%H %s', f"{train['base_sha']}..train/{train['train_id']}").splitlines():
        commit, subject = row.split(' ', 1)
        if not subject.startswith('fix(') or '): [' not in subject:
            continue
        cls = subject.split('): [', 1)[1].split(']', 1)[0]
        nums = runner.git(repo.path, 'show', '--format=', '--numstat', commit)
        count = sum(int(n) for line in nums.splitlines() for n in line.split('\t')[:2] if n.isdigit())
        attempt = subject[4:subject.index(')')]
        per_attempt[attempt] = per_attempt.get(attempt, 0) + count
        total += count
        if (cls not in authority['allowed_fix_classes']
                or per_attempt[attempt] > authority['fix_budget_lines']
                or total > authority['fix_budget_lines']):
            return [f'integrator fix {commit} exceeds allowed class or size']
    return landing.fix_budget([e for e in events if e["type"] != "integrator.fix" or e["data"].get("train_id") == train["train_id"]], authority, counts)


def cycle(log, *, max_trains=3, publish_fn=None):
    """Review/evaluate, train, deploy, land and publish within explicit authority."""
    if max_trains < 1:
        return []
    authority = _authority()
    allowed = set(authority.get('autonomous_classes', ()))
    if not allowed:
        return []
    lock_path = log.path.with_suffix('.integrator.lock')
    with open(lock_path, 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return ['integrator: another cycle is active']
        return _cycle(log, allowed, max_trains, publish_fn or publish)


def _accepted(log, attempt_id):
    try:
        rules = evaluator.load_rules()
    except (OSError, ValueError):
        return False
    verdict = evaluator.evaluate_attempt(log, attempt_id, rules)
    return bool(verdict and verdict.get('verdict') == 'accept'
                and verdict.get('rules_revision') == f"evaluator/v{rules['revision']}")


def _cycle(log, allowed, max_trains, publish_fn):
    repos = load_repos()
    releases = {r.id: r for r in load_releases()}
    lines = []
    # Pending PR publication survives local landing and worktree cleanup.
    events = log.read()
    published = set()
    for e in events:
        if e['type'] != 'item.landed':
            continue
        d = e['data']; rel = releases.get(e['item_id'])
        if rel is None or rel.task_class not in allowed or rel.repo not in repos:
            continue
        repo = repos[rel.repo]
        key = d['train_id']
        if repo.landing != 'pr' or key in published or not d.get('landed_sha'):
            continue
        published.add(key)
        try:
            if not work.merged(repo, d['landed_sha']):
                lines.append(publish_fn(repo, key, d['landed_sha']))
        except Exception as exc:
            lines.append(f'{key}: publication held: {exc}')
    lines.extend(f"tracker {r['work']}: {'synced' if r['ok'] else r.get('error', 'failed')}" for r in work.reconcile(log))
    # Reuse unfinished trains before creating new ones.
    trains = {e['data']['train_id']: e['data'] for e in log.read() if e['type'] == 'train.built'}
    views = project_items(log.read())
    active = {a['attempt_id'] for v in views.values() if v.state == 'in-train' for a in v.attempts[-1:]}
    ready_trains = [d for d in trains.values() if d['passed'] and set(d['attempts']) & active]
    grouped = {}
    for candidate in runner.candidates(log):
        rel = releases.get(candidate['item_id'])
        if rel is None or rel.task_class not in allowed:
            continue
        if not _accepted(log, candidate['attempt_id']):
            continue
        grouped.setdefault(rel.repo, []).append(candidate['attempt_id'])
    for repo_name, aids in grouped.items():
        if len(ready_trains) >= max_trains:
            break
        lines.append(runner.build_train(log, repo_name, aids))
        train = [e['data'] for e in log.read() if e['type'] == 'train.built'][-1]
        if train['passed']:
            ready_trains.append(train)
        else:
            lines.append(f"{train['train_id']}: failed train held for review")
    for train in ready_trains[:max_trains]:
        authority = _authority()
        current_allowed = set(authority.get('autonomous_classes', ()))
        events = log.read()
        by_attempt = {a['attempt_id']: v.item_id for v in project_items(events).values() for a in v.attempts}
        rels = [releases.get(by_attempt.get(a)) for a in train['attempts']]
        if any(r is None or r.task_class not in current_allowed for r in rels):
            lines.append(f"{train['train_id']}: authority held")
            continue
        repo = repos[train['repo']]
        if _fix_warnings(repo, train, events, authority):
            lines.append(f"{train['train_id']}: fix budget held")
            continue
        if any(not _accepted(log, aid) for aid in train['attempts']):
            lines.append(f"{train['train_id']}: evaluation held")
            continue
        if repo.deploy is not None and train['train_id'] not in deploy.live(events):
            lines.append(deploy.deploy_train(log, train['train_id']))
        result = runner.land(log, train['train_id'])
        lines.append(result)
        if result.startswith('landed') and repo.landing == 'pr':
            try:
                sha = runner.git(repo.path, 'rev-parse', f"train/{train['train_id']}")
                lines.append(publish_fn(repo, train['train_id'], sha))
            except Exception as exc:
                lines.append(f"{train['train_id']}: publication held: {exc}")
    lines.extend(f"tracker {r['work']}: {'synced' if r['ok'] else r.get('error', 'failed')}" for r in work.reconcile(log))
    return lines


def register(sub):
    p = sub.add_parser('integrate', help='policy-bounded headless train integration')
    p.add_argument('--max-trains', type=int, default=3)
    return {'integrate': _cmd}


def _cmd(args, log):
    for line in cycle(log, max_trains=args.max_trains):
        print(line)
    return 0
