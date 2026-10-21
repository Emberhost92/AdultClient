/* Local storage overview and bounded, cached video previews. */
(function(root){
 'use strict';
 const make=(tag,text='',cls='')=>{const n=document.createElement(tag);n.textContent=text;if(cls)n.className=cls;return n;};
 const bytes=n=>{if(n==null)return 'Wird ermittelt …';const units=['B','KB','MB','GB','TB'];let i=0;while(n>=1024&&i<units.length-1){n/=1024;i++;}return new Intl.NumberFormat('de-DE',{maximumFractionDigits:1}).format(n)+' '+units[i];};
 async function folder(path){const r=await fetch('/api/download-open-folder',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})});const d=await r.json();if(!r.ok||!d.ok)throw Error(d.error||'Der Ordner konnte nicht geöffnet werden.');}
 let summaryRun=0,summaryTimer;
 async function summary(host,on){clearTimeout(summaryTimer);const run=++summaryRun;host.hidden=!on;if(!on){host.replaceChildren();return;}
  const refresh=async(fresh=false)=>{try{const response=await fetch('/api/download-storage'+(fresh?'?fresh=1':''),{signal:AbortSignal.timeout(8000)});if(!response.ok)throw Error('Speicherübersicht derzeit nicht erreichbar.');const data=await response.json();if(run!==summaryRun||host.hidden)return;
   host.replaceChildren(make('h3','Offline-Videos & Speicher'),make('p','Downloadordner belegt: '+bytes(data.bytes)+(data.pending?' · Wird im Hintergrund aktualisiert …':'')));
   for(const row of data.folders){const box=make('div','','ov-folder'),open=make('button','Ordner im Explorer öffnen');open.type='button';open.onclick=async()=>{try{await folder(row.path);const note=make('span','Ordner im Explorer geöffnet.');note.setAttribute('role','status');box.append(note);}catch(e){box.append(make('p',e.message));}};box.append(make('strong',row.path),make('span',bytes(row.bytes)+' · '+(row.files??'…')+' Dateien inklusive Unterordnern'),open);host.append(box);}
   for(const disk of data.drives){const box=make('div','','ov-disk'),meter=make('meter');meter.min=0;meter.max=disk.total;meter.value=disk.used;meter.setAttribute('aria-label','Belegung von '+disk.path);box.append(make('strong','Laufwerk '+disk.path),make('span',bytes(disk.free)+' frei · '+bytes(disk.used)+' belegt · '+bytes(disk.total)+' gesamt'),meter);host.append(box);}
   if(!data.folders.length)host.append(make('p','Noch kein Downloadordner eingerichtet. Wähle beim Download einen Zielordner.'));
   const reload=make('button','Speicherübersicht aktualisieren');reload.type='button';reload.onclick=()=>refresh(true);host.append(reload);
   summaryTimer=setTimeout(()=>{if(run===summaryRun&&!document.hidden&&!host.closest('.hidden'))refresh();},data.pending?1500:15000);
  }catch(e){if(run===summaryRun){const retry=make('button','Erneut versuchen');retry.type='button';retry.onclick=()=>refresh();host.replaceChildren(make('p',e.message),retry);summaryTimer=setTimeout(()=>{if(run===summaryRun&&!document.hidden&&!host.closest('.hidden'))refresh();},5000);}}};await refresh();
 }
 let dbPromise;
 function database(){return dbPromise||=(new Promise(resolve=>{const request=indexedDB.open('adultclient-offline-posters',1);request.onupgradeneeded=()=>{const store=request.result.createObjectStore('posters',{keyPath:'key'});store.createIndex('at','at');};request.onsuccess=()=>resolve(request.result);request.onerror=()=>resolve(null);}));}
 async function cached(key,blob){try{const db=await database();if(!db)return null;return await new Promise(resolve=>{const tx=db.transaction('posters',blob?'readwrite':'readonly'),store=tx.objectStore('posters');if(blob){store.put({key,blob,at:Date.now()});const count=store.count();count.onsuccess=()=>{let remove=count.result-200;if(remove>0){const cursor=store.index('at').openCursor();cursor.onsuccess=()=>{if(remove-->0&&cursor.result){cursor.result.delete();cursor.result.continue();}};}};tx.oncomplete=()=>resolve(blob);tx.onerror=()=>resolve(null);}else{const r=store.get(key);r.onsuccess=()=>resolve(r.result?.blob||null);r.onerror=()=>resolve(null);}});}catch{return null;}}
 const posterUrls=new Map();
 function cleanPosters(){for(const [url,img] of posterUrls)if(!img.isConnected){URL.revokeObjectURL(url);posterUrls.delete(url);}}
 function poster(image,blob){cleanPosters();if(image.dataset.objectUrl){URL.revokeObjectURL(image.dataset.objectUrl);posterUrls.delete(image.dataset.objectUrl);}const url=URL.createObjectURL(blob);posterUrls.set(url,image);image.hidden=false;image.src=url;image.dataset.objectUrl=url;}
 let current=null,working=false,queue=[],observer;
 function stop(){if(current){clearTimeout(current.timer);current.handle?.dispose?.();current.video.pause();current.video.removeAttribute('src');current.video.load();current.video.remove();current.resolve?.();current=null;}}
 function leave(){stop();cleanPosters();queue=[];observer?.disconnect();clearTimeout(summaryTimer);summaryRun++;}
 async function media(cover,item,ctx,image,moving=false){if(!cover.isConnected||document.hidden)return;stop();const video=make('video');video.muted=true;video.loop=!!moving;video.playsInline=true;video.crossOrigin='anonymous';video.preload='metadata';video.className='ov-preview';video.setAttribute('aria-label','Lokale Videovorschau');if(!moving)video.style.opacity='0';cover.append(video);const job=current={video,handle:null,timer:null,moving};
  const finish=()=>{if(current===job){if(!image.naturalWidth){const note=cover.querySelector('.ov-preview-note');if(note)note.textContent='Vorschaubild nicht verfügbar · Video öffnen';}stop();}};
  job.timer=setTimeout(finish,18000);
  const save=()=>{if(current!==job||!video.videoWidth||video.readyState<2)return;
   try{const canvas=make('canvas'),factor=Math.min(1,480/video.videoWidth,480/video.videoHeight);canvas.width=Math.round(video.videoWidth*factor);canvas.height=Math.round(video.videoHeight*factor);canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);canvas.toBlob(async blob=>{if(!blob)return;await cached(item.previewKey,blob);if(cover.isConnected){poster(image,blob);cover.classList.remove('ml-missing-image');}if(!moving)finish();},'image/jpeg',.78);}catch{if(!moving)finish();}
  };
  video.addEventListener('loadeddata',()=>{if(current!==job)return;if(moving){clearTimeout(job.timer);save();}else{const at=Math.min(6,Math.max(0,(video.duration||0)*.12));if(Number.isFinite(at)&&at>.1){video.currentTime=at;}else save();}},{once:true});video.addEventListener('seeked',save,{once:true});video.addEventListener('error',finish,{once:true});
  try{job.handle=ctx.attach(video,make('select'),{path:item.previewSrc,mime:item.previewMime,title:item.title},true);if(moving)video.play().catch(()=>{});}catch{finish();}
  if(!moving)await new Promise(resolve=>{if(current!==job)resolve();else job.resolve=resolve;});
 }
 async function drain(){if(working)return;working=true;try{while(queue.length&&!current?.moving){const row=queue.shift();if(row.cover.isConnected&&!document.hidden){const blob=await cached(row.item.previewKey);if(blob){poster(row.image,blob);row.cover.classList.remove('ml-missing-image');}else await media(row.cover,row.item,row.ctx,row.image);}}}finally{working=false;}}
 function preview(cover,item,ctx){const image=make('img');image.alt='Videovorschau';image.hidden=true;image.decoding='async';cover.prepend(image);cover.classList.add('ml-missing-image');cover.append(make('span','Vorschaubild wird lokal erstellt …','ov-preview-note'));
  const show=()=>{const note=cover.querySelector('.ov-preview-note');if(note)note.remove();};image.onload=show;
  observer||=new IntersectionObserver(entries=>{for(const e of entries){if(e.isIntersecting&&e.target._offline){observer.unobserve(e.target);queue.push(e.target._offline);drain();}}},{rootMargin:'150px'});
  cover._offline={cover,item,ctx,image};observer.observe(cover);
  cover.addEventListener('mouseenter',()=>media(cover,item,ctx,image,true));cover.addEventListener('mouseleave',()=>{if(current?.video.parentElement===cover)stop();drain();});
 }
 document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();else drain();});
 root.OfflineVideos={summary,preview,folder,leave,bytes};
})(globalThis);
