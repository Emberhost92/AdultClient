/* Live-Cam rules adapted from the user's Camclient 0.39.68 domain modules.
 * Provider identities are always site:name; browser-extension APIs stay out.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.LiveCamDomain = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';
  const SITES = [['stripchat','Stripchat'],['chaturbate','Chaturbate'],['bongacams','BongaCams'],['camsoda','CamSoda'],['cam4','CAM4'],['xlovecam','XloveCam']];
  const CAPACITIES = [1,2,3,4,6,9,12,15,16,20];
  const HEIGHTS = [240,360,480,720,1080,1440,2160];
  const clone = value => structuredClone(value);
  const clamp = (value, min, max, fallback = min) => Number.isFinite(Number(value)) ? Math.max(min, Math.min(max, Number(value))) : fallback;
  const key = room => room && SITES.some(([site]) => site === room.site) && /^[A-Za-z0-9_-]{2,40}$/.test(room.name || '') ? room.site + ':' + room.name : '';
  const room = id => { const at = String(id).indexOf(':'); const item = {site:String(id).slice(0,at),name:String(id).slice(at+1)}; return key(item) === id ? item : null; };
  const id = () => 'w_' + (typeof crypto === 'object' && crypto.randomUUID ? crypto.randomUUID().replace(/-/g,'') : Date.now().toString(36) + Math.random().toString(36).slice(2));
  const list = value => Array.isArray(value) ? value : [];
  const tokens = value => String(value || '').toLowerCase().split(/[\s,#]+/).filter(Boolean);
  function filters() {
    return {q:'',group:'',status:'all',sort:'manual',country:'',gender:'',minAge:'',maxAge:'',personal:'all',favorite:false,following:false,inGrid:false,notes:false,favoritesFirst:false,seen:'all',include:'',tagMode:'any',exclude:'',minutes:0,sessions:0,days:0,minViewers:'',maxViewers:''};
  }
  function settings() {
    return {capacity:4,layout:'grid',symmetricVersion:1,rows:2,cols:2,fit:'contain',aspect:'auto',mode:'normal',sidebar:true,toolbar:true,panels:{top:true,providers:false,quick:false,footer:true,sideFilters:false,sideGroups:false},sidebarWidth:260,listHeight:480,density:'compact',source:'workspace',focus:null,focusWidth:72,focusHeight:78,thumbSize:140,thumbnails:true,volume:100,muteAll:false,audio:'manual',solo:null,quality:0,adaptive:true,qualityBudget:0,prioritizeFocus:true,activeLimit:20,performance:'custom',freeZoom:true,meterMode:'individual',meterDefault:false,tileSize:360,sidebarSource:'models',sidebarPage:0,page:0,sites:SITES.map(s=>s[0]),sidebarFilters:filters(),playbackFilters:filters(),contexts:{},expandedGroups:{},autoFollowing:false,autoReplace:false,replaceDelay:30,replaceGroup:'',preferred:[],rotation:{source:'favorites',group:'',feed:'',order:'catalog',mode:'off',minutes:5,queueMode:'dynamic',queue:[],step:'all',shuffle:false,targets:[],targetsAll:true,excluded:[],schedule:'anytime',windows:[]}};
  }
  function camera() {
    return {muted:true,volume:100,quality:'global',zoom:100,x:0,y:0,brightness:100,contrast:100,saturation:100,hue:0,sepia:0,grayscale:0,invert:0,blur:0,flipX:false,flipY:false,rotate:0,meter:'global',paused:false};
  }
  function workspace(name = 'Standard', workspaceId = id()) {
    return {id:workspaceId,name,description:'',archived:false,slots:Array(20).fill(null),settings:settings(),scenes:[],created:Date.now()};
  }
  function initial(legacy = {}) {
    const first = workspace('Standard','default');
    first.settings.capacity = CAPACITIES.includes(Number(legacy.capacity)) ? Number(legacy.capacity) : 4;
    first.settings.quality = {low:240,mid:720,high:2160}[legacy.quality] || 0;
    if(legacy.quality==='high')first.settings.adaptive=false;
    if(['contain','cover'].includes(legacy.fit))first.settings.fit=legacy.fit;
    // Legacy fixed cells cropped portrait sources. Start with a symmetric grid; contain keeps the original video intact.
    for (const item of list(legacy.rooms).slice(0,20)) {
      const identity = key(item); if (!identity || first.slots.includes(identity)) continue;
      let slot = Number(item.slot);
      if (!Number.isInteger(slot) || slot < 0 || slot >= 20 || first.slots[slot]) slot = first.slots.indexOf(null);
      if (slot >= 0) first.slots[slot] = identity;
    }
    return {schema:1,revision:0,active:'default',workspaces:[first],cameras:{},models:{},templates:[],urls:[],shortcuts:{search:'Control+Shift+k',quick:'/',refresh:'r',grid:'g',focus:'f',pure:'Alt+p',viewer:'Alt+v',thumbs:'Alt+t'},capture:{minutes:15,bitrate:4,warn:true,download:false},private:false,theme:'inherit',language:'de'};
  }
  function validate(state) {
    if (!state || state.schema !== 1) throw Error('Unbekannte Multicam-Datenversion. Der gespeicherte Stand bleibt erhalten.');
    if (!Array.isArray(state.workspaces) || state.workspaces.length < 1 || state.workspaces.length > 60) throw Error('Es sind 1 bis 60 Arbeitsbereiche erlaubt.');
    const ids = new Set();
    for (const w of state.workspaces) {
      if (!w || typeof w.id !== 'string' || !/^[A-Za-z0-9_-]{1,80}$/.test(w.id) || ids.has(w.id) || typeof w.name !== 'string' || !w.name.trim() || w.name.length > 100 || typeof w.description !== 'string' || w.description.length > 2000) throw Error('Ungültiger Arbeitsbereich.');
      ids.add(w.id);
      if (!Array.isArray(w.slots) || w.slots.length !== 20 || w.slots.some(value => value !== null && !room(value))) throw Error('Ungültige Kameraplätze.');
      if (new Set(w.slots.filter(Boolean)).size !== w.slots.filter(Boolean).length) throw Error('Ein Model darf in einer Belegung nur einmal vorkommen.');
      if (!w.settings || !Number.isInteger(w.settings.capacity) || w.settings.capacity < 1 || w.settings.capacity > 20) throw Error('Ungültige Platzzahl.');
      validateSettings(w.settings);
      if (!Array.isArray(w.settings.sites) || w.settings.sites.length > SITES.length || w.settings.sites.some(site=>!SITES.some(s=>s[0]===site))) throw Error('Ungültige Anbieterauswahl.');
      if (!Array.isArray(w.scenes) || w.scenes.length > 24 || !Array.isArray(w.settings.rotation.queue) || w.settings.rotation.queue.length > 200 || w.settings.rotation.queue.some(value=>!room(value))) throw Error('Zu viele oder ungültige Szenen beziehungsweise Rotationskandidaten.');
      validateWindows(w.settings.rotation.windows);
      const sceneIds=new Set();
      for (const scene of w.scenes) {
        if (!scene || typeof scene.name !== 'string' || !scene.name.trim() || scene.name.length>100 || typeof scene.id!=='string' || sceneIds.has(scene.id) || !Array.isArray(scene.slots) || scene.slots.length !== 20 || scene.slots.some(value=>value!==null&&!room(value))) throw Error('Ungültige Szene.');
        sceneIds.add(scene.id);validateSettings({...settings(),...scene.settings});
      }
    }
    if (!ids.has('default') || state.workspaces.find(w=>w.id==='default').archived || !ids.has(state.active)) throw Error('Der Standardarbeitsbereich muss erhalten bleiben.');
    if (!Array.isArray(state.templates) || state.templates.length > 40 || !Array.isArray(state.urls) || state.urls.length > 100) throw Error('Zu viele Vorlagen oder temporäre Raumlinks.');
    if (!state.models || !state.cameras || typeof state.models !== 'object' || typeof state.cameras !== 'object' || Object.keys(state.models).length > 60000 || Object.keys(state.cameras).length > 60000) throw Error('Ungültiger Modelbestand.');
    for (const [identity,p] of Object.entries(state.cameras)) {
      if (!room(identity) || !p || !Number.isFinite(p.zoom) || p.zoom < 100 || p.zoom > 2000 || !Number.isFinite(p.volume) || p.volume < 0 || p.volume > 100) throw Error('Ungültige Kameraeinstellungen.');
      const ranges={x:[-5000,5000],y:[-5000,5000],brightness:[25,250],contrast:[25,250],saturation:[0,300],hue:[-180,180],sepia:[0,100],grayscale:[0,100],invert:[0,100],blur:[0,12]};
      for(const [field,[min,max]] of Object.entries(ranges))if(!Number.isFinite(p[field])||p[field]<min||p[field]>max)throw Error('Ungültiger Bildwert: '+field);
      if(![0,90,180,270].includes(p.rotate)||!['global','on','off'].includes(p.meter)||!['global','auto',...HEIGHTS.map(String)].includes(String(p.quality))||['muted','paused','flipX','flipY'].some(field=>typeof p[field]!=='boolean'))throw Error('Ungültige Kameraoption.');
    }
    for(const [identity,model] of Object.entries(state.models))if(!room(identity)||!model||typeof model!=='object'||model.notes!=null&&(typeof model.notes!=='string'||model.notes.length>10000)||model.tags!=null&&(!Array.isArray(model.tags)||model.tags.length>100||model.tags.some(t=>typeof t!=='string'||t.length>40)))throw Error('Ungültige persönliche Modeldaten.');
    if(!state.capture||!Number.isFinite(state.capture.minutes)||state.capture.minutes<1||state.capture.minutes>180||!Number.isFinite(state.capture.bitrate)||state.capture.bitrate<.5||state.capture.bitrate>20||typeof state.capture.warn!=='boolean'||typeof state.capture.download!=='boolean')throw Error('Ungültige Aufnahmeeinstellungen.');
    const shortcuts=new Set();for(const value of Object.values(state.shortcuts||{})){const normalized=shortcut(value);if(!normalized||shortcuts.has(normalized))throw Error('Ungültige oder doppelte Tastenkombination.');shortcuts.add(normalized);}
    for(const value of state.urls)if(!key(value)||Object.keys(value).some(k=>!['site','name'].includes(k)))throw Error('Raumlinks dürfen nur öffentliche Anbieteridentitäten enthalten.');
    const templateIds=new Set();for(const template of state.templates){if(!template||typeof template.id!=='string'||templateIds.has(template.id)||typeof template.name!=='string'||!template.name.trim()||template.name.length>100||typeof template.description!=='string'||template.description.length>2000)throw Error('Ungültige Layoutvorlage.');templateIds.add(template.id);validateSettings({...settings(),...template.settings});}
    const json = JSON.stringify(state);
    if (json.length > 12_000_000) throw Error('Die Multicam-Konfiguration ist zu groß.');
    if (/"(?:__proto__|prototype|constructor)"\s*:/.test(json)) throw Error('Ungültiger Datenschlüssel.');
    return state;
  }
  function validateSettings(c){
    const choices={layout:['mosaic','grid','focus','custom'],fit:['contain','cover'],aspect:['auto','16:9','4:3','21:9','1:1','9:16'],mode:['normal','viewer','pure'],density:['compact','comfortable'],source:['workspace','library'],audio:['manual','solo','followFocus'],performance:['economy','balanced','performance','custom'],meterMode:['individual','all','none'],sidebarSource:['models','following']};
    for(const [field,values] of Object.entries(choices))if(!values.includes(c[field]))throw Error('Ungültige Multicam-Option: '+field);
    const ranges={capacity:[1,20],rows:[1,5],cols:[1,5],sidebarWidth:[180,460],focusWidth:[45,94],focusHeight:[40,90],thumbSize:[80,320],volume:[0,100],qualityBudget:[0,21600],activeLimit:[1,20],tileSize:[220,900],replaceDelay:[0,600],page:[0,59999],sidebarPage:[0,59999]};
    for(const [field,[min,max]] of Object.entries(ranges))if(!Number.isFinite(c[field])||c[field]<min||c[field]>max)throw Error('Ungültiger Multicam-Wert: '+field);
    if(!Number.isInteger(c.capacity)||!Number.isInteger(c.rows)||!Number.isInteger(c.cols)||c.rows*c.cols>20||c.layout==='custom'&&c.rows*c.cols!==c.capacity||![0,...HEIGHTS].includes(c.quality)||![200,320,480,640,800,1000].includes(c.listHeight))throw Error('Ungültiges Raster oder Qualitätsziel.');
    for(const field of ['sidebar','toolbar','thumbnails','muteAll','adaptive','prioritizeFocus','freeZoom','meterDefault','autoFollowing','autoReplace'])if(typeof c[field]!=='boolean')throw Error('Ungültiger Schalter: '+field);
    if(!Array.isArray(c.sites)||c.sites.length>SITES.length||new Set(c.sites).size!==c.sites.length||c.sites.some(site=>!SITES.some(s=>s[0]===site)))throw Error('Ungültige Anbieterauswahl.');
    for(const f of [c.sidebarFilters,c.playbackFilters]){
      if(!f||typeof f!=='object')throw Error('Ungültige Filter.');
      for(const field of ['q','group','status','sort','country','gender','personal','seen','include','tagMode','exclude'])if(typeof f[field]!=='string'||f[field].length>5000)throw Error('Ungültiger Filter: '+field);
      for(const field of ['minAge','maxAge','minViewers','maxViewers','minutes','sessions','days'])if(f[field]!==''&&(!Number.isFinite(Number(f[field]))||Number(f[field])<0))throw Error('Ungültiger Zahlenfilter.');
    }
    if(!c.contexts||typeof c.contexts!=='object'||Object.keys(c.contexts).length>83)throw Error('Zu viele gespeicherte Filteransichten.');
    for(const context of Object.values(c.contexts)){if(!context||typeof context!=='object'||context.page!=null&&(!Number.isInteger(context.page)||context.page<0||context.page>59999))throw Error('Ungültige Ansichtsseite.');for(const field of ['order','hidden'])if(context[field]!=null&&(!Array.isArray(context[field])||context[field].length>60000||context[field].some(value=>!room(value))))throw Error('Ungültige Ansichtsbelegung.');}
    const r=c.rotation;
    if(!r||!['favorites','following','group','feed'].includes(r.source)||!['off','manual','session'].includes(r.mode)||![1,5,10,15].includes(r.minutes)||!['dynamic','fixed'].includes(r.queueMode)||!['all','one'].includes(r.step)||!['anytime','windows'].includes(r.schedule))throw Error('Ungültige Rotationsregel.');
    for(const field of ['queue','excluded'])if(!Array.isArray(r[field])||r[field].length>200||r[field].some(value=>!room(value)))throw Error('Ungültige Rotationsliste.');
    if(r.targetsAll!=null&&typeof r.targetsAll!=='boolean')throw Error('Ungültige Rotationsplatzauswahl.');
    if(!Array.isArray(r.targets)||r.targets.some(value=>!Number.isInteger(value)||value<0||value>=20))throw Error('Ungültige Rotationsplätze.');
    validateWindows(r.windows);
  }
  function shortcut(value){
    if(typeof value!=='string'||value.length>80)return null;
    const parts=value.toLowerCase().replace(/\s/g,'').split('+'),key=parts.pop();if(!key||key.length>20)return null;
    const aliases={ctrl:'control',cmd:'control',meta:'control',command:'control',option:'alt'};const mods=parts.map(v=>aliases[v]||v);
    if(mods.some(v=>!['control','alt','shift'].includes(v))||new Set(mods).size!==mods.length)return null;
    return [...['control','alt','shift'].filter(v=>mods.includes(v)),key].join('+');
  }
  function recover(state) {
    if (!state || state.schema !== 1) return validate(state);
    const next = clone(state);
    for (const w of next.workspaces || []) {
      const base = settings();
      if(!w.settings?.symmetricVersion&&w.settings?.layout==='mosaic')w.settings.layout='grid';
      w.settings = {...base,...w.settings,panels:{...base.panels,...w.settings?.panels},sidebarFilters:{...filters(),...w.settings?.sidebarFilters},playbackFilters:{...filters(),...w.settings?.playbackFilters},rotation:{...base.rotation,...w.settings?.rotation}};
      if(w.settings.rotation.targetsAll==null)w.settings.rotation.targetsAll=!w.settings.rotation.targets.length;
      w.settings.symmetricVersion=1;
      w.scenes = w.scenes || []; w.description = w.description || '';
    }
    next.capture = {...initial().capture,...next.capture};
    next.shortcuts = {...initial().shortcuts,...next.shortcuts};
    return validate(next);
  }
  function stateOf(model) {
    if (!model) return 'unknown';
    if (['privat','private','group'].includes(model.show) || ['private','group'].includes(model.roomState)) return 'private';
    if (['away','denied'].includes(model.roomState)) return model.roomState;
    if (model.online === false || model.roomState === 'offline') return 'offline';
    if (model.online === true || model.roomState === 'public') return 'online';
    return 'unknown';
  }
  function freshModel(model, now=Date.now()) {
    const stamp=v=>Number(v)>0?(Number(v)<1e12?Number(v)*1000:Number(v)):0;
    const at=Math.max(stamp(model?._observedAt),stamp(model?.seen));
    if(!at||now-at<=120000)return model;
    return {...model,online:null,show:'unknown',roomState:'unknown',staleStatus:true};
  }
  function prepareMatch(f, context = {}) {
    return {...context,prepared:{q:tokens(f.q),include:tokens(f.include),exclude:tokens(f.exclude),group:f.group?new Set(list(context.groups?.[f.group])):null}};
  }
  function matches(model, f, context = {}) {
    const identity = key(model), meta = model.personal || {}, local = model.local || {};
    const prepared=context.prepared||prepareMatch(f,context).prepared;
    if (prepared.group && !prepared.group.has(identity)) return false;
    const status = stateOf(model);
    if (f.status === 'online' && status !== 'online' || f.status === 'offline' && status !== 'offline' || f.status === 'private' && status !== 'private' || f.status === 'unknown' && status !== 'unknown') return false;
    if (['hide-offline','hide-both'].includes(f.status) && status === 'offline' || ['hide-private','hide-both'].includes(f.status) && status === 'private') return false;
    if (f.country && String(model.country||'').toLowerCase() !== f.country.toLowerCase()) return false;
    if (f.gender && !String(model.gender||'').toLowerCase().includes(f.gender)) return false;
    for (const [field,lo,hi] of [['age','minAge','maxAge'],['viewers','minViewers','maxViewers']]) {
      const value = model[field];
      if (f[lo] !== '' && f[lo] != null && (!Number.isFinite(Number(value)) || value == null || Number(value)<Number(f[lo]))) return false;
      if (f[hi] !== '' && f[hi] != null && (!Number.isFinite(Number(value)) || value == null || Number(value)>Number(f[hi]))) return false;
    }
    const seen = Number(meta.watchMs || local.watch_ms || 0) > 0 || Number(meta.sessions || local.sessions || 0) > 0;
    const notes = !!String(meta.notes||'').trim();
    if ((f.favorite || f.personal==='favorites') && !model.fav || f.following && !model.accountFav || f.inGrid && !context.occupied?.has(identity) || (f.notes || f.personal==='notes') && !notes) return false;
    if ((f.seen==='seen'||f.personal==='seen') && !seen || (f.seen==='never'||f.personal==='never') && seen) return false;
    const {include,exclude,q}=prepared;
    const tags=q.length||include.length||exclude.length?[...list(model.tags),...list(meta.tags)].map(t=>String(t).toLowerCase()):[];
    if(q.length){const text=[model.name,model.displayName,model.subject,meta.notes,...tags].join(' ').toLowerCase();if(q.some(word=>!text.includes(word)))return false;}
    if (include.length && (f.tagMode==='all' ? !include.every(t=>tags.includes(t)) : !include.some(t=>tags.includes(t)))) return false;
    if (exclude.some(t=>tags.includes(t))) return false;
    if (Number(meta.watchMs||local.watch_ms||0)<Number(f.minutes||0)*60000 || Number(meta.sessions||local.sessions||0)<Number(f.sessions||0)) return false;
    if (Number(f.days)>0 && Number(meta.lastVisit||local.last_visit||0)<Date.now()-Number(f.days)*86400000) return false;
    return !meta.archived && !(Number(meta.hiddenUntil)>Date.now());
  }
  function sortModels(models, f, order = []) {
    const positions = new Map(order.map((value,index)=>[value,index]));
    const fields = {watch:'watchMs',sessions:'sessions',last:'lastVisit',first:'firstVisit',added:'created',rating:'rating',priority:'priority',lastOnline:'lastOnline'};
    return models.map((m,i)=>({m,i})).sort((a,b)=>{
      const x=a.m,y=b.m,p=x.personal||{},q=y.personal||{};
      if (f.favoritesFirst && !!x.fav!==!!y.fav) return x.fav ? -1:1;
      let result=0;
      if (f.sort==='manual') result=(positions.get(key(x))??a.i)-(positions.get(key(y))??b.i);
      else if (f.sort==='name'||f.sort==='name-desc') result=x.name.localeCompare(y.name,undefined,{numeric:true})*(f.sort==='name-desc'?-1:1);
      else if (f.sort==='status') result=['online','away','private','unknown','offline','denied'].indexOf(stateOf(x))-['online','away','private','unknown','offline','denied'].indexOf(stateOf(y));
      else if (f.sort==='country') result=String(x.country||'').localeCompare(String(y.country||''));
      else if (f.sort==='age'||f.sort==='age-desc') result=(Number(x.age||999)-Number(y.age||999))*(f.sort==='age-desc'?-1:1);
      else if (['viewers','viewers-low','followers','uptime'].includes(f.sort)) { const field=f.sort.startsWith('viewers')?'viewers':f.sort; result=(Number(y[field]||0)-Number(x[field]||0))*(f.sort==='viewers-low'?-1:1); }
      else if (fields[f.sort]) result=Number(q[fields[f.sort]]||0)-Number(p[fields[f.sort]]||0);
      return result||a.i-b.i;
    }).map(row=>row.m);
  }
  function aspect(value) { const pair=String(value).split(':').map(Number); return pair.length===2&&pair.every(v=>v>0)?pair[0]/pair[1]:null; }
  function gridLayout(count,width,height,ratios=[],options={}) {
    const n=Math.max(1,count),gap=6;
    if (options.layout==='mosaic' && count) return mosaicLayout(ratios.slice(0,count).map(v=>clamp(v,.2,5,16/9)),width,height,gap);
    const maxCols=Math.max(1,Math.floor((width+gap)/116));
    const desired=n<=3?n:n%2===0?n/2:Math.ceil(Math.sqrt(n));
    let cols=options.layout==='custom'?options.cols:1;
    if(options.layout!=='custom') {
      const divisors=Array.from({length:n},(_,i)=>i+1).filter(c=>n%c===0&&c<=maxCols);
      cols=divisors.sort((a,b)=>Math.abs(a-desired)-Math.abs(b-desired)||b-a)[0]||1;
    }
    cols=Math.max(1,Math.min(cols,n,maxCols));
    const rows=Math.ceil(n/cols),cw=Math.max(1,(width-(cols-1)*gap)/cols),ch=Math.max(90,(height-(rows-1)*gap)/rows);
    return {width,height:rows*(ch+gap)-gap,cols,rects:Array.from({length:count},(_,i)=>({x:(i%cols)*(cw+gap),y:Math.floor(i/cols)*(ch+gap),width:cw,height:ch}))};
  }
  function justifiedRows(ratios,width,height,gap=6) {
    // Justified rows preserve native portrait/landscape formats. Evaluate
    // contiguous partitions with dynamic programming (20 tiles, O(n^3)).
    const n=ratios.length;
    if(!n)return {width,height:0,cols:0,rects:[]};
    const sums=[0];for(const r of ratios)sums.push(sums.at(-1)+r);
    let best=null;
    for(let rows=1;rows<=n;rows++) {
      const target=Math.max(100,(height-(rows-1)*gap)/rows);
      const dp=Array.from({length:rows+1},()=>Array(n+1).fill(Infinity));
      const prev=Array.from({length:rows+1},()=>Array(n+1).fill(0));dp[0][0]=0;
      for(let r=1;r<=rows;r++)for(let end=r;end<=n;end++)for(let start=r-1;start<end;start++) {
        const h=(width-(end-start-1)*gap)/(sums[end]-sums[start]);
        if(h<=0)continue;
        const narrow=ratios.slice(start,end).some(a=>a*h<95);
        const cost=dp[r-1][start]+Math.pow(Math.log(h/target),2)+(narrow?1:0);
        if(cost<dp[r][end]){dp[r][end]=cost;prev[r][end]=start;}
      }
      let end=n;const groups=[];
      for(let r=rows;r>0;r--){const start=prev[r][end];groups.unshift([start,end]);end=start;}
      if(end!==0||!Number.isFinite(dp[rows][n]))continue;
      const heights=groups.map(([a,b])=>(width-(b-a-1)*gap)/(sums[b]-sums[a]));
      const total=heights.reduce((a,b)=>a+b,0)+(rows-1)*gap;
      const score=Math.abs(Math.log(total/Math.max(1,height)))*(total>height?2:1)+dp[rows][n]/n*.15;
      if(!best||score<best.score)best={groups,heights,total,score};
    }
    let y=0;const rects=[];
    best.groups.forEach(([a,b],index)=>{let x=0;const h=best.heights[index];for(let i=a;i<b;i++){const w=h*ratios[i];rects.push({x,y,width:w,height:h});x+=w+gap;}y+=h+gap;});
    return {width,height:best.total,cols:Math.max(...best.groups.map(([a,b])=>b-a)),rects};
  }
  function focusLayout(ratios,width,height,config,gap=6){
    const thumbs=ratios.length>1&&config.thumbnails;
    const mainWidth=thumbs?width*config.focusWidth/100:width,mainHeight=thumbs?height*config.focusHeight/100:height;
    const h=Math.min(mainHeight,mainWidth/ratios[0]),w=h*ratios[0];
    const rects=[{x:(mainWidth-w)/2,y:0,width:w,height:h}];
    if(!thumbs)return {rects,height};
    const sideWidth=width-mainWidth-gap,right=sideWidth>=140;
    const miniWidth=right?sideWidth:width,miniHeight=right?height:Math.max(config.thumbSize,height-h-gap);
    const packed=mosaicLayout(ratios.slice(1),miniWidth,miniHeight,gap);
    rects.push(...packed.rects.map(r=>({...r,x:r.x+(right?mainWidth+gap:0),y:r.y+(right?0:h+gap)})));
    return {rects,height:Math.max(height,...rects.map(r=>r.y+r.height))};
  }
  function mosaicLayout(ratios,width,height,gap=6) {
    if(!ratios.length)return {width,height:0,cols:0,rects:[]};
    const original=ratios.map((ratio,index)=>({ratio,index}));
    const orders=[original,[...original].sort((a,b)=>a.ratio-b.ratio||a.index-b.index),[...original].sort((a,b)=>b.ratio-a.ratio||a.index-b.index)];
    let best=null;
    for(const order of orders)for(const transpose of [false,true]){
      const packed=justifiedRows(order.map(item=>transpose?1/item.ratio:item.ratio),transpose?height:width,transpose?width:height,gap);
      const rects=Array(ratios.length);
      packed.rects.forEach((box,i)=>{rects[order[i].index]=transpose?{x:box.y,y:box.x,width:box.height,height:box.width}:box;});
      const usedWidth=Math.max(...rects.map(r=>r.x+r.width)),usedHeight=Math.max(...rects.map(r=>r.y+r.height));
      if(usedWidth>width+.01)continue;
      const area=rects.reduce((sum,r)=>sum+r.width*r.height,0)/(width*height);
      const overflow=Math.max(0,usedWidth/width-1)+Math.max(0,usedHeight/height-1);
      const small=rects.filter(r=>Math.min(r.width,r.height)<70).length/rects.length;
      const score=area-overflow*5-small*.2;
      if(!best||score>best.score+.0001)best={rects,usedWidth,usedHeight,score,cols:packed.cols};
    }
    const shiftX=Math.max(0,(width-best.usedWidth)/2),shiftY=Math.max(0,(height-best.usedHeight)/2);
    best.rects.forEach(rect=>{rect.x+=shiftX;rect.y+=shiftY;});
    return {width,height:Math.max(height,best.usedHeight),cols:best.cols,rects:best.rects};
  }
  function levelIndex(levels,cap) {
    if(!cap)return -1;
    const all=levels.map((level,index)=>({height:Number(level.height)||0,index})).filter(v=>v.height>0);
    if(!all.length)return -1;
    const below=all.filter(v=>v.height<=cap);
    return (below.length?below.sort((a,b)=>b.height-a.height):all.sort((a,b)=>a.height-b.height))[0].index;
  }
  function qualityTarget(config,prefs,active,focused=false) {
    const own=Number(prefs.quality)||0, caps=[];
    if(own)caps.push(own);
    if(Number(config.quality))caps.push(Number(config.quality));
    if(config.adaptive&&!own)caps.push(active>=13?360:active>=9?480:active>=5?720:2160);
    if(config.qualityBudget>0&&!own){const weight=focused&&config.prioritizeFocus?2:1; const share=config.qualityBudget*weight/Math.max(1,active+(config.prioritizeFocus?1:0));caps.push(HEIGHTS.filter(h=>h<=share).at(-1)||240);}
    if(config.performance==='economy')caps.push(480);
    return caps.length?Math.min(...caps):0;
  }
  function audioState(config,prefs,identity,focus) {
    const routed=config.audio==='manual'||config.audio==='solo'&&identity===config.solo||config.audio==='followFocus'&&identity===focus;
    return {muted:!!config.muteAll||!routed||(config.audio==='manual'&&prefs.muted),volume:clamp(config.volume,0,100,100)*clamp(prefs.volume,0,100,100)/10000};
  }
  function parsePublicURL(value,site='') {
    const raw=String(value||'').trim();
    if(!raw.includes('://'))return key({site,name:raw})?{site,name:raw}:null;
    let url;try{url=new URL(raw);}catch{return null;}
    if(!['https:','http:'].includes(url.protocol)||url.username||url.password||url.search||url.hash||url.port)return null;
    const host=url.hostname.toLowerCase().replace(/^www\./,'');
    const provider={'stripchat.com':'stripchat','chaturbate.com':'chaturbate','bongacams.com':'bongacams','camsoda.com':'camsoda','cam4.com':'cam4','xlovecam.com':'xlovecam'}[host];
    const paths=url.pathname.split('/').filter(Boolean);
    if(provider==='xlovecam'){if(paths.length!==3||!['en','de','fr','es','it','pt','nl','ja'].includes(paths[0])||paths[1]!=='model')return null;}else if(!provider||paths.length!==1)return null;
    const result={site:provider,name:paths.at(-1)};return key(result)?result:null;
  }
  function publicURL(identity) {
    const item=typeof identity==='string'?room(identity):identity;
    if(!key(item))return '';
    const domains={stripchat:'stripchat.com',chaturbate:'chaturbate.com',bongacams:'bongacams.com',camsoda:'camsoda.com',cam4:'www.cam4.com',xlovecam:'www.xlovecam.com'};
    return 'https://'+domains[item.site]+'/'+(item.site==='xlovecam'?'en/model/':'')+encodeURIComponent(item.name)+'/';
  }
  function validateWindows(windows) {
    if(!Array.isArray(windows)||windows.length>14)throw Error('Höchstens 14 Wochenzeitfenster sind erlaubt.');
    const minutes=new Uint8Array(10080);
    for(const w of windows){
      if(!w||!Array.isArray(w.days)||!w.days.length||w.days.some(d=>!Number.isInteger(d)||d<0||d>6)||!Number.isInteger(w.start)||!Number.isInteger(w.end)||w.start<0||w.end<0||w.start>=1440||w.end>=1440||w.start===w.end)throw Error('Ungültiges Wochenzeitfenster.');
      const duration=(w.end-w.start+1440)%1440;
      for(const day of w.days)for(let i=0;i<duration;i++){const t=(day*1440+w.start+i)%10080;if(minutes[t])throw Error('Wochenzeitfenster dürfen sich nicht überschneiden.');minutes[t]=1;}
    }
    return windows;
  }
  function scheduleAt(rotation,date=new Date()) {
    if(rotation.schedule!=='windows')return {allowed:true,next:null};
    const minute=date.getDay()*1440+date.getHours()*60+date.getMinutes();
    let next=Infinity;
    for(const w of rotation.windows)for(const day of w.days){
      const start=day*1440+w.start,duration=(w.end-w.start+1440)%1440;
      if((minute-start+10080)%10080<duration)return {allowed:true,next:null};
      next=Math.min(next,(start-minute+10080)%10080);
    }
    return {allowed:false,next:Number.isFinite(next)?new Date(date.getTime()+next*60000):null};
  }
  function share(workspace,slots) {
    return {version:1,rooms:slots.filter(Boolean).slice(0,20).map(identity=>room(identity)),capacity:workspace.settings.capacity,layout:workspace.settings.layout,aspect:workspace.settings.aspect};
  }
  function snapshot(workspace,includeSlots=true) {
    const allowed=['capacity','layout','rows','cols','fit','aspect','focus','focusWidth','focusHeight','thumbSize','thumbnails','volume','audio','solo','source','sites','playbackFilters'];
    const result={settings:Object.fromEntries(allowed.map(k=>[k,clone(workspace.settings[k])]))};
    if(includeSlots)result.slots=clone(workspace.slots);
    return result;
  }
  return {SITES,CAPACITIES,HEIGHTS,clone,clamp,key,room,id,tokens,filters,settings,camera,workspace,initial,validate,recover,stateOf,freshModel,prepareMatch,matches,sortModels,aspect,gridLayout,mosaicLayout,focusLayout,levelIndex,qualityTarget,audioState,parsePublicURL,publicURL,validateWindows,scheduleAt,share,snapshot,shortcut};
});
