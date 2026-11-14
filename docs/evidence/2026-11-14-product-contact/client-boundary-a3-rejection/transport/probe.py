import pathlib, json, sys
import fixture
fixture.ROOT=pathlib.Path('/projects/dev/_wt/lanes/hla-attention-client-boundary-a3'); fixture.WEB=fixture.ROOT/'apps/web/frontend'; fixture.PINNED_MODULES=fixture.WEB/'node_modules'
fixture.BOUNDARY_ROUTE='''import { getAttentionRecord } from "@/lib/attention-record";
import { isRedirectError } from "next/dist/client/components/redirect";
export const dynamic = "force-dynamic";
export async function GET(request: Request) {
 const u=new URL(request.url); const kind=JSON.parse(u.searchParams.get("kind") || "null"); const key=JSON.parse(u.searchParams.get("key") || "null");
 const original=globalThis.fetch; const secret="<synthetic-sentinel-omitted>"; const fault=new Error("SYNTHETIC_SECRET_99332 synthetic_key_fragment", {cause: new Error("SYNTHETIC_CAUSE_99332")});
 globalThis.fetch=async () => { throw fault; };
 try { const result=await getAttentionRecord(kind,key); return Response.json({result}); }
 catch(e) { if(isRedirectError(e)) throw e; const x=e as Error; return Response.json({thrown:true, same:e===fault, name:x?.name, message:x?.message, cause:x?.cause instanceof Error ? x.cause.message : null}, {status:500}); }
 finally {globalThis.fetch=original;}
}'''
root=pathlib.Path('/tmp/hla-transport-a3-independent-20261114'); item='SYNTHETIC_KEY_99332'; out=[]
with fixture.Lab(root/'lab') as lab:
 for kind in fixture.SEGMENTS:
  status,headers,payload=lab.call(kind,fixture.key(item)); result=json.loads(payload); result.update({'kind':kind,'http_status':status}); out.append(result); print(json.dumps(result),flush=True)
 print(json.dumps({'next_pid':lab.proc.pid,'fixture_root':str(lab.copy),'backend_source':'unchanged copied candidate','node':fixture.NODE}),flush=True)
print(json.dumps({'lab_cleanup_complete':True}),flush=True)
(root/'results.json').write_text(json.dumps(out,indent=2))
