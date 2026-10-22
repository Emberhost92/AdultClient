// Read-only public provider playback probe. Never log signed URLs or credentials.
const {chromium}=require('playwright'),fs=require('node:fs'),path=require('node:path');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--autoplay-policy=no-user-gesture-required']});
 const reports=[];
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(30000);
  await page.addInitScript(()=>localStorage.setItem('ah-cam-preview',JSON.stringify({on:false,rate:'off',hover:true,delay:0,zoom:100,quality:'auto'})));
  await page.goto('http://127.0.0.1:8765');await page.locator('#app').waitFor({state:'visible'});
  await page.evaluate(()=>{state.view='live';camView='rooms';const card=document.createElement('article');card.id='provider-hover-probe';card.className='card';card.style.cssText='position:fixed;left:320px;top:140px;width:320px;height:220px;z-index:200;background:#222';card.innerHTML='<button class="cam-open" style="width:320px;height:180px"></button>';document.body.append(card);card.addEventListener('mouseenter',()=>camHoverEnter(card,card._camRoom));card.addEventListener('mouseleave',()=>camHoverLeave(card));});
  for(const site of ['stripchat','chaturbate','bongacams','camsoda','cam4','xlovecam']){
   const report={site,first_frame:false};
   try{
    await page.mouse.move(20,20);
    const ready=await page.evaluate(async site=>{
     stopCamPreview();const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),20000);
     try{const p=await fetch('/api/cam-rooms?site='+site+'&gender=all',{signal:controller.signal}).then(r=>r.json());
      const room=p.items?.find(r=>r.online!==false&&!['private','privat','away','offline','hidden'].includes(r.show)&&(!r.age||r.age>=18));
      if(!p.ok||!room)return false;document.querySelector('#provider-hover-probe')._camRoom=room;return true;
     }finally{clearTimeout(timer);}
    },site);
    if(!ready){report.result='No public room available';reports.push(report);console.log(JSON.stringify(report));continue;}
    const start=Date.now();await page.locator('#provider-hover-probe .cam-open').hover();
    await page.waitForFunction(()=>{const v=document.querySelector('#provider-hover-probe video');return v&&!v.paused&&v.getVideoPlaybackQuality().totalVideoFrames>0;},null,{timeout:25000});
    report.first_frame=true;report.first_frame_ms=Date.now()-start;
    await page.evaluate(()=>{window.probeVideo=document.querySelector('#provider-hover-probe video');window.probeFrames=probeVideo.getVideoPlaybackQuality().totalVideoFrames;});
    await page.mouse.move(20,20);await page.waitForTimeout(150);const back=Date.now();await page.locator('#provider-hover-probe .cam-open').hover();
    await page.waitForFunction(()=>!probeVideo.paused&&!probeVideo.hidden&&probeVideo.getVideoPlaybackQuality().totalVideoFrames>probeFrames,null,{timeout:5000});
    report.return_frame_ms=Date.now()-back;
   }catch{report.result=report.first_frame?'First playback confirmed; return could not be confirmed':'No decoded video within probe timeout';}
   finally{await page.evaluate(()=>stopCamPreview()).catch(()=>{});}
   reports.push(report);console.log(JSON.stringify(report));
  }
  fs.writeFileSync(path.join(__dirname,'hover-real-provider-check.json'),JSON.stringify({at:new Date().toISOString(),reports},null,2));
 }finally{await browser.close();}
})().catch(()=>{console.error('Provider probe could not complete');process.exitCode=1;});
