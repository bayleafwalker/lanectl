/* Browser observation only: never reports pass. Inputs: trusted API/SQL facts,
   selectors inspected against the future candidate, and loopback web URL. */
const fs = require('fs');
const componentsDisjoint = require('./disjoint.cjs');
if (!/^ID=ubuntu$/m.test(fs.readFileSync('/etc/os-release','utf8'))) throw Error('browser container must be Ubuntu');
if (require('playwright/package.json').version !== '1.59.1') throw Error('wrong Playwright version');
const { chromium } = require('playwright');
const [web, factsPath, selectorPath, outputPath] = process.argv.slice(2);
const url = new URL(web);
if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || !url.port || url.pathname !== '/' || url.search || url.hash) throw Error('web URL must be exact loopback origin');
const facts = JSON.parse(fs.readFileSync(factsPath));
const s = JSON.parse(fs.readFileSync(selectorPath));
for (const key of ['queue','queueRow','title','severity','link','cashflow','detail','components']) if (typeof s[key] !== 'string' || !s[key]) throw Error('missing selector '+key);
(async () => {
 const browser = await chromium.launch({headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:960}});
  await page.goto(new URL('/login',web).href,{waitUntil:'networkidle'});
  await page.locator('#username').fill('admin');
  await page.locator('#password').fill('replace-me-local-admin-password');
  await page.locator('button[type=submit]').click();
  await page.goto(new URL('/operating-picture',web).href,{waitUntil:'networkidle'});
  if (page.url().includes('/login')) throw Error('login failed');
  const queue=page.locator(s.queue), cashflow=page.locator(s.cashflow);
  if (await queue.count()!==1 || await cashflow.count()!==1 || !(await queue.isVisible()) || !(await cashflow.isVisible())) throw Error('ambiguous or hidden queue or cashflow');
  const queueCurrent=/current report/i.test(await queue.innerText());
  const distinct=await queue.evaluate((q,sel)=>{const c=document.querySelector(sel);return !!c && !q.contains(c) && !c.contains(q);},s.cashflow);
  const rows=queue.locator(s.queueRow), observed=[];
  for (let i=0;i<await rows.count();i++) {
   const row=rows.nth(i), link=row.locator(s.link);
   if (await link.count()!==1 || !(await row.isVisible()) || !(await link.isVisible()) || !(await row.locator(s.title).isVisible()) || !(await row.locator(s.severity).isVisible())) throw Error('ambiguous or hidden row content');
   const href=await link.getAttribute('href');
   const dest=new URL(href,web);
   if(dest.origin!==url.origin || dest.search || dest.hash) throw Error('detail link outside bound web origin');
   observed.push({title:(await row.locator(s.title).innerText()).trim(),label:(await row.locator(s.severity).innerText()).trim(),href:dest.pathname});
  }
  const details={};
  for(let i=0;i<observed.length;i++) {
   const candidates=facts.feed.filter(x=>x.title===observed[i].title);
   if(candidates.length!==1) throw Error('ambiguous feed title; supply independently reviewed locator mapping');
   const key=candidates[0].item_id;
   await page.goto(new URL('/operating-picture',web).href,{waitUntil:'networkidle'});
   await page.locator(s.queue).locator(s.queueRow).nth(i).locator(s.link).click();
   await page.waitForLoadState('networkidle');
   const clicked=new URL(page.url());
   if(clicked.origin!==url.origin || clicked.search || clicked.hash) throw Error('click escaped bound web origin');
   let detail=page.locator(s.detail);
   if(await detail.count()!==1 || !(await detail.isVisible())) throw Error('ambiguous or hidden detail');
   const groups=detail.locator(s.components); for(let j=0;j<await groups.count();j++) if (!(await groups.nth(j).isVisible())) throw Error('hidden component group');
   if (!(await groups.evaluateAll(componentsDisjoint))) throw Error('overlapping component groups on click');
   const text=await detail.innerText();
   const components=await detail.locator(s.components).allInnerTexts();
   await page.goto(new URL(observed[i].href,web).href,{waitUntil:'networkidle'});
   const direct=new URL(page.url());
   if(direct.origin!==url.origin || direct.search || direct.hash) throw Error('deep link escaped bound web origin');
   detail=page.locator(s.detail);
   if(await detail.count()!==1 || !(await detail.isVisible())) throw Error('ambiguous or hidden direct detail');
   const directGroups=detail.locator(s.components);
   for(let j=0;j<await directGroups.count();j++) if (!(await directGroups.nth(j).isVisible())) throw Error('hidden direct component group');
   if (!(await directGroups.evaluateAll(componentsDisjoint))) throw Error('overlapping component groups on direct load');
   if(await detail.innerText()!==text || JSON.stringify(await directGroups.allInnerTexts())!==JSON.stringify(components)) throw Error('click and deep link render different content');
   details[key]={click_url:clicked.pathname,direct_url:direct.pathname,current_report:/current report/i.test(text),text,components};
  }
  fs.writeFileSync(outputPath,JSON.stringify({queue:observed,queue_current_report:queueCurrent,cashflow_distinct:distinct,details},null,2),{flag:'wx',mode:0o600});
 } finally { await browser.close(); }
})().catch(err=>{console.error(err.message);process.exitCode=1});
