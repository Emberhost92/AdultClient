// Real 360/720/1440 HLS decoding, including manual quality changes.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.argv[2]||'http://127.0.0.1:8765',label=process.argv[3]||'local';
(async()=>{const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--autoplay-policy=no-user-gesture-required']});
 try{
  const p=await browser.newPage({viewport:{width:1440,height:1000}});p.setDefaultTimeout(30000);const errors=[];p.on('pageerror',e=>{errors.push(e.message);console.error(e.message);});
  await p.route('**/__quality_test__/**',r=>{const name=new URL(r.request().url()).pathname.split('/').pop();
   if(name==='master.m3u8')return r.fulfill({body:'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=2560x1440\n1440.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=700000,RESOLUTION=1280x720\n720.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=250000,RESOLUTION=640x360\n360.m3u8\n',contentType:'application/vnd.apple.mpegurl'});
   assert.match(name,/^(360|720|1440)(\.m3u8|-\d+\.ts)$/);return r.fulfill({path:path.join(__dirname,'fixtures/tube-quality',name),contentType:name.endsWith('.ts')?'video/mp2t':'application/vnd.apple.mpegurl'});
  });
  await p.goto(base);await p.locator('#app').waitFor({state:'visible'});
  await p.evaluate(()=>{show('watch');const v=document.getElementById('video');v.muted=true;mainHandle=attachStream(v,document.getElementById('quality'),{path:'/__quality_test__/master.m3u8'},true);});
  await p.waitForFunction(()=>document.getElementById('video').videoHeight===1440&&document.getElementById('video').getVideoPlaybackQuality().totalVideoFrames>0);
  const options=await p.locator('#quality option').allTextContents();assert.ok(options.includes('1440p'));assert.ok(options.includes('360p'));
  assert.equal(await p.locator('#quality').inputValue(),'-2');
  const index=await p.evaluate(()=>mainHandle.hls.levels.findIndex(l=>l.height===360));
  await p.locator('#quality').selectOption(String(index));await p.waitForFunction(()=>document.getElementById('video').videoHeight===360);
  await p.locator('#quality').selectOption('-2');await p.waitForFunction(()=>document.getElementById('video').videoHeight===1440);
  await p.locator('#quality').selectOption('-1');assert.equal(await p.evaluate(()=>mainHandle.hls.autoLevelEnabled),true);
  await p.evaluate(()=>{mainHandle.dispose();mainHandle=attachStream(document.getElementById('video'),document.getElementById('quality'),{path:'/__quality_test__/360.m3u8'},true);});
  await p.waitForFunction(()=>document.getElementById('video').videoHeight===360&&[...document.querySelector('#quality').options].some(o=>o.textContent==='360p'));
  assert.match(await p.locator('#quality-actual').innerText(),/640 × 360/);
  await p.evaluate(()=>AppI18n.setLanguage('en'));await p.waitForFunction(()=>document.querySelector('#quality option[value="-2"]').textContent==='Best quality');
  assert.deepEqual(errors,[]);await p.evaluate(()=>mainHandle.dispose());
  const report={ok:true,label,decoded_heights:[1440,360,1440],options,adaptive:true,english:true,errors};fs.writeFileSync(path.join(__dirname,`tube-quality-${label}.json`),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
