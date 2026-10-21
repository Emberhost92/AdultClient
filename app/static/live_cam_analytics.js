/* Local observations only. Website account statistics remain a separate source. */
(function(root){
  'use strict';
  const SITES=(typeof module==='object'&&module.exports?require('./live_cam_domain.js'):root.LiveCamDomain).SITES.map(row=>row[0]);
  const KEY='livecam-usage-v1',DAY=86400000;
  function dayKey(at){const d=new Date(at);return [d.getFullYear(),String(d.getMonth()+1).padStart(2,'0'),String(d.getDate()).padStart(2,'0')].join('-');}
  function union(intervals){const result=[];for(const [start,end] of intervals.filter(r=>Number.isFinite(r[0])&&Number.isFinite(r[1])&&r[1]>r[0]).sort((a,b)=>a[0]-b[0])){const last=result.at(-1);if(last&&start<=last[1]+1)last[1]=Math.max(last[1],end);else result.push([start,end]);}return result;}
  function elapsed(intervals,from=0,to=Date.now()){return union(intervals).reduce((n,[a,b])=>n+Math.max(0,Math.min(b,to)-Math.max(a,from)),0);}
  function pieces(start,end){const result=[];while(start<end){const d=new Date(start);d.setHours(24,0,0,0);const next=Math.min(end,d.getTime());result.push([dayKey(start),start,next]);start=next;}return result;}
  function blank(state={},at=Date.now()){return {version:1,startedAt:at,paused:false,pauseUntil:0,retention:365,baseline:Object.fromEntries(Object.entries(state.models||{}).map(([id,m])=>[id,{watchMs:m.watchMs||0,sessions:m.sessions||0,firstVisit:m.firstVisit,lastVisit:m.lastVisit,longestSession:m.longestSession}])),days:{}};}
  function paused(data,at=Date.now()){return !!data?.paused&&(data.pauseUntil===-1||data.pauseUntil>at);}
  function add(data,{kind,identity,start,end,at=Date.now(),sites=[]}){
    if(paused(data,at))return data;if(kind==='discovery'){data.discovered||={};if(Object.hasOwn(data.discovered,identity)||Object.hasOwn(data.baseline||{},identity))return data;if(Object.keys(data.discovered).length>=60000)return data;data.discovered[identity]=at;}
    const since=at-data.retention*DAY;for(const key of Object.keys(data.days))if(new Date(key+'T00:00:00').getTime()<since-DAY)delete data.days[key];
    const chunks=kind==='watch'||kind==='activity'?pieces(Math.max(start,data.startedAt),Math.min(end,at)):[[dayKey(at),at,at]];
    for(const [key,a,b] of chunks){const day=data.days[key]||=( {activity:[],providers:{},models:{}} );if(kind==='filter'){day.signals||=[];if(day.signals.length<5000)day.signals.push({kind,at,sites:[...sites]});continue;}if(kind==='activity'){day.activity=union([...day.activity,[a,b]]);for(const site of sites)day.providers[site]=union([...(day.providers[site]||[]),[a,b]]);continue;}if(!/^(stripchat|chaturbate|bongacams|camsoda|cam4|xlovecam):[A-Za-z0-9_-]{2,40}$/.test(identity||''))continue;const model=day.models[identity]||={intervals:[],events:{}};if(kind==='watch')model.intervals=union([...model.intervals,[a,b]]);else model.events[kind]=(model.events[kind]||0)+1;}
    return data;
  }
  function periodStart(range,now){if(!range)return 0;const d=new Date(now);d.setHours(0,0,0,0);d.setDate(d.getDate()-range+1);return d.getTime();}
  function report(data,state,models,sites,range=30,now=Date.now()){
    const from=periodStart(range,now),rows=new Map(),days=[],activity=[],events={};
    const ensure=id=>{if(!rows.has(id))rows.set(id,{id,site:id.split(':')[0],name:id.split(':')[1],watchMs:0,sessions:0,days:new Set(),events:{},...(models.get(id)||{})});return rows.get(id);};
    if(!range)for(const [id,old] of Object.entries(data.baseline||{}))if(sites.includes(id.split(':')[0])){const r=ensure(id);r.watchMs=old.watchMs||0;r.sessions=old.sessions||0;r.legacyMs=old.watchMs||0;}
    for(const [key,day] of Object.entries(data.days||{})){
      for(const signal of day.signals||[])if(signal.at>=from&&signal.at<=now&&signal.sites.some(site=>sites.includes(site)))events[signal.kind]=(events[signal.kind]||0)+1;
      const intervals=sites.length===SITES.length?day.activity:union(sites.flatMap(site=>day.providers?.[site]||[]));activity.push(...intervals);let watch=0;
      for(const [id,value] of Object.entries(day.models||{})){if(!sites.includes(id.split(':')[0]))continue;const ms=elapsed(value.intervals||[],from,now);const inside=key>=dayKey(from)&&key<=dayKey(now);if(!ms&&!inside)continue;const row=ensure(id);row.watchMs+=ms;if(ms)row.days.add(key);if(inside){for(const [kind,count] of Object.entries(value.events||{})){row.events[kind]=(row.events[kind]||0)+count;events[kind]=(events[kind]||0)+count;}row.sessions+=value.events?.visit||0;}watch+=ms;}
      const active=elapsed(intervals,from,now);if(active||watch)days.push({date:key,active,watch});
    }
    const allRows=[...rows.values()].sort((a,b)=>b.watchMs-a.watchMs),watched=allRows.filter(r=>r.watchMs>0),total=allRows.reduce((n,r)=>n+r.watchMs,0);
    return {from,to:now,rows:allRows,total,activity:elapsed(activity,from,now),days:days.sort((a,b)=>a.date.localeCompare(b.date)),events,sessions:allRows.reduce((n,r)=>n+r.sessions,0),watched:watched.length,topShare:total?watched.slice(0,3).reduce((n,r)=>n+r.watchMs,0)/total:null,legacy:!range};
  }
  function interests(rows,field,source='watch'){
    const counts=new Map();let covered=0,total=0;
    for(const row of rows){const weight=source==='favorites'?(row.fav?1:0):source==='watch'?row.watchMs:row.events?.[source]||0;if(!weight)continue;total+=weight;let values=field==='ownTags'?row.personal?.tags:field==='location'?[row.place||row.location]:field==='topic'?[row.subject]:field==='ageGroup'?(row.age?[Math.floor(row.age/10)*10+'–'+(Math.floor(row.age/10)*10+9)]:[]):row[field];if(values!=null&&!Array.isArray(values))values=[values];values=[...new Set((values||[]).filter(v=>v!==''&&v!=null))];if(values.length)covered+=weight;for(const value of values)counts.set(String(value),(counts.get(String(value))||0)+weight);}
    return {rows:[...counts].sort((a,b)=>b[1]-a[1]),covered,total};
  }
  function timeInterests(data,sites,range=30,field='hour',now=Date.now()){
    const from=periodStart(range,now),counts=new Map();let total=0;
    for(const day of Object.values(data.days||{}))for(const [id,model] of Object.entries(day.models||{}))if(sites.includes(id.split(':')[0]))for(const [start,end] of union(model.intervals||[])){
      let at=Math.max(start,from);const stop=Math.min(end,now);while(at<stop){const d=new Date(at),boundary=new Date(at);boundary.setMinutes(60,0,0);const next=Math.min(stop,(boundary.getTime()>at?boundary.getTime():at+3600000)),key=field==='weekday'?['Sonntag','Montag','Dienstag','Mittwoch','Donnerstag','Freitag','Samstag'][d.getDay()]:String(d.getHours()).padStart(2,'0')+':00';counts.set(key,(counts.get(key)||0)+next-at);total+=next-at;at=next;}
    }
    return {rows:[...counts].sort((a,b)=>b[1]-a[1]),covered:total,total};
  }
  function selectUsage(data,sites){const next=structuredClone(data),selected=id=>sites.includes(id.split(':')[0]);next.baseline=Object.fromEntries(Object.entries(next.baseline||{}).filter(([id])=>selected(id)));next.discovered=Object.fromEntries(Object.entries(next.discovered||{}).filter(([id])=>selected(id)));for(const day of Object.values(next.days)){day.models=Object.fromEntries(Object.entries(day.models).filter(([id])=>selected(id)));day.providers=Object.fromEntries(Object.entries(day.providers||{}).filter(([site])=>sites.includes(site)));if(sites.length!==SITES.length)day.activity=union(Object.values(day.providers).flat());day.signals=(day.signals||[]).map(signal=>({...signal,sites:signal.sites.filter(site=>sites.includes(site))})).filter(signal=>signal.sites.length);}return next;}
  function mergeUsage(current,source){
    if(source?.version!==1||!source.days||Array.isArray(source.days)||Object.keys(source.days).length>3660)throw Error('Keine gültige Nutzungssicherung.');
    const next=structuredClone(current),validId=id=>/^(stripchat|chaturbate|bongacams|camsoda|cam4|xlovecam):[A-Za-z0-9_-]{2,40}$/.test(id);let intervals=0;
    const safeIntervals=values=>{if(!Array.isArray(values))throw Error('Beschädigte Zeitintervalle.');intervals+=values.length;if(intervals>250000||values.some(v=>!Array.isArray(v)||v.length!==2||!v.every(Number.isFinite)||v[0]<0||v[1]<v[0]))throw Error('Ungültige Zeitintervalle.');return values;};
    for(const [id,row] of Object.entries(source.baseline||{})){if(!validId(id))throw Error('Ungültige Modelkennung.');const existing=next.baseline[id]||={};for(const field of ['watchMs','sessions','longestSession'])if(row[field]!=null){if(!Number.isFinite(row[field])||row[field]<0)throw Error('Ungültiger Altbestand.');existing[field]=Math.max(existing[field]||0,row[field]);}}
    for(const [date,day] of Object.entries(source.days)){
      if(!/^\d{4}-\d{2}-\d{2}$/.test(date)||!Number.isFinite(new Date(date+'T00:00:00').getTime())||!day.models||Array.isArray(day.models))throw Error('Beschädigte Tageswerte.');
      const old=next.days[date]||={activity:[],providers:{},models:{}};old.activity=union([...old.activity,...safeIntervals(day.activity)]);
      for(const [site,values] of Object.entries(day.providers||{})){if(!SITES.includes(site))throw Error('Ungültiger Anbieter.');old.providers[site]=union([...(old.providers[site]||[]),...safeIntervals(values)]);}
      for(const [id,value] of Object.entries(day.models)){if(!validId(id))throw Error('Ungültige Modelkennung.');const existing=old.models[id]||={intervals:[],events:{}};existing.intervals=union([...existing.intervals,...safeIntervals(value.intervals)]);for(const [kind,count] of Object.entries(value.events||{})){if(!['visit','preview','info','discovery','quality'].includes(kind)||!Number.isSafeInteger(count)||count<0)throw Error('Ungültige Ereigniszahl.');existing.events[kind]=Math.max(existing.events[kind]||0,count);}}
      const signals=new Map((old.signals||[]).map(s=>[JSON.stringify(s),s]));for(const signal of day.signals||[]){if(signal.kind!=='filter'||!Number.isFinite(signal.at)||!Array.isArray(signal.sites)||signal.sites.some(site=>!SITES.includes(site)))throw Error('Ungültige Filterereignisse.');const value={kind:'filter',at:signal.at,sites:[...signal.sites].sort()};signals.set(JSON.stringify(value),value);}old.signals=[...signals.values()].slice(-5000);
    }
    next.imports=[...(next.imports||[]),{at:Date.now(),sourceStartedAt:source.startedAt,days:Object.keys(source.days).length}].slice(-20);return next;
  }
  class Recorder{
    async init(){this.store=new root.LiveCamStore();this.state=await this.store.open(root.LiveCamDomain.initial(root.camStudioBridge?.().legacy()||{}));this.store.subscribe(v=>this.state=v);this.data=await this.store.updateCache(KEY,v=>v||blank(this.state));this.store.channel?.addEventListener('message',event=>{if(event.data.cache===KEY)this.store.get('cache',KEY).then(value=>this.data=value).catch(()=>{});});this.last=Date.now();this.timer=setInterval(()=>this.activity().catch(()=>{}),10000);document.addEventListener('visibilitychange',()=>{this.last=Date.now();});return this;}
    async record(entry){await root.LiveCamAnalytics.start();if(this.state.private)return;try{this.data=await this.store.updateCache(KEY,value=>add(value||blank(this.state),entry));}catch(error){root.LiveCamAnalytics.error=error.message;throw error;}}
    event(kind,identity){return this.record({kind,identity}).then(()=>root.LiveCamStatisticsRecorder?.modelEvents(kind,[identity]));}
    signal(kind,sites){return this.record({kind,sites});}
    watch(identity,ms){const end=Date.now();return this.record({kind:'watch',identity,start:end-Math.max(0,Math.min(ms,60000)),end});}
    async activity(){const end=Date.now(),start=Math.max(this.last||end,end-15000);this.last=end;if(document.hidden||!document.body.classList.contains('live-single-open')&&document.querySelector('#view-live')?.classList.contains('hidden'))return;const single=root.LiveCamSingle?.instance,sites=single?.active?[single.room.site]:root.LiveCamUser?.instance?.active?root.LiveCamUser.instance.sites:root.LiveCamStudio?.instance?.active?root.LiveCamStudio.instance.config().sites:root.camAnalyticsSites?.()||SITES;await this.record({kind:'activity',start,end,sites});}
    async read(){await this.ready;this.data=await this.store.get('cache',KEY);return this.data;}
    async pause(minutes){await this.ready;this.data=await this.store.updateCache(KEY,v=>({...v,paused:minutes!==0,pauseUntil:minutes===-1?-1:Date.now()+minutes*60000}));}
  }
  const api={KEY,dayKey,periodStart,union,elapsed,pieces,blank,paused,add,report,interests,timeInterests,mergeUsage,selectUsage};
  if(typeof module==='object'&&module.exports)module.exports=api;
  root.LiveCamAnalytics=api;
  if(root.document){const recorder=new Recorder();api.recorder=recorder;api.start=()=>{if(!recorder.ready)recorder.ready=recorder.init().catch(error=>{api.error=error.message;recorder.ready=null;recorder.store?.close();throw error;});return recorder.ready;};}
})(globalThis);
