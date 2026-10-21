/* Real application fixture, isolated browser profile, synthetic model/user content. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const BASE=process.env.AH_TEST_URL||'http://127.0.0.1:20181';
const executablePath=['C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe','C:/Program Files/Google/Chrome/Application/chrome.exe'].find(fs.existsSync);
const errors=[],misses=new Set(),results=[];
let browser;
async function run(){
 browser=await chromium.launch({headless:true,executablePath});
 const ctx=await browser.newContext({locale:'de-DE'}),page=await ctx.newPage();
 page.on('pageerror',e=>errors.push(e.stack));
 await page.goto(BASE);await page.waitForFunction(()=>window.SettingsStudio?.instance?.saved);
 assert.equal(await page.locator('html').getAttribute('lang'),'de');
 await page.locator('#ui-language').selectOption('en');
 await page.getByRole('button',{name:'Settings',exact:true}).waitFor();
 assert.equal(await page.locator('html').getAttribute('lang'),'en');
 await page.getByRole('button',{name:'Settings',exact:true}).click();
 await page.getByRole('tab',{name:'Colours & fonts',exact:true}).waitFor();
 const tabs=await page.locator('#set-tabs button').all();
 for(const tab of tabs){
   await tab.click();await page.waitForTimeout(60);
   const missing=await page.evaluate(()=>{
     const found=[];const walk=document.createTreeWalker(document.querySelector('#view-settings'),NodeFilter.SHOW_TEXT);
     while(walk.nextNode()){
       const n=walk.currentNode,p=n.parentElement,s=n.nodeValue.trim();
       if(!s||!p||!p.checkVisibility()||p.closest('[translate="no"],[data-i18n-content],script,style,textarea,code'))continue;
       if(/\b(?:Einstellungen|wird|werden|nicht|keine|gespeichert|anzeigen|wählen|Sprache|Schrift|Darstellung|Bilder|Größe|ausgewählt|Schließen|Speichern|Übernehmen|öffnen|hinzufügen)\b/.test(s))found.push(s);
     }return found;
   });
   missing.forEach(s=>misses.add(s));
   results.push('settings:'+await tab.innerText());
 }
 await page.evaluate(()=>{
   const model=document.createElement('p');model.id='i18n-test-model';model.dataset.i18nContent='';model.textContent='Einstellungen · Deutsche Modelbiografie mit unveränderten Tags';document.body.append(model);
   const input=document.createElement('textarea');input.id='i18n-test-draft';input.value='Meine Notizen bleiben genau so';document.body.append(input);
   const status=document.createElement('p');status.id='i18n-test-status';status.textContent='Gespeichert';document.body.append(status);
   const canvas=document.createElement('canvas');canvas.width=160;canvas.height=90;canvas.getContext('2d').fillRect(0,0,160,90);
   const video=document.createElement('video');video.id='i18n-test-video';video.muted=true;video.autoplay=true;video.srcObject=canvas.captureStream(10);document.body.append(video);video.play();
   window.i18nTestTimer=setInterval(()=>{canvas.getContext('2d').fillRect(Math.random()*100,0,2,2);},50);
 });
 await page.waitForFunction(()=>document.querySelector('#i18n-test-status').textContent==='Saved');
 const before=await page.evaluate(()=>({node:!!document.querySelector('#i18n-test-video').srcObject,time:document.querySelector('#i18n-test-video').currentTime}));
 const timings=[];
 for(const language of ['de','en','de','en'])timings.push(await page.evaluate(lang=>{const now=performance.now();AppI18n.setLanguage(lang);return performance.now()-now;},language));
 await page.waitForTimeout(300);
 const after=await page.evaluate(()=>({draft:document.querySelector('#i18n-test-draft').value,model:document.querySelector('#i18n-test-model').textContent,paused:document.querySelector('#i18n-test-video').paused,time:document.querySelector('#i18n-test-video').currentTime,status:document.querySelector('#i18n-test-status').textContent}));
 assert.equal(after.draft,'Meine Notizen bleiben genau so');assert.equal(after.model,'Einstellungen · Deutsche Modelbiografie mit unveränderten Tags');assert.equal(after.status,'Saved');assert.equal(after.paused,false);assert.ok(after.time>before.time);
 assert.ok(Math.max(...timings)<1200,'language switching must remain responsive: '+timings);
 await page.evaluate(()=>{const p=document.createElement('p');p.id='i18n-late';p.textContent='Keine neuen Meldungen';document.body.append(p);});
 await page.waitForFunction(()=>document.querySelector('#i18n-late').textContent==='No new notifications');
 const second=await ctx.newPage();await second.goto(BASE);await second.waitForFunction(()=>window.SettingsStudio?.instance?.saved);
 assert.equal(await second.locator('html').getAttribute('lang'),'en');
 await page.locator('#ui-language').selectOption('de');await second.waitForFunction(()=>document.documentElement.lang==='de');
 await page.reload();await page.waitForFunction(()=>window.SettingsStudio?.instance?.saved);assert.equal(await page.locator('html').getAttribute('lang'),'de');
 assert.deepEqual(errors,[]);
 const report={results,timings,missing:[...misses],errors};fs.writeFileSync(path.join(__dirname,'browser-report.json'),JSON.stringify(report,null,2));
 console.log(JSON.stringify(report,null,2));
 await browser.close();browser=null;
}
run().catch(async e=>{console.error(e);if(browser)await browser.close();process.exitCode=1;});
