/* SingleCam rules derived from the user's Camclient reference. No provider or DOM calls. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.LiveCamSingleDomain=api;})(globalThis,function(){
  'use strict';
  const TABS=[['overview','Übersicht'],['chat','Chat'],['notes','Notizen'],['statistics','Statistik'],['images','Bilder'],['profile','Profil'],['settings','Einstellungen']];
  const SITES=(typeof module==='object'&&module.exports?require('./live_cam_domain.js'):globalThis.LiveCamDomain).SITES.map(row=>row[0]);
  const clamp=(v,min,max,fallback=min)=>Number.isFinite(Number(v))?Math.min(max,Math.max(min,Number(v))):fallback;
  const identity=r=>r&&SITES.includes(r.site)&&/^[A-Za-z0-9_-]{2,40}$/.test(r.name||'')?r.site+':'+r.name:'';
  function defaults(){return {sizing:'auto',frameAspect:false,dim:false,dimStrength:78,dimBlur:3,layout:'wide',cockpitPosition:'right',cockpitWidth:'normal',playerHeight:'auto',aspect:'16:9',fit:'contain',controlSize:'normal',corners:'subtle',background:'soft',toolsOpen:false,sidebar:true,toolbar:true,maximized:false,cinema:false,streamWidth:100,streamHeight:65,activeTab:'overview',autoplay:true,mutedStart:true,rememberVolume:true,maxVolume:100,siteSounds:false,pauseHidden:true,lowLatency:true,buffer:10,autoReconnect:true,statusSeconds:30,showLocal:true,showProfile:true,showChat:true,showStatus:true,showSimilar:true,mediaImportQuality:'high',screenshotFormat:'png',screenshotHeight:0,screenshotCover:false,sites:[...SITES]};}
  function settings(value={}){const s={...defaults(),...value};validate(s);return s;}
  function validate(s){
    const choices={sizing:['auto','width','fit','fill','manual'],layout:['wide','focus','compact'],cockpitPosition:['right','left','bottom'],cockpitWidth:['compact','normal','extra-wide'],playerHeight:['auto','normal','large','maximum','custom'],aspect:['16:9','4:3','21:9'],fit:['contain','cover'],controlSize:['compact','normal','large'],corners:['square','subtle','round'],background:['black','soft','ambient'],activeTab:TABS.map(t=>t[0]),mediaImportQuality:['original','high','balanced','compact'],screenshotFormat:['png','jpeg','webp']};
    for(const [key,values] of Object.entries(choices))if(!values.includes(s[key]))throw Error('Ungültige Einzelansicht-Einstellung: '+key);
    for(const key of ['frameAspect','dim','toolsOpen','sidebar','toolbar','maximized','cinema','autoplay','mutedStart','rememberVolume','siteSounds','pauseHidden','lowLatency','autoReconnect','showLocal','showProfile','showChat','showStatus','showSimilar','screenshotCover'])if(typeof s[key]!=='boolean')throw Error('Ungültiger Schalter: '+key);
    if(!Number.isFinite(s.dimStrength)||s.dimStrength<0||s.dimStrength>98||!Number.isFinite(s.dimBlur)||s.dimBlur<0||s.dimBlur>20)throw Error('Ungültiger Dimmerwert.');
    if(s.streamWidth<25||s.streamWidth>100||!Number.isFinite(s.streamWidth)||s.streamHeight<20||s.streamHeight>150||!Number.isFinite(s.streamHeight)||![25,50,75,100].includes(s.maxVolume)||![5,10,20,30,45].includes(s.buffer)||![15,30,45,60,90].includes(s.statusSeconds)||![0,720,1080,1440,2160].includes(s.screenshotHeight))throw Error('Ungültige Größe oder Wiedergabeoption.');
    if(!Array.isArray(s.sites)||s.sites.some(site=>!SITES.includes(site))||new Set(s.sites).size!==s.sites.length)throw Error('Ungültige Anbieterauswahl.');return s;
  }
  function camera(value={}){
    const c={muted:true,volume:100,quality:'auto',zoom:100,x:0,y:0,brightness:100,contrast:100,saturation:100,hue:0,sepia:0,grayscale:0,invert:0,blur:0,flipX:false,flipY:false,rotate:0,original:false,...value};
    if(c.quality==='global')c.quality='auto';
    const ranges={volume:[0,100],zoom:[50,2000],x:[-5000,5000],y:[-5000,5000],brightness:[25,250],contrast:[25,250],saturation:[0,300],hue:[-180,180],sepia:[0,100],grayscale:[0,100],invert:[0,100],blur:[0,12]};
    for(const [key,[min,max]] of Object.entries(ranges))if(!Number.isFinite(c[key])||c[key]<min||c[key]>max)throw Error('Ungültiger Bild-/Audiowert: '+key);
    if(![0,90,180,270].includes(c.rotate)||['muted','flipX','flipY','original'].some(key=>typeof c[key]!=='boolean')||!(c.quality==='auto'||Number.isFinite(Number(c.quality))&&Number(c.quality)>=100&&Number(c.quality)<=4320))throw Error('Ungültige Kameraeinstellung.');return c;
  }
  function normalizeState(value){const s=value||{};if(s.version!=null&&s.version!==1)throw Error('Neuere SingleCam-Daten bleiben erhalten.');const result={version:1,settings:settings(s.settings),models:s.models||{},globalBackground:s.globalBackground||null,compare:s.compare||[]};if(typeof result.models!=='object'||Array.isArray(result.models)||Object.keys(result.models).length>60000)throw Error('Ungültige Modelansichten.');return result;}
  function enabledTabs(s){return TABS.filter(([id])=>id!=='chat'||s.showChat).filter(([id])=>id!=='profile'||s.showProfile).filter(([id])=>!['notes','statistics'].includes(id)||s.showLocal);}
  function qualityChoices(levels){const values=[...new Set((levels||[]).map(level=>Number(level.height)).filter(h=>h>0&&h<=4320))].sort((a,b)=>a-b);return [['auto','Automatisch'],...values.map(height=>[String(height),height+'p'])];}
  function levelIndex(levels,wanted){if(wanted==='auto')return -1;const rows=(levels||[]).map((level,index)=>({height:Number(level.height)||0,index})).filter(row=>row.height>0).sort((a,b)=>a.height-b.height);return rows.filter(row=>row.height<=Number(wanted)).at(-1)?.index??rows[0]?.index??-1;}
  function screenshotSize(width,height,target=0){const factor=target>0?Math.min(1,target/height):1;return {width:Math.max(1,Math.round(width*factor)),height:Math.max(1,Math.round(height*factor))};}
  function sourceState(data){if(data?.status&&['online','offline','private','away','denied','unknown'].includes(data.status))return data.status;const error=String(data?.error||'').toLowerCase();if(/privat|private|ticket show/.test(error))return 'private';if(/offline|nicht online/.test(error))return 'offline';if(/zugriff verweigert|forbidden|access denied/.test(error))return 'denied';return data?.ok?'online':'failed';}
  function nextDelay(attempt,enabled=true){return enabled&&Number.isInteger(attempt)&&attempt>=0&&attempt<6?[1000,3000,5000,10000,20000,30000][attempt]:null;}
  function safeURL(value){try{const u=new URL(value);return ['https:','http:'].includes(u.protocol)&&!u.username&&!u.password?u.href:null;}catch{return null;}}
  function filterStyle(c,original=false){return original||c.original?'none':`brightness(${c.brightness}%) contrast(${c.contrast}%) saturate(${c.saturation}%) hue-rotate(${c.hue}deg) sepia(${c.sepia}%) grayscale(${c.grayscale}%) invert(${c.invert}%) blur(${c.blur}px)`;}
  function transformStyle(c,original=false){return original||c.original?'none':`translate(${c.x}px, ${c.y}px) rotate(${c.rotate}deg) scale(${c.zoom/100*(c.flipX?-1:1)}, ${c.zoom/100*(c.flipY?-1:1)})`;}
  function surfaceSize(width,height,videoWidth,videoHeight,mode='auto',preset='auto'){
    height*=preset==='normal'?.75:preset==='large'?.9:1;
    const ratio=videoWidth>0&&videoHeight>0?videoWidth/videoHeight:16/9;
    width=Math.max(1,width);height=Math.max(1,height);
    if(mode==='fill')return {width,height,fit:'cover'};
    if(mode==='width'||mode==='auto'&&ratio>=1)return {width,height:width/ratio,fit:'contain'};
    const w=Math.min(width,height*ratio);return {width:w,height:w/ratio,fit:'contain'};
  }
  function profileContent(p){return JSON.stringify({bio:p?.bio||'',sections:p?.sections||[],links:p?.links||[],tags:p?.tags||[],displayName:p?.displayName||''});}
  function notebook(previous,notes,tags){const max=Math.max(4000,String(previous?.notes||'').length),limit=Math.max(40,previous?.tags?.length||0);if(typeof notes!=='string'||notes.length>max)throw Error('Höchstens 4000 neue Notizzeichen; längere Altbestände bleiben geschützt.');const unique=[...new Set(tags.map(v=>String(v).trim().toLowerCase()).filter(Boolean))];if(unique.length>limit||unique.some(t=>t.length>40))throw Error('Höchstens 40 eigene Tags mit je 40 Zeichen.');return {notes,tags:unique};}
  function queue(items,sites){const seen=new Set();return (items||[]).filter(item=>{const key=identity(item);if(!key||seen.has(key)||!sites.includes(item.site))return false;seen.add(key);return true;});}
  function publicContext(value){return {version:1,view:['rooms','models','favs','following','groups','account','multi','statistics','gallery','notifications'].includes(value?.view)?value.view:'rooms',site:SITES.includes(value?.site)?value.site:'all',group:String(value?.group||'').slice(0,40),scroll:clamp(value?.scroll,0,1000000,0),page:clamp(value?.page,0,59999,0),offset:clamp(value?.offset,0,5000,0),tag:String(value?.tag||'').slice(0,50),favOnly:!!value?.favOnly,hdOnly:!!value?.hdOnly,fields:Object.fromEntries(['cam-gender','cam-sort','cam-per','cam-size','cam-filter','cam-topic','cam-min','cam-model-q','cam-model-site'].filter(key=>typeof value?.fields?.[key]==='string').map(key=>[key,value.fields[key].slice(0,500)])),rooms:queue(value?.rooms,SITES).slice(0,2000).map(r=>({site:r.site,name:r.name})),at:Date.now()};}
  return {surfaceSize,TABS,SITES,clamp,identity,defaults,settings,validate,camera,normalizeState,enabledTabs,qualityChoices,levelIndex,screenshotSize,sourceState,nextDelay,safeURL,filterStyle,transformStyle,profileContent,notebook,queue,publicContext};
});
