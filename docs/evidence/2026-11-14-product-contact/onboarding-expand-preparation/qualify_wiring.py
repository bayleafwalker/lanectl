"""Fail-closed candidate wiring gate against two completed acceptance evidence dirs."""
import argparse,json,xml.etree.ElementTree as ET
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--candidate',required=True);p.add_argument('--mutant',required=True);a=p.parse_args()
c=Path(a.candidate);m=Path(a.mutant)
expected={'initial','partial','optional','auto_core','auto_all','manual_incomplete','dismiss','dismiss_compact','storage_failure_incomplete','expand_core','expand_then_minimise','expand_source_transition','unknown_stored','dismiss_after_override','storage_failure_dismiss','storage_failure'}
def evidence(d):
 snap=json.loads((d/'source-fingerprint.json').read_text());result=json.loads((d/'browser.stdout').read_text());root=ET.parse(d/'junit.xml').getroot();cases=list(root.iter('testcase'))
 assert len(cases)==16 and set(result)==expected and {x.get('name') for x in cases}=={f'test_onboarding[{n}]' for n in expected} and not list(root.iter('skipped')) and not list(root.iter('error'))
 assert (d/'browser.exit').read_text().strip()=='0' and (d/'source-invariance.txt').read_text().strip()=='tracked source unchanged' and (d/'outer-invariance.txt').read_text().strip()=='tracked source unchanged' and (d/'aggregate-errors.txt').read_text().strip()=='none'
 assert 'browser group absent\nNext group absent\nbrowser container absent' in (d/'cleanup.txt').read_text()
 return snap,result,cases
cs,cr,cc=evidence(c);ms,mr,mc=evidence(m)
assert set(cs)==set(ms)
changed=[k for k in cs if cs[k]!=ms[k]]
assert changed==['apps/web/frontend/lib/onboarding-checklist-state.mjs'], f'unexpected mutation paths: {changed}'
assert all(v['ok'] for v in cr.values()) and not list(ET.parse(c/'junit.xml').getroot().iter('failure'))
assert {n for n,v in mr.items() if not v['ok']}=={'expand_core','expand_then_minimise','expand_source_transition','dismiss_after_override','storage_failure'}
assert not mr['expand_core']['ok'] and 'heading' in mr['expand_core']['error'] and 'Get started' in mr['expand_core']['error']
controls=['initial','partial','optional','auto_core','auto_all','manual_incomplete','dismiss','dismiss_compact','storage_failure_incomplete','unknown_stored','storage_failure_dismiss']
assert all(mr[k]['ok'] for k in controls)
print('production helper wiring mutant triggered actual Expand failure; controls preserved')
