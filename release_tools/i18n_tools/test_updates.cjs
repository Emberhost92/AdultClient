/* Actual portable app, isolated profile; synthetic update feed for UI states. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {spawn}=require('node:child_process'),{chromium}=require('playwright');
const workspace=path.resolve(__dirname,'../..'),root=path.join(workspace,'distribution/AdultClient-0.3.0-beta.1');
const profile=fs.mkdtempSync(path.join(workspace,'distribution/ac-update-ui-'));
const testRoot=path.join(profile,'program');
// Keep the UI fixture small even when the complete release contains its 1.6 GB seed.
fs.cpSync(root,testRoot,{recursive:true,filter:file=>!['data','userdata','build-source','__pycache__'].includes(path.basename(file))});
const write=(name,value)=>{const file=path.join(profile,name);fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,JSON.stringify(value));};
write('update-settings.json',{automatic:false,beta:true});
const candidate=(kind)=>({version:kind==='program'?'0.4.0':'2026-11-01T00:00:00Z',available:true,notes:'Update test release notes',manifest:{version:'0.4.0',created:'2026-11-01T00:00:00Z',bytes:1024*1024,sha256:'1'.repeat(64)}});
write('updates/discovery.json',{repository:'Emberhost92/AdultClient',beta:true,checked:Date.now()/1000,available:{program:candidate('program'),data:candidate('data')}});
const server=spawn(path.join(testRoot,'runtime/pythonw.exe'),[path.join(testRoot,'app/portable_entry.py')],{cwd:testRoot,windowsHide:true,env:{...process.env,AC_TEST_PROFILE:profile,AC_TEST_NO_BROWSER:'1'}});
const pause=ms=>new Promise(r=>setTimeout(r,ms));
let browser,base;
const errors=[];
async function run(){
  for(let i=0;i<180;i++){
    try{base=JSON.parse(fs.readFileSync(path.join(profile,'instance.json'))).url;if((await fetch(base+'/api/health')).ok)break;}catch(_){}
    await pause(500);
  }
  assert.ok(base,'server started');
  const executablePath=['C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe','C:/Program Files/Google/Chrome/Application/chrome.exe'].find(fs.existsSync);
  browser=await chromium.launch({headless:true,executablePath});
  const page=await browser.newPage({viewport:{width:1440,height:1100}});
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base);await page.waitForFunction(()=>window.SettingsStudio?.instance?.saved);
  await page.locator('#portable-update-notice').waitFor({state:'visible'});
  await page.locator('#portable-update-notice').click();
  await page.locator('#ds-panel-updates').waitFor({state:'visible'});
  await page.getByRole('button',{name:'Programmupdate herunterladen',exact:true}).waitFor();
  assert.ok(await page.getByRole('button',{name:'Modelldaten herunterladen',exact:true}).isEnabled());
  await page.locator('#ui-language').selectOption('en');
  await page.getByRole('button',{name:'Download program update',exact:true}).waitFor();
  assert.ok(await page.getByRole('button',{name:'Download model data',exact:true}).isEnabled());
  assert.equal(await page.locator('[data-preference="automatic"]').isChecked(),false);
  await page.screenshot({path:path.join(workspace,'distribution/update-settings-english.png'),fullPage:false});
  await page.locator('#ui-language').selectOption('de');
  await page.getByRole('button',{name:'Nach Updates suchen',exact:true}).waitFor();
  await page.screenshot({path:path.join(workspace,'distribution/update-settings-deutsch.png'),fullPage:false});
  const current=await (await fetch(base+'/api/distribution')).json();
  let posts=[];
  await page.route('**/api/distribution',async route=>{
    const body=route.request().postDataJSON();
    if(body)posts.push(body);
    const data=structuredClone(current);
    if(body?.op==='program-update')data.update={running:true,kind:'program',phase:'download',done:524288,total:1048576,message:''};
    if(body?.op==='data-update')data.update={running:false,kind:'data',phase:'ready',done:1048576,total:1048576,message:''},data.pending=true;
    await route.fulfill({json:data});
  });
  await page.getByRole('button',{name:'Programmupdate herunterladen',exact:true}).click();
  await page.getByRole('progressbar').waitFor();
  assert.equal(await page.getByRole('progressbar').getAttribute('value'),'524288');
  assert.ok(await page.getByRole('button',{name:'Modelldaten herunterladen',exact:true}).isDisabled());
  await page.unroute('**/api/distribution');
  // Real endpoint persists settings; no external requests are made when automatic is off.
  await page.locator('#ds-tab-look').click();await page.locator('#ds-tab-updates').click();
  await pause(5500);
  await page.locator('[data-preference="beta"]').uncheck();
  await page.waitForFunction(async()=>!(await (await fetch('/api/distribution')).json()).preferences.beta);
  assert.equal(JSON.parse(fs.readFileSync(path.join(profile,'update-settings.json'))).beta,false);
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({passed:true,checks:['global update notice opens settings','independent program/data buttons','instant German/English switch','download progress','parallel download prevented','settings persisted'],posts,errors}));
}
run().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{
  if(browser)await browser.close();
  if(base)try{await fetch(base+'/api/distribution',{method:'POST',headers:{'Content-Type':'application/json','Origin':base},body:JSON.stringify({op:'shutdown'})});}catch(_){}
  await pause(2500);if(server.exitCode===null)server.kill();await pause(500);
  fs.rmSync(profile,{recursive:true,force:true,maxRetries:8,retryDelay:500});
});
