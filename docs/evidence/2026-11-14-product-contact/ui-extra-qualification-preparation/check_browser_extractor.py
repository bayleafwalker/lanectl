"""Exercise the exact browser extraction against tiny semantic DOM controls."""
from __future__ import annotations

import html
import json
import os
import socket
import subprocess
import time
import uuid
from contextlib import closing
from pathlib import Path

from semantic_oracle import FIELDS, LABELS, PRICE_FIELDS, assert_rows
from test_semantic_records import extractor, frozen, source_rows


def markup(kind, rows, layout='dl'):
    groups = []
    for row in rows:
        cells = []
        for field in FIELDS[kind]:
            value = row.get(field)
            rendered = 'Unknown' if value is None else str(value)
            if field in PRICE_FIELDS and value is not None:
                rendered += ' ' + row['currency']
            label, value = html.escape(LABELS[field][0]), html.escape(rendered)
            if layout == 'spans':
                cells.append('<div><span>' + label + '</span><span>' + value + '</span></div>')
            elif layout == 'paragraphs':
                cells.append('<p><strong>' + label + ':</strong> ' + value + '</p>')
            else:
                cells.append('<dt>' + label + '</dt><dd>' + value + '</dd>')
        if layout == 'dl':
            groups.append('<li><dl>' + ''.join(cells) + '</dl></li>')
        else:
            groups.append('<section>' + ''.join(cells) + '</section>')
    return '<main>' + ('<ul>' if layout == 'dl' else '') + ''.join(groups) + ('</ul>' if layout == 'dl' else '') + '</main>'


cases = []
for kind in frozen.SEGMENTS:
    rows = source_rows(kind)
    good = markup(kind, rows)
    cases.append((kind, rows, 'valid', good))
    cases.append((kind, rows, 'valid_spans', markup(kind, rows, 'spans')))
    cases.append((kind, rows, 'valid_paragraphs', markup(kind, rows, 'paragraphs')))
    if kind == 'contract_review':
        cases.extend([
            (kind, rows, 'valid_market_without_currency', good.replace('17.3456 EUR', '17.3456', 1)),
            (kind, [rows[0], rows[0]], 'nested_one_row', markup(kind, [rows[0]])),
            (kind, rows, 'market_wrong', good.replace('17.3456 EUR', '17.3457 EUR', 1)),
            (kind, rows, 'market_missing', good.replace('<dt>market reference</dt><dd>17.3456 EUR</dd>', '', 1)),
            (kind, rows, 'labels_swapped', good.replace('<dt>provider</dt><dd>Oak Provider</dd>', '<dt>utility type</dt><dd>Oak Provider</dd>', 1).replace('<dt>utility type</dt><dd>electricity</dd>', '<dt>provider</dt><dd>electricity</dd>', 1)),
            (kind, rows, 'fabricated', good.replace('<li><dl>', '<li><h3>Component 1</h3><dl>', 1)),
            (kind, rows, 'component_type', good.replace('</dl>', '<dt>Component type</dt><dd>Solar</dd></dl>', 1)),
            (kind, rows, 'component_label', good.replace('</dl>', '<dt>Price component label</dt><dd>Energy</dd></dl>', 1)),
            (kind, rows, 'valid_component_facts', good.replace('</dl>', '<dt>Component price</dt><dd>7.1234 EUR</dd><dt>Part date</dt><dd>2026-01-02</dd><dt>Component provider</dt><dd>Oak Provider</dd></dl>', 1).replace('<li><dl>', '<li><h3>Component details</h3><dl>', 1)),
        ])

with closing(socket.socket()) as sock:
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
name = 'hla-ui-semantics-' + uuid.uuid4().hex[:12]
cid = None
try:
    modules = Path('/tmp/hla-attention-ui-spec/base/apps/web/frontend/node_modules')
    cid = subprocess.check_output(['docker', 'run', '-d', '--name', name, '--network', 'host', '--ipc=host',
                                   '-v', str(modules) + ':/opt/node_modules:ro', frozen.IMAGE,
                                   'node', '/opt/node_modules/playwright/cli.js', 'run-server',
                                   '--host', '127.0.0.1', '--port', str(port)], text=True).strip()
    for _ in range(40):
        logs = subprocess.run(['docker', 'logs', cid], text=True, capture_output=True)
        if 'Listening on' in logs.stdout + logs.stderr:
            break
        time.sleep(.5)
    else:
        raise RuntimeError('browser startup: ' + logs.stdout + logs.stderr)
    root = Path('/tmp/hla-ui-extra-qualification')
    (root / 'browser-control-input.json').write_text(json.dumps([c[3] for c in cases]))
    js = root / 'browser-control.cjs'
    js.write_text("const fs=require('fs');const {chromium}=require('playwright');(async()=>{let b=await chromium.connect(process.argv[2]);let p=await b.newPage();for(const markup of JSON.parse(fs.readFileSync(process.argv[3],'utf8'))){await p.setContent(markup);" + extractor + "console.log(JSON.stringify(semantic));}await b.close()})().catch(e=>{console.error(e);process.exit(1)})")
    env = dict(os.environ, NODE_PATH=str(modules), PATH=frozen.NODE + ':' + os.environ['PATH'])
    lines = subprocess.check_output(['node', str(js), f'ws://127.0.0.1:{port}/', str(root / 'browser-control-input.json')], env=env, text=True).splitlines()
    assert len(lines) == len(cases)
    for (kind, rows, label, _), line in zip(cases, lines):
        groups = json.loads(line)
        try:
            assert_rows(kind, rows, groups)
            passed = True
        except AssertionError:
            passed = False
        assert passed == label.startswith('valid'), (kind, label, groups)
        print(kind, label, 'accepted' if passed else 'rejected')
finally:
    if cid:
        subprocess.run(['docker', 'rm', '-f', cid], capture_output=True)
        inv = subprocess.run(['docker', 'ps', '-a', '--no-trunc', '--format', '{{.ID}}'], capture_output=True, text=True)
        assert inv.returncode == 0 and cid not in inv.stdout.splitlines(), 'owned browser remains'
        print('owned browser absent')
