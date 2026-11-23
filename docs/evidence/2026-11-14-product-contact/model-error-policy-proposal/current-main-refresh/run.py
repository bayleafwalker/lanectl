from pathlib import Path
import subprocess,json,time
p=Path(__file__).resolve().parent
start=time.monotonic()
with (p/'native-review.json').open('w') as out, (p/'native-review.stderr').open('w') as err:
 r=subprocess.run(['claude','-p','--model','claude-sonnet-5-5','--output-format','json','--restricted','--strict-mcp-config','--tools','Read,Grep,Glob','--allowedTools','Read,Grep,Glob','--permission-prompts','none'],input=(p/'prompt.txt').read_text(),text=True,cwd='/projects/dev/_wt/lanectl-model-error-policy-20261114',stdout=out,stderr=err)
result={'returncode':r.returncode,'elapsed_s':round(time.monotonic()-start,3),'requested_model':'claude-sonnet-5-5','preparation_only':True,'canonical_activated':False}
(p/'execution.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result),flush=True)
raise SystemExit(r.returncode)
