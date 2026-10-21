/* Library vocabulary and view rules adapted from Camclient's library/studio.ts. */
(function(root,factory){const api=factory(typeof module==='object'&&module.exports?require('./live_cam_domain.js'):root.LiveCamDomain);if(typeof module==='object'&&module.exports)module.exports=api;else root.LiveCamModelsDomain=api;})(globalThis,function(D){
  'use strict';
  const VIEWS=[['active','Aktive Bibliothek'],['all','Alle erfassten Models'],['collection','Meine Sammlung'],['groups','In Gruppen'],['favorites','Favoriten'],['remembered','Favoriten oder Merkliste'],['favorite-watchlist','Favorit und Merkliste'],['following','Offiziell gefolgt'],['watchlist','Merkliste'],['paused','Pausiert / ausgeblendet'],['live','Gerade live bestätigt'],['notes','Mit Notizen'],['archive','Archiv']];
  const SORTS=[['last-active','Zuletzt angesehen'],['longest-inactive','Am längsten nicht angesehen'],['newest-saved','Zuletzt gespeichert'],['oldest-saved','Zuerst gespeichert'],['watch-most','Meiste Sehzeit'],['watch-least','Wenigste Sehzeit'],['rating-high','Höchste Bewertung'],['rating-low','Niedrigste Bewertung'],['priority-high','Höchste Priorität'],['priority-low','Niedrigste Priorität'],['viewers-high','Meiste Zuschauer'],['viewers-low','Wenigste Zuschauer'],['followers-high','Meiste Follower'],['online-longest','Längste aktuelle Onlinezeit'],['age-low','Alter aufsteigend'],['age-high','Alter absteigend'],['sessions-most','Meiste Sitzungen'],['average-longest','Längste durchschnittliche Sitzung'],['session-longest','Längste Einzelsitzung'],['active-days-most','Meiste aktive Tage'],['appearances-most','Meiste beobachtete Auftritte'],['samples-most','Meiste Beobachtungen'],['last-live','Zuletzt live beobachtet'],['first-seen','Zuerst erfasst'],['name-az','Name A–Z'],['name-za','Name Z–A'],['country-az','Land'],['gender','Typ'],['public-tags-most','Meiste öffentliche Tags'],['groups-most','Meiste Gruppen']];
  const FIELDS=[['image','Bild / Live-Vorschau'],['subject','Raumthema'],['catalogStatus','Katalogherkunft'],['liveStatus','Öffentlicher Status'],['viewers','Zuschauer'],['country','Land'],['location','Ort'],['age','Alter'],['gender','Typ'],['watchTime','Sehzeit'],['sessions','Sitzungen'],['averageSession','Durchschnittliche Sitzung'],['longestSession','Längste Sitzung'],['activeDays','Aktive Tage'],['firstSeen','Zuerst erfasst'],['lastSeen','Zuletzt beobachtet'],['lastLive','Zuletzt live'],['previews','Vorschauen'],['quickFacts','Schnellinfos'],['typicalTimes','Beobachtete Onlinezeiten'],['activity','Aktivität'],['sampleImages','Gespeicherte Beispielbilder'],['groups','Gruppen'],['publicTags','Öffentliche Tags'],['organization','Persönliche Organisation'],['rating','Bewertung / Priorität'],['groupAssignment','Direkte Gruppenzuordnung'],['actions','Aktionen']];
  const PRESETS={compact:['image','liveStatus','actions'],core:['image','liveStatus','viewers','country','actions'],balanced:['image','liveStatus','viewers','country','age','watchTime','groups','organization','actions'],details:['image','subject','liveStatus','viewers','country','age','gender','watchTime','sessions','publicTags','groups','rating','groupAssignment','actions'],full:FIELDS.map(r=>r[0])};
  const label=site=>D.SITES.find(r=>r[0]===site)?.[1]||site;
  const defaults=()=>({query:'',view:'active',sort:'last-active',sites:D.SITES.map(r=>r[0]),genders:[],statuses:[],countries:[],publicTags:[],localTags:[],groupIds:[],publicTagMode:'any',localTagMode:'any',groupMode:'any',source:'all',profile:'any',media:'all',seen:'any',localTagsState:'any',groupsState:'any',notesState:'any',minAge:null,maxAge:null,minViewers:null,maxViewers:null,minFollowers:null,maxFollowers:null,minWatchMinutes:null,minOnlineMinutes:null,minSessions:null,minRating:null,minPriority:null,activeWithinDays:null,minAppearances:null,minSamples:null,weekday:null,hour:null});
  const appearance=()=>({fields:[...PRESETS.balanced],columns:'auto',scale:100,density:'comfortable',imageAction:'single'});
  function validateAppearance(value={}){const next={...appearance(),...value};if(!Array.isArray(next.fields)||next.fields.some(v=>!FIELDS.some(r=>r[0]===v))||!['auto','1','2','3','4','5','6'].includes(String(next.columns))||!Number.isFinite(next.scale)||next.scale<70||next.scale>160||!['compact','comfortable','large','cinema','extra-large'].includes(next.density)||!['single','details'].includes(next.imageAction))throw Error('Ungültige Modelansicht.');return next;}
  function validateFilters(value={}){const f={...defaults(),...structuredClone(value)};if(!Array.isArray(f.sites)||f.sites.some(s=>!D.SITES.some(r=>r[0]===s))||!VIEWS.some(r=>r[0]===f.view)||!SORTS.some(r=>r[0]===f.sort))throw Error('Ungültige Modelbibliotheksansicht.');return f;}
  const duration=ms=>ms==null?'Unbekannt':Math.floor(ms/3600000)+':'+String(Math.floor(ms/60000)%60).padStart(2,'0')+':'+String(Math.floor(ms/1000)%60).padStart(2,'0');
  const date=ms=>ms?new Date(ms<1e10?ms*1000:ms).toLocaleString((globalThis.AppI18n?.locale() || 'de-DE')):'Unbekannt';
  const STATUS={live:'Live bestätigt',away:'Abwesend',offline:'Offline beobachtet',private:'Privat',unknown:'Unbekannt / älterer Stand',error:'Abruffehler'};
  function details(row){const p=row.personal||{},gender={f:'Weiblich',m:'Männlich',t:'Trans',c:'Paar',unknown:'Unbekannt'},hours=row.byHour||[],peak=hours.some(v=>v>0)?hours.indexOf(Math.max(...hours)):null;return {subject:row.subject||'Kein bekanntes Raumthema',catalogStatus:p.saved?'Persönlich gespeichert':'Öffentlich erfasst',liveStatus:STATUS[row.status]||STATUS.unknown,viewers:row.viewers??'Unbekannt',country:row.country||'Unbekannt',location:row.place||'Unbekannt',age:row.age??'Unbekannt',gender:gender[row.gender]||'Unbekannt',watchTime:duration(row.watchMs),sessions:row.sessions??'Unbekannt',averageSession:duration(row.averageSession),longestSession:duration(row.longestSession),activeDays:row.activeDays??'Unbekannt',firstSeen:date(row.firstSeen),lastSeen:date(row.seen),lastLive:date(row.lastOnline),previews:row.previews??'Unbekannt',quickFacts:row.infos??'Unbekannt',typicalTimes:peak==null?'Noch nicht beobachtet':String(peak).padStart(2,'0')+'–'+String((peak+1)%24).padStart(2,'0')+' Uhr (lokal)',activity:row.observations==null?'Noch nicht erfasst':row.observations+' Beobachtungen',publicTags:(row.tags||[]).join(' · ')||'Keine bekannt',organization:[p.saved?'Gespeichert':(p.notes||p.tags?.length||p.rating||p.priority)?'Persönlich organisiert':'',row.groupIds?.length?'In Gruppen':'',row.fav?'Favorit':'',p.bookmarked?'Merkliste':'',row.accountFav?'Offiziell gefolgt':'',p.archived?'Archiviert':''].filter(Boolean).join(' · ')||'Automatisch erfasst',rating:(p.rating??0)+' / 5 · Priorität '+(p.priority??0)};}
  function names(text,site){const result=[],invalid=[];for(const line of String(text).split(/[\r\n,;]+/).map(v=>v.trim()).filter(Boolean)){let room;if(line.includes('://'))room=D.parsePublicURL(line);else if(line.includes(':'))room=D.room(line);else room=D.parsePublicURL(line,site);if(room){const key=D.key(room);if(!result.includes(key))result.push(key);}else invalid.push(line);}return {ids:result,invalid};}
  function exportRows(rows){return {format:'AdultClient-Models',version:1,at:Date.now(),models:rows.map(row=>({site:row.site,name:row.name,personal:Object.fromEntries(Object.entries(row.personal||{}).filter(([k])=>['notes','tags','rating','priority','bookmarked','archived','saved','hiddenUntil','pauseUntil','suggestionHidden','savedAt'].includes(k))),favorite:!!row.fav,groups:row.groupIds||[]}))};}
  function imageURL(path,origin){if(typeof path!=='string'||!path)return '';try{const base=new URL(origin),u=new URL(path,origin);if(u.pathname==='/api/cam-model-cover'&&u.origin===base.origin)return u.pathname+u.search;if(u.pathname==='/api/image'&&['127.0.0.1','localhost',base.hostname].includes(u.hostname)&&['http:','https:'].includes(u.protocol))return u.pathname+u.search;if(u.protocol==='https:'&&!u.username&&!u.password)return '/api/image?url='+encodeURIComponent(path);}catch{}return '';}
  function observedTimes(usage,now=Date.now()){
    const result={};for(const day of Object.values(usage.days||{}))for(const [id,model] of Object.entries(day.models||{})){
      if(!D.room(id)||!model.intervals?.length)continue;const row=result[id]||={byHour:Array(24).fill(0),byDay:Array(7).fill(0)};
      for(const interval of model.intervals){let cursor=Math.max(interval[0],usage.startedAt||0),end=Math.min(interval[1],now);if(!Number.isFinite(cursor)||!Number.isFinite(end))continue;
        while(cursor<end){const date=new Date(cursor),next=new Date(cursor);next.setMinutes(60,0,0);const stop=Math.min(end,next.getTime()>cursor?next.getTime():cursor+3600000);row.byHour[date.getHours()]+=stop-cursor;row.byDay[date.getDay()]+=stop-cursor;cursor=stop;}
      }
    }return result;
  }
  function cardImageURL(row,origin,now=Date.now()){
    const observed=Number(row.playbackAt)||Number(row.seen)*1000;
    const current=row.status==='live'&&row.thumb&&observed>0&&now>=observed-5000&&now-observed<(row.playbackAt?95000:120000);
    const path=imageURL(current?row.thumb:row.cover||row.thumb||'',origin);
    if(!current||!path.startsWith('/api/image?'))return path;
    const url=new URL(path,origin);url.searchParams.set('live','1');url.searchParams.set('frame',String(Math.floor(now/60000)));
    return url.pathname+url.search;
  }
  function statusTone(value){return ({live:'online',online:'online',offline:'offline',private:'private',away:'away',unknown:'unknown',error:'error'})[value]||'all';}
  function statusLabel(value,label){const marker={online:'🟢',offline:'🔴',private:'🟠',away:'🟡',unknown:'?',error:'!'}[statusTone(value)];return marker?marker+' '+label:label;}
  function decorateStatusSelect(input,label){
    if(!/status|zust[aä]nd|modelbestand/i.test(label))return input;
    input.classList.add('lc-state-select');
    for(const option of input.options){option.dataset.state=statusTone(option.value);if(!option.dataset.statusDecorated){option.textContent=statusLabel(option.value,option.textContent);option.dataset.statusDecorated='1';}}
    const update=()=>{input.dataset.state=statusTone(input.value);};input.addEventListener('change',update);update();return input;
  }
  // Advancing media time/decoded frames are evidence; a resolved URL or a
  // frozen video with phase=playing is not. No stream is opened by this helper.
  function playingRooms(players,samples,now=Date.now()){
    const found=new Set();
    for(const player of players){const video=player?.video,room=player?.room||player?.model,id=player?.identity||D.key(room);
      if(!video||!D.room(id)||player.closed||player.paused||video.paused||video.ended||video.readyState<2||player.phase&&player.phase!=='playing')continue;
      const frames=video.getVideoPlaybackQuality?.().totalVideoFrames||player.frames||0,position=Number(video.currentTime)||0,old=samples.get(video);
      const changed=old?(position>old.position+.01||frames>old.frames):(position>0&&frames>0);
      const at=changed?now:old?.at||0;samples.set(video,{position,frames,at});
      if(at&&now-at<15000)found.add(id);
    }
    return [...found].slice(0,240);
  }
  return {imageURL,cardImageURL,statusTone,statusLabel,decorateStatusSelect,playingRooms,observedTimes,VIEWS,SORTS,FIELDS,PRESETS,defaults,appearance,validateAppearance,validateFilters,label,duration,date,STATUS,details,names,exportRows};
});
