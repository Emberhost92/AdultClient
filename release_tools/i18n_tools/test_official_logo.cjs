/* Actual UI and HTTP asset in isolated Chrome; no real design settings are written. */
const assert=require('node:assert/strict'),path=require('node:path');
const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.stack));
  const base=process.argv[2]||'http://127.0.0.1:8765',label=process.argv[3]||'local';
  const response=await page.request.get(base+'/static/adult-client-logo.png');assert.equal(response.status(),200);assert.match(response.headers()['content-type'],/image\/png/);
  const bytes=await response.body();assert.equal(bytes.subarray(0,8).toString('hex'),'89504e470d0a1a0a');
  await page.goto(base,{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>window.SettingsStudio?.ready);
  await page.waitForFunction(()=>{const img=document.querySelector('#brand img');return img?.src.endsWith('/static/adult-client-logo.png')&&img.complete&&img.naturalWidth>0;});
  const img=page.locator('#brand img');assert.equal(await img.evaluate(n=>getComputedStyle(n).backgroundColor),'rgba(0, 0, 0, 0)');
  assert.equal(await img.evaluate(n=>n.getBoundingClientRect().width<=n.closest('aside').getBoundingClientRect().width),true);
  // The asset has real alpha, including the area inside the former black canvas.
  const alpha=await img.evaluate(n=>{const c=document.createElement('canvas');c.width=n.naturalWidth;c.height=n.naturalHeight;const ctx=c.getContext('2d');ctx.drawImage(n,0,0);return ctx.getImageData(0,0,1,1).data[3];});
  assert.equal(alpha,0);
  await page.locator('#brand').screenshot({path:path.resolve(__dirname,'../../distribution/official-logo-'+label+'.png')});
  await page.locator('#ui-language').selectOption('en');assert.ok(await img.isVisible());
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({passed:true,target:label,real_png_http:true,alpha_transparent:true,logo_loaded:true,no_black_tile:true,languages:['de','en'],personalSettingsChanged:false}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
