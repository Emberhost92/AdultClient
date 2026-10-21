const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const BASE='http://127.0.0.1:19990';
let browser;const errors=[],missing=new Set(),visited=[];
async function scan(page){
 const rows=await page.evaluate(()=>{
   const out=[],walker=document.createTreeWalker(document.querySelector('main'),NodeFilter.SHOW_TEXT);
   while(walker.nextNode()){
    const n=walker.currentNode,p=n.parentElement,s=n.nodeValue.trim();
    if(!s||!p?.checkVisibility()||p.closest('[translate="no"],[data-i18n-content],.sf-biography,script,style,textarea,code'))continue;
    if(/\b(?:Einstellungen|wird|werden|nicht|keine|gespeichert|anzeigen|wählen|Sprache|Schrift|Darstellung|Bilder|Größe|ausgewählt|Schließen|Speichern|Übernehmen|öffnen|hinzufügen|verfügbar|Räume|Gruppen|Ausgeschaltet|Unbekannt)\b/.test(s))out.push(s);
   }return out;
 });rows.forEach(s=>missing.add(s));
}
async function run(){
 browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe'});
 const ctx=await browser.newContext({viewport:{width:1500,height:1050}});await ctx.route('https://**/*',r=>r.abort());
 const page=await ctx.newPage();page.on('pageerror',e=>errors.push(e.stack));
 await page.goto(BASE);await page.waitForFunction(()=>window.SettingsStudio?.instance?.saved);
 await page.locator('#ui-language').selectOption('en');
 await page.locator('nav [data-id="live"]').click();
 await page.locator('[data-cam-view="models"]').waitFor();
 const ids=await page.locator('[data-cam-view]').evaluateAll(nodes=>nodes.map(n=>n.dataset.camView));
 for(const id of [...new Set(ids)]){
  const node=page.locator('[data-cam-view="'+id+'"]');
  if(!await node.isVisible())continue;
  await node.click();await page.waitForTimeout(500);await scan(page);visited.push(id);
 }
 await page.locator('[data-cam-view="models"]').click();await page.locator('#cam-panel-models .lm-row,#cam-panel-models .lm-card').first().waitFor();
 const details=page.locator('#cam-panel-models').getByRole('button',{name:'Details',exact:true}).first();
 if(await details.count()){await details.click();await page.waitForTimeout(300);await scan(page);visited.push('model-details');}
 const report={visited,missing:[...missing],errors};fs.writeFileSync(path.join(__dirname,'live-report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
 assert.deepEqual(errors,[]);await browser.close();browser=null;
}
run().catch(async e=>{console.error(e);if(browser)await browser.close();process.exitCode=1;});
