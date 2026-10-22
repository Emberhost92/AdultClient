const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const url=process.argv[2]||'http://127.0.0.1:8765',label=process.argv[3]||'local';
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 try{
  const page=await browser.newPage({viewport:{width:1920,height:1200}});page.setDefaultTimeout(45000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(url);await page.locator('#app').waitFor({state:'visible'});const entered=Date.now();await page.locator('[data-view="live"]').click();
  await page.locator('#cam-discover-grid .lm-card').first().waitFor();const firstCards=Date.now()-entered;
  const counts=await page.locator('#cam-discover-grid .lm-card').count();assert.ok(counts>0&&counts<=240);
  const measured=await page.evaluate(async()=>{
   const view=LiveCamDiscover.instance,oldGet=view.ctx.get,oldRefresh=view.refresh;
   const calls=[],paints=[],start=performance.now();
   view.ctx.get=async function(url,...args){if(!url.startsWith('/api/cam-rooms?'))return oldGet.call(this,url,...args);const site=new URL(url,location.origin).searchParams.get('site');calls.push({site,ms:performance.now()-start});await new Promise(r=>setTimeout(r,site==='xlovecam'?2200:100));return {ok:true};};
   view.refresh=async function(...args){await oldRefresh.apply(this,args);paints.push(performance.now()-start);};
   try{await view.updateStatus();return {calls,paints,total:performance.now()-start};}
   finally{view.ctx.get=oldGet;view.refresh=oldRefresh;}
  });
  assert.equal(new Set(measured.calls.map(r=>r.site)).size,6);assert.ok(Math.max(...measured.calls.map(r=>r.ms))<100);
  assert.ok(measured.paints[0]<2100,'Faster hosts must appear before the slow one completes');
  await page.locator('#cam-discover-root input[type="search"]').fill('Demo_');
  await page.waitForTimeout(1000);await page.locator('#cam-discover-root input[type="search"]').fill('');
  await page.locator('#cam-discover-grid .lm-card').first().waitFor({state:'visible'});
  assert.ok(await page.locator('#cam-discover-grid .lm-card').count()>0);
  assert.deepEqual(errors,[]);
  const report={label,url,first_cards_ms:firstCards,cards:counts,controlled_slow_provider:measured,errors};
  fs.writeFileSync(path.join(__dirname,`live-catalog-${label}.json`),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
