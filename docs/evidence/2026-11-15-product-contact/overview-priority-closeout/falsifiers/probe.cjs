'use strict';
const fs=require('node:fs');
const path=require('node:path');
const Module=require('node:module');
const crypto=require('node:crypto');
const root=path.resolve(process.env.HLA_CHECKOUT || process.cwd());
const filename=path.join(root,'apps/web/frontend/lib/overview-priority.js');
const req=Module.createRequire(path.join(root,'apps/web/frontend/package.json'));
const esbuild=req('esbuild');
const source=fs.readFileSync(filename,'utf8');
const {code}=esbuild.transformSync(source,{loader:'js',format:'cjs',sourcefile:filename});
const mod=new Module(filename,module);mod.filename=filename;mod.paths=Module._nodeModulePaths(path.dirname(filename));mod._compile(code,filename);
const rows=JSON.parse(fs.readFileSync(path.join(__dirname,'rows.json'),'utf8'));
const original=JSON.stringify(rows);
console.log(JSON.stringify({node:process.version,esbuild_version:esbuild.version,actual_source_sha256:crypto.createHash('sha256').update(source).digest('hex'),input:rows,
 ordered_ids:mod.exports.sortAttentionItems(rows).map(r=>r.item_id),reversed_input_ordered_ids:mod.exports.sortAttentionItems([...rows].reverse()).map(r=>r.item_id),
 actual_compare_emoji_fullwidth:mod.exports.compareAttention(rows[0],rows[1]),
 title_code_points:Object.fromEntries(rows.map(r=>[r.item_id,Array.from(r.title,c=>c.codePointAt(0))])),
 title_utf16_code_units:Object.fromEntries(rows.map(r=>[r.item_id,Array.from({length:r.title.length},(_,i)=>r.title.charCodeAt(i))])),
 source_values_unchanged:JSON.stringify(rows)===original},null,2));
