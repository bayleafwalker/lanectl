import importlib.util, os
from pathlib import Path
p=Path('/tmp/hla-onboarding-acceptance-portability-r2-20261114/fresh/tests/test_onboarding_expand_acceptance.py');spec=importlib.util.spec_from_file_location('test_harness',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
root=Path('/tmp/hla-onboarding-acceptance-portability-r2-20261114');m.OUT=root/'actual-timeout';m.SCRIPT="console.log('synthetic partial output'); setInterval(()=>{},1000);";m.BROWSER_TIMEOUT=.5
os.environ['HLA_CHROMIUM']='/nix/store/fqriy9vihl23l4md56qgiks8z0d2xdlw-chromium-156.0.8078.79/bin/chromium'
try: m.observations.__wrapped__();raise AssertionError('timeout guard passed')
except AssertionError as e: assert 'browser timeout' in str(e),str(e)
assert 'synthetic partial output' in (m.OUT/'browser.stdout').read_text()
assert 'browser group absent\nNext group absent\nbrowser container absent' in (m.OUT/'cleanup.txt').read_text()
assert (m.OUT/'outer-invariance.txt').read_text().strip()=='tracked source unchanged'
file=m.ROOT/'README.md';original=file.read_bytes();m.OUT=root/'actual-invariance'
def fault(*args): file.write_bytes(original+b'\nsynthetic mutation\n');raise RuntimeError('synthetic setup fault')
m.select_browser=fault
try:
 try:m.observations.__wrapped__();raise AssertionError('mutation guard passed')
 except AssertionError as e: assert 'tracked source changed' in str(e) and 'synthetic setup fault' in str(e),str(e)
finally:file.write_bytes(original)
assert 'tracked source CHANGED' in (m.OUT/'outer-invariance.txt').read_text()
print('actual harness timeout preserved partial log and stopped owned groups; tracked alteration and setup error both reported')
