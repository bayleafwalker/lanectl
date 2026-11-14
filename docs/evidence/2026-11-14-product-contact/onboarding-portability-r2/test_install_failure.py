import importlib.util,tempfile
from pathlib import Path
p=Path('/tmp/hla-onboarding-acceptance-portability-r2-20261114/fresh/tests/test_onboarding_expand_acceptance.py');s=importlib.util.spec_from_file_location('harness',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
m.OUT=Path('/tmp/hla-onboarding-acceptance-portability-r2-20261114/install-failure')
with tempfile.TemporaryDirectory(prefix='hla-fake-npm-') as temp:
 path=Path(temp);node=path/'node';node.write_text('#!/bin/sh\necho v20.20.1\n');node.chmod(0o700);npm=path/'npm';npm.write_text('#!/bin/sh\necho synthetic install failure >&2\nexit 72\n');npm.chmod(0o700);m.NODE=str(node)
 try:m.observations.__wrapped__();raise AssertionError('install failure accepted')
 except AssertionError as exc: assert 'locked npm ci failed' in str(exc),str(exc)
assert (m.OUT/'npm-ci.exit').read_text().strip()=='72';assert 'synthetic install failure' in (m.OUT/'npm-ci.stderr').read_text();assert (m.OUT/'deps-cleanup.txt').read_text().strip()=='owned dependency directory absent';assert (m.OUT/'outer-invariance.txt').read_text().strip()=='tracked source unchanged'
print('install failure surfaced as infrastructure error; logs, source invariance and owned dependency cleanup confirmed')
