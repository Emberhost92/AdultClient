// Production hover handlers and Hls.js, with real decoded synthetic HLS video.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.argv[2]||'http://127.0.0.1:8765',label=process.argv[3]||'local';
const baseline=process.argv[4]==='before';
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--autoplay-policy=no-user-gesture-required']});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],reports=[];let resolves=0;
  page.setDefaultTimeout(30000);page.on('pageerror',e=>{errors.push(e.message);console.error('Browser:',e.message);});
  await page.addInitScript(()=>localStorage.setItem('ah-cam-preview',JSON.stringify({on:false,rate:'off',hover:true,delay:0,zoom:100,quality:'auto'})));
  if(baseline){const old=fs.readFileSync(path.resolve(__dirname,'../../distribution/AdultClient-0.3.10-beta.1/app/static/app.html'),'utf8').replace('<script src="/static/portable.js"></script>','');assert.ok(!old.includes('let camHoverWarm'));await page.route(base+'/',r=>r.fulfill({body:old,contentType:'text/html'}));}
  await page.route('**/api/cam-play?**',async r=>{resolves++;await new Promise(done=>setTimeout(done,450));await r.fulfill({json:{ok:true,path:'/__hover_test__/index.m3u8'}});});
  await page.route('**/__hover_test__/**',r=>{const name=new URL(r.request().url()).pathname.split('/').pop();assert.match(name,/^(index\.m3u8|part-\d+\.ts)$/);return r.fulfill({path:path.join(__dirname,'fixtures/hover-hls',name),contentType:name.endsWith('.ts')?'video/mp2t':'application/vnd.apple.mpegurl',headers:{'Access-Control-Allow-Origin':'*'}});});
  await page.goto(base);await page.locator('#app').waitFor({state:'visible'});await page.waitForFunction(()=>window.Hls);
  await page.evaluate(()=>{
   const host=document.createElement('section');host.id='hover-speed-test';host.style.cssText='position:fixed;left:300px;top:150px;width:500px;height:400px;z-index:200;background:#222';document.body.append(host);
   state.view='live';camView='rooms';
   window.addHoverCard=site=>{
    stopCamPreview();host.replaceChildren();const card=document.createElement('article');card.id='hover-card';card.className='card';card.style.cssText='width:320px;height:220px';card.innerHTML='<button class="cam-open" style="width:320px;height:180px"></button>';
    card._camRoom={site,name:'Demo_Hover',online:true,show:'public',age:30};
    card.addEventListener('mouseenter',()=>camHoverEnter(card,card._camRoom));card.addEventListener('mouseleave',()=>camHoverLeave(card));host.append(card);
   };
  });
  for(const site of ['stripchat','chaturbate','bongacams','camsoda','cam4','xlovecam']){
   await page.mouse.move(20,20);await page.evaluate(s=>window.addHoverCard(s),site);const before=resolves,start=Date.now();
   await page.locator('#hover-card .cam-open').hover();
   await page.waitForFunction(()=>{const v=document.querySelector('#hover-card video');return v&&!v.paused&&v.getVideoPlaybackQuality().totalVideoFrames>0;});
   const first=Date.now()-start;
   await page.evaluate(()=>{window.hoverFirstVideo=document.querySelector('#hover-card video');window.hoverFrameCount=hoverFirstVideo.getVideoPlaybackQuality().totalVideoFrames;});
   await page.mouse.move(20,20);await page.waitForFunction(()=>window.hoverFirstVideo.paused);
   await page.waitForTimeout(100);const returned=Date.now();await page.locator('#hover-card .cam-open').hover();
   if(baseline)await page.waitForFunction(()=>{const v=document.querySelector('#hover-card video');return v&&!v.paused&&v.getVideoPlaybackQuality().totalVideoFrames>0;});
   else await page.waitForFunction(()=>!window.hoverFirstVideo.paused&&!window.hoverFirstVideo.hidden&&window.hoverFirstVideo.getVideoPlaybackQuality().totalVideoFrames>window.hoverFrameCount);
   const repeat=Date.now()-returned;assert.equal(resolves-before,baseline?2:1,'Returning must reuse the media connection');if(!baseline)assert.ok(repeat<450,'Resume must beat the simulated resolver delay');
   assert.equal(await page.evaluate(()=>document.querySelector('#hover-card video')===window.hoverFirstVideo),!baseline);
   reports.push({site,first_frame_ms:first,return_frame_ms:repeat,resolver_calls:resolves-before});
   await page.mouse.move(20,20);await page.evaluate(()=>{document.querySelector('#hover-card').dataset.lmStatus='private';});
   await page.locator('#hover-card .cam-open').hover();assert.equal(await page.evaluate(()=>window.hoverFirstVideo.paused),true);
  }
  if(!baseline){
   await page.mouse.move(20,20);const before=resolves;await page.evaluate(()=>{
    window.addHoverCard('chaturbate');const card=document.querySelector('#hover-card');card.dataset.camOn='1';
    Object.assign(camPreviewState(),{on:true,rate:'live'});window.pendingGrid=camPreviewConnect(card,card._camRoom,0,camPreviewSeq);
   });
   await page.waitForFunction(()=>document.querySelector('#hover-card').dataset.camPlay==='wait');
   await page.locator('#hover-card .cam-open').hover();
   await page.waitForFunction(()=>{const v=document.querySelector('#hover-card video');return v&&!v.paused&&v.getVideoPlaybackQuality().totalVideoFrames>0;});
   assert.equal(resolves-before,1,'Hover must not add a second resolver to the already pending grid request');
  }
  await page.evaluate(()=>stopCamPreview());assert.equal(await page.locator('#hover-speed-test video').count(),0);assert.deepEqual(errors,[]);
  const result={label,source:'real HLS decoding; simulated 450 ms provider resolution; no real accounts',reports,errors};
  fs.writeFileSync(path.join(__dirname,`hover-speed-${label}.json`),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
