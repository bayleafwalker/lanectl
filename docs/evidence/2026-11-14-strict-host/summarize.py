import json,re,subprocess,pathlib
root=pathlib.Path('/tmp/lanectl-strict-qualification-20261114')
d=json.loads((root/'sovite-fenced.json').read_text())
def counts(s):
 lines=[re.match(r'^([.sFxE]+)\s*\[\s*\d+%\]',line).group(1) for line in s.splitlines() if re.match(r'^([.sFxE]+)\s*\[\s*\d+%\]',line)]
 p=''.join(lines)
 return {'passed_dot':p.count('.'),'skipped_s':p.count('s'),'failed_F':p.count('F'),'errors_E':p.count('E'),'xfail_x':p.count('x'),'total':len(p),'progress_lines':len(lines)}
units=set(re.findall(r'lanectl-train@(fenced-[0-9a-f]+)\.service',json.dumps(d)))
for name in ('lifecycle.json','setsid.json'):
 units.update(re.findall(r'lanectl-train@(fenced-[0-9a-f]+)\.service',(root/name).read_text()))
units.update(re.findall(r'train (fenced-[0-9a-f]+) timeout',(root/'lifecycle.json').read_text()))
units.update(re.findall(r'lanectl-train@(fenced-[0-9a-f]+)\.service',(root/'network.json').read_text()))
state={}
for u in sorted(units):
 s=subprocess.run(['systemctl','show',f'lanectl-train@{u}.service','-p','ActiveState','-p','SubState'],capture_output=True,text=True,check=True).stdout
 state[u]={'systemctl':s.strip(),'spool_exists':pathlib.Path('/var/lib/lanectl-train/trains',u).exists()}
result={'source_sha':'00d29faa84415ca802a68247f98294072b5d4c7d','host_runtime':str(pathlib.Path('/run/current-system').resolve()),'client_python':str(pathlib.Path('/home/bayleaf/.local/share/uv/tools/lanectl/bin/python').resolve()),'parser':'lines matching ^([.sFxE]+)\\s*\\[\\s*\\d+%\\]; concatenate captured symbols and count each','baseline':counts((root/'sovite-baseline.log').read_text()),'strictroot':counts(d['result']['check']['stdout']),'named_units':state,'note':'Boundary/probes harnesses do not retain generated unit names; their successful client return establishes terminal receipt and removal through client path. Named units listed are those retained in other evidence.'}
(root/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
