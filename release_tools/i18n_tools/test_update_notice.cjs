/* Actual settings/navigation UI with isolated, mocked update discovery; no downloads. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  const state={ok:true,repository:'Emberhost92/AdultClient',version:'0.3.4-beta.1',preferences:{automatic:true,beta:true},check:{running:false,checked:1,error:''},available:{program:null,data:null},update:{running:false},images:{stored:0,stored_bytes:0,done:0,failed:0},package:null};
  let reads=0;
  await page.route('**/api/distribution',route=>{reads++;return route.fulfill({json:state});});
  await page.route('**/static/settings_schema.json',async route=>{await new Promise(r=>setTimeout(r,700));await route.continue();});
  const base=process.argv[2]||'http://127.0.0.1:8765';
  if(!process.argv[2]){
   await page.route('**/static/settings_studio.js',route=>route.fulfill({contentType:'text/javascript',body:fs.readFileSync(path.resolve(__dirname,'../../AdultHideoutWeb/static/settings_studio.js'),'utf8').replace('["tools", "Speicher & Extras",','["updates", "Updates & Modellbilder", "Programm, Datenpakete und Offline-Bilder"],\n    ["tools", "Speicher & Extras",')}));
  }
  await page.goto(base,{waitUntil:'domcontentloaded'});
  if(!process.argv[2])await page.addScriptTag({path:path.resolve(__dirname,'../portable.js')});
  const notice=page.locator('#portable-update-notice');
  await page.waitForFunction(()=>document.querySelector('#portable-update-notice'));
  assert.equal(await notice.isVisible(),false);
  const candidate={available:true,version:'0.4.0',manifest:{bytes:1024},notes:'Example'};
  async function refresh(){const before=reads;await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await page.waitForFunction(()=>document.querySelector('#portable-update-notice'));await assertEventually(()=>reads>before);await page.waitForTimeout(50);}
  state.available.program=candidate;await refresh();
  await notice.waitFor();assert.match(await notice.innerText(),/Update verfügbar · Programm/);
  assert.equal(await notice.evaluate(n=>n.previousElementSibling.dataset.id),'settings');
  await notice.click();await page.locator('#ds-panel-updates').waitFor();
  await page.getByRole('heading',{name:'Updates & Modellbilder',exact:true}).waitFor();
  assert.equal(await page.locator('[data-preference="automatic"]').isChecked(),true);
  state.available.data=candidate;await refresh();assert.match(await notice.innerText(),/Programm \+ Modelldaten/);
  state.available.program=null;await refresh();assert.match(await notice.innerText(),/Update verfügbar · Modelldaten/);
  await page.locator('#ui-language').selectOption('en');assert.match(await notice.innerText(),/Update available · Model data/);
  state.pending=true;await refresh();assert.match(await notice.innerText(),/Update ready/);
  state.install_result={ok:false,error:'Example'};await refresh();assert.match(await notice.innerText(),/Update failed/);
  state.pending=false;state.install_result=null;state.available.data=null;await refresh();assert.equal(await notice.isVisible(),false);
  state.available.program=candidate;await refresh();
  // Rebuilding/reordering the menu must keep the status immediately under Settings.
  await page.evaluate(()=>document.querySelector('nav').prepend(document.querySelector('#portable-update-notice')));
  await assertEventually(async()=>await notice.evaluate(n=>n.previousElementSibling?.dataset.id==='settings'));
  await page.locator('#ui-language').selectOption('de');
  await page.locator('nav [data-id="live"]').click();
  await notice.screenshot({path:path.resolve(__dirname,'../../distribution/update-menu-notice.png')});
  const before=reads;await page.waitForTimeout(1200);assert.ok(reads-before<=1,'No polling or observer loop');
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({passed:true,checks:['hidden when current','under Settings','opens update settings','automatic enabled','program/data/both','pending and failure','German/English','menu reorder','no observer loop'],downloadsTriggered:false}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
async function assertEventually(check){for(let i=0;i<60;i++){if(await check())return;await new Promise(r=>setTimeout(r,50));}throw Error('Condition did not become true');}
