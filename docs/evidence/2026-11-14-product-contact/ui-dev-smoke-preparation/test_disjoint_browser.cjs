const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const disjoint = require('./disjoint.cjs');
(async () => {
 const browser=await chromium.launch({headless:true});
 try {
  const page=await browser.newPage();
  await page.setContent('<main><ul><li class="row"><dl class="row"><dt>One</dt></dl></li><li class="sibling">Two</li></ul></main>');
  assert.equal(await page.locator('.row').count(),2);
  assert.equal(await page.locator('.row').evaluateAll(disjoint),false,'nested aliases are not two rows');
  assert.equal(await page.locator('li').count(),2);
  assert.equal(await page.locator('li').evaluateAll(disjoint),true,'sibling rows are distinct');
  assert.equal(await page.locator('li.row').count(),1);
  assert.equal(await page.locator('li.row').evaluateAll(disjoint),true,'nested-one is one row');
  console.log('actual Chromium evaluateAll disjoint controls passed');
 } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1});
