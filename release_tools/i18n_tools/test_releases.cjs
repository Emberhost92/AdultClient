const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');let browser;
async function run(){
 browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe'});
 const reports=[];
 for(const [name,base]of [['pc','http://127.0.0.1:8765'],['portable','http://127.0.0.1:18765']]){
  const ctx=await browser.newContext({viewport:{width:1550,height:1050}}),p=await ctx.newPage(),errors=[];
  p.on('pageerror',e=>errors.push(e.stack));await p.goto(base);await p.waitForFunction(()=>window.SettingsStudio?.instance?.saved,null,{timeout:60000});
  await p.locator('nav [data-id="settings"]').click();await p.locator('#ui-language').selectOption('en');
  await p.getByRole('tab',{name:'Colours & fonts',exact:true}).waitFor();
  await p.screenshot({path:path.resolve(__dirname,'../../distribution/'+name+'-ui-english.png')});
  await p.locator('#ui-language').selectOption('de');await p.getByRole('tab',{name:'Farben & Schriften',exact:true}).waitFor();
  await p.screenshot({path:path.resolve(__dirname,'../../distribution/'+name+'-ui-deutsch.png')});
  if(name==='portable'){
   await p.locator('#ui-language').selectOption('en');await p.getByRole('tab',{name:'Updates & model images',exact:true}).click();
   await p.getByRole('button',{name:'Prepare model data update',exact:true}).waitFor();
   await p.getByRole('button',{name:'Check for updates',exact:true}).click();
   const expected=await p.evaluate(()=>AppI18n.t('Noch kein Veröffentlichungs-Repository eingerichtet. Es wurde nichts hochgeladen.'));
   await p.getByText(expected,{exact:false}).waitFor({timeout:10000});
  }
  assert.deepEqual(errors,[]);reports.push({version:name,de:true,en:true,errors});await ctx.close();
 }
 console.log(JSON.stringify(reports,null,2));fs.writeFileSync(path.join(__dirname,'releases-report.json'),JSON.stringify(reports,null,2));await browser.close();browser=null;
}
run().catch(async e=>{console.error(e);if(browser)await browser.close();process.exitCode=1;});
