(function(root){
  'use strict';
  const clamp=(v,a,b)=>Math.min(b,Math.max(a,Number(v)||a));
  function preferences(raw={}){return {size:clamp(raw.size??85,25,150),width:clamp(raw.width??100,25,100),zoom:clamp(raw.zoom??100,100,220),fit:raw.fit==='cover'?'cover':'contain'};}
  function uploadLabel(facts={}){
    const value=String(facts.uploadDate||'');
    if(/^\d{4}-\d{2}-\d{2}$/.test(value)){const [y,m,d]=value.split('-');return `Upload: ${d}.${m}.${y} · Uhrzeit nicht angegeben`;}
    if(/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(value)&&Number.isFinite(Date.parse(value))){
      const [day,time]=value.split(/[T ]/),[y,m,d]=day.split('-');
      const zone=time.match(/(Z|[+-]\d{2}:?\d{2})$/)?.[0];
      return `Upload: ${d}.${m}.${y}, ${time.replace(/(Z|[+-]\d{2}:?\d{2})$/,'')} ${zone==='Z'?'UTC':zone?'UTC'+zone:'· Zeitzone nicht angegeben'}`;
    }
    if(facts._loading&&!facts.when)return 'Upload-Datum wird von der Quelle geladen …';
    return facts.when?'Upload laut Quelle: '+facts.when+' · genaues Datum nicht verfügbar':'Genaues Upload-Datum von der Quelle nicht angegeben';
  }
  function detailRows(facts={}){
    const d=facts.details||{},rows=[['Upload laut Anbieter',uploadLabel(facts).replace(/^Upload: /,'')]];
    for(const [label,value]of [['Originaltitel',d.title],['Hoster',facts.site||String(d.sourceUrl||'').match(/^https?:\/\/([^/]+)/i)?.[1]],['Uploader / Kanal',d.uploader],['Herausgeber / Studio',d.publisher],['Video-ID',d.videoId],['Dauer laut Quelle',facts.duration],['Aufrufe',facts.views],['Bewertung',d.rating||facts.rating],['Kommentare',d.comments],['Positive Bewertungen',d.likes],['Negative Bewertungen',d.dislikes],['Sprache laut Quelle',d.languages],['Qualität laut Anbieter',d.sourceQuality||facts.quality],['Bildgröße laut Quelle',d.width&&d.height?d.width+' × '+d.height:null],['Bitrate laut Quelle',d.bitrate],['Dateigröße laut Quelle',d.fileSize],['Zuletzt geändert laut Anbieter',d.modifiedDate]]){
      if(value!==undefined&&value!==null&&value!==''){const count=['Aufrufe','Kommentare','Positive Bewertungen','Negative Bewertungen'].includes(label)&&/^\d+$/.test(String(value));rows.push([label,count?Number(value).toLocaleString((globalThis.AppI18n?.locale() || 'de-DE')):String(value)]);}
    }
    return rows;
  }
  function renderDetails(box,facts={}){
    const section=document.createElement('section');section.className='tube-video-details';section.setAttribute('aria-label','Videoinformationen');
    const title=document.createElement('h3');title.textContent='Videoinformationen';section.append(title);
    const list=document.createElement('dl');list.className='tube-detail-grid';
    for(const [label,value]of detailRows(facts)){const term=document.createElement('dt'),data=document.createElement('dd');term.textContent=label;data.textContent=value;if(label==='Upload laut Anbieter')data.id='watch-upload-detail';list.append(term,data);}
    section.append(list);
    const d=facts.details||{},description=d.description||facts.about;
    if(description&&description!==d.title){const text=document.createElement('p');(globalThis.AppI18n?.protect(text), text.textContent=description);section.append(text);}
    for(const [label,url]of [['Originalseite öffnen',d.sourceUrl],['Uploader-Seite öffnen',d.uploaderUrl]]){
      if(!/^https?:\/\//i.test(url||''))continue;const link=document.createElement('a');link.textContent=label;link.href=url;link.target='_blank';link.rel='noopener noreferrer';section.append(link,document.createTextNode(' · '));
    }
    const heading=document.createElement('h4');heading.textContent='Aktuelle Wiedergabe';const technical=document.createElement('p');technical.id='watch-technical-info';technical.className='muted';section.append(heading,technical);box.append(section);refreshTechnical();
  }
  function refreshTechnical(){
    if(typeof document==='undefined')return;const target=document.getElementById('watch-technical-info'),video=document.getElementById('video');if(!video)return;
    const actual=document.getElementById('quality-actual');if(actual)actual.textContent=video.videoWidth&&video.videoHeight?video.videoWidth+' × '+video.videoHeight+' px':'';
    if(!target)return;
    const parts=[];if(video.videoWidth&&video.videoHeight)parts.push('Bild: '+video.videoWidth+' × '+video.videoHeight+' Pixel');
    if(Number.isFinite(video.duration)&&video.duration>0){const seconds=Math.round(video.duration);parts.push('Dauer: '+Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0'));}
    const quality=document.getElementById('quality')?.selectedOptions?.[0]?.textContent;if(quality)parts.push('Qualität: '+quality);
    if(parts.length){parts.push('Tempo: '+video.playbackRate+'×');target.textContent=parts.join(' · ');}else target.textContent='Wiedergabedaten werden nach dem Laden des Videos ergänzt.';
  }
  function mount(){
    const video=document.getElementById('video'),frame=video?.parentElement,host=document.getElementById('tube-size-controls');if(!host||!frame)return;
    const quality=document.getElementById('quality');if(quality){const actual=document.createElement('strong');actual.id='quality-actual';actual.setAttribute('aria-live','polite');quality.after(actual);}
    let raw={};try{raw=JSON.parse(localStorage.getItem('adultclient.tube-player')||'{}');}catch{}
    let prefs=preferences(raw),ratio=16/9;
    const save=()=>{try{localStorage.setItem('adultclient.tube-player',JSON.stringify(prefs));}catch{}};
    function paint(){frame.style.width=`min(${prefs.width}%, calc(${prefs.size}vh * ${ratio}))`;frame.style.height='auto';frame.style.aspectRatio=String(ratio);video.style.objectFit=prefs.fit;video.style.objectViewBox=`inset(${(100-100/(prefs.zoom/100))/2}%)`;video.style.transform=typeof CSS!=='undefined'&&CSS.supports('object-view-box','inset(1%)')?'none':`scale(${prefs.zoom/100})`;save();}
    const addRange=(label,key,min,max)=>{const wrap=document.createElement('label'),name=document.createElement('span'),input=document.createElement('input'),value=document.createElement('output');name.textContent=label;input.type='range';input.min=min;input.max=max;input.value=prefs[key];input.setAttribute('aria-label',label);value.textContent=prefs[key]+(key==='size'?' vh':' %');input.oninput=()=>{prefs[key]=Number(input.value);value.textContent=prefs[key]+(key==='size'?' vh':' %');paint();};wrap.append(name,input,value);host.append(wrap);return {input,value,key};};
    const ranges=[addRange('Playergröße','size',25,150),addRange('Maximale Breite','width',25,100),addRange('Bildzoom','zoom',100,220)];
    const fit=document.createElement('select');fit.setAttribute('aria-label','Bild im Player');for(const [v,t]of [['contain','Ganzes Bild'],['cover','Rahmen füllen · Randbeschnitt']]){const option=document.createElement('option');option.value=v;option.textContent=t;fit.append(option);}fit.value=prefs.fit;fit.onchange=()=>{prefs.fit=fit.value;paint();};host.append(fit);
    const reset=document.createElement('button');reset.type='button';reset.textContent='Größe zurücksetzen';reset.onclick=()=>{prefs=preferences();for(const r of ranges){r.input.value=prefs[r.key];r.value.textContent=prefs[r.key]+(r.key==='size'?' vh':' %');}fit.value=prefs.fit;paint();};host.append(reset);
    const handle=document.createElement('button');handle.type='button';handle.className='tube-resize';handle.textContent='↘';handle.setAttribute('aria-label','Playergröße ziehen');handle.title='Ziehen zum Vergrößern oder Verkleinern; Pfeiltasten ändern die Größe';frame.append(handle);
    handle.onkeydown=e=>{if(!['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.key))return;e.preventDefault();prefs.size=clamp(prefs.size+(['ArrowUp','ArrowLeft'].includes(e.key)?-5:5),25,150);ranges[0].input.value=prefs.size;ranges[0].value.textContent=prefs.size+' vh';paint();};
    handle.onpointerdown=e=>{e.preventDefault();handle.setPointerCapture(e.pointerId);const start=frame.getBoundingClientRect(),x=e.clientX,y=e.clientY;handle.onpointermove=move=>{const height=Math.max(start.height+move.clientY-y,(start.width+move.clientX-x)/ratio);prefs.size=clamp(height/innerHeight*100,25,150);ranges[0].input.value=prefs.size;ranges[0].value.textContent=Math.round(prefs.size)+' vh';paint();};};handle.onpointerup=handle.onpointercancel=()=>{handle.onpointermove=null;};
    video.addEventListener('loadedmetadata',()=>{if(video.videoWidth&&video.videoHeight)ratio=video.videoWidth/video.videoHeight;paint();refreshTechnical();});
    for(const event of ['resize','durationchange','ratechange','playing'])video.addEventListener(event,refreshTechnical);
    document.getElementById('quality')?.addEventListener('change',refreshTechnical);
    root.TubePlayer={...root.TubePlayer,resetVideo(){ratio=16/9;paint();}};paint();
  }
  root.TubePlayer={preferences,uploadLabel,detailRows,renderDetails,refreshTechnical};
  if(typeof module==='object'&&module.exports)module.exports={preferences,uploadLabel,detailRows};
  if(typeof document!=='undefined')mount();
})(globalThis);
