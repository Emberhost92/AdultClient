const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');let browser;
async function run(){
 browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe'});
 const context=await browser.newContext();await context.route('https://**/*',r=>r.abort());
 const page=await context.newPage(),errors=[],missing=new Set(),visited=[];page.on('pageerror',e=>errors.push(e.stack));
 await page.goto('http://127.0.0.1:20181');await page.waitForFunction(()=>SettingsStudio?.instance?.saved);
 await page.locator('#ui-language').selectOption('en');
 for(const id of ['home','sites','search','downloads','offline','profile','stats','multi']){
  await page.locator('nav [data-id="'+id+'"]').click();await page.waitForTimeout(300);visited.push(id);
  const rows=await page.evaluate(()=>{
    const found=[],walker=document.createTreeWalker(document.querySelector('main'),NodeFilter.SHOW_TEXT);
    while(walker.nextNode()){
      const n=walker.currentNode,p=n.parentElement,s=n.nodeValue.trim();
      if(!s||!p?.checkVisibility()||p.closest('[translate="no"],[data-i18n-content],script,style,textarea,code'))continue;
      if(/\b(?:Einstellungen|wird|werden|nicht|keine|gespeichert|anzeigen|wählen|Sprache|Darstellung|Größe|ausgewählt|Schließen|Speichern|Übernehmen|öffnen|hinzufügen|verfügbar|Unbekannt)\b/.test(s))found.push(s);
    }return found;
  });rows.forEach(s=>missing.add(s));
 }
 const report={visited,missing:[...missing],errors};fs.writeFileSync(path.join(__dirname,'menus-report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
 assert.deepEqual(errors,[]);await browser.close();browser=null;
}
run().catch(async e=>{console.error(e);if(browser)await browser.close();process.exitCode=1;});
