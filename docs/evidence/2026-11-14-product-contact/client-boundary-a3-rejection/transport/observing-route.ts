import { getAttentionRecord } from "@/lib/attention-record";
import { isRedirectError } from "next/dist/client/components/redirect";
export const dynamic = "force-dynamic";
export async function GET(request: Request) {
 const u=new URL(request.url); const kind=JSON.parse(u.searchParams.get("kind") || "null"); const key=JSON.parse(u.searchParams.get("key") || "null");
 const original=globalThis.fetch; const secret="<synthetic-sentinel-omitted>"; const fault=new Error("SYNTHETIC_SECRET_99332 synthetic_key_fragment", {cause: new Error("SYNTHETIC_CAUSE_99332")});
 globalThis.fetch=async () => { throw fault; };
 try { const result=await getAttentionRecord(kind,key); return Response.json({result}); }
 catch(e) { if(isRedirectError(e)) throw e; const x=e as Error; return Response.json({thrown:true, same:e===fault, name:x?.name, message:x?.message, cause:x?.cause instanceof Error ? x.cause.message : null}, {status:500}); }
 finally {globalThis.fetch=original;}
}