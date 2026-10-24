const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
const base=process.argv[2]||'http://127.0.0.1:8765',label=process.argv[3]||'local';
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--autoplay-policy=no-user-gesture-required']});
 try{
  const page=await browser.newPage({viewport:{width:1500,height:1050}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/cam-library?**',r=>r.fulfill({json:{ok:true,items:[],groups:[],favs:[]}}));
  await page.route('**/api/cam-rooms?**',r=>r.fulfill({json:{ok:true,items:[]}}));
  await page.route('**/api/cam-play?**',r=>r.fulfill({json:{ok:false,status:'offline',error:'Teststream'}}));
  page.setDefaultTimeout(20000);console.log('Loading',label);await page.goto(base+'/?page=cam-multi',{waitUntil:'domcontentloaded'});console.log('Page loaded');
  await page.waitForFunction(()=>window.LiveCamStudio?.instance?.root?.isConnected).catch(async e=>{console.log(await page.evaluate(()=>({body:document.body.innerText.slice(-1500),studio:!!window.LiveCamStudio,view:typeof camView==='undefined'?'none':camView})));throw e;});console.log('Studio mounted');
  await page.evaluate(async()=>{
   const s=LiveCamStudio.instance,D=LiveCamDomain;
   const models=Array.from({length:4},(_,i)=>({site:'chaturbate',name:'Layout_Demo_'+i,online:true,show:'public'}));
   s.absorb(models,true);
   await s.change(data=>{const w=data.workspaces.find(w=>w.id===s.workspaceId);w.slots=models.map(D.key).concat(Array(16).fill(null));Object.assign(w.settings,{layout:'grid',capacity:4,fit:'cover'});});
  });
  await page.waitForFunction(()=>LiveCamStudio.instance.players.size===4);
  await page.evaluate(async()=>{
   const s=LiveCamStudio.instance;
   for(const [i,p] of [...s.players.values()].entries()){
    clearTimeout(p.retryTimer);p.video.removeAttribute('src');const c=document.createElement('canvas');c.width=i%2?360:640;c.height=i%2?640:360;
    const cx=c.getContext('2d');cx.fillStyle='#d8b86a';cx.fillRect(0,0,c.width,c.height);cx.fillStyle='#31688e';cx.fillRect(12,12,c.width-24,c.height-24);
    p.video.srcObject=c.captureStream(15);await p.video.play();s.applyPlayer(p);
   }s.layout();
  });
  assert.deepEqual(await page.locator('.lc-video video').evaluateAll(v=>v.map(n=>getComputedStyle(n).objectFit)),Array(4).fill('contain'));
  await page.getByLabel('Ansicht',{exact:true}).selectOption('mosaic');
  await page.getByLabel('Plätze',{exact:true}).selectOption('6');
  await page.waitForFunction(()=>LiveCamStudio.instance.config().capacity===6&&document.querySelectorAll('.lc-empty:not([hidden])').length===2);
  const rects=await page.locator('.lc-tile').evaluateAll(nodes=>nodes.map(n=>{const r=n.getBoundingClientRect();return {w:r.width,h:r.height,hidden:n.hidden};}));
  assert.equal(rects.length,6);assert.ok(rects.every(r=>!r.hidden&&r.w>50&&r.h>50));
  await page.screenshot({path:path.resolve(__dirname,'../../distribution/multicam-layout-'+label+'.png'),fullPage:true});
  await page.getByLabel('Plätze',{exact:true}).selectOption('4');
  await page.waitForFunction(()=>LiveCamStudio.instance.config().capacity===4&&document.querySelectorAll('.lc-tile').length===4);
  assert.equal(await page.evaluate(()=>LiveCamStudio.instance.players.size),4);
  await page.getByLabel('Ansicht',{exact:true}).selectOption('grid');
  assert.deepEqual(await page.locator('.lc-video video').evaluateAll(v=>v.map(n=>getComputedStyle(n).objectFit)),Array(4).fill('contain'));
  assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,target:label,gridWholeImage:true,mosaicCapacity:'4 → 6 → 4',occupiedStreamsPreserved:true}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
