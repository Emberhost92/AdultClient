/* Real portable server and HLS decoder; generated video replaces external providers. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {spawn,execFileSync}=require('node:child_process'),{chromium}=require('playwright');
const workspace=path.resolve(__dirname,'../..'),root=path.join(workspace,'distribution/AdultClient-0.3.2-beta.1');
const fixture=fs.mkdtempSync(path.join(workspace,'distribution/ac-preview-test-')),profile=path.join(fixture,'profile'),media=path.join(fixture,'media');
fs.mkdirSync(profile);fs.mkdirSync(media);fs.writeFileSync(path.join(profile,'update-settings.json'),JSON.stringify({automatic:false}));
const ffmpeg=fs.readdirSync(path.join(workspace,'output/media-tools/imageio_ffmpeg/binaries')).find(n=>n.endsWith('.exe'));
execFileSync(path.join(workspace,'output/media-tools/imageio_ffmpeg/binaries',ffmpeg),['-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc2=size=320x180:rate=12','-t','8','-c:v','libx264','-pix_fmt','yuv420p','-g','12','-hls_time','1','-hls_list_size','0','-hls_playlist_type','vod',path.join(media,'test.m3u8')]);
const server=spawn(path.join(root,'runtime/pythonw.exe'),[path.join(root,'app/portable_entry.py')],{cwd:root,windowsHide:true,env:{...process.env,AC_TEST_PROFILE:profile,AC_TEST_NO_BROWSER:'1'}});
const pause=ms=>new Promise(r=>setTimeout(r,ms));let browser,base;const errors=[],requests=[];
async function run(){
 for(let i=0;i<180;i++){try{base=JSON.parse(fs.readFileSync(path.join(profile,'instance.json'))).url;if((await fetch(base+'/api/health')).ok)break}catch{}await pause(500)}
 assert.ok(base);const port=Number(new URL(base).port);assert.ok(port>=18765);
 // Media-only listeners deliberately reject the UI health endpoint with 404.
 for(const offset of [1,2,9,21])assert.equal((await fetch(`http://127.0.0.1:${port+offset}/api/health`)).status,404);
 browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 const page=await browser.newPage();page.on('pageerror',e=>errors.push(e.message));
 await page.route('https://**/*',r=>r.abort());
 await page.route('**/api/cam-play?**',async r=>{requests.push(r.request().url());await r.fulfill({json:{ok:true,path:'https://fixture.invalid/test.m3u8'},headers:{'access-control-allow-origin':base}})});
 await page.route('**/api/stream?**',async r=>{
  requests.push(r.request().url());const origin=new URL(r.request().url()).origin;
  const body=fs.readFileSync(path.join(media,'test.m3u8'),'utf8').split('\n').map(line=>line.endsWith('.ts')?origin+'/fixture/'+line:line).join('\n');
  await r.fulfill({body,contentType:'application/vnd.apple.mpegurl',headers:{'access-control-allow-origin':base}});
 });
 await page.route('**/fixture/**',async r=>{requests.push(r.request().url());await r.fulfill({body:fs.readFileSync(path.join(media,path.basename(new URL(r.request().url()).pathname))),contentType:'video/mp2t',headers:{'access-control-allow-origin':base}})});
 await page.goto(base);await page.waitForFunction(()=>window.Hls&&typeof camPreviewConnect==='function');
 for(const slot of [0,47]){
  await page.evaluate(async slot=>{
   camPreview={...camPreviewDefaults(),on:true,rate:'live'};
   const card=document.createElement('article');card.id='portable-preview-proof';card.className='card';card.dataset.camOn='1';card.innerHTML='<button class="cam-open" type="button"></button>';
   document.body.prepend(card);await camPreviewConnect(card,{site:'stripchat',name:'GeneratedTest'},slot,camPreviewSeq);
  },slot);
  await page.waitForFunction(()=>document.querySelector('#portable-preview-proof video')?.currentTime>1,{},{timeout:20000});
  const before=await page.locator('#portable-preview-proof video').evaluate(v=>({time:v.currentTime,frames:v.getVideoPlaybackQuality().totalVideoFrames,width:v.videoWidth}));
  await page.waitForFunction(time=>document.querySelector('#portable-preview-proof video')?.currentTime>time+.5,before.time,{timeout:10000});
  assert.equal(before.width,320);assert.ok(before.frames>1);
  await page.evaluate(()=>{const card=document.querySelector('#portable-preview-proof');camPreviewDropCard(card);card.remove()});
 }
 assert.ok(requests.some(url=>url.startsWith(`http://127.0.0.1:${port+2}/api/cam-play?`)));
 assert.ok(requests.some(url=>url.startsWith(`http://127.0.0.1:${port+9}/api/cam-play?`)));
 assert.ok(requests.every(url=>Number(new URL(url).port)>port));assert.deepEqual(errors,[]);
 const report={passed:true,browser:'Chrome',portablePort:port,checks:['real media listeners','cam discovery on portable origins','HLS manifest and segments','decoded moving video','slot wrap at 47'],externalProviderPlaybackTested:false};
 fs.writeFileSync(path.join(workspace,'distribution/PORTABLE-PREVIEW-0.3.2.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}
run().catch(e=>{console.error(e);process.exitCode=1}).finally(async()=>{await browser?.close();if(base)try{await fetch(base+'/api/distribution',{method:'POST',headers:{'Content-Type':'application/json',Origin:base},body:JSON.stringify({op:'shutdown'})})}catch{}await pause(1500);if(server.exitCode===null)server.kill();});
