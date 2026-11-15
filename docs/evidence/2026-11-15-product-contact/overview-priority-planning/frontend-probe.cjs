'use strict';
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const root='/projects/dev/homelab-analytics/apps/web/frontend';
const req=Module.createRequire(path.join(root,'package.json'));
const esbuild=req('esbuild');
const React=req('react');
const {renderToStaticMarkup}=req('react-dom/server');
const records=fs.readFileSync('/tmp/hla-overview-priority-prerequisite-20261115/probe.stdout','utf8').trim().split('\n').map(JSON.parse).filter(x=>x.stage==='http');
const generic=({children})=>React.createElement(React.Fragment,null,children);
function compile(rel, overrides) {
 const file=path.join(root,rel);
 const code=esbuild.transformSync(fs.readFileSync(file,'utf8'),{loader:'jsx',format:'cjs',jsx:'automatic',sourcefile:file}).code;
 const mod=new Module(file,module);mod.filename=file;mod.paths=Module._nodeModulePaths(path.dirname(file));
 const orig=Module._load;
 Module._load=function(request,parent,isMain){if(parent===mod && Object.hasOwn(overrides,request)) return overrides[request];return orig.call(this,request,parent,isMain)};
 try { mod._compile(code,file); } finally {Module._load=orig}
 return mod.exports;
}
const view=compile('components/operating-picture-view.js',{
 './eyebrow':{Eyebrow:generic}, './freshness-pulse':{FreshnessPulse:generic}, './horizon-strip':{HorizonStrip:generic}, './num-mono':{NumMono:generic}, './pill':{Pill:generic}, './spark':{Spark:generic}, '../lib/state-indicators':{stateIndicatorBadge:()=>({})}, '../lib/format':{formatMoney:String}
});
const shell=({children})=>React.createElement(React.Fragment,null,children);
(async()=>{
 for (const record of records) {
  const items=record.body.rows;
  const backend=new Proxy({}, {get:(_target,key)=>async()=>key==='getCurrentUser'?{role:'admin'}:key==='getAttentionItems'?structuredClone(items):[]});
  const common={'@/components/app-shell':{AppShell:shell},'@/lib/backend':backend,'@/lib/format':{formatMoney:String,formatMonth:String},'@/components/operating-picture-view':view};
  const op=compile('app/operating-picture/page.js',common);
  const tree=await op.default();
  const children=React.Children.toArray(tree.props.children);
  const viewElement=children.find(c=>c.type===view.OperatingPictureView);
  const ranked=viewElement.props.rankedAttention;
  const html=renderToStaticMarkup(tree);
  const review=compile('app/review/page.js',common);
  const reviewHtml=renderToStaticMarkup(await review.default({searchParams:{}}));
  const opTitles=ranked.map(x=>x.title);
  const reviewTitles=items.map(x=>x.title).sort((a,b)=>reviewHtml.indexOf(a)-reviewHtml.indexOf(b));
  const opLabels=[...html.matchAll(/>(urgent|soon|watch)</g)].map(m=>m[1]);
  console.log(JSON.stringify({mode:record.mode,input:items.map(x=>({id:x.item_id,severity:x.severity})),operating:ranked.map(x=>({id:x.item_id,severity:x.severity})),operating_labels:opLabels,operating_titles:opTitles,review_titles:reviewTitles}));
  if(ranked.map(x=>x.severity).join(',')!=='1,2,2,3,3') throw Error('unexpected operating order');
  if(opLabels.join(',')!=='urgent,soon,soon,watch,watch') throw Error('unexpected operating labels');
  if(reviewTitles[0]!==items.find(x=>x.severity===3).title) throw Error('unexpected review priority');
 }
})().catch(e=>{console.error(e.stack||String(e));process.exitCode=1});
