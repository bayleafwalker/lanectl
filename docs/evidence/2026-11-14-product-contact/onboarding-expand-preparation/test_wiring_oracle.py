import json, subprocess, sys, tempfile, xml.etree.ElementTree as ET
from pathlib import Path
root=Path('/tmp/hla-onboarding-acceptance-draft-20261114'); orig=root/'repaired-final'; data=json.loads((orig/'browser.stdout').read_text())
with tempfile.TemporaryDirectory(prefix='hla-oracle-selftest-') as temp:
 temp=Path(temp)
 def create(name,mutant):
  d=temp/name;d.mkdir();values={k:{'ok':True} for k in data}
  if mutant:
   for n in ('expand_core','expand_then_minimise','expand_source_transition','dismiss_after_override','storage_failure'):values[n]={'ok':False,'error':'heading Get started missing'}
  (d/'browser.stdout').write_text(json.dumps(values));(d/'browser.exit').write_text('0\n');(d/'source-invariance.txt').write_text('tracked source unchanged\n');(d/'outer-invariance.txt').write_text('tracked source unchanged\n');(d/'aggregate-errors.txt').write_text('none\n');(d/'cleanup.txt').write_text('browser group absent\nNext group absent\nbrowser container absent\n');(d/'source-fingerprint.json').write_text(json.dumps({'apps/web/frontend/lib/onboarding-checklist-state.mjs':['file',str(mutant)]}))
  suite=ET.Element('testsuite');[ET.SubElement(suite,'testcase',name='test_onboarding['+k+']') for k in values];ET.ElementTree(suite).write(d/'junit.xml');return d
 c=create('candidate',False);m=create('mutant',True);cmd=[sys.executable,str(root/'qualify_wiring.py'),'--candidate',str(c),'--mutant',str(m)]
 good=subprocess.run(cmd,capture_output=True,text=True);assert good.returncode==0,good.stderr
 (m/'browser.stdout').write_text((c/'browser.stdout').read_text());bad=subprocess.run(cmd,capture_output=True,text=True);assert bad.returncode!=0,'oracle accepted mutant that did not fail'
 (m/'browser.stdout').unlink();missing=subprocess.run(cmd,capture_output=True,text=True);assert missing.returncode!=0,'oracle accepted missing evidence'
 print('oracle mechanics: positive synthetic fixture accepted; no-failure and missing-evidence falsifiers rejected (not candidate evidence)')
