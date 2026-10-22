// Optional private query supplied only through the environment; never saved/logged.
const {chromium}=require('playwright'),fs=require('node:fs'),path=require('node:path');
(async()=>{const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--autoplay-policy=no-user-gesture-required']});
 try{const p=await browser.newPage({viewport:{width:1440,height:1000}});p.setDefaultTimeout(40000);
  await p.goto('http://127.0.0.1:8765');await p.locator('#app').waitFor({state:'visible'});
  const query=process.env.AH_TEST_VIDEO_QUERY;if(!query)throw Error('A test video query is required');
  const meta=await p.evaluate(async query=>{const data=await fetch('/api/browse?'+query,{signal:AbortSignal.timeout(45000)}).then(r=>r.json());if(!data.resolved)throw Error('Video resolution failed');
   show('watch');const v=document.getElementById('video');v.muted=true;mainHandle=attachStream(v,document.getElementById('quality'),data.resolved,true);
   return {childProxy:/127\.0\.0\.1:\d+\/playlist\.m3u8/.test(data.resolved.path),sourceCount:data.resolved.sources?.length||1};},query);
  await p.waitForFunction(()=>{const v=document.getElementById('video');return v.videoHeight>0&&v.getVideoPlaybackQuality().totalVideoFrames>0;},null,{timeout:45000});
  const result=await p.evaluate(()=>({decoded:[video.videoWidth,video.videoHeight],available:mainHandle.hls?.levels?.map(l=>l.height)||[],options:[...document.querySelector('#quality').options].map(o=>o.textContent),selection:document.getElementById('quality').value}));
  if(result.available.length&&result.decoded[1]<Math.max(...result.available))throw Error('Playback did not reach the highest rendition');
  if(meta.childProxy)throw Error('The master was reduced to a helper playlist');
  const report={ok:true,hoster:'xvideos',...meta,...result};fs.writeFileSync(path.join(__dirname,'tube-quality-real-provider.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));await p.evaluate(()=>mainHandle.dispose());
 }finally{await browser.close();}
})().catch(()=>{console.error('Real video quality check failed; no private URLs logged');process.exitCode=1;});
