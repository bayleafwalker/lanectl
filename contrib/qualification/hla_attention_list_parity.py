#!/usr/bin/env python3
"""Compare ordered attention lists at two exact, clean Git revisions.

Runs synthetic loader fixtures in isolated archives, and checks WAREHOUSE,
PUBLISHED, PREFER_PUBLISHED with and without a publication. No HTTP is used.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from unittest.mock import patch

FIXTURE_SHA256 = 'b67ebe0894f3c33fbe18bc183064dbee6f0ef06e9fb938d9ee2a4bba880b4c8e'


def sha(b):
    return hashlib.sha256(b).hexdigest()


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


def source(repo, expected):
    if not re.fullmatch(r'[0-9a-f]{40}', expected):
        raise ValueError('revision must be a full 40-character SHA')
    actual = git(repo, 'rev-parse', 'HEAD')
    if actual != expected:
        raise ValueError(f'{repo}: HEAD {actual} does not match {expected}')
    if git(repo, 'status', '--porcelain=v1', '--untracked-files=all'):
        raise ValueError(f'{repo}: source worktree is not clean')
    return actual


def snapshot(repo, rev, destination):
    archive = subprocess.run(['git', '-C', str(repo), 'archive', rev], check=True, capture_output=True).stdout
    archive_file = destination.parent / (destination.name + '.tar')
    archive_file.write_bytes(archive)
    with tarfile.open(archive_file) as tf:
        tf.extractall(destination, filter='data')
    archive_file.unlink()


def child(fixture, result, reverse, db, seed_fixture):
    root = Path.cwd().resolve()
    sys.path.insert(0, str(root))
    spec = importlib.util.spec_from_file_location('parity_fixtures', fixture)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from apps.api.support import to_jsonable
    from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService
    from packages.pipelines.transformation_service import TransformationService
    from packages.storage.duckdb_store import DuckDBStore
    from packages.storage.postgres_reporting import PostgresReportingStore
    from tests import postgres_test_support
    assert Path(sys.modules[ReportingService.__module__].__file__).resolve().is_relative_to(root)
    assert postgres_test_support.docker_is_available(), 'Postgres is mandatory for parity qualification'
    ts = TransformationService(DuckDBStore.open(str(db)))
    if seed_fixture:
        module.seed(ts)
        ts.refresh_publications(module.REFRESH)
    asof = str(ts.store.fetchall("SELECT CURRENT_DATE")[0][0])
    before = to_jsonable(ts.store.fetchall_dicts('SELECT * FROM mart_open_attention_items ORDER BY item_id'))
    calls = []
    original_run = subprocess.run
    def observe(args, *a, **kw):
        if isinstance(args, list) and args and args[0] == 'docker':
            calls.append(list(args))
        return original_run(args, *a, **kw)
    if reverse:
        original = ReportingService.get_open_attention_items
        def reversed_list(self):
            return list(reversed(original(self)))
        ReportingService.get_open_attention_items = reversed_list
    rows = {}
    try:
        with patch.object(postgres_test_support.subprocess, 'run', side_effect=observe):
            with postgres_test_support.running_postgres_container() as dsn:
                pg = PostgresReportingStore(dsn)
                module.publication(ts, pg)
                pg_before = to_jsonable(pg.fetchall_dicts('SELECT * FROM mart_open_attention_items ORDER BY item_id'))
                configs = {
                    'warehouse': (ReportingAccessMode.WAREHOUSE, None),
                    'published': (ReportingAccessMode.PUBLISHED, pg),
                    'prefer_published': (ReportingAccessMode.PREFER_PUBLISHED, pg),
                    'prefer_fallback': (ReportingAccessMode.PREFER_PUBLISHED, None),
                }
                for name, (mode, store) in configs.items():
                    service = ReportingService(ts, publication_store=store, access_mode=mode)
                    rows[name] = to_jsonable(service.get_open_attention_items())
                    assert len(rows[name]) > 1, (name, rows[name])
                assert pg_before == to_jsonable(pg.fetchall_dicts('SELECT * FROM mart_open_attention_items ORDER BY item_id'))
                assert before == to_jsonable(ts.store.fetchall_dicts('SELECT * FROM mart_open_attention_items ORDER BY item_id'))
    finally:
        ts.store.close()
    created = [c[c.index('--name') + 1] for c in calls if len(c) > 1 and c[1] == 'run' and '--name' in c]
    assert len(created) == 1, created
    name = created[0]
    assert any(c[1:3] == ['rm', '-f'] and c[-1] == name for c in calls), calls
    assert original_run(['docker', 'inspect', name], capture_output=True).returncode != 0
    Path(result).write_text(json.dumps({'asof': asof, 'rows': rows,
                                        'container': name, 'container_removed': True}, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-repo', type=Path)
    parser.add_argument('--base-sha')
    parser.add_argument('--candidate-repo', type=Path)
    parser.add_argument('--candidate-sha')
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--reverse-candidate', action='store_true', help='falsifier: reverse candidate facade output')
    parser.add_argument('--child-result', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--child-db', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--child-seed', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    fixture = args.fixture.resolve()
    if sha(fixture.read_bytes()) != FIXTURE_SHA256:
        raise ValueError('fixture bytes do not match the qualified native acceptance file')
    if args.child_result:
        child(fixture, args.child_result, args.reverse_candidate, args.child_db, args.child_seed)
        return
    if not all((args.base_repo, args.base_sha, args.candidate_repo, args.candidate_sha)):
        parser.error('both source repos and full SHAs are required')
    source(args.base_repo, args.base_sha)
    source(args.candidate_repo, args.candidate_sha)
    with tempfile.TemporaryDirectory(prefix='hla-list-parity-') as td:
        temp = Path(td)
        outputs = {}
        for label, repo, revision in (('base', args.base_repo, args.base_sha),
                                      ('candidate', args.candidate_repo, args.candidate_sha)):
            wt = temp / label
            wt.mkdir()
            snapshot(repo, revision, wt)
            result = temp / (label + '.json')
            database = temp / (label + '.duckdb')
            if label == 'candidate':
                shutil.copyfile(temp / 'base.duckdb', database)
            command = [args.python, str(Path(__file__).resolve()), '--fixture', str(fixture), '--child-result', str(result), '--child-db', str(database)]
            if label == 'base':
                command.append('--child-seed')
            if label == 'candidate' and args.reverse_candidate:
                command.append('--reverse-candidate')
            env = dict(os.environ, PYTHONPATH=str(wt))
            subprocess.run(command, cwd=wt, env=env, check=True)
            outputs[label] = json.loads(result.read_text())
        base, candidate = outputs['base'], outputs['candidate']
        assert base['asof'] == candidate['asof'], 'fixture dates differ'
        mismatches = [mode for mode in base['rows'] if base['rows'][mode] != candidate['rows'][mode]]
        diagnostics = {}
        for mode in mismatches:
            a, b = base['rows'][mode], candidate['rows'][mode]
            encode = lambda row: json.dumps(row, sort_keys=True)
            index = next((i for i, pair in enumerate(zip(a, b)) if pair[0] != pair[1]), None)
            diagnostics[mode] = {'same_multiset': sorted(map(encode, a)) == sorted(map(encode, b)),
                                 'first_difference': index,
                                 'base_row': a[index] if index is not None else None,
                                 'candidate_row': b[index] if index is not None else None}
        summary = {'diagnostics': diagnostics, 'base_sha': args.base_sha, 'candidate_sha': args.candidate_sha,
                   'fixture_sha256': FIXTURE_SHA256, 'asof': base['asof'],
                   'counts': {mode: len(rows) for mode, rows in base['rows'].items()},
                   'base_containers_removed': base['container_removed'],
                   'candidate_containers_removed': candidate['container_removed'],
                   'order_reversal_injected': args.reverse_candidate, 'mismatches': mismatches}
        print(json.dumps(summary, sort_keys=True))
        if mismatches:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
