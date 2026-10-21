/* General provider library. Live-Cam modules and their media stores are separate. */
(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.MediaLibrary = api;
})(globalThis, function (root) {
  'use strict';
  const LABELS = {video:'Videos',image:'Bilder',animation:'Animationen',audio:'Audio',gallery:'Galerien',folder:'Sammlungen',document:'Dokumente',file:'Dateien',live:'Live-Cams'};
  const ICONS = {video:'▷',image:'▧',animation:'◈',audio:'♫',gallery:'▦',folder:'▤',document:'▱',file:'↓',live:'●'};
  const LIVE = new Set(['chaturbate','stripchat','cam4','xlovecam','bongacams','camsoda']);
  const TYPES = {image:['jpg','jpeg','png','webp','avif','bmp','svg','jxl'],animation:['gif','apng','gifv'],video:['mp4','m4v','webm','mkv','mov','avi','wmv','flv','ts','m3u8','mpd'],audio:['mp3','m4a','aac','ogg','oga','opus','wav','flac'],document:['pdf','txt','md','csv','json'],file:['zip','rar','7z','tar','gz','epub','cbz','cbr','psd','blend']};
  const COLLATOR = new Intl.Collator('de', {numeric:true,sensitivity:'base'});
  const SORTS = [['source','Anbieter-Reihenfolge'],['title','Name A–Z'],['title-desc','Name Z–A'],['date-desc','Neueste zuerst'],['date','Älteste zuerst'],['duration-desc','Längste zuerst'],['duration','Kürzeste zuerst'],['rating-desc','Beste Bewertung'],['rating','Niedrigste Bewertung'],['views-desc','Meistgesehen'],['views','Wenigste Aufrufe'],['uploader','Uploader A–Z'],['uploader-desc','Uploader Z–A'],['quality-desc','Höchste Auflösung'],['quality','Niedrigste Auflösung'],['saved','Gemerkte zuerst'],['preview','Mit Vorschau zuerst'],['kind','Nach Medientyp']];
  const KIND_ORDER = ['video','image','animation','gallery','folder','audio','document','file'];
  const PRELOAD_CHOICES=[0,1,3,6,10,15,25,50,100,250];
  const QUALITY_CHOICES = [['','Alle Qualitäten'],['240','ab 240p'],['360','ab 360p'],['480','ab 480p'],['720','ab 720p (HD)'],['1080','ab 1080p (Full HD)'],['1440','ab 1440p'],['2160','ab 2160p (4K)'],['4320','ab 4320p (8K)']];
  const DEFAULT = {q:'',kind:'all',sort:'source',format:'',uploader:'',orientation:'',minQuality:'',minDuration:'',maxDuration:'',minRating:'',saved:false,descriptions:true,view:'grid',fit:'contain',size:220,per:36,page:1,prefetch:3};
  let memory = null, library = null, viewer = null, sitePreview = null;

  function preferences(value) {
    const result={...DEFAULT};
    if(!value || typeof value!=='object')return result;
    for(const key of Object.keys(DEFAULT))if(typeof value[key]===typeof DEFAULT[key])result[key]=value[key];
    if(!SORTS.some(([id]) => id===result.sort))result.sort='source';
    if(!QUALITY_CHOICES.some(([id])=>id===result.minQuality))result.minQuality='';
    if(!['all',...Object.keys(LABELS)].includes(result.kind))result.kind='all';
    if(!['grid','masonry','list'].includes(result.view))result.view='grid';
    if(!['contain','cover'].includes(result.fit))result.fit='contain';
    if(![12,24,36,48,60,96,120].includes(result.per))result.per=36;
    if(!Number.isInteger(result.prefetch) || result.prefetch<0 || result.prefetch>250)result.prefetch=3;
    if(![160,220,300].includes(result.size))result.size=220;
    result.page=Math.max(1,Math.floor(result.page)||1);
    return result;
  }

  function read() {
    if (memory) return memory;
    const record=value => value && typeof value==='object' && !Array.isArray(value);
    try {
      const value = JSON.parse(root.localStorage?.getItem('ah-media-library-v1') || 'null');
      if(value?.version===1 && record(value.providers) && record(value.sites) && record(value.viewer) && Array.isArray(value.profiles)) {
        memory=value;memory.profiles=memory.profiles.filter(profile => record(profile) && typeof profile.name==='string' && record(profile.prefs)).slice(-20);
        if(![3,5,10,20].includes(memory.viewer.seconds))memory.viewer.seconds=5;
        if(!['dark','light','checker'].includes(memory.viewer.background))memory.viewer.background='dark';
      }
    } catch (_) {}
    return memory ||= {version:1,providers:{},sites:{kind:'all',sort:'title',group:false},profiles:[],viewer:{filmstrip:true,background:'dark',seconds:5}};
  }
  function persist() { try { root.localStorage?.setItem('ah-media-library-v1', JSON.stringify(read())); } catch (_) { /* A storage restriction never prevents viewing. */ } }
  function target(value) {
    value = String(value || '');
    if (value.startsWith('plugin://') || /^\??mode=/.test(value)) return new URLSearchParams(value.includes('?') ? value.split('?').slice(1).join('?') : value.replace(/^\?/, '')).get('url') || '';
    return value;
  }
  function safeURL(value) { try { const u = new URL(String(value).split('|')[0], root.location?.href || 'http://127.0.0.1/'); return ['http:','https:'].includes(u.protocol) && !u.username && !u.password ? u.href : ''; } catch (_) { return ''; } }
  function knownExtension(value) {
    const ext = String(value || '').toLowerCase();
    return Object.keys(TYPES).some(kind => TYPES[kind].includes(ext)) ? ext : '';
  }
  function media(item) {
    if (item.media?.kind) return {...item.media, extension: knownExtension(item.media.extension)};
    if (item.mediaType) return {kind:item.mediaType,extension:knownExtension(item.extension)};
    if (item.folder) return {kind:'folder',extension:''};
    const path = target(item.url).split('|')[0].split('?')[0].toLowerCase();
    const ext = knownExtension(path.split('/').at(-1)?.split('.').slice(1).at(-1) || '');
    return {kind:Object.keys(TYPES).find(kind => TYPES[kind].includes(ext)) || 'video',extension:ext};
  }
  function groupMixed(items, prefs) {
    if (!prefs || prefs.kind !== 'all' || prefs.sort !== 'source') return items;
    const rank = kind => { const index = KIND_ORDER.indexOf(kind); return index < 0 ? KIND_ORDER.length : index; };
    const kinds = new Set(items.map(item => media(item).kind));
    if (kinds.size < 2) return items;
    return items.slice().sort((a,b) => rank(media(a).kind) - rank(media(b).kind));
  }
  function isLive(item) {return media(item).kind==='live' || LIVE.has(item.site || item.media?.provider || new URLSearchParams(queryOf(item)).get('website'));}
  function duration(value) {
    if (typeof value === 'number') return value;
    const s = String(value || '').trim();
    if (/^\d+(?::\d{1,2}){1,2}$/.test(s)) return s.split(':').reduce((n,v) => n*60+Number(v),0);
    const n = Number(s); return Number.isFinite(n) && n > 0 ? n : null;
  }
  function stamp(value) {
    if (!value) return null;
    const s = String(value), match = s.match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
    const n = Date.parse(match ? `${match[3]}-${match[2]}-${match[1]}` : s);
    return Number.isFinite(n) ? n : null;
  }
  function rating(value) { const n = Number(String(value ?? '').replace('%','').replace(',','.')); return Number.isFinite(n) && value !== '' && value != null ? n : null; }
  function viewCount(value) {
    if(typeof value==='number')return Number.isFinite(value)&&value>=0?value:null;
    let text=String(value??'').trim().toLowerCase().replace(/\s+/g,'');
    const match=text.match(/^(\d[\d.,]*)(k|m|b|tsd\.?|mio\.?|mrd\.?)?(?:views?|aufrufe?)?$/);
    if(!match)return null;
    let digits=match[1];const unit=match[2]||'';
    if(unit)digits=digits.replace(',','.');
    else if(/^\d{1,3}(?:[.,]\d{3})+$/.test(digits))digits=digits.replace(/[.,]/g,'');
    const count=Number(digits),factor=/^(k|tsd)/.test(unit)?1e3:/^(m$|mio)/.test(unit)?1e6:/^(b|mrd)/.test(unit)?1e9:1;
    return Number.isFinite(count)?count*factor:null;
  }
  function quality(item) {
    const m=media(item),height=Number(m.height||item.height),width=Number(m.width||item.width);
    if(Number.isFinite(height)&&height>0)return width>0?Math.min(width,height):height;
    const text=String(m.quality||item.quality||item.facts?.quality||item.facts?.details?.sourceQuality||'');
    const values=Array.from(text.matchAll(/\b(\d{3,4})p\b/gi),match=>Number(match[1]));
    if(/\b8k\b/i.test(text))values.push(4320);
    if(/\b(?:4k|UHD)\b/i.test(text))values.push(2160);
    if(/\b(?:FHD|Full\s*HD)\b/i.test(text))values.push(1080);
    return values.length?Math.max(...values):null;
  }
  function sortLabel(value) {
    const labels={relevance:'Relevanz',newest:'Neueste zuerst',latest:'Neueste zuerst',rating:'Beste Bewertung',length:'Längste zuerst',views:'Meistgesehen',random:'Zufällig',popular:'Beliebteste',mostviewed:'Meistgesehen','most viewed':'Meistgesehen','top rated':'Beste Bewertung'};
    return labels[String(value).trim().toLowerCase()]||value;
  }
  function compareKnown(a,b,descending=false) { if (a == null && b == null) return 0; if (a == null) return 1; if (b == null) return -1; return (a-b)*(descending?-1:1); }
  function filterItems(items, prefs, isSaved = () => false) {
    const words = String(prefs.q || '').toLocaleLowerCase('de').trim().split(/\s+/).filter(Boolean);
    const rows = items.map((item,index) => ({item,index,m:media(item)})).filter(({item,m}) => {
      if (isLive(item)) return false;
      if (prefs.kind !== 'all' && m.kind !== prefs.kind && !(prefs.kind === 'gallery' && m.kind === 'folder')) return false;
      if (prefs.format && String(m.extension || '').toLowerCase() !== prefs.format) return false;
      if (prefs.uploader && item.uploader !== prefs.uploader) return false;
      if (prefs.saved && !isSaved(item.url)) return false;
      if (prefs.minQuality && (m.kind!=='video' || quality(item)==null || quality(item)<Number(prefs.minQuality))) return false;
      const blob = [item.title,item.uploader,...(item.categories || []).map(x => typeof x === 'string' ? x : x.name),prefs.descriptions ? item.plot : ''].join(' ').toLocaleLowerCase('de');
      if (words.some(word => !blob.includes(word))) return false;
      if (prefs.orientation) {
        const orientation = m.width && m.height ? (m.width > m.height*1.05 ? 'landscape' : m.height > m.width*1.05 ? 'portrait' : 'square') : 'unknown';
        if (orientation !== prefs.orientation) return false;
      }
      const seconds = duration(m.duration || item.duration);
      if (prefs.minDuration !== '' && (seconds == null || seconds < Number(prefs.minDuration)*60)) return false;
      if (prefs.maxDuration !== '' && (seconds == null || seconds > Number(prefs.maxDuration)*60)) return false;
      const score = rating(m.rating ?? item.rating);
      if (prefs.minRating !== '' && (score == null || score < Number(prefs.minRating))) return false;
      return true;
    });
    rows.sort((a,b) => {
      let n = 0;
      if (prefs.sort === 'title' || prefs.sort === 'title-desc') n = COLLATOR.compare(a.item.title,b.item.title)*(prefs.sort.endsWith('desc')?-1:1);
      if (prefs.sort.startsWith('date')) n = compareKnown(stamp(a.m.date || a.item.date),stamp(b.m.date || b.item.date),prefs.sort.endsWith('desc'));
      if (prefs.sort.startsWith('duration')) n = compareKnown(duration(a.m.duration || a.item.duration),duration(b.m.duration || b.item.duration),prefs.sort.endsWith('desc'));
      if (prefs.sort.startsWith('rating')) n = compareKnown(rating(a.m.rating ?? a.item.rating),rating(b.m.rating ?? b.item.rating),prefs.sort.endsWith('desc'));
      if (prefs.sort.startsWith('views')) n = compareKnown(viewCount(a.m.views ?? a.item.views ?? a.item.facts?.views),viewCount(b.m.views ?? b.item.views ?? b.item.facts?.views),prefs.sort.endsWith('desc'));
      if (prefs.sort.startsWith('quality')) n = compareKnown(quality(a.item),quality(b.item),prefs.sort.endsWith('desc'));
      if (prefs.sort.startsWith('uploader')) {const x=a.item.uploader,y=b.item.uploader;n=!x&&!y?0:!x?1:!y?-1:COLLATOR.compare(x,y)*(prefs.sort.endsWith('desc')?-1:1);}
      if (prefs.sort==='saved') n=Number(isSaved(b.item.url))-Number(isSaved(a.item.url));
      if (prefs.sort==='preview') n=Number(!!(b.item.clip||(b.item.preview||[]).length>1))-Number(!!(a.item.clip||(a.item.preview||[]).length>1));
      if (prefs.sort === 'kind') n = COLLATOR.compare(LABELS[a.m.kind],LABELS[b.m.kind]);
      return n || a.index-b.index;
    });
    return rows.map(row => row.item);
  }
  function element(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key,value] of Object.entries(attrs)) {
      if (key === 'text') node.textContent = value;
      else if (key === 'class') node.className = value;
      else if (key.startsWith('on')) node.addEventListener(key.slice(2),value);
      else if (value !== undefined && value !== null) { if (key in node && !['list','form'].includes(key)) node[key] = value; else node.setAttribute(key,value); }
    }
    node.append(...children.filter(x => x != null)); return node;
  }
  const button = (text, click, attrs={}) => element('button',{type:'button',text,onclick:click,...attrs});
  function select(label,value,choices,change,attrs={}) {
    const input = element('select',{'aria-label':label,...attrs,onchange:e => change(e.target.value)});
    for (const choice of choices) { const [id,title] = Array.isArray(choice) ? choice : [choice,choice]; input.append(element('option',{value:id,text:title})); }
    input.value = String(value); return element('label',{class:'ml-field'},element('span',{text:label}),input);
  }
  function field(label,value,change,type='text',attrs={}) { return element('label',{class:'ml-field'},element('span',{text:label}),element('input',{type,value,'aria-label':label,...attrs,oninput:e => change(e.target.value)})); }
  function check(label,value,change) { return element('label',{class:'ml-check'},element('input',{type:'checkbox',checked:!!value,onchange:e => change(e.target.checked)}),label); }
  function notice(node,message,error=false) { node.textContent = message; node.hidden = !message; node.classList.toggle('ml-error',error); }
  function queryOf(item) { const value = String(item.url || ''); return value.startsWith('plugin://') ? value.split('?').slice(1).join('?') : value.replace(/^\?/,''); }

  const SITE_SORTS = [['title','Name A–Z'],['title-desc','Name Z–A'],['favorites','Favoriten zuerst'],['recent','Zuletzt geöffnet'],['formats','Viele Medientypen zuerst'],['newest','Zuletzt hinzugefügt'],['oldest','Zuerst hinzugefügt'],['category','Nach Inhaltsbereich'],['type','Nach Anbieterart']];
  function prepareSitePrefs(prefs) {
    if (!SITE_SORTS.some(([id]) => id === prefs.sort)) prefs.sort = 'title';
    if (prefs.view !== 'list') prefs.view = 'cards';
    if (typeof prefs.letter !== 'string' || !/^[A-Z#]?$/.test(prefs.letter)) prefs.letter = '';
    prefs.onlyFav = !!prefs.onlyFav;
    if (!['visible','hidden','all'].includes(prefs.visibility)) prefs.visibility = 'visible';
    prefs.recentOnly = !!prefs.recentOnly;
    prefs.group = !!prefs.group;
    if(typeof prefs.hoverPreview !== 'boolean')prefs.hoverPreview=true;
    if (!['all','image','video','animation','audio','file','mixed'].includes(prefs.kind)) prefs.kind = 'all';
    return prefs;
  }
  function siteLetter(site) {
    const raw = String(site.title || site.id || '').trim().normalize('NFD').replace(/\p{M}/gu, '');
    const ch = raw.charAt(0).toLocaleUpperCase('de');
    return /^[A-Z]$/.test(ch) ? ch : '#';
  }
  function siteCover(site) {
    const title = String(site.title || site.id || '');
    const clean = title.normalize('NFD').replace(/\p{M}/gu, '').replace(/[^0-9A-Za-z]/g, '');
    const mono = (clean.slice(0, 2) || 'AH').toUpperCase();
    let hash = 0;
    const key = String(site.id || title);
    for (let i = 0; i < key.length; i++) hash = Math.imul(hash, 33) + key.charCodeAt(i) | 0;
    const hue = (hash >>> 0) % 360;
    const hue2 = (hue + 28 + ((hash >>> 8) % 70)) % 360;
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="hsl(${hue},46%,32%)"/><stop offset="100%" stop-color="hsl(${hue2},42%,14%)"/></linearGradient></defs><rect width="640" height="360" fill="url(#g)"/><text x="320" y="214" text-anchor="middle" font-family="Segoe UI,Arial,sans-serif" font-size="148" font-weight="700" fill="#f5f7fb">${mono}</text></svg>`;
    return 'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(svg);
  }
  function siteImage(site) {
    const img = element('img', {alt:'', loading:'lazy'});
    const useCover = () => { img.dataset.fallback = '1'; img.hidden = false; img.src = siteCover(site); };
    if (!site.logo) useCover();
    else {
      img.src = site.logo;
      img.onerror = () => { if (img.dataset.fallback === '1') return; useCover(); };
    }
    return img;
  }

  function previewItems(items) {
    const seen=new Set();
    return (items||[]).filter(item=>{
      if(!item.url||!item.thumb||isLive(item)||['next','previous','search','sort'].includes(item.role)||item.folder&&!['gallery','image','animation'].includes(media(item).kind)||seen.has(item.url))return false;
      seen.add(item.url);return true;
    }).slice(0,6);
  }

  class SitePreview {
    constructor(){
      this.cache=new Map();this.epoch=0;
      document.addEventListener('visibilitychange',()=>{if(document.hidden)this.close();});
      document.addEventListener('keydown',event=>{if(event.key==='Escape'&&this.popup){event.preventDefault();this.close(true);}});
      document.addEventListener('scroll',event=>{if(this.popup&&!this.popup.contains(event.target))this.close();},true);
      root.addEventListener?.('resize',()=>this.close());
    }
    bind(node,site,ctx){
      node.addEventListener('pointerenter',event=>{
        if(event.pointerType==='touch'||!prepareSitePrefs(read().sites).hoverPreview||this.pinned)return;
        clearTimeout(this.openTimer);clearTimeout(this.closeTimer);
        this.openTimer=setTimeout(()=>{if(node.isConnected&&!document.hidden)this.show(site,node,ctx,false);},450);
      });
      node.addEventListener('pointerleave',event=>{clearTimeout(this.openTimer);if(!this.pinned&&!this.popup?.contains(event.relatedTarget))this.closeTimer=setTimeout(()=>this.close(),350);});
    }
    position(){
      if(!this.popup||!this.anchor?.isConnected)return;
      const viewWidth=document.documentElement?.clientWidth||root.innerWidth;
      this.popup.style.maxWidth=Math.max(0,viewWidth-16)+'px';
      const box=this.anchor.getBoundingClientRect(),width=this.popup.getBoundingClientRect().width,height=this.popup.getBoundingClientRect().height;
      const x=box.right+10+width<=viewWidth?box.right+10:box.left-width-10>=8?box.left-width-10:Math.max(8,(viewWidth-width)/2);
      Object.assign(this.popup.style,{left:Math.max(8,Math.min(viewWidth-width-8,x))+'px',top:Math.max(8,Math.min(root.innerHeight-height-8,box.top))+'px'});
    }
    async show(site,anchor,ctx,pinned=false){
      clearTimeout(this.openTimer);clearTimeout(this.closeTimer);
      if(this.site?.id===site.id&&this.popup){this.pinned=pinned||this.pinned;if(pinned)this.popup.querySelector?.('header button')?.focus?.({preventScroll:true});return;}
      this.close();this.ctx=ctx;this.site=site;this.anchor=anchor;this.pinned=pinned;
      const epoch=this.epoch,controller=new AbortController();this.abort=controller;
      const open=()=>{this.close();ctx.openSite(site.id);};
      this.status=element('p',{class:'ml-muted',role:'status',text:'Inhalte werden geladen …'});
      this.items=element('div',{class:'ml-site-preview-items'});
      this.popup=element('section',{class:'ml-site-preview',role:'region','aria-label':'Inhaltsvorschau '+site.title},
        element('header',{},element('div',{},element('strong',{text:site.title}),element('small',{text:'Inhaltsvorschau · stumm'})),button('×',()=>this.close(true),{'aria-label':'Inhaltsvorschau schließen'})),
        this.status,this.items,element('footer',{},button('Anbieter öffnen',open),button('Erneut laden',()=>{this.cache.delete(site.id);this.close();this.show(site,anchor,ctx,true);})),
        element('small',{class:'ml-muted',text:'Beispiele des Anbieters. Für weitere Inhalte den Anbieter öffnen.'}));
      this.popup.addEventListener('pointerenter',()=>clearTimeout(this.closeTimer));
      this.popup.addEventListener('pointerleave',event=>{if(!this.pinned&&!this.anchor?.contains(event.relatedTarget))this.closeTimer=setTimeout(()=>this.close(),350);});
      (document.fullscreenElement||document.body).append(this.popup);this.position();
      if(pinned)this.popup.querySelector?.('header button')?.focus?.({preventScroll:true});
      try{
        let hit=this.cache.get(site.id),data=hit&&Date.now()-hit.at<300000?hit.data:null;
        if(!data)data=await ctx.providerPreview(site,controller.signal);
        if(controller.signal.aborted||epoch!==this.epoch)return;
        if(!data.ok)throw Error(data.error||'Vorschau gerade nicht verfügbar.');
        const rows=previewItems(data.items);
        if(rows.length){this.cache.delete(site.id);this.cache.set(site.id,{at:hit&&data===hit.data?hit.at:Date.now(),data});while(this.cache.size>32)this.cache.delete(this.cache.keys().next().value);}
        this.status.textContent=rows.length?(data.cached?'Gespeicherte Beispiele':'Beispiele des Anbieters')+' · '+rows.length+' Inhalte':data.message||'Keine Vorschau verfügbar. Den Anbieter kannst du weiterhin öffnen.';
        let first=null,firstMotion=false;
        for(const item of rows){
          const img=element('img',{src:ctx.image(item)||item.thumb,alt:'',decoding:'async'}),cover=element('span',{class:'ml-site-preview-cover'},img);
          img.onerror=()=>{img.onerror=null;img.src=siteCover(site);};
          const card=button('',()=>{this.close();ctx.openProviderItem(site,item,rows);},{class:'ml-site-preview-item','aria-label':item.title+' öffnen'});
          card.append(cover,element('span',{class:'ml-site-preview-title',text:item.title}),element('small',{class:'ml-muted',text:(item.clip?'▷ Vorschauclip':(item.preview||[]).length>1?'▧ Bildfolge':LABELS[media(item).kind]||'Inhalt')+(item.duration?' · '+item.duration:'')}));
          const play=()=>this.play(card,cover,img,item);
          card.addEventListener('pointerenter',play);card.addEventListener('focus',play);this.items.append(card);
          const motion=!!item.clip||(item.preview||[]).length>1;
          if(!first||!firstMotion&&motion){first=play;firstMotion=motion;}
        }
        this.position();first?.();
      }catch(error){if(!controller.signal.aborted&&epoch===this.epoch){this.status.textContent=error.name==='TimeoutError'?'Der Anbieter antwortet zu langsam. Bitte erneut versuchen.':error.name==='TypeError'?'Die Verbindung zur Vorschau ist gerade nicht erreichbar.':error.message||'Die Vorschau konnte nicht geladen werden.';this.position();}}
    }
    play(card,cover,img,item){
      if(this.current?.card===card)return;this.stop();this.current={card,cover,img,item};card.classList.add('is-active');
      // Only supplied clips/frames; never resolve a full video just for hover.
      if(item.clip||(item.preview||[]).length>1)this.ctx.previewStart(cover,img,item);
    }
    stop(){if(this.current){const {card,cover,img,item}=this.current;this.ctx.previewStop(cover,img,item);card.classList.remove('is-active');this.current=null;}}
    close(focus=false){
      clearTimeout(this.openTimer);clearTimeout(this.closeTimer);this.epoch++;this.abort?.abort();this.abort=null;this.stop();
      const anchor=this.anchor;this.popup?.remove();this.popup=null;this.anchor=null;this.site=null;this.pinned=false;
      if(focus&&anchor?.isConnected)anchor.querySelector?.('button')?.focus();
    }
  }
  function closeSitePreview(){sitePreview?.close();}

  function renderSites(ctx) {
    if (!ctx.state.catalog) return true;
    sitePreview ||= new SitePreview();sitePreview.close();
    const host = document.getElementById('view-sites'), list = document.getElementById('site-list'), prefs = prepareSitePrefs(read().sites);
    let tools = document.getElementById('ml-site-tools');
    if (!tools) {
      const search = document.getElementById('site-filter'); search.placeholder = 'Anbieter suchen …'; search.setAttribute('aria-label','Anbieter suchen');
      const oldRow = search.parentElement;
      tools = element('div',{id:'ml-site-tools',class:'ml-site-tools'});
      const heading = element('div',{class:'ml-section-heading'},element('div',{},element('span',{class:'ml-eyebrow',text:'DEINE MEDIATHEK'}),element('h2',{text:'Anbieter entdecken'}),element('p',{class:'ml-muted',text:'Videos, Bilder und Galerien an einem Ort. Live-Cams findest du im eigenen Live-Menü.'})),button('● Zu Live-Cams',() => ctx.live(),{class:'ml-secondary'}));
      host.querySelector('h2')?.remove(); host.prepend(heading);
      const parked = element('div',{id:'ml-site-parked',hidden:true});
      for (const id of ['content','kind']) { const input = document.getElementById(id); for (const option of [...input.options]) if (option.value === 'live') option.remove(); input.setAttribute('aria-label', id === 'content' ? 'Inhaltsbereich' : 'Anbieterart'); parked.append(input); }
      const favorite = document.getElementById('only-fav');
      favorite.checked=prefs.onlyFav;
      favorite.addEventListener('input',()=>{prefs.onlyFav=favorite.checked;persist();},true);
      tools.append(element('div',{class:'ml-search-line'},search,select('Sortieren',prefs.sort,SITE_SORTS,value => { prefs.sort=value;persist();renderSites(ctx); },{id:'ml-site-sort'}),select('Ansicht',prefs.view,[['cards','Kacheln'],['list','Liste']],value => { prefs.view=value;persist();renderSites(ctx); },{id:'ml-site-view'})));
      tools.append(element('div',{class:'ml-chip-block'},element('span',{class:'ml-chip-label',text:'Medientyp'}),element('div',{id:'ml-site-kinds',class:'ml-chips','aria-label':'Anbieter nach Medien filtern'})));
      tools.append(element('div',{class:'ml-chip-block'},element('span',{class:'ml-chip-label',text:'Inhaltsbereich'}),element('div',{id:'ml-site-content',class:'ml-chips','aria-label':'Inhaltsbereich'})));
      tools.append(element('div',{class:'ml-chip-block'},element('span',{class:'ml-chip-label',text:'Anbieterart'}),element('div',{id:'ml-site-types',class:'ml-chips','aria-label':'Anbieterart'})));
      tools.append(element('div',{class:'ml-chip-block'},element('span',{class:'ml-chip-label',text:'Anfangsbuchstabe'}),element('div',{id:'ml-site-letters',class:'ml-chips ml-letters','aria-label':'Anfangsbuchstabe'})));
      tools.append(element('div',{class:'ml-fields'},select('Anbieter anzeigen',prefs.visibility,[['visible','Sichtbare Anbieter'],['hidden','Ausgeblendete Anbieter'],['all','Alle Anbieter']],value=>{prefs.visibility=value;persist();renderSites(ctx);},{id:'ml-site-visibility'}),element('label',{class:'ml-check'},favorite,'Nur Favoriten'),element('label',{class:'ml-check'},element('input',{id:'ml-site-recent',type:'checkbox',checked:prefs.recentOnly,onchange:e => { prefs.recentOnly=e.target.checked;persist();renderSites(ctx); }}),'Nur zuletzt geöffnet'),element('label',{class:'ml-check'},element('input',{id:'ml-site-group',type:'checkbox',checked:prefs.group,onchange:e => { prefs.group=e.target.checked;persist();renderSites(ctx); }}),'Nach Inhaltsbereich gruppieren')));
      tools.append(parked,element('div',{class:'ml-result-line'},element('span',{id:'ml-site-count','aria-live':'polite'}),button('Filter zurücksetzen',() => { prefs.kind='all';prefs.sort='title';prefs.letter='';prefs.recentOnly=false;prefs.group=false;prefs.onlyFav=false;prefs.visibility='visible';document.getElementById('site-filter').value='';document.getElementById('content').value='';document.getElementById('kind').value='';favorite.checked=false;persist();renderSites(ctx); })));
      tools.append(check('Hover-Vorschau mit Hoster-Inhalten',prefs.hoverPreview,value=>{prefs.hoverPreview=value;persist();sitePreview.close();}),element('p',{class:'ml-muted ml-site-help',text:'Für eine Inhaltsvorschau kurz über einem Anbieter bleiben oder „Vorschau“ wählen. Ausgeblendete Hoster kannst du über „Anbieter anzeigen“ wiederherstellen.'}),element('p',{id:'ml-site-status',class:'ml-notice',role:'status',hidden:true}));
      oldRow.hidden = true;list.before(tools);
    }
    const visibilityInput=document.getElementById('ml-site-visibility');
    if(visibilityInput)visibilityInput.value=prefs.visibility;
    const sortInput = document.getElementById('ml-site-sort'), viewInput = document.getElementById('ml-site-view');
    if (sortInput && sortInput.value !== prefs.sort) sortInput.value = prefs.sort;
    if (viewInput && viewInput.value !== prefs.view) viewInput.value = prefs.view;
    const recentBox = document.getElementById('ml-site-recent'), groupBox = document.getElementById('ml-site-group');
    if (recentBox) recentBox.checked = prefs.recentOnly;
    if (groupBox) groupBox.checked = prefs.group;
    const kindChoices = [['all','Alle Anbieter'],['image','▧ Bilder & Galerien'],['video','▷ Videos'],['animation','◈ Animationen'],['audio','♫ Audio'],['file','↓ Dokumente & Dateien'],['mixed','Gemischte Inhalte']];
    const catalog = (ctx.state.catalog.sites || []).filter(site => !LIVE.has(site.id) && !site.liveOnly);
    const supports = (site,kind) => { const types=site.mediaTypes || ['video'];return kind==='all' || kind==='mixed' && types.filter(t => t!=='gallery').length>1 || kind==='file' && types.some(t => ['document','file'].includes(t)) || kind==='image' && types.some(t => ['image','gallery'].includes(t)) || types.includes(kind); };
    const text = document.getElementById('site-filter').value.trim().toLowerCase(), content=document.getElementById('content').value, type=document.getElementById('kind').value, onlyFav=document.getElementById('only-fav').checked;
    const recent = ctx.state.catalog.recent || [], recentRank = id => { const index = recent.indexOf(id); return index < 0 ? 9999 : index; };
    const matches = (site, ignore = {}) => (prefs.visibility==='all' || (prefs.visibility==='hidden')===!!site.hidden) && supports(site, ignore.kind ? 'all' : (prefs.kind || 'all')) && (ignore.text || !text || (site.title+' '+site.id).toLowerCase().includes(text)) && (ignore.content || !content || site.content?.includes(content)) && (ignore.type || !type || site.types?.includes(type)) && (ignore.fav || !onlyFav || site.favorite) && (ignore.recent || !prefs.recentOnly || recent.includes(site.id)) && (ignore.letter || !prefs.letter || siteLetter(site) === prefs.letter);
    const paint = (id, choices, current, pick) => document.getElementById(id).replaceChildren(...choices.map(([value,label]) => button(label,() => pick(value),{class:current===value?'is-active':'','aria-pressed':String(current===value)})));
    paint('ml-site-kinds', kindChoices.map(([id,label]) => [id, label+' · '+catalog.filter(site => supports(site,id) && matches(site,{kind:true})).length]), prefs.kind || 'all', value => { prefs.kind=value;persist();renderSites(ctx); });
    paint('ml-site-content', [...document.getElementById('content').options].map(option => [option.value, option.textContent+' · '+catalog.filter(site => matches(site,{content:true}) && (!option.value || site.content?.includes(option.value))).length]), content, value => { document.getElementById('content').value=value;renderSites(ctx); });
    paint('ml-site-types', [...document.getElementById('kind').options].map(option => [option.value, option.textContent+' · '+catalog.filter(site => matches(site,{type:true}) && (!option.value || site.types?.includes(option.value))).length]), type, value => { document.getElementById('kind').value=value;renderSites(ctx); });
    const letters = [...'ABCDEFGHIJKLMNOPQRSTUVWXYZ#'];
    const letterCounts = Object.fromEntries(letters.map(letter => [letter, catalog.filter(site => matches(site,{letter:true}) && siteLetter(site)===letter).length]));
    paint('ml-site-letters', [['','Alle'], ...letters.filter(letter => letterCounts[letter] || prefs.letter===letter).map(letter => [letter, letter+' · '+letterCounts[letter]])], prefs.letter, value => { prefs.letter=value;persist();renderSites(ctx); });
    const optionLabel = (selectId, value) => [...document.getElementById(selectId).options].find(option => option.value===value)?.textContent || value || '';
    let sites = catalog.filter(site => matches(site));
    sites.sort((a,b) => (prefs.group ? COLLATOR.compare(ctx.contentLabel(a.content?.[0] || 'general'), ctx.contentLabel(b.content?.[0] || 'general')) : 0) || (prefs.sort==='favorites' ? Number(b.favorite)-Number(a.favorite) : prefs.sort==='recent' ? recentRank(a.id)-recentRank(b.id) : prefs.sort==='formats' ? (b.mediaTypes?.length || 1)-(a.mediaTypes?.length || 1) : prefs.sort==='newest' ? (Number(b.catalogId)||0)-(Number(a.catalogId)||0) : prefs.sort==='oldest' ? (Number(a.catalogId)||0)-(Number(b.catalogId)||0) : prefs.sort==='category' ? COLLATOR.compare(ctx.contentLabel(a.content?.[0] || 'general'), ctx.contentLabel(b.content?.[0] || 'general')) : prefs.sort==='type' ? COLLATOR.compare(optionLabel('kind', a.types?.[0] || ''), optionLabel('kind', b.types?.[0] || '')) : 0) || COLLATOR.compare(a.title,b.title)*(prefs.sort==='title-desc'?-1:1));
    document.getElementById('ml-site-count').textContent = `${sites.length} von ${catalog.length} Anbietern · ${catalog.filter(site=>site.hidden).length} ausgeblendet`;
    list.className = prefs.view==='list' ? 'ml-sites ml-sites-list' : 'ml-sites'; list.replaceChildren(); let group='';
    for (const site of sites) {
      const current=site.content?.[0] || 'general';
      if (prefs.group && group!==current) { group=current; list.append(element('h3',{class:'ml-group-heading',text:ctx.contentLabel(current)})); }
      const open=button('',() => ctx.openSite(site.id),{class:'ml-provider-open','aria-label':site.title+' öffnen'});
      open.append(element('span',{class:'ml-provider-cover'},siteImage(site)),element('span',{class:'ml-provider-body'},element('span',{class:'ml-provider-title',text:site.title}),element('span',{class:'ml-provider-category',text:(site.content || []).map(ctx.contentLabel).join(' · ') || 'Allgemein'}),element('span',{class:'ml-format-badges'},...(site.mediaTypes || ['video']).filter(t => t!=='gallery').map(t => element('span',{text:ICONS[t]+' '+LABELS[t]})))));
      const update=async(action,message)=>{
        const controls=[...list.querySelectorAll('.ml-provider-actions button')];
        controls.forEach(node=>node.disabled=true);
        try{await action(site);renderSites(ctx);notice(document.getElementById('ml-site-status'),message);}
        catch(e){notice(document.getElementById('ml-site-status'),e.message || 'Speichern fehlgeschlagen. Bitte erneut versuchen.',true);}
        finally{controls.forEach(node=>node.disabled=false);}
      };
      const fav=button(site.favorite?'★ Favorit':'☆ Favorit',()=>update(ctx.favoriteSite,site.title+(site.favorite?' aus Favoriten entfernt.':' als Favorit gespeichert.')),{class:'ml-provider-favorite','aria-label':site.title+(site.favorite?' aus Favoriten entfernen':' als Favorit speichern'),'aria-pressed':String(!!site.favorite)});
      const hide=button(site.hidden?'Einblenden':'Ausblenden',()=>update(ctx.hideSite,site.title+(site.hidden?' wieder eingeblendet.':' ausgeblendet. Über den Filter „Ausgeblendete Anbieter“ wiederherstellen.')),{class:'ml-provider-hide','aria-label':site.title+(site.hidden?' einblenden':' ausblenden')});
      if(site.hidden)open.append(element('span',{class:'ml-provider-hidden',text:'Ausgeblendet'}));
      const card=element('article',{class:'ml-provider'+(site.hidden?' is-hidden-provider':''),'data-provider':site.id},open,element('div',{class:'ml-provider-actions'},button('▷ Vorschau',()=>sitePreview.show(site,card,ctx,true),{'aria-label':'Inhaltsvorschau für '+site.title}),fav,hide));
      sitePreview.bind(card,site,ctx);list.append(card);
    }
    if (!sites.length) list.append(element('div',{class:'ml-empty'},element('strong',{text:'Keine passenden Anbieter'}),element('p',{text:'Prüfe Sichtbarkeit und Favoriten oder setze die Filter zurück. Ausgeblendete Hoster findest du über „Anbieter anzeigen“.'})));
    return true;
  }

  class Library {
    constructor(ctx) { this.ctx=ctx;this.scope='';this.busy=false; }
    render(ctx) {
      if(this.entry!==ctx.entry){this.entry=ctx.entry;this.prefetchKey=null;this.paused=false;this.customPrefetch=false;this.loadRevision=(this.loadRevision||0)+1;}
      this.ctx=ctx;
      const scope=ctx.scope || 'library';
      if (this.scope!==scope || !this.controls?.isConnected) {
        this.scope=scope;this.prefs={...preferences(read().providers[scope]),page:1};this.build();
      }
      this.update();return true;
    }
    change(key,value) { if(key==='page')return this.goPage(value);if(key==='prefetch'){this.loadRevision=(this.loadRevision||0)+1;this.paused=false;}this.prefs[key]=value;if(key!=='page')this.prefs.page=1;this.save();this.update(); }
    save() { const data=read();data.providers[this.scope]={...this.prefs};const keys=Object.keys(data.providers);for(const key of keys.slice(0,Math.max(0,keys.length-80)))delete data.providers[key];persist(); }
    build() {
      this.bottom?.remove();
      document.getElementById('ml-library-tools')?.remove();
      const p=this.prefs;
      this.controls=element('div',{id:'ml-library-tools',class:'ml-library-tools'});
      this.note=element('p',{class:'ml-notice',hidden:true,role:'status'});
      this.count=element('span',{'aria-live':'polite'});
      const q=field('In geladenen Medien suchen',p.q,value => this.change('q',value),'search',{placeholder:'Titel, Beschreibung, Tags oder Uploader …'});this.search=q.querySelector('input');
      this.controls.append(element('div',{class:'ml-section-heading'},element('div',{},element('span',{class:'ml-eyebrow',text:'MEDIEN & GALERIEN'}),element('p',{class:'ml-muted',text:'Filter und Sortierung gelten für die geladenen Einträge. Weitere Anbieter-Seiten werden beim Blättern automatisch vorgeladen.'})),button('▧ Galerie öffnen',() => this.openGallery(),{class:'ml-gallery-open'})),element('div',{class:'ml-search-line'},q,select('Geladene Medien sortieren',p.sort,SORTS,value => this.change('sort',value))));
      this.providerSort=select('Gesamten Anbieter sortieren','',[],async value=>{
        this.prefs.sort='source';this.save();
        try {await this.ctx.sortProvider?.(value);}catch(error){notice(this.note,error.message,true);}
      });
      this.controls.append(this.providerSort,element('p',{class:'ml-muted',text:'Für die gesamte Quelle die Anbieter-Sortierung verwenden. Die lokale Sortierung nutzt nur veröffentlichte Angaben; unbekannte Aufrufe, Bewertungen und Auflösungen stehen hinten.'}));
      this.qualityNote=element('p',{class:'ml-muted','aria-live':'polite'});
      this.controls.append(select('Video-Mindestqualität',p.minQuality,QUALITY_CHOICES,value=>this.change('minQuality',value)),this.qualityNote);
      this.preloadControl=select('Automatisch vorladen',PRELOAD_CHOICES.includes(p.prefetch)?p.prefetch:'custom',PRELOAD_CHOICES.map(n=>[n,n===0?'Aus':n+' '+(n===1?'Seite voraus':'Seiten voraus')]).concat([['custom','Eigene Anzahl …']]),value=>{
        this.customPrefetch=value==='custom';
        if(this.customPrefetch)this.update();else this.change('prefetch',Number(value));
      });
      const applyCustom=()=>{
        const n=Math.max(1,Math.min(250,Math.floor(Number(this.customInput.value)||3)));this.customInput.value=n;this.change('prefetch',n);
      };
      this.customInput=element('input',{type:'number',min:1,max:250,step:1,value:p.prefetch||3,'aria-label':'Eigene Vorlade-Seiten',onkeydown:e=>{if(e.key==='Enter'){e.preventDefault();applyCustom();}}});
      this.customControl=element('div',{class:'ml-custom-preload'},element('label',{class:'ml-field'},element('span',{text:'Eigene Vorlade-Seiten (1–250)'}),this.customInput),button('Anzahl übernehmen',applyCustom));
      this.loadingInfo=element('p',{class:'ml-muted','aria-live':'polite'});
      this.pauseButton=button('Vorladen pausieren',()=>{this.paused=!this.paused;this.loadRevision=(this.loadRevision||0)+1;this.prefetchKey=null;this.update();});
      this.chips=element('div',{class:'ml-chips','aria-label':'Medientypen'});this.controls.append(this.chips);
      this.controls.append(element('div',{class:'ml-view-line'},select('Ansicht',p.view,[['grid','Kacheln'],['masonry','Fotowand'],['list','Liste']],value => this.change('view',value)),select('Bildausschnitt',p.fit,[['contain','Ganzes Bild'],['cover','Kachel ausfüllen']],value => this.change('fit',value)),select('Kachelgröße',p.size,[[160,'Klein'],[220,'Mittel'],[300,'Groß']],value => this.change('size',Number(value))),this.preloadControl,this.customControl,this.pauseButton,select('Pro Seite',p.per,[12,24,36,48,60,96,120].map(n => [n,String(n)]),value => this.change('per',Number(value))),button('Filter zurücksetzen',() => {this.prefs={...DEFAULT,view:p.view,fit:p.fit,size:p.size,per:p.per,prefetch:p.prefetch};this.save();this.build();this.update();})));
      this.controls.append(this.loadingInfo);
      const advanced=element('details',{class:'ml-details'},element('summary',{text:'Feinfilter & gespeicherte Ansichten'}));
      this.format=select('Dateiformat',p.format,[['','Alle Formate']],value => this.change('format',value));
      this.uploader=select('Uploader',p.uploader,[['','Alle Uploader']],value => this.change('uploader',value));
      advanced.append(element('div',{class:'ml-fields'},this.format,this.uploader,select('Bildformat',p.orientation,[['','Alle / unbekannt'],['portrait','Hochformat'],['landscape','Querformat'],['square','Quadratisch'],['unknown','Noch keine Größenangabe']],value => this.change('orientation',value)),field('Dauer ab (Minuten)',p.minDuration,value => this.change('minDuration',value),'number',{min:0,max:10000}),field('Dauer bis (Minuten)',p.maxDuration,value => this.change('maxDuration',value),'number',{min:0,max:10000}),field('Bewertung mindestens',p.minRating,value => this.change('minRating',value),'number',{min:0,max:100}),check('Nur gemerkte Medien',p.saved,value => this.change('saved',value)),check('Auch Beschreibungen durchsuchen',p.descriptions,value => this.change('descriptions',value))));
      const profileName=element('input',{placeholder:'Name dieser Filteransicht',maxLength:60,'aria-label':'Name dieser Filteransicht'});
      this.profiles=element('div',{class:'ml-profile-list'});
      advanced.append(element('p',{class:'ml-muted',text:'Dauer und Bewertung filtern nur Einträge mit veröffentlichten Angaben. Unbekannte Werte werden nicht erfunden.'}),element('div',{class:'ml-search-line'},profileName,button('Ansicht speichern',() => {const name=profileName.value.trim();if(!name){profileName.focus();return;}const data=read();data.profiles=(data.profiles || []).filter(x => x.name!==name);data.profiles.push({name,prefs:{...this.prefs,page:1}});data.profiles=data.profiles.slice(-20);persist();profileName.value='';this.paintProfiles();})),this.profiles);
      this.controls.append(advanced,this.note,element('div',{class:'ml-result-line'},this.count));
      document.getElementById('grid').before(this.controls);
      this.pager=element('div',{class:'ml-pagination'});this.bottom=element('div',{class:'ml-pagination'});
      this.controls.append(this.pager);document.getElementById('grid').after(this.bottom);
      // Existing provider sorting remains wired to its original controls.
      const row=document.getElementById('site-sort')?.closest('.row');
      if(row && !row.closest('.ml-source-options')) {
        const details=element('details',{class:'ml-details ml-source-options'},element('summary',{text:'Beim Anbieter sortieren & laden'}));row.before(details);details.append(row);
        const local=document.getElementById('local-sort');if(local)local.parentElement.hidden=true;
        const filter=document.getElementById('clip-filter');if(filter)filter.hidden=true;
        const per=document.getElementById('per-page');if(per)per.parentElement.firstChild.textContent='Einträge pro Anbieter-Seite ';
      }
      this.paintProfiles();
    }
    paintProfiles() {
      this.profiles.replaceChildren(...(read().profiles || []).map(profile => element('span',{class:'ml-profile'},button(profile.name,() => {this.prefs={...preferences(profile.prefs),page:1};this.save();this.build();this.update();}),button('×',() => {read().profiles=read().profiles.filter(x => x!==profile);persist();this.paintProfiles();},{'aria-label':profile.name+' löschen'}))));
    }
    sourceItems() { const seen=new Set();return this.ctx.items().filter(item => {if(['next','search','categories','stars','channels','collections'].includes(item.role) || isLive(item) || seen.has(item.url))return false;seen.add(item.url);return true;}); }
    filtered() { return filterItems(this.sourceItems(),this.prefs,this.ctx.isSaved); }
    paintProviderSorts() {
      if(!this.providerSort)return;
      const data=this.ctx.providerSorting?.(),input=this.providerSort.querySelector('select');
      this.providerSort.hidden=!data?.options?.length;
      if(!data?.options?.length || document.activeElement===input)return;
      input.replaceChildren(...data.options.map(([value,label])=>element('option',{value,text:sortLabel(label)})));
      input.value=data.value;input.disabled=false;
    }
    update() {
      this.paintProviderSorts();
      if(this.preloadControl) {
        const custom=this.customPrefetch || !PRELOAD_CHOICES.includes(this.prefs.prefetch);
        this.preloadControl.querySelector('select').value=custom?'custom':String(this.prefs.prefetch);
        this.customControl.hidden=!custom;
        if(document.activeElement!==this.customInput)this.customInput.value=this.prefs.prefetch||3;
        this.pauseButton.textContent=this.paused?'Vorladen fortsetzen':'Vorladen pausieren';
        this.pauseButton.disabled=!this.busy && !this.ctx.hasMore();
        this.loadingInfo.textContent=this.paused?'Vorladen pausiert. Bereits geladene Videos bleiben verfügbar.':this.busy?'Videos werden schrittweise nachgeladen …':this.prefs.prefetch===0?'Automatisches Vorladen ist ausgeschaltet.':'Ziel: '+this.prefs.prefetch+' Medienseiten voraus · Abrufe nacheinander · jederzeit pausierbar';
      }
      const source=this.sourceItems(),p=this.prefs,counts=Object.fromEntries(Object.keys(LABELS).map(kind => [kind,source.filter(item => media(item).kind===kind).length]));
      const videos=source.filter(item=>media(item).kind==='video'),unknown=videos.filter(item=>quality(item)==null).length;
      this.qualityNote.textContent=p.minQuality?`Nur Videos ab ${p.minQuality}p laut Anbieterangabe · ${unknown} geladene Videos ohne genaue Auflösung ausgeblendet. Weitere Seiten werden mit demselben Filter geprüft.`:`${videos.length-unknown} von ${videos.length} geladenen Videos mit genauer Auflösung. Ein allgemeines „HD“ bestätigt keine bestimmte Qualitätsstufe.`;
      const choices=[['all','Alle',source.length],...['image','animation','video','gallery','audio','document','file'].map(kind => [kind,LABELS[kind],kind==='gallery'?counts.gallery+counts.folder:counts[kind]])].filter(([id,,n]) => id==='all' || n || p.kind===id);
      this.chips.replaceChildren(...choices.map(([id,label,n]) => button((ICONS[id] || '')+' '+label+' · '+n,() => this.change('kind',id),{class:p.kind===id?'is-active':'','aria-pressed':String(p.kind===id)})));
      const fill=(label,values,value) => {const input=label.querySelector('select');if(document.activeElement===input)return;input.replaceChildren(element('option',{value:'',text:'Alle'}),...values.map(v => element('option',{value:v,text:v.toUpperCase && label===this.format?v.toUpperCase():v})));input.value=value;};
      fill(this.format,[...new Set(source.map(item => media(item).extension).filter(Boolean))].sort(),p.format);
      fill(this.uploader,[...new Set(source.map(item => item.uploader).filter(Boolean))].sort(COLLATOR.compare),p.uploader);
      this.rows=groupMixed(this.filtered(),p);const total=this.rows.length,pages=Math.max(1,Math.ceil(total/p.per));p.page=Math.max(1,Math.min(pages,p.page));
      const showGroups=p.kind==='all' && (p.sort==='source' || p.sort==='kind') && new Set(this.rows.map(item => media(item).kind)).size>1;
      this.count.title='Sortierungen nach Aufrufen, Bewertung und Auflösung verwenden veröffentlichte Angaben. Einträge ohne diese Angaben stehen hinten. Für die gesamte Quelle die Anbieter-Sortierung verwenden.';
      this.count.textContent=`${total} passende von ${source.length} geladenen Einträgen`+(this.ctx.hasMore()?' · weitere beim Anbieter verfügbar':'');
      this.controls.querySelector('.ml-gallery-open').disabled=!this.rows.some(item => ['image','animation'].includes(media(item).kind));
      for (const id of ['pager','pager-bottom']) {const old=document.getElementById(id);if(old)old.hidden=true;}
      this.paintPager(this.pager,pages,total);this.paintPager(this.bottom,pages,total);
      this.paintGrid(showGroups,source.length);
      this.prefetch();
    }
    paintGrid(showGroups,sourceCount) {
      const p=this.prefs,visible=this.rows.slice((p.page-1)*p.per,p.page*p.per),grid=document.getElementById('grid');
      const signature=JSON.stringify([this.scope,p.view,p.fit,p.size,showGroups,sourceCount>0,visible.map(item=>[item.url,item.title,item.thumb,item.plot,item.uploader,item.duration,item.media,item.quality,item.facts?.quality,item.clip,item.preview,this.ctx.isSaved(item.url)])]);
      if(this.gridSignature===signature&&this.paintedGrid===grid&&this.gridFirst===grid.firstChild)return;
      this.gridSignature=signature;this.paintedGrid=grid;
      for(const cover of grid.querySelectorAll('.ml-media-cover')) {const img=cover.querySelector('img');if(img && (cover.querySelector('.clip') || img._timer || cover._hover))this.ctx.previewStop?.(cover,img,{});}
      grid.className='ml-media-grid ml-'+p.view;grid.style.setProperty('--ml-card-min',p.size+'px');grid.dataset.fit=p.fit;grid.replaceChildren();
      let previous='';
      for(const item of visible){
        const kind=media(item).kind;
        if(showGroups && kind!==previous){previous=kind;grid.append(element('h3',{class:'ml-group-heading',text:(ICONS[kind]||'▤')+' '+(LABELS[kind]||'Medien')}));}
        grid.append(this.card(item));
      }
      if(!visible.length)grid.append(element('div',{class:'ml-empty'},element('strong',{text:sourceCount?'Keine Medien passen zu diesen Filtern':'Hier wurden noch keine Medien geliefert'}),element('p',{text:sourceCount?'Setze die Filter zurück oder lade weitere Anbieter-Seiten.':'Öffne eine Galerie oder einen Kanal. Bei einer blockierten Quelle kannst du erneut laden.'})));
      this.gridFirst=grid.firstChild;
    }
    prefetch() {
      if(this.busy || this.paused || this.prefs.prefetch===0 || !this.ctx.hasMore() || this.ctx.active?.()===false)return;
      const key=this.scope+JSON.stringify(this.prefs),entry=this.ctx.entry;
      if(this.prefetchKey===key)return;
      this.prefetchKey=key;
      if(this.filtered().length>=(this.prefs.page+(this.prefs.prefetch||3))*this.prefs.per)return;
      queueMicrotask(() => {
        if(this.prefetchKey===key && this.ctx.entry===entry && this.ctx.active?.()!==false)
          return this.loadMore(false,this.prefs.page+(this.prefs.prefetch||3),true);
      });
    }
    async goPage(value) {
      const target=Math.max(1,Math.floor(Number(value)||1)),scope=this.scope,entry=this.ctx.entry;
      if(this.busy && this.filtered().length<target*this.prefs.per && this.ctx.hasMore())return;
      if(this.filtered().length<target*this.prefs.per && this.ctx.hasMore())await this.loadMore(false,target);
      if(this.scope!==scope || this.ctx.entry!==entry || this.ctx.active?.()===false)return;
      this.prefs.page=Math.min(target,Math.max(1,Math.ceil(this.filtered().length/this.prefs.per)));
      this.save();this.update();
    }
    paintPager(node,pages,total) {
      const p=this.prefs,hasMore=this.ctx.hasMore();
      const jump=element('input',{type:'number',value:p.page,min:1,max:pages+(hasMore?1:0),'aria-label':'Zur Medienseite',onchange:e => this.change('page',Number(e.target.value)||1)});
      const more=button(this.busy?'Lade Videos …':'Mehr Videos / Medien laden',() => this.loadMore(false,Math.ceil(total/p.per)+(p.prefetch||3)),{disabled:this.busy || !hasMore,class:'ml-load-more'});
      node.replaceChildren(button('‹ Zurück',() => this.change('page',p.page-1),{disabled:p.page<=1}),element('span',{text:`Seite ${p.page} / ${pages}${hasMore?"+":""} · ${total} geladen`}),jump,button('Weiter ›',() => this.change('page',p.page+1),{disabled:(this.busy && (p.page+1)*p.per>total) || (p.page>=pages && !hasMore)}),more);
    }
    async loadMore(advance=false,targetPage=0,quiet=false) {
      if(this.busy || !this.ctx.hasMore())return;
      if(!quiet)this.paused=false;
      const ctx=this.ctx,scope=this.scope,entry=ctx.entry,page=this.prefs.page,revision=this.loadRevision||0;
      const current=()=>this.scope===scope && this.ctx.entry===entry && ctx.active?.()!==false;
      const target=targetPage || (advance?page+1:page),wanted=target*this.prefs.per;
      this.busy=true;this.update();
      try {
        let noMatches=0,lastPaint=Date.now();
        for(let reads=0;reads<2000 && ctx.hasMore() && current() && !this.paused && (this.loadRevision||0)===revision;reads++) {
          const before=this.filtered().length;
          await ctx.more({quiet:true});if(!current())return;
          const total=this.filtered().length;
          noMatches=total<=before?noMatches+1:0;
          if(total>=wanted || (!targetPage && !advance))break;
          if(noMatches>=4){notice(this.note,'Vier Anbieter-Seiten ohne zusätzliche passende Einträge. Ändere die Filter oder lade bei Bedarf weiter.');break;}
          if(Date.now()-lastPaint>600){this.update();lastPaint=Date.now();}
          await new Promise(resolve=>setTimeout(resolve,100));
        }
        if(current()) {
          if(advance && this.filtered().length>page*this.prefs.per)this.prefs.page=page+1;
          if(!quiet && !this.paused)notice(this.note,'Weitere Anbieter-Seiten geladen.');
          this.update();
        }
      }
      catch(error){if(current())notice(this.note,error.message,true);}
      finally{this.busy=false;if(current() || (this.controls?.isConnected && this.ctx.active?.()!==false))this.update();}
    }
    openGallery() { const index=this.rows.findIndex(item => ['image','animation'].includes(media(item).kind));if(index>=0)this.open(this.rows[index],true); }
    open(item,photoOnly=false) {
      if(item.folder) {this.ctx.openFolder(item);return;}
      if(media(item).kind==='video') {this.ctx.playVideo(item);return;}
      const base=this.ctx,prefs={...this.prefs};
      const viewerItems=() => filterItems(base.items().filter(row => !['next','search','categories','stars','channels','collections'].includes(row.role)),prefs,base.isSaved).filter(row => !row.folder && (!photoOnly || ['image','animation'].includes(media(row).kind)));
      open(item,{...base,viewerItems},viewerItems());
    }
    card(item) {
      const ctx=this.ctx,m=media(item),kind=m.kind;
      const card=element('article',{class:'ml-media-card','data-media-kind':kind});
      const cover=button('',() => this.open(item),{class:'ml-media-cover','aria-label':item.title+' öffnen'});
      const imageURL=item.offline?null:safeURL(ctx.image(item));
      if(imageURL)cover.append(element('img',{src:imageURL,alt:'',loading:'lazy',decoding:'async',onerror:e => {e.target.hidden=true;cover.classList.add('ml-missing-image');}}));
      cover.append(element('span',{class:'ml-type-badge',text:(ICONS[kind] || '▤')+' '+(LABELS[kind] || 'Medium')}));
      if(item.offline&&!item.folder)ctx.offlinePreview?.(cover,item,ctx);
      if(kind==='video'&&!item.offline) {
        cover.addEventListener('mouseenter',() => ctx.previewStart?.(cover,cover.querySelector('img'),item));
        cover.addEventListener('mouseleave',() => ctx.previewStop?.(cover,cover.querySelector('img'),item));
        card.addEventListener('contextmenu',e => {e.preventDefault();ctx.menu?.(e,item);});
      }
      const body=element('div',{class:'ml-card-body'},button(item.title || 'Medium',() => this.open(item),{class:'ml-card-title'}));
      const meta=[item.uploader,item.duration,m.width&&m.height?m.width+' × '+m.height:'',kind==='video'?(quality(item)?quality(item)+'p':(m.quality||item.quality||'Auflösung unbekannt')):'',m.extension?.toUpperCase()].filter(Boolean);
      if(meta.length)body.append(element('div',{class:'ml-card-detail',text:meta.join(' · ')}));
      if(item.offline&&Number.isFinite(item.sizeBytes))body.append(element('div',{class:'ov-file-size',text:new Intl.NumberFormat('de-DE',{maximumFractionDigits:1}).format(item.sizeBytes/1048576)+' MB'}));
      if(item.plot)body.append(element('p',{class:'ml-card-description',text:item.plot}));
      const actions=element('div',{class:'ml-card-actions'});
      if(!item.folder) {
        const save=button(ctx.isSaved(item.url)?'★ Gemerkt':'☆ Merken',async () => {try{await ctx.save(item);this.update();}catch(error){notice(this.note,error.message,true);}}, {'aria-pressed':String(ctx.isSaved(item.url))});actions.append(save);
        actions.append(button('In Gruppe',() => ctx.group(item)));
        if(kind==='video'&&!item.offline) {actions.append(button('Multitube',() => ctx.multi(item)));const d=ctx.download?.(item);if(d)actions.append(d);}
      } else actions.append(button('Öffnen ›',() => this.open(item)));
      if(item.offline)actions.append(button('Ordner im Explorer',async()=>{try{await ctx.openOfflineFolder(item);}catch(error){notice(this.note,error.message,true);}}));
      card.append(cover,body,actions);return card;
    }
  }

  class Viewer {
    constructor(item,ctx,rows) {
      this.ctx=ctx;this.rows=rows.length?rows:[item];this.index=Math.max(0,this.rows.findIndex(row => row.url===item.url));this.epoch=0;this.zoom=1;this.rotate=0;this.flip=false;this.offset={x:0,y:0};this.opening=document.activeElement;this.prefs=read().viewer;
      this.dialog=element('dialog',{class:'ml-viewer','aria-label':'Medienbetrachter'});
      this.name=element('strong',{class:'ml-viewer-title'});this.counter=element('span',{class:'ml-muted'});
      this.stage=element('div',{class:'ml-viewer-stage',tabIndex:0,'aria-label':'Medienansicht'});
      this.info=element('span',{class:'ml-viewer-info','aria-live':'polite'});
      this.caption=element('p',{class:'ml-viewer-credit'});
      this.download=element('a',{class:'ml-button',text:'↓ Herunterladen',download:''});
      this.original=element('a',{class:'ml-button',text:'Original öffnen',target:'_blank',rel:'noopener noreferrer'});
      this.quality=element('select',{'aria-label':'Videoqualität',hidden:true});
      this.slideButton=button('▷ Diashow',() => this.slideshow());
      this.strip=element('div',{class:'ml-filmstrip','aria-label':'Medienvorschau'});
      this.dialog.append(element('div',{class:'ml-viewer-header'},element('div',{},this.name,this.counter),button('✕ Schließen',() => this.close(),{'aria-label':'Medienbetrachter schließen'})),element('div',{class:'ml-viewer-toolbar'},button('‹',() => this.move(-1),{'aria-label':'Vorheriges Medium'}),button('›',() => this.move(1),{'aria-label':'Nächstes Medium'}),button('−',() => this.setZoom(this.zoom/1.25),{'aria-label':'Verkleinern'}),button('+',() => this.setZoom(this.zoom*1.25),{'aria-label':'Vergrößern'}),button('Einpassen',() => this.fit()),button('1:1',() => this.actual()),button('↻ Drehen',() => {this.rotate=(this.rotate+90)%360;this.transform();}),button('↔ Spiegeln',() => {this.flip=!this.flip;this.transform();}),button('⛶ Vollbild',() => this.fullscreen()),this.slideButton,select('Bildwechsel',this.prefs.seconds || 5,[[3,'3 Sek.'],[5,'5 Sek.'],[10,'10 Sek.'],[20,'20 Sek.']],value => {this.prefs.seconds=Number(value);persist();if(this.slideTimer){this.stopSlides();this.slideshow();}}),button('Vorschauleiste',() => {this.prefs.filmstrip=!this.prefs.filmstrip;persist();this.paintStrip();}),select('Hintergrund',this.prefs.background || 'dark',[['dark','Dunkel'],['light','Hell'],['checker','Schachbrett']],value => {this.prefs.background=value;persist();this.dialog.dataset.background=value;}),this.quality),this.stage,this.strip,this.caption,element('div',{class:'ml-viewer-footer'},this.info,this.download,this.original));
      this.dialog.dataset.background=this.prefs.background || 'dark';
      this.key=e => this.onKey(e);this.hidden=() => {if(document.hidden)this.stopSlides();};
      this.dialog.addEventListener('cancel',e => {e.preventDefault();this.close();});
      this.dialog.addEventListener('click',e => {if(e.target===this.dialog)this.close();});
      this.dialog.addEventListener('close',() => this.cleanup());
      this.stage.addEventListener('wheel',e => {if(this.image){e.preventDefault();this.setZoom(this.zoom*(e.deltaY<0?1.12:1/1.12));}},{passive:false});
      this.stage.addEventListener('dblclick',() => this.zoom>1?this.fit():this.actual());
      this.stage.addEventListener('pointerdown',e => {if(!this.image || e.button!==0)return;this.drag={x:e.clientX,y:e.clientY,offset:{...this.offset}};this.stage.setPointerCapture(e.pointerId);});
      this.stage.addEventListener('pointermove',e => {if(!this.drag)return;this.offset={x:this.drag.offset.x+e.clientX-this.drag.x,y:this.drag.offset.y+e.clientY-this.drag.y};this.transform();});
      const end=() => {this.drag=null;};this.stage.addEventListener('pointerup',end);this.stage.addEventListener('pointercancel',end);
      document.body.append(this.dialog);this.dialog.showModal();document.addEventListener('keydown',this.key,true);document.addEventListener('visibilitychange',this.hidden);this.load();
    }
    async load() {
      const epoch=++this.epoch;this.abort?.abort();this.abort=new AbortController();this.release();this.fit();this.rotate=0;this.flip=false;
      const item=this.rows[this.index];this.caption.textContent=this.ctx.caption?.(item)||'';this.caption.hidden=!this.caption.textContent;(globalThis.AppI18n?.protect(this.name), this.name.textContent=item.title || 'Medium');this.counter.textContent=`${this.index+1} / ${this.rows.length}`;this.info.textContent='Originaldatei wird geladen …';this.download.removeAttribute('href');this.original.removeAttribute('href');this.quality.hidden=true;
      this.stage.replaceChildren(element('p',{class:'ml-viewer-message',text:'Medium wird geladen …'}));this.paintStrip();
      try {
        const response=await fetch('/api/media/resolve?'+new URLSearchParams({query:queryOf(item)}),{signal:AbortSignal.any([this.abort.signal,AbortSignal.timeout(40000)]),cache:'no-store'});
        if(!response.ok)throw Error('Die Medienabfrage ist fehlgeschlagen.');const data=await response.json();
        if(epoch!==this.epoch || !this.dialog.open)return;if(!data.ok)throw Error(data.error || 'Die Quelle lieferte keine Mediendatei.');
        const kind=data.media.kind,src=data.src;this.download.href=data.download;const raw=safeURL(target(item.url));if(raw)this.original.href=raw;
        this.info.textContent=[LABELS[kind],data.media.extension?.toUpperCase(),item.uploader].filter(Boolean).join(' · ');
        this.stage.replaceChildren();
        if(kind==='image' || kind==='animation') {
          this.image=element('img',{src,alt:item.title || 'Bild',draggable:false,onload:() => {if(epoch!==this.epoch)return;this.info.textContent=`${LABELS[kind]} · ${this.image.naturalWidth} × ${this.image.naturalHeight} Pixel · ${data.media.extension?.toUpperCase() || 'Original'} · Mausrad zoomt, Ziehen verschiebt`;this.transform();},onerror:() => {if(epoch===this.epoch)this.fail('Das Originalbild konnte nicht geladen werden. Erneut versuchen oder das Original öffnen.');}});
          this.stage.append(this.image);
        } else if(kind==='video' || kind==='audio') {
          this.stopSlides();this.video=element(kind,{controls:true,playsInline:true,preload:'metadata'});this.stage.append(this.video);
          if(kind==='video' && data.resolved && this.ctx.attach) {this.handle=this.ctx.attach(this.video,this.quality,data.resolved,false);this.quality.hidden=false;this.quality.onchange=() => this.ctx.quality?.(this.handle,this.quality.value);}
          else this.video.src=src;
          this.video.addEventListener('error',() => {if(epoch===this.epoch)this.fail('Dieses Medienformat kann der Browser nicht wiedergeben. Die Originaldatei kannst du herunterladen.');},{once:true});
        } else if(kind==='document' && data.media.mime==='application/pdf') {
          this.stopSlides();this.stage.append(element('iframe',{src,title:item.title || 'PDF-Dokument',sandbox:'allow-scripts',class:'ml-document'}));
        } else if(kind==='document') {
          this.stopSlides();const r=await fetch(src,{signal:this.abort.signal});if(!r.ok)throw Error('Das Dokument konnte nicht gelesen werden.');
          const reader=r.body.getReader(),decoder=new TextDecoder();let text='',bytes=0,truncated=false;
          try {while(true){const part=await reader.read();if(part.done)break;bytes+=part.value.length;if(bytes>1_000_000){truncated=true;await reader.cancel();break;}text+=decoder.decode(part.value,{stream:true});}text+=decoder.decode();}finally{reader.releaseLock();}
          if(epoch===this.epoch)this.stage.append(element('pre',{class:'ml-text-document',text:text+(truncated?'\n\n… Vorschau auf 1 MB begrenzt. Vollständige Datei über Herunterladen.':'')}));
        } else {
          this.stopSlides();this.stage.append(element('div',{class:'ml-file-panel'},element('span',{class:'ml-file-icon',text:'↓'}),element('h3',{text:'Originaldatei'}),element('p',{text:'Für diesen Dateityp gibt es keine direkte Browseransicht. Du kannst ihn unverändert herunterladen und mit einem passenden Programm öffnen.'}),element('a',{href:data.download,class:'ml-button',text:'Datei herunterladen',download:''})));
        }
      } catch(error) {if(epoch===this.epoch && !this.abort.signal.aborted)this.fail(error.name==='TimeoutError'?'Die Quelle hat nicht rechtzeitig geantwortet.':error.message);}
    }
    fail(message) {this.stopSlides();this.stage.replaceChildren(element('div',{class:'ml-file-panel'},element('p',{text:message}),button('Erneut versuchen',() => this.load()),button('Nächstes Medium',() => this.move(1))));this.info.textContent='Quelle derzeit nicht verfügbar';}
    release() {this.image=null;if(this.handle?.dispose)this.handle.dispose();else this.handle?.hls?.destroy();this.handle=null;if(this.video){this.video.pause();this.video.removeAttribute('src');this.video.load();this.video=null;}}
    fit() {this.zoom=1;this.offset={x:0,y:0};this.transform();}
    actual() {if(!this.image)return;const scale=Math.min(this.stage.clientWidth/this.image.naturalWidth,this.stage.clientHeight/this.image.naturalHeight,1);this.setZoom(1/(scale || 1));}
    setZoom(value) {this.zoom=Math.max(.25,Math.min(16,value));if(this.zoom<=1)this.offset={x:0,y:0};this.transform();}
    transform() {if(this.image)this.image.style.transform=`translate(${this.offset.x}px,${this.offset.y}px) rotate(${this.rotate}deg) scale(${this.zoom*(this.flip?-1:1)},${this.zoom})`;}
    async move(delta) {
      let next=this.index+delta;
      if(next>=this.rows.length && this.ctx.hasMore?.()) {
        this.info.textContent='Weitere Galerie-Seite wird geladen …';const scope=this.ctx.scope;
        try {await this.ctx.more();if(!this.dialog.open || this.ctx.scope!==scope)return;const current=this.rows[this.index].url;this.rows=this.ctx.viewerItems?this.ctx.viewerItems():this.ctx.items().filter(row => !row.folder);this.index=Math.max(0,this.rows.findIndex(row => row.url===current));next=this.index+delta;}
        catch(error){this.info.textContent=error.message;this.stopSlides();return;}
      }
      if(next<0 || next>=this.rows.length){this.stopSlides();return;}this.index=next;this.load();
    }
    paintStrip() {
      this.strip.hidden=this.prefs.filmstrip===false;this.strip.replaceChildren();if(this.strip.hidden)return;
      const start=Math.max(0,this.index-12);
      for(let index=start;index<Math.min(this.rows.length,start+25);index++) {
        const item=this.rows[index],src=safeURL(this.ctx.image(item));const b=button('',() => {this.index=index;this.load();},{'aria-label':item.title || `Medium ${index+1}`,'aria-current':index===this.index?'true':'false',class:index===this.index?'is-active':''});
        if(src)b.append(element('img',{src,alt:'',loading:'lazy'}));else b.textContent=ICONS[media(item).kind] || '▤';this.strip.append(b);
      }
    }
    slideshow() {if(this.slideTimer){this.stopSlides();return;}if(!this.rows.some(item => ['image','animation'].includes(media(item).kind)))return;this.slideButton.textContent='Ⅱ Diashow';this.slideTimer=setInterval(() => {if(this.image?.complete)this.move(1);},(this.prefs.seconds || 5)*1000);}
    stopSlides() {clearInterval(this.slideTimer);this.slideTimer=null;this.slideButton.textContent='▷ Diashow';}
    async fullscreen() {try{if(document.fullscreenElement)await document.exitFullscreen();else await this.dialog.requestFullscreen();}catch(_){this.info.textContent='Vollbild ist in diesem Browserfenster nicht verfügbar.';}}
    onKey(e) {
      if(!this.dialog.open || e.altKey || e.ctrlKey || e.metaKey)return;
      if(['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName))return;
      const actions={ArrowLeft:() => this.move(-1),ArrowRight:() => this.move(1),Home:() => {this.index=0;this.load();},End:() => {this.index=this.rows.length-1;this.load();},'+':() => this.setZoom(this.zoom*1.25),'=':() => this.setZoom(this.zoom*1.25),'-':() => this.setZoom(this.zoom/1.25),'0':() => this.fit(),f:() => this.fullscreen(),' ':() => {if(this.video){this.video.paused?this.video.play().catch(()=>{}):this.video.pause();}else this.slideshow();}};
      if(actions[e.key]){e.preventDefault();e.stopImmediatePropagation();actions[e.key]();}
    }
    close() {this.dialog.close();this.cleanup();}
    cleanup() {if(this.cleaned)return;this.cleaned=true;this.epoch++;this.abort?.abort();this.stopSlides();this.release();document.removeEventListener('keydown',this.key,true);document.removeEventListener('visibilitychange',this.hidden);if(document.fullscreenElement===this.dialog)document.exitFullscreen().catch(()=>{});this.dialog.remove();if(this.opening?.isConnected)this.opening.focus();if(viewer===this)viewer=null;}
  }
  function open(item,ctx,rows=[]) {viewer?.close();viewer=new Viewer(item,ctx,rows);return true;}
  function suspend() {
    library?.controls?.remove();library?.bottom?.remove();
    const source=document.querySelector('.ml-source-options'),row=source?.querySelector('.row');
    if(row)source.before(row);source?.remove();
    const local=document.getElementById('local-sort');if(local)local.parentElement.hidden=false;
    const filter=document.getElementById('clip-filter');if(filter)filter.hidden=false;
    for(const id of ['pager','pager-bottom','status']){const node=document.getElementById(id);if(node)node.hidden=false;}
  }
  function render(ctx) {if(ctx.tube){suspend();return false;}library ||= new Library(ctx);return library.render(ctx);}
  function leave() {viewer?.close();closeSitePreview();}
  return {LABELS,LIVE,media,isLive,target,duration,stamp,filterItems,groupMixed,compareKnown,preferences,renderSites,render,suspend,open,leave,SitePreview,previewItems,closeSitePreview,viewCount,quality,sortLabel,refreshProviderSorts:()=>library?.paintProviderSorts()};
});
