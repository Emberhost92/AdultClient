/* Real local/portable settings; intercept GitHub draft navigation so no issue is submitted. */
const assert=require('node:assert/strict'),path=require('node:path');
const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000},permissions:['clipboard-read','clipboard-write']});
  const page=await context.newPage(),errors=[],external=[];
  page.on('pageerror',e=>errors.push(e.message));
  await context.route('https://github.com/**',route=>{external.push(route.request().url());return route.fulfill({contentType:'text/html',body:'<h1>GitHub draft test. No issue submitted.</h1>'});});
  // Delay schema to test mounting after asynchronous settings initialization.
  await page.route('**/static/settings_schema.json',async route=>{await new Promise(r=>setTimeout(r,400));await route.continue();});
  await page.goto(process.argv[2]||'http://127.0.0.1:8765',{waitUntil:'domcontentloaded'});
  await page.locator('nav [data-id="settings"]').click();await page.locator('#ds-tab-feedback').click();
  const form=page.locator('#ac-feedback-form');await form.waitFor();
  assert.equal(await external.length,0);
  const link=form.getByRole('link',{name:'Meldung auf GitHub vorbereiten',exact:true});
  await link.click();assert.equal(await form.evaluate(n=>n.checkValidity()),false);assert.equal(external.length,0);
  await page.locator('#feedback-title').fill('Player & Größe? <Test>');
  await page.locator('#feedback-description').fill('Der Player bleibt beim Vergrößern stehen. ÄÖÜ & ? #');
  await page.locator('#feedback-area').selectOption('live');
  await page.locator('#feedback-steps').fill('1. Live öffnen\n2. Größe ändern');
  await page.locator('#feedback-expected').fill('Das Bild wird größer.');
  let url=new URL(await link.getAttribute('href'));
  assert.equal(url.origin,'https://github.com');assert.equal(url.searchParams.has('labels'),false,'Ordinary users must not need label permissions');assert.equal(url.pathname,'/Emberhost92/AdultClient/issues/new');
  assert.equal(url.searchParams.get('template'),'bug_report.md');assert.equal(url.searchParams.get('title'),'[Bug][live] Player & Größe? <Test>');
  assert.match(url.searchParams.get('body'),/### Beschreibung/);assert.match(url.searchParams.get('body'),/ÄÖÜ & \? #/);assert.match(url.searchParams.get('body'),/Browser: Chrome/);
  await page.locator('#feedback-environment').uncheck();url=new URL(await link.getAttribute('href'));assert.ok(!url.searchParams.get('body').includes('Browser:'));
  await page.locator('#feedback-kind').selectOption('wish');assert.equal(new URL(await link.getAttribute('href')).searchParams.get('template'),'feature_request.md');
  await page.locator('#feedback-kind').selectOption('feedback');assert.equal(new URL(await link.getAttribute('href')).searchParams.get('template'),'feedback.md');
  await page.locator('#ui-language').selectOption('en');
  const englishLink=form.getByRole('link',{name:'Prepare report on GitHub',exact:true});
  assert.equal(await page.locator('#feedback-title').inputValue(),'Player & Größe? <Test>');assert.equal(await page.locator('#feedback-environment').isChecked(),false);
  assert.match(new URL(await englishLink.getAttribute('href')).searchParams.get('body'),/### Description/);
  await form.getByRole('button',{name:'Copy text',exact:true}).click();
  const copied=await page.evaluate(()=>navigator.clipboard.readText());assert.match(copied,/\[Feedback\]\[live\]/);assert.match(copied,/### Description/);
  const popupPromise=page.waitForEvent('popup');await englishLink.click();const popup=await popupPromise;await popup.waitForLoadState();
  assert.equal(external.length,1);assert.equal(new URL(external[0]).searchParams.get('template'),'feedback.md');await popup.close();
  await page.locator('#feedback-description').fill('😀'.repeat(900));
  await form.getByRole('link',{name:'Open GitHub · paste the text there',exact:true}).waitFor();assert.equal(new URL(await form.locator('.ac-feedback-primary').getAttribute('href')).searchParams.has('body'),false);
  assert.match(await form.getByRole('status').innerText(),/too long/);
  await page.locator('#feedback-description').fill('The player freezes when resizing.');await page.locator('#feedback-environment').check();
  await page.locator('nav [data-id="home"]').click();await page.locator('nav [data-id="settings"]').click();await page.locator('#ds-tab-feedback').click();assert.equal(await page.locator('#feedback-title').inputValue(),'Player & Größe? <Test>');
  await page.locator('#ui-language').selectOption('de');await page.setViewportSize({width:390,height:844});
  assert.ok(await form.evaluate(n=>n.getBoundingClientRect().width<=innerWidth));
  assert.deepEqual(errors,[]);
  await page.setViewportSize({width:1440,height:1000});
  await page.locator('#ac-feedback').screenshot({path:path.resolve(__dirname,'../../distribution/github-feedback-form.png')});
  console.log(JSON.stringify({passed:true,checks:['settings category','delayed settings mount','required fields','encoded title and body','three GitHub labels','optional visible context','German/English with preserved draft','clipboard','real popup to GitHub draft','long URL fallback','draft survives navigation','mobile'],issuesCreated:0}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
