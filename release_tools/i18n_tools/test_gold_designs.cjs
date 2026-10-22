/* Exercise real preset buttons; local settings remain untouched. */
const assert=require('node:assert/strict'),path=require('node:path');
const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[];
  page.on('pageerror',e=>errors.push(e.stack));
  const base=process.argv[2]||'http://127.0.0.1:8765',label=process.argv[3]||'local';
  await page.goto(base,{waitUntil:'domcontentloaded'});await page.waitForFunction(()=>window.SettingsStudio?.ready);
  await page.locator('nav [data-id=settings]').click();await page.locator('#ds-tab-look').click();
  const palettes=['Dunkel · Gold','Weiß · Gold','Elfenbein · Gold','Mitternachtsblau · Gold','Salbei · Gold','Aubergine · Gold'];
  const results=[];
  for(const name of palettes){
   await page.locator('#theme-presets button').filter({has:page.locator('span',{hasText:name})}).click();
   await page.evaluate(()=>Promise.all(document.getAnimations().filter(a=>a.effect?.getComputedTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{}))));
   const result=await page.evaluate(()=>{
    const s=getComputedStyle(document.documentElement),d=SettingsStudio.design();
    const bg=s.getPropertyValue('--bg').trim(),text=s.getPropertyValue('--text').trim(),muted=s.getPropertyValue('--muted').trim(),accent=s.getPropertyValue('--accent').trim();
    return {bg,accent,textContrast:SettingsDomain.contrast(text,bg),mutedContrast:SettingsDomain.contrast(muted,bg),buttonContrast:SettingsDomain.contrast(d.colors.buttonText,accent),wall:d.backgrounds.all.mode,profiles:d.profiles.length};
   });
   assert.equal(result.accent,'#d8b56a');assert.ok(result.textContrast>=4.5,name+' text');assert.ok(result.mutedContrast>=4.5,name+' secondary text');assert.ok(result.buttonContrast>=4.5,name+' buttons');assert.equal(result.wall,'legacy');
   results.push({name,...result});
   if(['Dunkel · Gold','Weiß · Gold','Mitternachtsblau · Gold'].includes(name)){
    await page.locator('aside').evaluate(n=>n.scrollTop=0);
    await page.screenshot({path:path.resolve(__dirname,'../../distribution/design-'+label+'-'+palettes.indexOf(name)+'.png')});
    await page.locator('#ds-panel-look .ds-section').first().screenshot({path:path.resolve(__dirname,'../../distribution/design-palette-'+label+'-'+palettes.indexOf(name)+'.png')});
   }
  }
  await page.locator('#ui-language').selectOption('en');
  for(const name of ['Dark · Gold','White · Gold','Ivory · Gold','Midnight Blue · Gold','Sage · Gold'])assert.ok(await page.getByRole('button',{name,exact:true}).isVisible());
  await page.getByRole('button',{name:'White · Gold',exact:true}).click();
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.locator('#theme-presets').evaluate(n=>n.scrollWidth<=n.clientWidth+1),'Preset grid fits a narrow screen');
  await page.setViewportSize({width:1440,height:1100});
  if(label==='portable'){
   await page.getByRole('button',{name:'Save changes',exact:true}).click();
   await page.waitForFunction(()=>!SettingsStudio.instance.dirty);
   await page.reload({waitUntil:'domcontentloaded'});await page.waitForFunction(()=>window.SettingsStudio?.ready);
   assert.equal(await page.evaluate(()=>getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()),'#f7f8fa');
  }else{
   await page.getByRole('button',{name:'Discard draft',exact:true}).click();
   assert.equal(await page.evaluate(()=>SettingsStudio.instance.dirty),false);
  }
  assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,target:label,results,narrowScreen:true,languages:['de','en'],saveAndReload:label==='portable'}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
