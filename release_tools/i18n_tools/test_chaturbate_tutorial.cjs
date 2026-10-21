/* Real app in an isolated profile; no personal keys or provider traffic. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {spawn}=require('node:child_process'),{chromium}=require('playwright');
const workspace=path.resolve(__dirname,'../..');
const release=process.argv[2]||'AdultClient-0.3.0-beta.1';
const fixture=fs.mkdtempSync(path.join(workspace,'distribution/ac-tutorial-test-')),root=path.join(fixture,'program'),profile=path.join(fixture,'profile');
fs.cpSync(path.join(workspace,'distribution',release),root,{recursive:true,filter:file=>!['data','userdata','build-source','__pycache__'].includes(path.basename(file))});
fs.mkdirSync(profile);fs.writeFileSync(path.join(profile,'update-settings.json'),JSON.stringify({automatic:false,beta:true}));
if(!process.argv[2])for(const name of ['app.html','chaturbate_tutorial.js','tutorials'])fs.cpSync(path.join(workspace,'AdultHideoutWeb/static',name),path.join(root,'app/static',name),{recursive:true});
if(!process.argv[2])fs.copyFileSync(path.join(workspace,'AdultHideoutWeb/server.py'),path.join(root,'app/server.py'));
const server=spawn(path.join(root,'runtime/pythonw.exe'),[path.join(root,'app/portable_entry.py')],{cwd:root,windowsHide:true,env:{...process.env,AC_TEST_PROFILE:profile,AC_TEST_NO_BROWSER:'1'}});
const pause=ms=>new Promise(r=>setTimeout(r,ms));let browser,base;const errors=[];
async function run(){
 for(let i=0;i<180;i++){try{base=JSON.parse(fs.readFileSync(path.join(profile,'instance.json'))).url;if((await fetch(base+'/api/health')).ok)break;}catch{}await pause(500);}
 assert.ok(base);
 browser=await chromium.launch({headless:true,executablePath:['C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe','C:/Program Files/Google/Chrome/Application/chrome.exe'].find(fs.existsSync)});
 const page=await browser.newPage({viewport:{width:1440,height:1100}});page.on('pageerror',e=>errors.push(e.message));
 await page.route('https://**/*',r=>r.abort());
 await page.goto(base);await page.waitForFunction(()=>window.SettingsStudio?.instance?.saved,{},{timeout:90000}).catch(async error=>{console.log(JSON.stringify({errors,title:await page.title(),body:(await page.locator('body').innerText()).slice(0,500)}));throw error});
 await page.locator('nav [data-id="settings"]').click();await page.locator('#ds-tab-live').click();
 const input=page.locator('#set-cam-key');await input.fill('UNSAVED-EXAMPLE');
 // Actual input form, without any stored user credential; do not publish the tutorial button recursively.
 await input.fill('');await page.locator('#set-cam-key-box').screenshot({path:path.join(workspace,'AdultHideoutWeb/static/tutorials/chaturbate-settings.png')});
 fs.copyFileSync(path.join(workspace,'AdultHideoutWeb/static/tutorials/chaturbate-settings.png'),path.join(root,'app/static/tutorials/chaturbate-settings.png'));
 await input.fill('UNSAVED-EXAMPLE');
 await page.getByRole('button',{name:'Chaturbate einrichten · Anleitung',exact:true}).click();
 const dialog=page.locator('#chaturbate-tutorial');
 if(!await dialog.count())console.log(JSON.stringify({diagnostic:await page.evaluate(async()=>({script:document.querySelector('script[src*="chaturbate"]')?.outerHTML,response:await fetch('/static/chaturbate_tutorial.js').then(async r=>({status:r.status,type:r.headers.get('content-type'),start:(await r.text()).slice(0,100)}))})),errors}));
 await dialog.waitFor({state:'visible'});assert.equal(await dialog.locator('section').count(),5);
 assert.equal(await dialog.locator('a').count(),3);
 for(const anchor of await dialog.locator('a').all()){assert.ok((await anchor.getAttribute('href')).startsWith('https://chaturbate.com/affiliates/'));assert.equal(await anchor.getAttribute('target'),'_blank');}
 await page.waitForFunction(()=>[...document.querySelectorAll('#chaturbate-tutorial img')].every(i=>i.complete&&i.naturalWidth>0));
 await page.screenshot({path:path.join(workspace,'distribution/chaturbate-tutorial-deutsch.png')});
 // Change language during an open dialog, as a second browser tab would do.
 await page.evaluate(()=>AppI18n.setLanguage('en'));await page.getByRole('heading',{name:'Set up Chaturbate step by step',exact:true}).waitFor();
 assert.ok((await dialog.innerText()).includes('made-up example code'));
 await page.screenshot({path:path.join(workspace,'distribution/chaturbate-tutorial-english.png')});
 await page.getByRole('button',{name:'Close tutorial and enter code',exact:true}).click();
 await input.waitFor();await page.waitForFunction(()=>document.activeElement?.id==='set-cam-key');assert.equal(await input.inputValue(),'UNSAVED-EXAMPLE');
 await page.getByRole('button',{name:'Set up Chaturbate · Tutorial',exact:true}).click();await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});
 await page.locator('#ui-language').selectOption('de');await page.getByRole('button',{name:'Chaturbate einrichten · Anleitung',exact:true}).waitFor();
 // Narrow viewport: help remains scrollable and all controls remain reachable.
 await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'Chaturbate einrichten · Anleitung',exact:true}).click();
 assert.ok(await dialog.evaluate(d=>d.getBoundingClientRect().width<=window.innerWidth&&d.scrollHeight>d.clientHeight));
 await page.getByRole('button',{name:'Anleitung schließen und Code eingeben',exact:true}).click();
 assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,release,checks:['settings button','official links','both screenshots load','German/English while open','input unchanged','focus restored','Escape','mobile scrolling'],errors}));
}
run().catch(e=>{console.error(e);process.exitCode=1}).finally(async()=>{if(browser)await browser.close();if(base)try{await fetch(base+'/api/distribution',{method:'POST',headers:{'Content-Type':'application/json',Origin:base},body:JSON.stringify({op:'shutdown'})})}catch{}await pause(2000);if(server.exitCode===null)server.kill();await pause(500);fs.rmSync(fixture,{recursive:true,force:true,maxRetries:8,retryDelay:500});});

