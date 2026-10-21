/* Real UI, isolated browser storage. Key status/save are intercepted: no real credential is changed. */
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const {chromium}=require('playwright');let browser;
async function run(){
 let configured=false,fail=false;const errors=[];
 browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/cam-key',async route=>{
  if(route.request().method()==='POST'){const data=route.request().postDataJSON();configured=!data.clear&&!!data.wm;}
  await route.fulfill({status:fail?503:200,json:fail?{ok:false}:{ok:true,has_key:configured}});
 });
 await page.goto(process.argv[2]||'http://127.0.0.1:8765');
 await page.waitForFunction(()=>window.SettingsStudio?.instance?.saved&&window.ChaturbateHelp);
 if(await page.locator('#fav-nav').isVisible())await page.locator('nav [data-id="bookmarks"] .chev').click();
 await page.locator('nav [data-id="live"]').click();
 const notice=page.locator('#chaturbate-setup-notice');await notice.waitFor();
 assert.ok((await notice.innerText()).includes('keine aktuelle Chaturbate-Raumliste'));
 await notice.getByRole('button',{name:'Chaturbate jetzt einrichten · Anleitung',exact:true}).click();
 const dialog=page.locator('#chaturbate-tutorial');await dialog.waitFor();
 assert.equal(await dialog.locator('section').count(),5);
 await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});
 assert.equal(await notice.getByRole('button',{name:'Chaturbate jetzt einrichten · Anleitung',exact:true}).evaluate(e=>e===document.activeElement),true);
 await notice.getByRole('button',{name:'Ich habe einen Code · Jetzt eingeben',exact:true}).click();
 const input=page.locator('#set-cam-key');await input.waitFor();assert.equal(await input.evaluate(e=>e===document.activeElement),true);
 await input.fill('UiTestOnly');await page.locator('#set-cam-key-box').getByRole('button',{name:'Speichern',exact:true}).click();
 await notice.waitFor({state:'hidden'});
 await page.locator('nav [data-id="live"]').click();await page.waitForTimeout(200);assert.equal(await notice.isVisible(),false);
 // Removing a code makes the setup explanation visible on the next Live entry.
 await page.locator('nav [data-id="settings"]').click();await page.locator('#ds-tab-live').click();
 await page.locator('#set-cam-key-clear').click();await page.locator('nav [data-id="live"]').click();await notice.waitFor();
 await page.locator('#ui-language').selectOption('en');
 assert.ok((await notice.innerText()).includes('Without your own Chaturbate affiliate code'));
 await notice.getByRole('button',{name:'Set up Chaturbate now · Guide',exact:true}).click();
 await dialog.getByRole('button',{name:'Close tutorial and enter code',exact:true}).click();
 await input.waitFor();assert.equal(await input.evaluate(e=>e===document.activeElement),true);
 // API failures explain an unknown status instead of claiming the code is absent.
 fail=true;await page.locator('nav [data-id="live"]').click();
 await notice.getByRole('heading',{name:'Could not check Chaturbate setup',exact:true}).waitFor();
 fail=false;configured=true;await notice.getByRole('button',{name:'Check status again',exact:true}).click();await notice.waitFor({state:'hidden'});
 configured=false;await page.evaluate(()=>window.ChaturbateHelp.refresh());await notice.waitFor();
 await page.locator('#ui-language').selectOption('de');await page.setViewportSize({width:390,height:844});
 assert.ok(await notice.evaluate(el=>el.getBoundingClientRect().width<=innerWidth));
 const output=path.resolve(__dirname,'../../distribution/chaturbate-live-setup-notice.png');await notice.screenshot({path:output});
 assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,checks:['missing code notice in Live','direct tutorial','Escape focus return','direct settings and focused input','save hides notice','removal restores notice','German and English','tutorial-to-input navigation','unknown status and retry','mobile'],realCredentialsChanged:false,screenshot:output}));
}
run().catch(e=>{console.error(e);process.exitCode=1}).finally(async()=>{await browser?.close()});
