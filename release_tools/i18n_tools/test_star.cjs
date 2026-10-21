const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');let browser;
async function run(){
 browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe'});
 const context=await browser.newContext();await context.route('https://**/*',r=>r.abort());
 await context.route('**/api/star-finder/profile?*',async route=>{
   const response=await route.fetch(),data=await response.json();
   data.bio='Einstellungen';if(data.extra){data.extra.about='Einstellungen';data.extra.awards=['Speichern'];}
   data.tags=['Einstellungen'];if(data.all_facts?.length)data.all_facts[0].value='Einstellungen';
   await route.fulfill({response,json:data});
 });
 const page=await context.newPage(),errors=[],missing=new Set(),visited=[];page.on('pageerror',e=>errors.push(e.stack));
 await page.goto('http://127.0.0.1:20091');await page.waitForFunction(()=>SettingsStudio?.instance?.saved);
 await page.locator('nav [data-id="stars"]').click();
 await page.getByRole('button',{name:'Demo Model 1',exact:true}).click();
 await page.locator('.sf-biography').first().waitFor();const biography=await page.locator('.sf-biography').first().innerText();
 await page.locator('#ui-language').selectOption('en');
 assert.equal(await page.locator('.sf-biography').first().innerText(),biography);
 assert.equal(await page.locator('.sf-fact-cards .sf-stat strong').first().innerText(),'Einstellungen');
 assert.ok((await page.locator('.sf-pane').innerText()).includes('Speichern'),'model award data must not be translated as a Save button');
 const tabs=await page.locator('.sf-tabs button').all();
 for(const tab of tabs){
  await tab.click();await page.waitForTimeout(150);visited.push(await tab.innerText());
  const rows=await page.evaluate(()=>{
    const found=[],walker=document.createTreeWalker(document.querySelector('.sf-pane'),NodeFilter.SHOW_TEXT);
    while(walker.nextNode()){
      const n=walker.currentNode,p=n.parentElement,s=n.nodeValue.trim();
      if(!s||!p?.checkVisibility()||p.closest('[translate="no"],[data-i18n-content],.sf-biography,.sf-badges,.sf-source-value,.sf-tag-filter,script,style,textarea'))continue;
      if(/\b(?:wird|werden|nicht|keine|gespeichert|anzeigen|wählen|Schließen|Speichern|Übernehmen|öffnen|hinzufügen|verfügbar|Unbekannt|Quellen|Vorbereitet)\b/.test(s))found.push(s);
    }return found;
  });rows.forEach(s=>missing.add(s));
 }
 const note=page.locator('.sf-pane textarea').first();await note.fill('Meine unveränderten Notizen');
 await page.locator('#ui-language').selectOption('de');assert.equal(await note.inputValue(),'Meine unveränderten Notizen');
 await page.locator('#ui-language').selectOption('en');assert.equal(await note.inputValue(),'Meine unveränderten Notizen');
 assert.deepEqual(errors,[]);
 const report={visited,model_biography_unchanged:true,notes_unchanged:true,missing:[...missing],errors};fs.writeFileSync(path.join(__dirname,'star-report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
 await browser.close();browser=null;
}
run().catch(async e=>{console.error(e);if(browser)await browser.close();process.exitCode=1;});
