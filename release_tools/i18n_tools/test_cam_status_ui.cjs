/* Production UI; provider states are controlled, playback uses a generated test video. */
const assert=require('node:assert/strict'),path=require('node:path');
const {chromium}=require('playwright');
const fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--autoplay-policy=no-user-gesture-required']});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];let mode='private',calls=0,blob='';
  page.on('pageerror',e=>{errors.push(e.stack);console.error(e.stack);});page.on('response',r=>{if(new URL(r.url()).pathname.startsWith('/static/')&&!r.ok())console.error('Asset HTTP',new URL(r.url()).pathname,r.status());});page.on('requestfailed',r=>{if(new URL(r.url()).pathname.startsWith('/static/'))console.error('Asset failed',new URL(r.url()).pathname,r.failure());});
  const base=process.argv[2]||'http://127.0.0.1:8765',label=process.argv[3]||'local';
  await page.route('**/api/cam-library?**',r=>r.fulfill({json:{ok:true,items:[],groups:[],favs:[]}}));
  await page.route('**/api/cam-rooms?**',r=>r.fulfill({json:{ok:true,items:[]}}));
  await page.route('**/api/cam-play?**',r=>{calls++;return r.fulfill({json:mode==='online'?{ok:true,status:'online',room_status:'public',path:blob,sources:[]}:{ok:false,status:mode,room_status:mode,error:mode==='private'?'Private Show · öffentliche Wiedergabe ist derzeit nicht verfügbar.':mode==='offline'?'Das Model ist derzeit offline.':'Das Model ist derzeit abwesend.',retryable:false}});});
  await page.goto(base+'/?page=cam&site=chaturbate&name=Demo_Status',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>window.LiveCamSingle?.instance?.player?.phase==='private');
  assert.ok(await page.locator('.sc-status-overlay').isVisible());assert.equal(await page.locator('.sc-status-title').innerText(),'Private Show');
  await page.locator('.sc-room-status').screenshot({path:path.resolve(__dirname,'../../distribution/cam-status-'+label+'-badge.png')});
  await page.locator('.sc-status-overlay').screenshot({path:path.resolve(__dirname,'../../distribution/cam-status-'+label+'-private.png')});
  const settled=calls;await page.waitForTimeout(1600);assert.equal(calls,settled,'Private show is not retried as a media failure');
  mode='offline';await page.getByRole('button',{name:'Status erneut prüfen',exact:true}).click();await page.waitForFunction(()=>window.LiveCamSingle?.instance?.player?.phase==='offline');
  assert.equal(await page.locator('.sc-status-title').innerText(),'Offline');
  mode='away';await page.getByRole('button',{name:'Status erneut prüfen',exact:true}).click();await page.waitForFunction(()=>window.LiveCamSingle?.instance?.player?.phase==='away');
  assert.equal(await page.locator('.sc-status-title').innerText(),'Abwesend');
  mode='private';await page.getByRole('button',{name:'Status erneut prüfen',exact:true}).click();await page.waitForFunction(()=>window.LiveCamSingle?.instance?.player?.phase==='private');
  await page.evaluate(()=>AppI18n.setLanguage('en'));assert.equal(await page.getByRole('button',{name:'Check status again',exact:true}).isVisible(),true);
  const bytes=Array.from(fs.readFileSync(path.join(__dirname,'fixtures/status.webm')));
  blob=await page.evaluate(bytes=>{
    LiveCamSingle.instance.ctx.proxy=path=>path;LiveCamSingle.instance.video.loop=true;
    return URL.createObjectURL(new Blob([new Uint8Array(bytes)],{type:'video/webm'}));
  },bytes);
  mode='online';await page.evaluate(()=>{LiveCamSingle.instance.lastResolveAt=0;return LiveCamSingle.instance.refreshMeta(true);});
  await page.waitForFunction(()=>{const v=document.querySelector('.sc-screen video');return LiveCamSingle.instance.player?.phase==='playing'&&v.videoWidth===320&&v.currentTime>.1;},{},{timeout:7000}).catch(async e=>{console.error('playback diagnostics',await page.evaluate(()=>{const s=LiveCamSingle.instance,v=s.video;return {phase:s.player?.phase,title:s.player?.title,w:v.videoWidth,h:v.videoHeight,time:v.currentTime,paused:v.paused,ready:v.readyState,error:v.error?.message,src:v.src};}));throw e;});
  assert.equal(await page.locator('.sc-status-overlay').isVisible(),false);
  assert.equal(await page.locator('.sc-room-status').innerText(),'Public live stream');
  assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,target:label,privateVisible:true,offlineAndAwayDistinct:true,noPrivateRetryLoop:true,automaticReturnToPublicWithDecodedFrames:true,languages:['de','en']}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
