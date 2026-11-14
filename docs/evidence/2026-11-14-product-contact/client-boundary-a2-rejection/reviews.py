import concurrent.futures, pathlib, subprocess, json
repo=pathlib.Path('/projects/dev/_wt/hla-boundary-qualification-20261114')
out=pathlib.Path('/tmp/hla-boundary-candidate-qualification-20261114')
diff=(out/'worker.diff').read_text()
base='''Independently review ONLY the immutable worker diff below (seed d25fbe193f35a33d097f0c90776bd28ce578caaa, candidate eff30fe4f4d832eb48f2eb96f619037d21c5c414). Planner acceptance is in seed and is not worker diff. This is a public frontend typed reader/codec prerequisite, not the four-kind UI. Requirements: exact UTF-8 canonical key, authorized four generated API row contracts, status before error body, strict envelope/field scalar validation, no warehouse fallback, invented fields, decimal coercion, or suppressed auth. Full UI remains required. Product intention: docs/product/core-household-operating-picture.md and docs/plans/kotona-operating-picture-brief.md. Follow the selected specialist prompt exactly. Review source and references with Read/Grep/Glob as useful. Output ONLY a JSON array of findings with severity (blocker/advisory/watchlist), file, line, finding, evidence, recommendation, blocker (boolean). Return [] if none. State any missing evidence in a finding. Do not modify files or run commands.\n\nSELECTED SPECIALIST PROMPT:\n'''
def go(p):
 name=p.stem; prompt=base+p.read_text()+'\n\nWORKER DIFF:\n'+diff
 (out/(name+'.prompt.txt')).write_text(prompt)
 with (out/(name+'.json')).open('w') as stdout, (out/(name+'.stderr')).open('w') as stderr:
  r=subprocess.run(['claude','-p','--model','claude-sonnet-5-5','--output-format','json','--restricted','--strict-mcp-config','--tools','Read,Grep,Glob','--allowedTools','Read,Grep,Glob','--permission-prompts','none'],input=prompt,text=True,cwd=repo,stdout=stdout,stderr=stderr)
 (out/(name+'.exit')).write_text(str(r.returncode)+'\n')
 return name,r.returncode
ps=sorted((repo/'.agents/overlays/review-specialists').glob('*.md'))
with concurrent.futures.ThreadPoolExecutor(max_workers=7) as pool:
 for name,rc in pool.map(go,ps): print(name,rc,flush=True)
