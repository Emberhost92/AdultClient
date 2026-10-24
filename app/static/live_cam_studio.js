/* MultiCam workspace for the existing Live section. The application supplies
 * its four provider adapters; no tube UI, account cookies or extension APIs.
 */
(function(root){
  'use strict';
  const D=root.LiveCamDomain;
  const text=value=>String(value==null?'':value);
  const statusNames={online:'Live',offline:'Offline',private:'Privat',away:'Abwesend',denied:'Zugriff verweigert',unknown:'Unbekannt',loading:'Verbindet',buffering:'Puffert',playing:'Wiedergabe',paused:'Pausiert',failed:'Medienfehler',queued:'Wartet',blocked:'Wiedergabe bitte anklicken'};
  const sortChoices=[['manual','Manuell'],['name','Name A–Z'],['name-desc','Name Z–A'],['status','Live zuerst'],['viewers','Zuschauer absteigend'],['viewers-low','Zuschauer aufsteigend'],['age','Alter aufsteigend'],['age-desc','Alter absteigend'],['country','Land'],['rating','Bewertung'],['priority','Priorität'],['watch','Sehzeit'],['sessions','Sitzungen'],['last','Letzter Besuch'],['first','Erster Besuch'],['added','Hinzugefügt'],['followers','Follower'],['uptime','Onlinedauer'],['lastOnline','Zuletzt online']];
  const statusChoices=[['all','Alle Zustände'],['online','🟢 Nur live'],['offline','🔴 Nur offline'],['private','🟠 Nur privat'],['unknown','? Nur unbekannt'],['hide-offline','Offline ausblenden'],['hide-private','Privat ausblenden'],['hide-both','Offline und privat ausblenden']];
  function el(tag,attrs={},...children){
    const node=document.createElement(tag);
    for(const [name,value] of Object.entries(attrs)){
      if(name==='class')node.className=value;
      else if(name==='text')node.textContent=text(value);
      else if(name.startsWith('on'))node.addEventListener(name.slice(2),value);
      else if(value!=null){if(name in node&&name!=='style')node[name]=value;else node.setAttribute(name,text(value));}
    }
    for(const child of children.flat())if(child!=null)node.append(typeof child==='string'?document.createTextNode(child):child);
    return node;
  }
  const button=(label,action,attrs={})=>el('button',{type:'button',text:label,onclick:action,...attrs});
  function select(label,value,choices,change){
    const input=el('select',{'aria-label':label,onchange:event=>{if(/status/i.test(label))event.target.dataset.state=event.target.value;change(event.target.value);}});
    if(/status/i.test(label)){input.classList.add('lc-state-select');input.dataset.state=value;}
    for(const choice of choices){const [id,name]=Array.isArray(choice)?choice:[choice,choice];input.append(el('option',{value:id,text:name}));}
    input.value=text(value);return el('label',{class:'lc-field'},el('span',{text:label}),input);
  }
  function input(label,value,change,type='text',attrs={}){
    const node=el('input',{type,value:text(value),'aria-label':label,...attrs});let timer,last=text(value);
    const apply=()=>{if(last===node.value)return;last=node.value;change(type==='number'?(node.value===''?'':Number(node.value)):node.value);};
    node.addEventListener('change',apply);
    if(type==='search')node.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(apply,140);});
    return el('label',{class:'lc-field'},el('span',{text:label}),node);
  }
  const check=(label,value,change)=>el('label',{class:'lc-check'},el('input',{type:'checkbox',checked:!!value,onchange:event=>change(event.target.checked)}),' '+label);
  function slider(label,value,min,max,step,change){
    const out=el('output',{text:value});
    return el('label',{class:'lc-field'},el('span',{},label+' ',out),el('input',{type:'range',min,max,step,value,'aria-label':label,oninput:event=>{(globalThis.AppI18n?.protect(out), out.textContent=event.target.value);change(Number(event.target.value));}}));
  }
  function download(blob,name){const url=URL.createObjectURL(blob),a=el('a',{href:url,download:name});document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);}
  const filename=value=>text(value).replace(/[^A-Za-z0-9_.-]/g,'_').slice(0,90);
  const duration=ms=>{const seconds=Math.max(0,Math.floor(ms/1000));return Math.floor(seconds/3600)+':'+String(Math.floor(seconds/60)%60).padStart(2,'0')+':'+String(seconds%60).padStart(2,'0');};
  const bytes=value=>value>=1e9?(value/1e9).toFixed(2)+' GB':value>=1e6?(value/1e6).toFixed(1)+' MB':Math.round(value/1000)+' kB';

  class Studio {
    constructor(){
      this.ctx=null;this.store=null;this.data=null;this.panel=null;this.root=null;this.active=false;this.workspaceId=null;
      this.players=new Map();this.catalog=new Map();this.saved=new Map();this.liveChecks=new Map();this.groups=[];this.accounts={};this.followed=new Set();this.favorites=new Set();
      this.dialogs=new Set();this.drafts=new Map();this.draftTimers=new Map();this.history=[];this.undo=[];this.rotation=null;this.temporary=[];this.epoch=0;this.loading=null;this.fetchAbort=null;this.statusAt=0;this.sidebarSignature='';this.layoutFrame=0;this.metricsAt=0;this.modelRevision=0;this.mediaURLs=[];this.capture=new CaptureCenter(this);this.onCaptureSaved=entry=>this.capture.sharedGallery().captureSaved(entry);this.onCaptureRescue=(entry,blob)=>this.capture.sharedGallery().captureRescue(entry,blob);
      this.resize=()=>this.scheduleLayout();
      this.keyHandler=event=>this.onKey(event);
      this.visibility=()=>this.visibilityChanged();
      this.beforeUnload=event=>{if(this.capture.jobs.size&&this.data?.capture.warn){event.preventDefault();event.returnValue='';}};
      root.addEventListener('beforeunload',this.beforeUnload);
      root.addEventListener('pagehide',()=>{this.stopRotation();this.capture.sourceLostAll();});
    }
    async enter(panel,ctx){
      const generation=this.enterGeneration=(this.enterGeneration||0)+1;
      this.ctx=ctx;this.panel=panel;this.active=true;document.body.classList.add('lc-multicam-open');
      if(!this.loading)this.loading=this.initialize().catch(error=>{this.error(error);this.loading=null;throw error;});
      try{await this.loading;await this.adoptLegacy();}catch{return;}
      if(!this.active||generation!==this.enterGeneration)return;
      if(!this.root||!this.root.isConnected)this.build();
      const requested=new URLSearchParams(location.search).get('workspace');
      if(!this.requestedApplied&&requested&&this.data.workspaces.some(w=>w.id===requested&&!w.archived))this.workspaceId=requested;
      this.requestedApplied=true;
      if(!this.workspaceId||!this.data.workspaces.some(w=>w.id===this.workspaceId&&!w.archived))this.workspaceId=this.data.active;
      document.addEventListener('keydown',this.keyHandler,true);document.addEventListener('visibilitychange',this.visibility);root.addEventListener('resize',this.resize);root.addEventListener('scroll',this.resize,{passive:true});
      clearInterval(this.timer);this.timer=setInterval(()=>this.tick(),1000);
      this.render();this.refreshData(false);
    }
    async initialize(){
      this.store=new root.LiveCamStore();this.store.notifyError=error=>this.error(error);
      const state=await this.store.open(D.initial(this.ctx.legacy()));this.data=state;
      this.store.subscribe(value=>{this.data=value;if(!value.workspaces.some(w=>w.id===this.workspaceId&&!w.archived))this.workspaceId='default';if(this.rotation&&this.rotation.context!==this.contextKey())this.stopRotation();if(this.replacement&&this.replacement.context!==this.contextKey())this.replacement=null;if(this.active){this.ctx.legacyWrite?.(value.workspaces.find(w=>w.id==='default').slots,value.workspaces.find(w=>w.id==='default').settings);this.render();}});
      this.workspaceId=this.data.active;
      const cached=await this.store.get('cache','catalog');
      if(cached){this.absorb(cached.items||[],true);this.groups=cached.groups||[];this.accounts=cached.accounts||{};this.favorites=new Set(cached.favs||[]);this.followed=new Set(cached.followed||[]);this.followingMeta=cached.followingMeta||{};this.savedAt=cached.at;}
      const history=await this.store.get('cache','status-history');if(Array.isArray(history))this.history=history.filter(item=>D.room(item.identity)).slice(0,2000);
      await this.adoptLegacy();
    }
    async adoptLegacy(){
      const old=this.ctx.legacy();if(!old.rooms?.length)return;
      // Existing card actions keep working. Do not overwrite another workspace
      // or an edited placement merely because an old tab sends a sync message.
      const before=this.data.workspaces.find(w=>w.id==='default');
      const additions=old.rooms.filter(r=>D.key(r)&&!before.slots.includes(D.key(r)));
      if(!additions.length)return;
      await this.change(data=>{const w=data.workspaces.find(w=>w.id==='default');for(const r of additions){if(w.slots.includes(D.key(r)))continue;const slot=w.slots.indexOf(null);if(slot<0)break;w.slots[slot]=D.key(r);}});
    }
    leave(){
      this.enterGeneration=(this.enterGeneration||0)+1;
      this.cancelModelDrag?.();
      if(this.data&&this.players.size)this.saveUsage();
      this.active=false;this.epoch++;clearInterval(this.timer);this.fetchAbort?.abort();this.fetchAbort=null;this.stopRotation();
      document.body.classList.remove('lc-multicam-open');document.removeEventListener('keydown',this.keyHandler,true);document.removeEventListener('visibilitychange',this.visibility);root.removeEventListener('resize',this.resize);root.removeEventListener('scroll',this.resize);
      this.flushDrafts();this.releasePreview();for(const identity of [...this.players.keys()])this.removePlayer(identity);
      for(const dialog of [...this.dialogs])dialog.close();this.previewClose();
      this.resizeObserver?.disconnect();this.resizeObserver=null;
    }
    workspace(){return this.data.workspaces.find(w=>w.id===this.workspaceId&&!w.archived)||this.data.workspaces.find(w=>w.id==='default');}
    config(){return this.workspace().settings;}
    prefs(identity){return {...D.camera(),...this.data.cameras[identity],...this.drafts.get('camera:'+identity)};}
    async change(action){try{return await this.store.mutate(action);}catch(error){this.error(error);throw error;}}
    workspaceEvent(kind,details={}){const w=this.workspace();const sites=[...new Set([details.from,details.to].filter(Boolean).map(id=>D.room(id)?.site).filter(Boolean))];return root.LiveCamStatisticsRecorder?.workspaceEvent(kind,{workspace:w.id,name:w.name,sites:sites.length?sites:[...this.config().sites],...details})?.catch(error=>{if(root.LiveCamAnalytics)root.LiveCamAnalytics.error=error.message;});}
    async applyScene(scene){const before=JSON.stringify(D.snapshot(this.workspace()));this.stopRotation();await this.change(data=>{const target=data.workspaces.find(x=>x.id===this.workspaceId);target.slots=D.clone(scene.slots);Object.assign(target.settings,D.clone(scene.settings));});if(before!==JSON.stringify(D.snapshot(this.workspace())))await this.workspaceEvent('scene',{detail:scene.name});}
    async applyTemplate(template){const before=JSON.stringify(this.config());await this.change(data=>Object.assign(data.workspaces.find(w=>w.id===this.workspaceId).settings,D.clone(template.settings)));if(before!==JSON.stringify(this.config()))await this.workspaceEvent('template',{detail:template.name});}
    async setting(name,value){return this.change(data=>{const c=data.workspaces.find(w=>w.id===this.workspaceId).settings,apply=()=>{c[name]=value;};if(['source','sites','playbackFilters'].includes(name))this.changeView(c,apply);else apply();if(name==='focus')c.contexts[this.contextKeyFor(c)]={...c.contexts[this.contextKeyFor(c)],focus:value};if(name==='capacity'&&c.layout==='custom'&&c.rows*c.cols!==value)c.layout='grid';if(name==='layout'&&value==='custom')c.capacity=c.rows*c.cols;});}
    cameraSetting(identity,name,value){
      const draft={...this.drafts.get('camera:'+identity),[name]:value};this.drafts.set('camera:'+identity,draft);
      this.applyPlayer(this.players.get(identity));
      clearTimeout(this.draftTimers.get(identity));this.draftTimers.set(identity,setTimeout(()=>this.commitCamera(identity),180));
    }
    async commitCamera(identity){
      const draft=this.drafts.get('camera:'+identity);if(!draft)return;
      this.drafts.delete('camera:'+identity);this.draftTimers.delete(identity);
      try{await this.change(data=>{data.cameras[identity]={...D.camera(),...data.cameras[identity],...draft};});}catch{this.drafts.set('camera:'+identity,draft);}
    }
    flushDrafts(){for(const identity of this.draftTimers.keys()){clearTimeout(this.draftTimers.get(identity));this.commitCamera(identity);}}
    notify(message,error=false){
      if(!this.notice)return;
      this.notice.textContent=text(message);this.notice.classList.toggle('lc-error',error);this.notice.hidden=false;
    }
    error(error){const dialog=[...this.dialogs].at(-1);if(dialog){let note=dialog.querySelector('.lc-dialog-error');if(!note){note=el('p',{class:'lc-error lc-dialog-error',role:'alert'});dialog.querySelector('.lc-dialog-body').prepend(note);}note.textContent=error?.message||error;}if(this.notice)this.notify(error?.message||error,true);else if(this.panel){this.panel.replaceChildren(el('p',{class:'lc-error',text:error?.message||error}),button('Erneut laden',()=>{this.loading=null;this.enter(this.panel,this.ctx);}));}}
    command(action){return async event=>{try{await action(event);}catch(error){this.error(error);}};}
    build(){
      this.panel.replaceChildren();this.root=el('section',{class:'lc-studio','aria-label':'Multicam-Arbeitsbereich'});this.panel.append(this.root);
      this.reveal=button('☰ Bedienung einblenden',()=>this.change(data=>{const c=data.workspaces.find(w=>w.id===this.workspaceId).settings;c.toolbar=true;c.mode='normal';}),{class:'lc-reveal'});
      this.chrome=el('div',{class:'lc-chrome','aria-label':'Multicam-Leisten'});
      this.top=el('div',{class:'lc-top'});this.providers=el('div',{class:'lc-providers'});this.quick=el('div',{class:'lc-quick'});
      this.notice=el('p',{class:'lc-notice',role:'status',hidden:true});
      this.area=el('div',{class:'lc-workarea'});this.sidebar=el('aside',{class:'lc-sidebar','aria-label':'Multicam-Modellliste'});
      this.splitter=el('div',{class:'lc-splitter',role:'separator','aria-label':'Modellleiste verbreitern',tabIndex:0});
      this.canvas=el('div',{class:'lc-canvas',tabIndex:0,'aria-label':'Multicam-Kameras'});this.footer=el('div',{class:'lc-footer'});
      this.area.append(this.sidebar,this.splitter,this.canvas);this.root.append(this.reveal,this.chrome,this.top,this.providers,this.quick,this.notice,this.area,this.footer);
      this.canvas.addEventListener('scroll',()=>this.refreshPauses(),{passive:true});
      this.splitter.addEventListener('pointerdown',event=>{
        const start=event.clientX,width=this.config().sidebarWidth;this.splitter.setPointerCapture(event.pointerId);
        const move=e=>{const value=Math.round(D.clamp(width+e.clientX-start,180,460)/10)*10;this.root.style.setProperty('--lc-sidebar',value+'px');};
        const up=e=>{this.splitter.removeEventListener('pointermove',move);this.splitter.removeEventListener('pointerup',up);this.setting('sidebarWidth',Math.round(D.clamp(width+e.clientX-start,180,460)/10)*10);};
        this.splitter.addEventListener('pointermove',move);this.splitter.addEventListener('pointerup',up,{once:true});
      });
      this.splitter.addEventListener('keydown',event=>{if(['ArrowLeft','ArrowRight'].includes(event.key)){event.preventDefault();this.setting('sidebarWidth',D.clamp(this.config().sidebarWidth+(event.key==='ArrowRight'?10:-10),180,460));}});
    }
    absorb(items,saved=true){for(const item of items){const identity=D.key(item);if(!identity)continue;(saved?this.saved:this.catalog).set(identity,{...(saved?this.saved:this.catalog).get(identity),...item,...(!saved?{_observedAt:Date.now()}:{})});}this.modelRevision++;}
    models(){
      const stamp=[this.data.revision,this.modelRevision,this.workspaceId,this.saved.size,this.catalog.size,this.favorites.size,this.followed.size,this.temporary.length,this.data.urls.length,Math.floor(Date.now()/30000)].join('/');
      if(this.modelStamp===stamp)return this.modelCache;
      const all=new Map(this.saved);
      for(const [identity,item] of this.catalog)all.set(identity,{...all.get(identity),...item,personal:{...all.get(identity)?.personal,...item.personal}});
      for(const identity of this.workspace().slots.filter(Boolean))if(!all.has(identity))all.set(identity,D.room(identity));
      for(const item of [...this.temporary,...this.data.urls])if(D.key(item)&&!all.has(D.key(item)))all.set(D.key(item),item);
      this.modelStamp=stamp;
      return this.modelCache=[...all].map(([identity,item])=>this.decorateModel(identity,item));
    }
    decorateModel(identity,item){
      let model=D.freshModel(item);const check=this.liveChecks.get(identity);
      if(check&&Date.now()-check.at<120000)model={...model,online:check.state==='online'?true:check.state==='offline'?false:null,show:check.state==='online'?'public':check.state==='private'?'private':'unknown',roomState:check.state,staleStatus:false,statusError:check.error};
      if(this.players.get(identity)?.phase==='playing')model={...model,online:true,show:'public',roomState:'public',staleStatus:false};
      return {...model,fav:this.favorites.has(identity),accountFav:this.followed.has(identity),personal:{...item.personal,...this.data.models[identity]}};
    }

    checkedRoom(identity, online, error='') {
      const known=D.stateOf(D.freshModel({...this.saved.get(identity),...this.catalog.get(identity)}));
      const state=online===true?'online':['private','offline','away','denied'].includes(known)?known:'unknown';
      this.liveChecks.set(identity,{online,state,at:Date.now(),error});this.modelRevision++;
      for(const row of this.sidebar?.querySelectorAll('.lc-model-row')||[])if(row.dataset.model===identity){
        row.dataset.state=state;row.title=error;
        const badge=row.querySelector('.lc-state-badge');if(badge){badge.dataset.state=state;badge.textContent=(state==='private'?'◆ ':state==='unknown'?'? ':'● ')+statusNames[state];}
      }
    }
    model(identity){const saved=this.saved.get(identity),current=this.catalog.get(identity);const item=saved||current?{...saved,...current,personal:{...saved?.personal,...current?.personal}}:this.temporary.find(row=>D.key(row)===identity)||this.data.urls.find(row=>D.key(row)===identity)||D.room(identity);return this.decorateModel(identity,item);}

    groupMap(){return Object.fromEntries(this.groups.map(group=>[group.id,group.items||[]]));}
    async refreshData(explicit=false){
      if(this.fetchAbort){if(explicit)this.fetchAbort.abort();else return;}
      const controller=new AbortController(),epoch=this.epoch;this.fetchAbort=controller;
      this.statusAt=Date.now();
      const options={signal:controller.signal};
      try{
        // Current provider observations must not wait for hundreds of local
        // library pages. Refresh the large saved catalog less often.
        const liveRefresh=Promise.allSettled(this.config().sites.map(async site=>{
          try{
            const data=await this.ctx.get('/api/cam-rooms?site='+site+'&gender=all&offset=0',options);
            if(epoch!==this.epoch||!this.active||controller.signal.aborted)return;
            if(!data.ok)throw Error(data.error||'Katalog gerade nicht erreichbar.');
            this.absorb(data.items||[],false);this.renderSidebar();this.reconcile();
          }catch(error){if(explicit&&!controller.signal.aborted)this.notify(D.SITES.find(s=>s[0]===site)[1]+': '+error.message+' Gespeicherter Stand bleibt sichtbar.',true);}
        }));
        if(epoch!==this.epoch||!this.active||controller.signal.aborted)return;
        if(!explicit&&this.libraryReadAt&&Date.now()-this.libraryReadAt<600000){await liveRefresh;this.recordStates();this.render();return;}
        const saved=[];let first=null,snapshot='';
        for(let offset=0;offset<60000;){
          const response=await this.ctx.get('/api/cam-library?part=studio&compact=1&offset='+offset+(snapshot?'&snapshot='+encodeURIComponent(snapshot):''),options);if(!response.ok)throw Error(response.error||'Die gespeicherten Models konnten nicht gelesen werden.');
          if(epoch!==this.epoch||!this.active)return;
          if(!first){first=response;snapshot=response.snapshot||'';this.groups=response.groups||[];this.accounts=response.accounts||{};this.favorites=new Set(response.favs||[]);}
          saved.push(...response.items);this.absorb(response.items);for(const item of response.items)if(item.accountFav)this.followed.add(D.key(item));
          if(offset===0){this.renderSidebar();this.reconcile();}
          if(offset+response.items.length>=response.total||!response.items.length)break;
          offset+=response.items.length;
        }
        this.saved=new Map(saved.map(item=>[D.key(item),item]));this.followed=new Set(saved.filter(item=>item.accountFav).map(D.key));this.followingMeta=first?.following_meta||{};this.modelRevision++;this.savedAt=Date.now();
        this.libraryReadAt=Date.now();
        await this.store.put('cache',{items:saved,groups:this.groups,accounts:this.accounts,favs:[...this.favorites],followed:[...this.followed],followingMeta:this.followingMeta,at:this.savedAt},'catalog');
        if(epoch!==this.epoch||!this.active)return;
        this.statusAt=Date.now();this.recordStates();this.render();
        await liveRefresh;if(explicit)this.notify('Gespeicherte Daten und erreichbare Anbieter aktualisiert.');
      }catch(error){if(!controller.signal.aborted)this.error(error);}
      finally{if(this.fetchAbort===controller)this.fetchAbort=null;}
    }
    async refreshFollowing(){
      for(const site of this.config().sites){try{const data=await this.ctx.post('/api/cam-account',{op:'favs',site});if(!data.ok)throw Error(data.error);this.absorb(data.items||[]);for(const item of data.items||[])this.followed.add(D.key(item));}catch(error){this.notify(D.SITES.find(s=>s[0]===site)[1]+': '+error.message,true);}}
      await this.refreshData(false);
    }
    async sync(){if(!this.data)return;await this.store.refresh();await this.adoptLegacy();if(this.active)this.render();}
    render(){
      if(!this.active||!this.root)return;
      const c=this.config();this.root.dataset.mode=c.mode;this.root.dataset.theme=this.data.theme;this.root.dataset.sidebar=String(c.sidebar);this.root.dataset.toolbar=String(c.toolbar);this.root.style.setProperty('--lc-sidebar',c.sidebarWidth+'px');
      for(const [key,on] of Object.entries(c.panels||D.settings().panels))this.root.dataset['panel'+key[0].toUpperCase()+key.slice(1)]=String(on);
      this.renderChrome();
      if(!this.top.contains(document.activeElement))this.renderTop();else this.syncControlValues(this.top,{'Arbeitsbereich':this.workspaceId,'Plätze':c.capacity,'Ansicht':c.layout});this.renderProviders();if(!this.quick.contains(document.activeElement))this.renderQuick();else this.syncControlValues(this.quick,{'Bestand':c.source,'Gruppe':c.playbackFilters.group,'Wiedergabebestand durchsuchen':c.playbackFilters.q,'Raumstatus':c.playbackFilters.status,'Reihenfolge':c.playbackFilters.sort,'Ton':c.audio,'Gesamtlautstärke':c.volume,'Maximale Qualität':c.quality});this.renderSidebar();this.reconcile();this.scheduleLayout();
      if(!this.resizeObserver){this.resizeObserver=new ResizeObserver(()=>this.scheduleLayout());this.resizeObserver.observe(this.area);}
    }
    togglePanel(key){return this.setting('panels',{...D.settings().panels,...this.config().panels,[key]:!this.config().panels?.[key]});}
    renderChrome(){
      const c=this.config(),p=c.panels||D.settings().panels;
      this.chrome.replaceChildren(
        ...[['top','⚙ Arbeitsbereich'],['providers','◈ Anbieter'],['quick','⛭ Filter & Ton'],['footer','↔ Werkzeuge']].map(([key,title])=>button((p[key]?'▴ ':'▾ ')+title,()=>this.togglePanel(key),{'aria-expanded':String(p[key])})),
        button((c.sidebar?'▴ ':'▾ ')+'☷ Models',()=>this.setting('sidebar',!c.sidebar),{'aria-expanded':String(c.sidebar)}),
        button('▣ Mehr Streamfläche',()=>{
          for(const id of ['ac-main-menu-toggle','ac-live-nav-toggle']){const n=document.getElementById(id);if(n?.getAttribute('aria-expanded')==='true')n.click();}
          this.change(data=>{const cfg=data.workspaces.find(w=>w.id===this.workspaceId).settings;cfg.sidebar=false;cfg.panels={...cfg.panels,top:false,providers:false,quick:false,footer:false};});
        }),
        button('▴ Bedienung',()=>this.setting('toolbar',false),{title:'Alle Bedienleisten einklappen'}),
        el('span',{class:'lc-status-legend'},el('span',{'data-state':'online',text:'● Live'}),el('span',{'data-state':'offline',text:'● Offline'}),el('span',{'data-state':'private',text:'◆ Privat'}),el('span',{'data-state':'unknown',text:'? Unbekannt'})));
    }
    syncControlValues(container,values){for(const control of container.querySelectorAll('input,select')){const label=control.getAttribute('aria-label');if(control!==document.activeElement&&Object.hasOwn(values,label)){control.value=String(values[label]);if(control.type==='range'){const output=control.closest('label')?.querySelector('output');if(output)output.textContent=String(values[label]);}}}}
    renderTop(){
      const w=this.workspace(),c=w.settings;
      this.top.replaceChildren(select('Arbeitsbereich',w.id,this.data.workspaces.filter(x=>!x.archived).map(x=>[x.id,x.name]),value=>this.switchWorkspace(value)),
        button('Arbeitsbereiche',()=>this.workspacePanel()),button(c.sidebar?'Modellleiste ausblenden':'Modellleiste',()=>this.setting('sidebar',!c.sidebar)),
        select('Plätze',c.capacity,D.CAPACITIES.map(n=>[n,String(n)]),value=>this.setting('capacity',Number(value))),
        select('Ansicht',c.layout,[['grid','Raster · symmetrisch'],['mosaic','Mosaik · Originalformate'],['focus','Fokus'],['custom','Eigenes Raster']],value=>this.setting('layout',value)),
        button('Fenster ausfüllen',()=>this.fillWindow()),button('Mehr …',()=>this.morePanel()),button('Szenen',()=>this.scenePanel()));
    }
    renderProviders(){
      const c=this.config();
      this.providers.replaceChildren(el('span',{text:'Anbieter:'}),button('Alle Anbieter',()=>this.setting('sites',D.SITES.map(s=>s[0])),{class:c.sites.length===D.SITES.length?'primary':''}),
        ...D.SITES.map(([site,name])=>check(name,c.sites.includes(site),on=>this.change(data=>{const settings=data.workspaces.find(w=>w.id===this.workspaceId).settings;this.changeView(settings,()=>{settings.sites=on?[...new Set([...settings.sites,site])]:settings.sites.filter(s=>s!==site);});}))));
    }
    renderQuick(){
      const c=this.config();
      this.quick.replaceChildren(select('Bestand',c.source,[['workspace','Arbeitsbereich'],['library','Gespeicherte Bibliothek']],value=>this.setting('source',value)),
        select('Gruppe',c.playbackFilters.group,[['','Alle Gruppen'],...this.groups.map(g=>[g.id,g.name])],value=>this.filterChange('playback','group',value)),
        input('Wiedergabebestand durchsuchen',c.playbackFilters.q,value=>this.filterChange('playback','q',value),'search',{'data-lc-quick':'1'}),
        select('Raumstatus',c.playbackFilters.status,statusChoices,value=>this.filterChange('playback','status',value)),
        select('Reihenfolge',c.playbackFilters.sort,sortChoices.filter(([s])=>!['age','age-desc','rating','priority','country','followers','uptime','name-desc'].includes(s)),value=>this.filterChange('playback','sort',value)),
        select('Ton',c.audio,[['manual','Manuell'],['solo','Nur Solo'],['followFocus','Hauptstream']],value=>this.setting('audio',value)),
        slider('Gesamtlautstärke',c.volume,0,100,1,value=>{this.setting('volume',value);this.unlockAudio();}),
        select('Maximale Qualität',c.quality,[[0,'Unbegrenzt'],...D.HEIGHTS.map(h=>[h,h+'p'])],value=>this.setting('quality',Number(value))),
        button(c.muteAll?'Audiostand wiederherstellen':'Alle stumm',()=>this.setting('muteAll',!c.muteAll)),
        button('Streams aktualisieren',()=>this.reconnectAll()),button('Filter …',()=>this.filterPanel('playback')));
    }
    filterChange(which,field,value){return this.change(data=>{const c=data.workspaces.find(w=>w.id===this.workspaceId).settings;if(which==='sidebar'){c.sidebarFilters[field]=value;c.sidebarPage=0;}else this.changeView(c,()=>{c.playbackFilters[field]=value;});});}
    candidates(which){
      const c=this.config(),f=c[which==='sidebar'?'sidebarFilters':'playbackFilters'];
      const all=this.models(),slots=this.currentSlots(),groups=this.groupMap();
      const temporary=!!this.hasTemporarySlots(),occupied=new Set(slots.filter(Boolean));
      const signature=JSON.stringify([this.workspaceId,c.sites,f,c.sidebarSource,c.source,temporary,slots,this.workspace().modelOrder,f.group?groups[f.group]:null]);
      const cached=this.candidateCache?.[which];
      if(cached?.models===all&&cached.signature===signature)return cached.rows;
      let models=all.filter(m=>c.sites.includes(m.site));
      if(which==='sidebar'&&c.sidebarSource==='following')models=models.filter(m=>m.accountFav);
      if(which==='playback'&&(c.source==='workspace'||temporary))models=models.filter(m=>occupied.has(D.key(m)));
      else if(which==='playback')models=models.filter(m=>this.saved.has(D.key(m))||m.personal?.saved);
      const matchContext=D.prepareMatch(f,{groups,occupied});
      models=models.filter(m=>D.matches(m,f,matchContext));
      const rows=D.sortModels(models,f,which==='playback'&&(c.source==='workspace'||this.hasTemporarySlots())?this.currentSlots():this.workspace().modelOrder||[]);
      // An uncustomized catalog order otherwise puts ancient saved rooms ahead
      // of today's observed public rooms. Explicit orders/filters stay intact.
      if(which==='sidebar'&&f.sort==='manual'&&!(this.workspace().modelOrder||[]).length)rows.sort((a,b)=>(D.stateOf(b)==='online')-(D.stateOf(a)==='online'));
      (this.candidateCache||={})[which]={models:all,signature,rows};
      return rows;
    }
    contextKeyFor(c){return JSON.stringify([c.source,D.SITES.map(s=>s[0]).filter(site=>c.sites.includes(site)),c.playbackFilters]);}
    contextKey(){return this.contextKeyFor(this.config());}
    changeView(c,apply){const before=this.contextKeyFor(c),focus=c.focus;apply();const after=this.contextKeyFor(c);if(before===after)return;c.contexts[before]={...c.contexts[before],focus};c.focus=c.contexts[after]?.focus??null;c.page=0;const keys=Object.keys(c.contexts);if(keys.length>83)delete c.contexts[keys[0]];}
    hasTemporarySlots(){return this.rotation?.workspace===this.workspaceId||this.replacement?.workspace===this.workspaceId;}
    sessionSlots(){return this.config().source==='workspace'?D.clone(this.workspace().slots):Array.from({length:20},(_,i)=>this.visibleEntries().rows[i]?.identity||null);}
    currentSlots(){return this.rotation?.workspace===this.workspaceId&&this.rotation.slots?this.rotation.slots:this.replacement?.workspace===this.workspaceId?this.replacement.slots:this.workspace().slots;}
    visibleEntries(){
      const c=this.config(),models=this.candidates('playback'),context=c.contexts[this.contextKey()]||{};
      let selected=models.filter(model=>!(context.hidden||[]).includes(D.key(model)));
      if(context.order&&!this.hasTemporarySlots()){const ordered=new Map(context.order.map((value,index)=>[value,index]));selected.sort((a,b)=>(ordered.get(D.key(a))??99999)-(ordered.get(D.key(b))??99999));}
      const physical=(c.source==='workspace'||this.hasTemporarySlots())&&this.currentSlots().every(identity=>!identity||c.sites.includes(D.room(identity)?.site))&&(!context.order||this.hasTemporarySlots())&&!(context.hidden||[]).length&&JSON.stringify(c.playbackFilters)===JSON.stringify(D.filters());
      let entries;
      if(physical){const slots=this.currentSlots(),last=slots.reduce((last,value,index)=>value?index:last,-1);entries=slots.slice(0,Math.max(c.capacity,last+1)).map((identity,slot)=>({identity,model:identity?this.model(identity):null,slot}));}
      else entries=selected.map(m=>({identity:D.key(m),model:m}));
      const pages=Math.max(1,Math.ceil(entries.length/c.capacity)),page=D.clamp(context.page??c.page,0,pages-1),rows=entries.slice(page*c.capacity,(page+1)*c.capacity);
      while(rows.length<c.capacity)rows.push({identity:null,model:null,slot:physical?page*c.capacity+rows.length:undefined});
      return {rows,page,pages,total:selected.length};
    }
    page(delta){
      const view=this.visibleEntries(),next=D.clamp(view.page+delta,0,view.pages-1);
      this.change(data=>{const c=data.workspaces.find(w=>w.id===this.workspaceId).settings;const k=this.contextKey();c.contexts[k]={...c.contexts[k],page:next};const keys=Object.keys(c.contexts);if(keys.length>83)delete c.contexts[keys[0]];});
    }
    scheduleLayout(){if(!this.active||this.layoutFrame)return;this.layoutFrame=requestAnimationFrame(()=>{this.layoutFrame=0;this.layout();});}
    layout(){
      if(!this.active||!this.canvas)return;
      const top=Math.max(0,this.area.getBoundingClientRect().top),foot=this.footer.getBoundingClientRect().height,height=Math.max(220,innerHeight-top-foot-12);this.area.style.height=height+'px';
      const width=this.canvas.clientWidth-2,c=this.config(),entries=this.visibleEntries().rows;
      if(width<=0)return;
      const actual=entries.filter(e=>e.identity),layoutEntries=c.layout==='focus'&&actual.length?[...actual]:entries;
      let result;
      if(c.layout==='focus'&&actual.length){
        const focus=c.focus&&actual.some(e=>e.identity===c.focus)?c.focus:actual[0].identity;
        const ordered=[actual.find(e=>e.identity===focus),...actual.filter(e=>e.identity!==focus)];if(!c.thumbnails)ordered.splice(1);layoutEntries.splice(0,layoutEntries.length,...ordered);
        result=D.focusLayout(ordered.map(e=>this.ratio(e.identity)),width,height,c);
      }else result=D.gridLayout(layoutEntries.length,width,height,layoutEntries.map(e=>this.ratio(e.identity)),c);
      this.canvas.style.setProperty('--lc-canvas-height',result.height+'px');
      let index=0;
      for(const entry of layoutEntries){const tile=entry.identity?this.players.get(entry.identity)?.cell:this.emptyTiles?.[entries.indexOf(entry)];const box=result.rects[index++];if(!tile||!box)continue;
        tile.hidden=false;Object.assign(tile.style,{left:box.x+'px',top:box.y+'px',width:box.width+'px',height:box.height+'px'});
        tile.dataset.focus=String(!!entry.identity&&c.focus===entry.identity);}
      for(const tile of this.emptyTiles||[])if(tile&&c.layout==='focus'&&actual.length)tile.hidden=true;
      if(c.layout==='focus'&&!c.thumbnails)for(const p of this.players.values())if(!layoutEntries.some(e=>e.identity===p.identity))p.cell.hidden=true;
      this.refreshPauses();
    }
    ratio(identity){const video=this.players.get(identity)?.video,forced=D.aspect(this.config().aspect);return forced||(video?.videoWidth&&video?.videoHeight?video.videoWidth/video.videoHeight:16/9);}
    reconcile(){
      if(!this.active||!this.canvas)return;
      const view=this.visibleEntries(),wanted=new Set(view.rows.map(e=>e.identity).filter(Boolean));
      for(const identity of this.players.keys())if(!wanted.has(identity))this.removePlayer(identity);
      for(const entry of view.rows)if(entry.identity&&!this.players.has(entry.identity))this.makePlayer(entry.model);
      for(const entry of view.rows)if(entry.identity){const p=this.players.get(entry.identity);p.room={...p.room,...entry.model};p.cell.dataset.state=D.stateOf(entry.model);p.headerName.textContent=entry.model.name+' · '+D.SITES.find(s=>s[0]===entry.model.site)[1];this.applyPlayer(p);}
      for(const tile of this.emptyTiles||[])tile?.remove();
      this.emptyTiles=view.rows.map((entry,index)=>{
        if(entry.identity)return null;
        const tile=el('div',{class:'lc-tile lc-empty'},button('Platz '+(index+1)+' · Model wählen',()=>this.picker(index)));
        this.dropTarget(tile,index);this.canvas.append(tile);return tile;
      });
      this.footerSummary=el('span');this.footerView=view;this.updatePlayerCount();
      this.footer.replaceChildren(button('‹ Vorherige Seite',()=>this.page(-1),{disabled:view.page===0}),this.footerSummary,button('Nächste Seite ›',()=>this.page(1),{disabled:view.page>=view.pages-1}),button('Layouts und Werkzeuge',()=>this.layoutPanel()),button('Kontrollzentrum',()=>this.controlPanel()),button('Aufnahmezentrale',()=>this.capturePanel()));
      this.scheduleLayout();this.ctx.pump();
    }
    updatePlayerCount(){if(!this.footerSummary)return;const view=this.footerView,playing=[...this.players.values()].filter(p=>p.phase==='playing'&&!p.video.paused).length;this.footerSummary.textContent='Seite '+(view.page+1)+' / '+view.pages+' · '+view.total+' passende Models · '+playing+' spielen'+(view.total>this.config().capacity?' · weitere Belegungen bleiben gespeichert':'');}
    sidebarFold(label,key,body){
      const open=!!this.config().panels?.[key],fold=el('details',{class:'lc-sidebar-fold',open},el('summary',{text:label}),body);
      fold.addEventListener('toggle',()=>{if(fold.open!==!!this.config().panels?.[key])this.togglePanel(key);});
      return fold;
    }
    cover(model){const src=text(model?.thumb||model?.cover||'');return /^https?:\/\//i.test(src)?'/api/image?url='+encodeURIComponent(src):src.startsWith('/')?src:'';}
    hoverModel(node,identity){
      const hover=()=>{
        clearTimeout(this.previewHideTimer);
        if(this.previewPinned||this.dragging||this.hoverIdentity===identity&&(this.previewHoverTimer||this.previewIdentity===identity))return;
        clearTimeout(this.previewHoverTimer);this.hoverIdentity=identity;
        this.previewHoverTimer=setTimeout(()=>{this.previewHoverTimer=0;if(node.isConnected&&!this.previewPinned&&!this.dragging)this.previewStart(identity,node,false);},0);
      };
      node.addEventListener('pointerenter',hover);node.addEventListener('pointermove',hover);
      node.addEventListener('pointerleave',()=>{clearTimeout(this.previewHoverTimer);this.previewHoverTimer=0;this.hoverIdentity=null;if(!this.previewPinned)this.previewHideTimer=setTimeout(()=>this.previewClose(true),250);});
      return node;
    }
    pointerModel(node,identity){
      node.addEventListener('pointerdown',event=>{
        if(event.button!==0||event.target.closest('button:not(.lc-model-name),input,select'))return;
        this.cancelModelDrag?.();
        const start={x:event.clientX,y:event.clientY,id:event.pointerId};let moved=false,ghost=null,target=null;
        clearTimeout(this.previewHoverTimer);event.preventDefault();
        const clearTarget=()=>{target?.classList.remove('lc-drop');target=null;};
        const move=e=>{
          if(e.pointerId!==start.id)return;
          if(!moved&&Math.hypot(e.clientX-start.x,e.clientY-start.y)<8)return;
          if(!moved){moved=true;this.dragging=true;if(!this.holdPreview(identity))this.previewClose();ghost=el('div',{class:'lc-drag-ghost',text:'＋ '+D.room(identity).name});document.body.append(ghost);}
          e.preventDefault();ghost.style.left=e.clientX+12+'px';ghost.style.top=e.clientY+12+'px';
          const hit=document.elementFromPoint(e.clientX,e.clientY)?.closest('.lc-tile');
          if(hit!==target){clearTarget();if(hit&&this.canvas.contains(hit)){target=hit;target.classList.add('lc-drop');}}
        };
        const end=e=>{
          if(e.pointerId!==start.id)return;
          root.removeEventListener('pointermove',move,true);root.removeEventListener('pointerup',end,true);root.removeEventListener('pointercancel',end,true);
          const destination=target?target._lcDropPosition?.():null;
          clearTarget();ghost?.remove();this.dragging=false;
          this.cancelModelDrag=null;
          if(e.type==='pointercancel'||!Number.isInteger(destination))this.releasePreview();
          if(moved){this.ignoreClickUntil=Date.now()+350;e.preventDefault();if(e.type!=='pointercancel'&&Number.isInteger(destination)&&destination>=0)this.command(()=>this.place(identity,destination))();}
        };
        this.cancelModelDrag=()=>end({pointerId:start.id,type:'pointercancel',preventDefault(){}});
        root.addEventListener('pointermove',move,{capture:true,passive:false});root.addEventListener('pointerup',end,true);root.addEventListener('pointercancel',end,true);
        // The pointer route also handles touch and browsers that omit custom
        // HTML drag types. An ordinary click keeps its existing action.
      });
      node.addEventListener('dragstart',event=>event.preventDefault());
    }
    renderSidebar(){
      if(!this.sidebar||!this.data)return;
      const c=this.config(),rows=this.candidates('sidebar'),page=Math.min(c.sidebarPage,Math.max(0,Math.ceil(rows.length/50)-1));
      const signature=JSON.stringify([this.workspaceId,c.sidebarFilters,c.sidebarSource,c.sites,c.expandedGroups,c.panels?.sideFilters,c.panels?.sideGroups,page,rows.length,this.groups,this.followed.size,this.currentSlots(),rows.slice(page*50,page*50+50).map(m=>[D.key(m),D.stateOf(m),m.viewers,this.cover(m),m.subject,m.statusError,m.staleStatus,m.personal?.notes])]);
      if(!c.panels?.sideGroups&&signature===this.sidebarSignature&&this.sidebar.querySelector('.lc-model-list'))return;
      this.sidebarSignature=signature;
      const controls=el('div',{class:'lc-side-controls'},select('Modellquelle',c.sidebarSource,[['models','Models und öffentliche Räume'],['following','Offiziell gefolgt']],value=>this.setting('sidebarSource',value)),
        select('Gruppe der Modellliste',c.sidebarFilters.group,[['','Alle Gruppen'],...this.groups.map(g=>[g.id,g.name])],value=>this.filterChange('sidebar','group',value)),
        select('Listenstatus',c.sidebarFilters.status,statusChoices,value=>this.filterChange('sidebar','status',value)),
        select('Listensortierung',c.sidebarFilters.sort,sortChoices,value=>this.filterChange('sidebar','sort',value)),
        el('div',{class:'lc-buttons'},button('Filter',()=>this.filterPanel('sidebar')),button('Alle '+this.models().length+' Models',()=>this.change(data=>{const cfg=data.workspaces.find(w=>w.id===this.workspaceId).settings;cfg.sidebarFilters=D.filters();cfg.sidebarSource='models';cfg.sidebarPage=0;})),button('＋ Model',()=>this.addModelPanel()),button('Gruppen',()=>this.groupPanel())));
      const followingRows=this.models().filter(m=>m.accountFav&&c.sites.includes(m.site));
      const official=el('details',{open:!!c.expandedGroups.following},el('summary',{text:'Offiziell gefolgt · '+followingRows.filter(m=>D.stateOf(m)==='online').length+' / '+followingRows.length}),
        el('p',{class:'lc-muted',text:c.sites.map(site=>{const meta=this.followingMeta?.[site];return D.SITES.find(s=>s[0]===site)[1]+': '+(meta?meta.user+' · vollständiger Stand '+new Date(meta.at*1000).toLocaleString():'kein bestätigtes vollständiges Abrufdatum');}).join(' · ')}),
        button('Following aktualisieren',this.command(()=>this.refreshFollowing())),button('Following in Liste',()=>this.setting('sidebarSource','following')));
      official.addEventListener('toggle',()=>{if(official.open!==!!this.config().expandedGroups.following)this.change(data=>{data.workspaces.find(w=>w.id===this.workspaceId).settings.expandedGroups.following=official.open;});});
      const groups=el('div',{class:'lc-side-groups'},official);
      for(const group of this.groups){
        const memberIds=new Set(group.items||[]);
        const members=this.models().filter(m=>memberIds.has(D.key(m))&&c.sites.includes(m.site));
        const detail=el('details',{open:!!c.expandedGroups[group.id]},el('summary',{},...(group.cover?[el('img',{src:group.cover.startsWith('/api/cam-group-artwork?')?group.cover:this.ctx.imageURL?.(group.cover)||this.ctx.thumb?.(group.cover)||group.cover,alt:'',loading:'lazy',style:'width:28px;height:28px;object-fit:cover;vertical-align:middle;border-radius:4px;margin-right:6px'})]:[]),el('span',{text:group.name+' · '+members.filter(m=>D.stateOf(m)==='online').length+' / '+members.length})),
          button('Gruppe anzeigen',()=>this.filterChange('sidebar','group',group.id)),...members.slice(0,8).map(m=>this.hoverModel(button(m.name,()=>this.chooseModel(D.key(m))),D.key(m))));
        detail.addEventListener('toggle',()=>{if(detail.open!==!!this.config().expandedGroups[group.id])this.change(data=>{data.workspaces.find(w=>w.id===this.workspaceId).settings.expandedGroups[group.id]=detail.open;});});
        detail.addEventListener('dragover',event=>{if(!group.systemRole&&group.kind!=='smart'&&!group.archived)event.preventDefault();});detail.addEventListener('drop',this.command(async event=>{event.preventDefault();if(group.systemRole||group.kind==='smart'||group.archived)return;const identity=event.dataTransfer.getData('text/x-livecam');if(D.room(identity)){await this.ctx.post('/api/cam-library',{op:'group-item',id:group.id,...D.room(identity),on:true});await this.refreshData(false);}}));groups.append(detail);
      }
      const listNode=el('div',{class:'lc-model-list',style:'max-height:'+c.listHeight+'px'});listNode.dataset.density=c.density;
      const occupied=this.currentSlots();
      for(const model of rows.slice(page*50,(page+1)*50)){
        const identity=D.key(model),slot=occupied.indexOf(identity),state=D.stateOf(model),personal=model.personal||{};
        const row=el('div',{class:'lc-model-row',draggable:true,'data-model':identity,'data-state':state,'data-occupied':String(slot>=0)});
        row.addEventListener('dragstart',event=>{this.dragging=true;this.previewClose();event.dataTransfer.effectAllowed='copyMove';event.dataTransfer.setData('text/x-livecam',identity);event.dataTransfer.setData('text/x-livecam-list',identity);event.dataTransfer.setData('text/plain',identity);});
        row.addEventListener('dragend',()=>{this.dragging=false;});
        row.addEventListener('dragover',event=>event.preventDefault());
        row.addEventListener('drop',this.command(event=>{event.preventDefault();const dragged=event.dataTransfer.getData('text/x-livecam-list');if(!D.room(dragged)||dragged===identity)return;return this.change(data=>{const w=data.workspaces.find(w=>w.id===this.workspaceId),order=w.modelOrder||this.models().map(D.key);w.modelOrder=order.filter(k=>k!==dragged);w.modelOrder.splice(Math.max(0,w.modelOrder.indexOf(identity)),0,dragged);});}));
        const name=button(model.name,()=>this.chooseModel(identity),{class:'lc-model-name',draggable:true,title:'Ziehen zum Einsetzen · '+(model.subject||'')+' · '+model.site});
        this.hoverModel(row,identity);
        this.pointerModel(row,identity);
        const avatar=el('span',{class:'lc-model-avatar',text:model.name.slice(0,1).toUpperCase()}),src=this.cover(model);
        if(src)avatar.append(el('img',{src,alt:'',loading:'lazy',decoding:'async',onerror:event=>event.target.remove()}));
        row.append(el('div',{class:'lc-model-summary'},avatar,el('div',{class:'lc-model-copy'},name,el('span',{class:'lc-state-badge','data-state':state,text:(state==='private'?'◆ ':state==='unknown'?'? ':'● ')+statusNames[state]}),el('small',{text:D.SITES.find(s=>s[0]===model.site)[1]+(slot>=0?' · ▣ Platz '+(slot+1):'')+(model.viewers!=null?' · '+model.viewers+' Zuschauer':'')}))),
          el('div',{class:'lc-row-actions'},button('＋ Einsetzen',()=>this.chooseModel(identity)),button('▷ Vorschau',()=>this.previewStart(identity,row,true)),button('⋯',()=>this.modelPanel(identity),{'aria-label':'Modelmenü für '+model.name})));
        if(model.staleStatus)row.title='Ältere Statusmeldung. Der öffentliche Stream wird beim Öffnen neu geprüft.';
        if(model.statusError)row.title=model.statusError;
        if(personal.notes)row.title=personal.notes;listNode.append(row);
      }
      if(!rows.length)listNode.append(el('p',{class:'lc-muted',text:c.sites.length?'Keine Models passen zu den Filtern.':'Wähle mindestens einen Anbieter.'}));
      const pager=el('div',{class:'lc-buttons'},button('‹',()=>this.setting('sidebarPage',Math.max(0,page-1)),{disabled:page===0}),el('span',{text:(page+1)+' / '+Math.max(1,Math.ceil(rows.length/50))+' · '+rows.length}),button('›',()=>this.setting('sidebarPage',page+1),{disabled:(page+1)*50>=rows.length}));
      const listScroll=this.sidebar.querySelector('.lc-model-list')?.scrollTop||0,sideScroll=this.sidebar.scrollTop,active=document.activeElement;
      if(active&&this.sidebar.contains(active)&&['INPUT','SELECT','TEXTAREA'].includes(active.tagName)&&this.sidebar.querySelector('.lc-model-list')){
        this.sidebar.querySelector('.lc-model-list').replaceWith(listNode);this.sidebar.querySelector('.lc-side-pager')?.replaceWith(pager);pager.classList.add('lc-side-pager');listNode.scrollTop=listScroll;this.sidebar.scrollTop=sideScroll;return;
      }
      const search=input('Modelle suchen',c.sidebarFilters.q,value=>this.filterChange('sidebar','q',value),'search');search.classList.add('lc-side-search');
      const states=el('div',{class:'lc-side-states','aria-label':'Modellliste nach Status filtern'},...[['online','● Live'],['offline','● Offline'],['private','◆ Privat'],['unknown','?']].map(([state,label])=>button(label,()=>this.filterChange('sidebar','status',c.sidebarFilters.status===state?'all':state),{'data-state':state,'aria-pressed':String(c.sidebarFilters.status===state),title:statusNames[state]})));
      pager.classList.add('lc-side-pager');this.sidebar.replaceChildren(search,states,this.sidebarFold('⛭ Weitere Filter und Sortierung','sideFilters',controls),this.sidebarFold('▦ Gruppen und Following','sideGroups',groups),pager,listNode);listNode.scrollTop=listScroll;this.sidebar.scrollTop=sideScroll;
    }
    async previewStart(identity,anchor,pinned,fresh=false){
      if(this.previewIdentity===identity&&this.previewPlayer?.phase!=='failed'){this.previewPinned=pinned||this.previewPinned;return;}
      const warm=!fresh&&this.warmPreview?.identity===identity?this.warmPreview:null;
      if(warm){clearTimeout(this.warmPreviewTimer);this.warmPreview=null;}
      this.previewClose(true);this.previewIdentity=identity;this.previewPinned=pinned;
      if(warm){const p=warm.player;this.previewPlayer=p;this.previewPopup=warm.popup;warm.popup.hidden=false;
        const box=anchor.getBoundingClientRect();Object.assign(warm.popup.style,{left:Math.max(8,Math.min(innerWidth-340,box.right+8))+'px',top:Math.max(8,Math.min(innerHeight-300,box.top-100))+'px'});
        p.phase='buffering';p.paused=false;p.previewStarted=performance.now();p.hls?.startLoad(-1);
        const target=p.hls?.liveSyncPosition;if(Number.isFinite(target))try{p.video.currentTime=target;}catch{}
        p.previewTimer=setTimeout(()=>{if(this.previewPlayer===p&&p.phase!=='playing')this.previewFailed(p,identity,'Die Vorschau liefert noch kein Videobild.');},30000);p.video.play()?.catch(()=>this.previewFailed(p,identity,'Die Vorschau konnte nicht fortgesetzt werden.'));return;
      }
      const model=this.model(identity),box=anchor.getBoundingClientRect(),popup=el('div',{class:'lc-preview',role:'region','aria-label':'Vorschau für '+model.name}),video=el('video',{muted:true,autoplay:true,playsInline:true,crossOrigin:'anonymous'});
      const title=el('div',{class:'lc-preview-status',text:model.name+' · Öffentlichen Stream prüfen …'}),retry=button('Erneut prüfen',()=>this.previewStart(identity,anchor,true,true),{hidden:true});
      const image=el('img',{src:this.cover(model),alt:'Gespeichertes Bild von '+model.name,hidden:!this.cover(model),onerror:event=>{event.target.hidden=true;}});
      popup.append(image,video,title,button('Schließen',()=>this.previewClose()),button('＋ Einsetzen',()=>this.chooseModel(identity)),button('Anheften',()=>{this.previewPinned=true;}),retry);(document.fullscreenElement||document.body).append(popup);
      popup.addEventListener('pointerenter',()=>clearTimeout(this.previewHideTimer));popup.addEventListener('pointerleave',()=>{if(!this.previewPinned)this.previewHideTimer=setTimeout(()=>this.previewClose(true),220);});
      Object.assign(popup.style,{left:Math.max(8,Math.min(innerWidth-Math.min(340,innerWidth-16),box.right+8))+'px',top:Math.max(8,Math.min(innerHeight-300,box.top-100))+'px'});
      const p=this.ctx.createPlayer({...this.model(identity),slot:38},popup,video,title,retry);p.preview=true;p.priority=true;p.resolveFresh=fresh;p.previewStarted=performance.now();
      p.onReady=()=>{title.textContent=model.name+' · Bild wird geladen …';};
      p.onManifest=()=>{if(p.hls){p.hls.autoLevelCapping=D.levelIndex(p.hls.levels,360);p.hls.loadLevel=-1;}};
      const playing=()=>{if(this.previewPlayer!==p)return;clearTimeout(p.previewTimer);popup.dataset.playing='true';image.hidden=true;p.phase='playing';this.checkedRoom(identity,true);p.firstFrameMs=Math.round(performance.now()-p.previewStarted);popup.dataset.firstFrameMs=String(p.firstFrameMs);title.textContent=model.name+' · ● Live · '+(p.firstFrameMs/1000).toFixed(1)+' s';};
      video.addEventListener('playing',playing);p.previewCleanup=()=>video.removeEventListener('playing',playing);
      p.onFailure=message=>this.previewFailed(p,identity,message);
      p.previewTimer=setTimeout(()=>{if(this.previewPlayer===p&&p.phase!=='playing')this.previewFailed(p,identity,'Die Vorschau hat noch kein Videobild geliefert. Bitte erneut prüfen.');},30000);
      this.previewPlayer=p;this.previewPopup=popup;this.ctx.pump();
    }
    previewFailed(player,identity,message){
      clearTimeout(player.previewTimer);player.controller?.abort();player.phase='failed';if(player.hls){player.hls.destroy();player.hls=null;}
      player.video.pause();player.video.removeAttribute('src');player.video.load();player.video.hidden=true;
      player.title.textContent=message+' Gespeichertes Bild, falls vorhanden.';player.retry.hidden=false;this.checkedRoom(identity,null,message);
    }
    releaseWarmPreview(){clearTimeout(this.warmPreviewTimer);const warm=this.warmPreview;this.warmPreview=null;if(warm){warm.player.previewCleanup?.();this.ctx.destroyPlayer(warm.player);warm.popup.remove();}}
    previewClose(keepWarm=false){clearTimeout(this.previewHoverTimer);this.previewHoverTimer=0;clearTimeout(this.previewHideTimer);if(!keepWarm)this.releaseWarmPreview();if(this.previewPlayer){const p=this.previewPlayer;clearTimeout(p.previewTimer);
      if(keepWarm&&p.phase==='playing'&&(p.hls||p.video.readyState>=2)){this.releaseWarmPreview();p.hls?.stopLoad();p.video.pause();p.phase='paused';p.paused=true;this.previewPopup.hidden=true;this.warmPreview={identity:this.previewIdentity,player:p,popup:this.previewPopup};this.warmPreviewTimer=setTimeout(()=>this.releaseWarmPreview(),8000);}
      else{p.previewCleanup?.();this.ctx.destroyPlayer(p);this.previewPopup?.remove();}this.previewPlayer=null;
    }else this.previewPopup?.remove();this.previewPopup=null;this.previewIdentity=null;this.previewPinned=false;this.hoverIdentity=null;}
    holdPreview(identity){
      if(this.previewIdentity!==identity||!this.previewPlayer||this.previewPlayer.closed||this.previewPlayer.phase==='failed')return false;
      // Keep the connected media element until the committed placement adopts
      // it; a resolver already in flight must still see a connected cell.
      this.releasePreview();clearTimeout(this.previewHoverTimer);this.previewHoverTimer=0;clearTimeout(this.previewHideTimer);
      const player=this.previewPlayer,popup=this.previewPopup;clearTimeout(player.previewTimer);this.heldPreview={identity,player,popup};popup.hidden=true;
      this.previewPlayer=null;this.previewPopup=null;this.previewIdentity=null;this.previewPinned=false;this.hoverIdentity=null;
      this.heldPreviewTimer=setTimeout(()=>this.releasePreview(),15000);return true;
    }
    releasePreview(){clearTimeout(this.heldPreviewTimer);if(!this.heldPreview)return;const {player,popup}=this.heldPreview;this.heldPreview=null;player.previewCleanup?.();this.ctx.destroyPlayer(player);popup.remove();}
    takePreview(identity){if(this.heldPreview?.identity!==identity)return null;clearTimeout(this.heldPreviewTimer);const held=this.heldPreview;this.heldPreview=null;held.player.previewCleanup?.();return held;}
    currentPosition(identity){return this.visibleEntries().rows.findIndex(e=>e.identity===identity);}
    chooseModel(identity){
      if(Date.now()<(this.ignoreClickUntil||0))return;
      if(this.currentPosition(identity)>=0){this.previewClose();this.setting('focus',identity);return;}
      const free=this.visibleEntries().rows.findIndex(e=>!e.identity);
      if(free>=0)this.place(identity,free);
      else this.picker(null,identity);
    }
    async addRoom(room){
      const identity=D.key(room);if(!identity)return null;
      const workspace=this.data.workspaces.find(w=>w.id===this.data.active&&!w.archived)||this.data.workspaces.find(w=>w.id==='default');
      await this.change(data=>{
        const target=data.workspaces.find(w=>w.id===workspace.id);
        if(!target.settings.sites.includes(room.site))this.changeView(target.settings,()=>{target.settings.sites.push(room.site);});
        if(target.slots.includes(identity))return;
        const slot=target.slots.indexOf(null);if(slot<0)throw Error('Alle 20 Plätze dieses Arbeitsbereichs sind belegt.');
        target.slots[slot]=identity;const occupied=target.slots.filter(Boolean).length;
        if(occupied>target.settings.capacity)target.settings.capacity=D.CAPACITIES.find(n=>n>=occupied)||20;
      });
      this.catalog.set(identity,room);this.ctx.legacyWrite?.(this.data.workspaces.find(w=>w.id==='default').slots,this.data.workspaces.find(w=>w.id==='default').settings);
      return workspace.id;
    }
    async place(identity,position){
      if(!D.room(identity))return;
      if(!this.holdPreview(identity)&&this.heldPreview?.identity!==identity)this.previewClose();
      this.stopRotation();const entries=this.visibleEntries().rows,replace=entries[position]?.identity,context=this.contextKey(),source=this.config().source;
      if(source==='library'&&!this.saved.has(identity)){await this.ctx.post('/api/cam-library',{op:'model-save',...D.room(identity)});this.saved.set(identity,{...this.model(identity),personal:{...this.model(identity)?.personal,saved:true}});}
      await this.change(data=>{
        const w=data.workspaces.find(w=>w.id===this.workspaceId);
        if(source==='workspace'){
          let target=replace?w.slots.indexOf(replace):entries[position]?.slot??w.slots.findIndex((value,index)=>!value&&index<w.settings.capacity);
          if(target<0)target=w.slots.indexOf(null);if(target<0)throw Error('Alle 20 gespeicherten Plätze sind belegt. Zuerst einen Platz leeren.');
          const previous=w.slots.indexOf(identity);if(previous>=0)w.slots[previous]=null;w.slots[target]=identity;
        }else{
          let order=(w.settings.contexts[context]?.order||this.candidates('playback').map(D.key)).slice();
          const from=order.indexOf(identity),to=replace?order.indexOf(replace):-1;
          if(from>=0&&to>=0)[order[from],order[to]]=[order[to],order[from]];
          else{order=order.filter(k=>k!==identity);const at=replace?order.indexOf(replace):-1;order.splice(at>=0?at:this.visibleEntries().page*w.settings.capacity+position,at>=0?1:0,identity);}
          w.settings.contexts[context]={...w.settings.contexts[context],order};
        }
      });
      this.ctx.legacyWrite?.(this.data.workspaces.find(w=>w.id==='default').slots);
    }
    async swap(a,b){
      if(a===b)return;const entries=this.visibleEntries().rows,x=entries[a]?.identity,y=entries[b]?.identity;
      if(!x&&!y)return;this.stopRotation();
      await this.change(data=>{const w=data.workspaces.find(w=>w.id===this.workspaceId);if(w.settings.source==='workspace'){
        const first=x?w.slots.indexOf(x):entries[a]?.slot??w.slots.indexOf(null),second=y?w.slots.indexOf(y):entries[b]?.slot??w.slots.indexOf(null);if(first>=0&&second>=0)[w.slots[first],w.slots[second]]=[w.slots[second],w.slots[first]];
      }else{const k=this.contextKey(),order=(w.settings.contexts[k]?.order||this.candidates('playback').map(D.key)).slice(),offset=this.visibleEntries().page*w.settings.capacity;[order[offset+a],order[offset+b]]=[order[offset+b],order[offset+a]];w.settings.contexts[k]={...w.settings.contexts[k],order};}});
    }
    dropTarget(tile,position){
      tile._lcDropPosition=()=>typeof position==='function'?position():position;
      tile.addEventListener('dragover',event=>{event.preventDefault();tile.classList.add('lc-drop');});tile.addEventListener('dragleave',()=>tile.classList.remove('lc-drop'));
      tile.addEventListener('drop',this.command(event=>{
        event.preventDefault();tile.classList.remove('lc-drop');this.dragging=false;this.previewClose();
        const target=typeof position==='function'?position():position,from=event.dataTransfer.getData('text/x-livecam-slot');
        if(/^\d+$/.test(from)&&Number(from)<this.visibleEntries().rows.length)return this.swap(Number(from),target);
        const value=event.dataTransfer.getData('text/x-livecam')||event.dataTransfer.getData('text/plain')||event.dataTransfer.getData('text/uri-list');
        const identity=D.room(value)?value:D.key(D.parsePublicURL(value));
        if(!identity){this.notify('Bitte ein Model oder einen öffentlichen Raumlink auf einen Platz ziehen.',true);return;}
        return this.place(identity,target);
      }));
    }
    makePlayer(model){
      const identity=D.key(model),held=this.takePreview(identity),cell=el('article',{class:'lc-tile','data-model':identity}),video=held?.player.video||el('video',{muted:true,autoplay:true,playsInline:true,crossOrigin:'anonymous'});
      const viewport=el('div',{class:'lc-video'}),head=el('div',{class:'lc-tile-head'}),name=el('strong',{text:model.name,"data-i18n-content":""}),title=el('span',{class:'lc-stream-state',text:'Wartet'}),retry=button('Erneut verbinden',()=>this.reconnect(identity),{hidden:true});
      video.controls=true;viewport.append(video);const meter=el('meter',{min:0,max:100,value:0,hidden:true,'aria-label':'Gemessener Audiopegel'});
      head.append(name,title,meter);
      const tools=el('div',{class:'lc-tile-tools'},button('◎',()=>this.focus(identity),{'aria-label':'Fokus',title:'Fokus'}),button('⏯',()=>this.pause(identity),{'aria-label':'Pause / Fortsetzen',title:'Pause / Fortsetzen'}),button('♪',()=>this.toggleAudio(identity),{'aria-label':'Ton',title:'Ton'}),button('↻',()=>this.reconnect(identity),{'aria-label':'Neu verbinden',title:'Neu verbinden'}),button('⋯',()=>this.cameraPanel(identity),{'aria-label':'Kameramenü',title:'Kameramenü'}),button('×',()=>this.removeRoom(identity),{'aria-label':'Aus Platz entfernen',title:'Aus Platz entfernen'}));
      cell.append(viewport,head,tools,retry);this.canvas.append(cell);
      const transport=held?held.player.room.slot:this.freeTransportSlot(),player=held?.player||this.ctx.createPlayer({...model,slot:transport},cell,video,title,retry);
      if(held){Object.assign(player,{cell,video,title,retry});held.popup.remove();}
      cell.dataset.playerOwner=player.key;
      Object.assign(player,{identity,viewport,headerName:name,meter,tools,started:performance.now(),frames:0,dropped:null,stalls:0,stallMs:0,reconnects:0,frameAt:performance.now(),lastTime:0,cleanup:[],room:{...model,slot:transport},rect:null,userPaused:false,failures:0});
      // A saved status is not an authority on today's availability. The public
      // resolver validates the actual room and rejects private/offline content.
      player.allowStart=()=>{const c=this.config();const ordered=[...this.players.keys()].sort((a,b)=>(b===c.focus)-(a===c.focus));return !(c.layout==='focus'&&!c.thumbnails&&identity!==(c.focus||this.visibleEntries().rows.find(e=>e.identity)?.identity)&&!this.capture.jobs.has(identity))&&!this.prefs(identity).paused&&ordered.indexOf(identity)<c.activeLimit;};
      player.onReady=()=>{title.textContent='Öffentliche Quelle gefunden · lädt …';this.applyPlayer(player);this.refreshPauses();};
      player.onBlocked=()=>{player.phase='blocked';title.textContent='Wiedergabe bitte im Video anklicken';};
      player.onManifest=()=>this.applyQuality(player);
      player.onFailure=message=>this.playerFailed(player,message);
      player.onVisibility=()=>this.refreshPauses();
      const listen=(name,fn)=>{video.addEventListener(name,fn);player.cleanup.push(()=>video.removeEventListener(name,fn));};
      listen('loadedmetadata',()=>{this.applyQuality(player);this.scheduleLayout();});
      const playing=()=>{
        this.checkedRoom(identity,true);cell.dataset.state='online';
        player.phase='playing';player.healthyAt=performance.now();if(!video.requestVideoFrameCallback&&player.firstFrame==null)player.firstFrame=performance.now()-player.started;
        if(player.waitAt){player.stallMs+=performance.now()-player.waitAt;player.waitAt=0;}
        title.textContent='Live';this.updatePlayerCount();this.capture.sourceReady(identity);
      };listen('playing',playing);
      listen('waiting',()=>{if(!player.paused){player.phase='buffering';if(!player.waitAt){player.stalls++;player.waitAt=performance.now();}title.textContent='Puffert …';}});
      listen('pause',()=>{if(!player.closed&&player.phase!=='failed')title.textContent=player.paused?'Pausiert':'Wiedergabe pausiert';});
      listen('ended',()=>this.playerFailed(player,'Die Videoquelle wurde beendet.'));
      listen('error',()=>{if(!player.closed&&!player.hls)this.playerFailed(player,'Der Stream konnte nicht geladen werden.');});
      listen('volumechange',()=>{if(player.applyingAudio)return;const prefs=this.prefs(identity);if(video.muted!==prefs.muted&&this.config().audio==='manual'&&!this.config().muteAll)this.cameraSetting(identity,'muted',video.muted);});
      if(video.requestVideoFrameCallback){const frame=(now,metadata)=>{if(player.closed)return;player.frames++;player.frameAt=now;if(player.firstFrame==null)player.firstFrame=now-player.started;player.presented=metadata.presentedFrames;player.frameCallback=video.requestVideoFrameCallback(frame);};player.frameCallback=video.requestVideoFrameCallback(frame);}
      this.installGestures(player);this.players.set(identity,player);this.applyPlayer(player);
      if(held&&video.readyState>=2&&!video.paused)playing();
      const position=()=>this.currentPosition(identity);this.dropTarget(cell,position);
      head.draggable=true;head.addEventListener('dragstart',event=>{event.dataTransfer.setData('text/x-livecam-slot',String(position()));event.dataTransfer.setData('text/x-livecam',identity);});
      cell.addEventListener('contextmenu',event=>{event.preventDefault();this.cameraPanel(identity);});
      return player;
    }
    freeTransportSlot(){const used=new Set([...this.players.values()].map(p=>p.room.slot));let slot=0;while(used.has(slot))slot++;return slot;}
    removePlayer(identity){const p=this.players.get(identity);if(!p)return;this.capture.sourceLost(identity);clearTimeout(p.retryTimer);p.cleanup.forEach(fn=>fn());if(p.frameCallback!=null)p.video.cancelVideoFrameCallback?.(p.frameCallback);this.stopMeter(p);p.audioSource?.disconnect();this.ctx.destroyPlayer(p);p.cell.remove();this.players.delete(identity);}
    playerFailed(player,message){
      if(player.closed)return;
      if(player.hls){player.hls.destroy();player.hls=null;}player.video.pause();player.video.removeAttribute('src');player.video.load();player.phase='failed';player.title.textContent=message;player.retry.hidden=false;this.capture.sourceLost(player.identity);
      this.checkedRoom(player.identity,null,message);player.cell.dataset.state=this.liveChecks.get(player.identity).state;this.renderSidebar();
      const state=D.stateOf(this.model(player.identity));
      clearTimeout(player.retryTimer);
      if(!/nicht öffentlich|offline|privat|private/i.test(message)&&!['private','offline','away','denied'].includes(state)&&!this.prefs(player.identity).paused&&player.failures<6){const delay=Math.min(60000,5000*2**player.failures);player.failures++;player.title.textContent=message+' Neuer Versuch in '+Math.round(delay/1000)+' s.';player.retryTimer=setTimeout(()=>{if(!player.closed&&this.active&&!this.prefs(player.identity).paused)this.reconnect(player.identity,false);},delay);}
    }
    reconnect(identity,manual=true){
      const p=this.players.get(identity);if(!p)return;
      clearTimeout(p.retryTimer);p.controller?.abort();if(p.hls)p.hls.destroy();p.hls=null;p.video.pause();p.video.removeAttribute('src');p.video.load();
      p.phase='queued';p.resolveFresh=true;p.paused=false;p.firstFrame=null;p.started=performance.now();p.reconnects++;if(manual)p.failures=0;p.retry.hidden=true;p.title.textContent='Neu verbinden …';this.ctx.pump();
    }
    reconnectAll(){for(const identity of this.players.keys())this.reconnect(identity);}
    applyQuality(player){if(!player?.hls?.levels?.length)return;const c=this.config(),prefs=this.prefs(player.identity),target=D.qualityTarget(c,prefs,this.players.size,c.focus===player.identity),index=D.levelIndex(player.hls.levels,target);if(player.qualityIndex!==index){player.hls.autoLevelCapping=index;player.hls.loadLevel=-1;player.qualityIndex=index;}}
    applyPlayer(player){
      if(!player||player.closed)return;const p=this.prefs(player.identity),c=this.config();
      player.video.style.objectFit=['grid','mosaic'].includes(c.layout)?'contain':c.fit;
      player.video.style.transform=`translate(${p.x}px,${p.y}px) rotate(${p.rotate}deg) scale(${p.zoom/100*(p.flipX?-1:1)},${p.zoom/100*(p.flipY?-1:1)})`;
      player.video.style.filter=`brightness(${p.brightness}%) contrast(${p.contrast}%) saturate(${p.saturation}%) hue-rotate(${p.hue}deg) sepia(${p.sepia}%) grayscale(${p.grayscale}%) invert(${p.invert}%) blur(${p.blur}px)`;
      const focus=c.focus||this.visibleEntries().rows.find(e=>e.identity)?.identity,audio=D.audioState(c,p,player.identity,focus);
      player.applyingAudio=true;player.video.muted=audio.muted;player.video.volume=audio.volume;queueMicrotask(()=>{player.applyingAudio=false;});
      player.userPaused=p.paused;this.applyQuality(player);
      const meter=c.meterMode==='all'||c.meterMode==='individual'&&(p.meter==='on'||p.meter==='global'&&c.meterDefault);
      if(meter)this.startMeter(player);else this.stopMeter(player);
    }
    visibilityChanged(){
      if(this.root)this.root.dataset.background=String(document.hidden);
      // Background tabs can stop presenting frames while the stream continues.
      // Give rendering time to resume before the frame watchdog diagnoses it.
      if(!document.hidden){const now=performance.now();this.usageTickAt=now;for(const p of this.players.values())p.visibleSince=now;}
      this.refreshPauses();this.ctx?.pump();
    }
    refreshPauses(){
      if(!this.active||!this.data)return;const c=this.config(),focus=c.focus||this.visibleEntries().rows.find(e=>e.identity)?.identity,limit=c.performance==='economy'?Math.min(4,c.activeLimit):c.activeLimit;
      const ordered=[...this.players.values()].sort((a,b)=>(b.identity===focus)-(a.identity===focus));
      ordered.forEach((p,index)=>{
        const prefs=this.prefs(p.identity);
        const pause=!!prefs.paused||index>=limit||(c.layout==='focus'&&!c.thumbnails&&p.identity!==focus&&!this.capture.jobs.has(p.identity));
        if(p.phase==='failed')return;
        if(['playing','buffering'].includes(p.phase)||p.paused)this.ctx.setPaused(p,pause);
        p.cell.dataset.paused=String(pause);
      });
    }
    async pause(identity){const p=this.prefs(identity);this.cameraSetting(identity,'paused',!p.paused);await this.commitCamera(identity);this.refreshPauses();}
    toggleAudio(identity){this.unlockAudio();this.cameraSetting(identity,'muted',!this.prefs(identity).muted);}
    async focus(identity){await this.change(data=>{const c=data.workspaces.find(w=>w.id===this.workspaceId).settings;const same=c.focus===identity;c.focus=identity;c.contexts[this.contextKeyFor(c)]={...c.contexts[this.contextKeyFor(c)],focus:identity};c.layout=c.layout==='focus'&&same?'mosaic':'focus';});}
    nextFocus(delta){const models=this.visibleEntries().rows.map(e=>e.identity).filter(Boolean);if(!models.length)return;const at=models.indexOf(this.config().focus);this.setting('focus',models[(at+delta+models.length)%models.length]);}
    async removeRoom(identity){
      this.stopRotation();await this.change(data=>{const w=data.workspaces.find(w=>w.id===this.workspaceId);w.slots=w.slots.map(value=>value===identity?null:value);if(w.settings.source==='library'){const k=this.contextKey();w.settings.contexts[k]={...w.settings.contexts[k],hidden:[...new Set([...(w.settings.contexts[k]?.hidden||[]),identity])]};}});
      this.ctx.legacyWrite?.(this.data.workspaces.find(w=>w.id==='default').slots);
    }
    installGestures(player){
      const video=player.video,viewport=player.viewport;
      const wheel=event=>{if(!this.config().freeZoom||!(event.ctrlKey||event.metaKey))return;event.preventDefault();this.cameraSetting(player.identity,'zoom',D.clamp(this.prefs(player.identity).zoom*(event.deltaY<0?1.1:1/1.1),100,2000));};
      viewport.addEventListener('wheel',wheel,{passive:false});player.cleanup.push(()=>viewport.removeEventListener('wheel',wheel));
      viewport.addEventListener('dblclick',event=>{if(this.prefs(player.identity).zoom>100){event.preventDefault();this.resetTransform(player.identity);}});
      viewport.addEventListener('pointerdown',event=>{
        if(!this.config().freeZoom||this.prefs(player.identity).zoom<=100||event.button!==0)return;
        const rect=video.getBoundingClientRect();if(event.clientY>rect.bottom-45)return;
        const start=this.prefs(player.identity),x=event.clientX,y=event.clientY;viewport.setPointerCapture(event.pointerId);event.preventDefault();
        const move=e=>{this.cameraSetting(player.identity,'x',D.clamp(start.x+e.clientX-x,-5000,5000));this.cameraSetting(player.identity,'y',D.clamp(start.y+e.clientY-y,-5000,5000));};
        const up=()=>{viewport.removeEventListener('pointermove',move);viewport.removeEventListener('pointerup',up);this.commitCamera(player.identity);};viewport.addEventListener('pointermove',move);viewport.addEventListener('pointerup',up,{once:true});
      });
    }
    resetTransform(identity){for(const [name,value] of Object.entries({zoom:100,x:0,y:0}))this.cameraSetting(identity,name,value);}
    unlockAudio(){try{if(!this.audioContext)this.audioContext=new (root.AudioContext||root.webkitAudioContext)();this.audioContext.resume().catch(()=>{});}catch{}}
    startMeter(player){
      if(player.analyser||!this.audioContext||this.audioContext.state!=='running')return;
      try{player.audioSource=player.audioSource||this.audioContext.createMediaElementSource(player.video);player.audioSource.disconnect();player.analyser=this.audioContext.createAnalyser();player.analyser.fftSize=256;player.audioSource.connect(player.analyser);player.analyser.connect(this.audioContext.destination);player.samples=new Uint8Array(256);player.meter.hidden=false;}
      catch{player.meter.title='Ein gemessener Pegel ist für diese Quelle nicht verfügbar.';player.meter.hidden=true;}
    }
    stopMeter(player){if(player.analyser){player.analyser.disconnect();player.analyser=null;player.audioSource.disconnect();if(!player.closed)player.audioSource.connect(this.audioContext.destination);}player.meter.hidden=true;}
    tick(){
      if(!this.active)return;
      const now=performance.now();
      const watchDelta=Math.max(0,Math.min(2000,now-(this.usageTickAt??now-1000)));this.usageTickAt=now;
      if(now-(this.sidebarStatusAt||0)>30000){this.sidebarStatusAt=now;this.renderSidebar();}
      for(const p of this.players.values()){
        if(!document.hidden&&!p.paused&&!p.userPaused&&p.phase==='buffering'&&now-Math.max(p.waitAt||p.started,p.visibleSince??-Infinity)>45000){this.playerFailed(p,'Der Stream liefert seit 45 Sekunden kein Bild.');continue;}
        if(!p.video.paused&&p.phase==='playing'){
          if(now-(p.healthyAt||now)>30000)p.failures=0;
          if(p.video.getVideoPlaybackQuality){const q=p.video.getVideoPlaybackQuality();p.decoded=Number.isFinite(q.totalVideoFrames)?q.totalVideoFrames:null;p.dropped=q.droppedVideoFrames;}
          const actualFrames=p.video.requestVideoFrameCallback?p.frames>0&&now-p.frameAt<3000:Number.isFinite(p.decoded)&&p.decoded>(p.lastWatchFrames??p.decoded);
          if(p.video.readyState>=2&&!p.video.seeking&&actualFrames)p.watched=(p.watched||0)+watchDelta;
          p.lastWatchFrames=p.decoded;
          if(!document.hidden&&now-(p.visibleSince||0)>10000&&p.video.readyState>=2&&!p.video.seeking&&p.video.currentTime>p.lastTime+.05&&now-p.frameAt>8000&&p.frames>0&&now-(p.lastRecovery||0)>15000){p.lastRecovery=now;this.playerFailed(p,'Bildstillstand erkannt. Verbindung wird erneuert.');}
          p.lastTime=p.video.currentTime;
        }
        if(p.analyser){p.analyser.getByteTimeDomainData(p.samples);let sum=0;for(const value of p.samples)sum+=((value-128)/128)**2;p.meter.value=Math.min(100,Math.sqrt(sum/p.samples.length)*200);}
      }
      if(now-this.metricsAt>15000){this.metricsAt=now;this.saveUsage();}
      if(!document.hidden&&Date.now()-this.statusAt>60000)this.refreshData(false);
      if(this.config().autoFollowing&&Date.now()-(this.followingAt||0)>600000){this.followingAt=Date.now();this.refreshFollowing();}
      this.rotationTick();this.replacementTick();this.capture.tick();this.updateHealth?.();this.updatePlayerCount();
    }
    saveUsage(){
      const values=[...this.players.values()].filter(p=>p.watched).map(p=>({id:p.identity,ms:p.watched,session:!p.sessionSaved}));if(!values.length||this.data.private)return;if(root.LiveCamAnalytics?.paused(root.LiveCamAnalytics.recorder?.data)){for(const p of this.players.values())p.watched=0;return;}
      for(const value of values){root.LiveCamAnalytics?.recorder?.watch(value.id,value.ms).catch(()=>{});if(value.session)root.LiveCamAnalytics?.recorder?.event('visit',value.id).catch(()=>{});}for(const p of this.players.values()){p.watched=0;p.sessionSaved=true;}
      this.change(data=>{for(const value of values){const m=data.models[value.id]||{};m.watchMs=(m.watchMs||0)+value.ms;m.lastVisit=Date.now();m.firstVisit=m.firstVisit||Date.now();m.sessions=(m.sessions||0)+(value.session?1:0);data.models[value.id]=m;}}).catch(()=>{});
    }
    recordStates(){
      const now=Date.now(),latest=new Map(),changes=[];
      for(const item of this.history)if(!latest.has(item.identity))latest.set(item.identity,item.state);
      for(const model of this.models()){
        const identity=D.key(model),state=D.stateOf(model);if(state==='unknown')continue;
        if(latest.get(identity)!==state){changes.push({identity,state,at:now});latest.set(identity,state);}
      }
      this.history=changes.reverse().concat(this.history).slice(0,2000);
      if(!this.data.private)this.store.put('cache',this.history,'status-history').catch(error=>this.error(error));
    }
    dialog(title){
      const dialog=el('dialog',{class:'lc-dialog','aria-label':title,'data-theme':this.data.theme}),body=el('div',{class:'lc-dialog-body'});
      dialog.append(el('header',{},el('h3',{text:title}),button('Schließen',()=>dialog.close())),body);
      dialog.addEventListener('close',()=>{this.dialogs.delete(dialog);dialog.remove();this.flushDrafts();if(dialog.onCleanup)dialog.onCleanup();},{once:true});
      dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}});
      document.body.append(dialog);this.dialogs.add(dialog);dialog.showModal();return {dialog,body};
    }
    section(title,...children){const details=el('details',{open:true},el('summary',{text:title}),el('div',{class:'lc-fields'},...children));return details;}
    filterPanel(which){
      const sidebar=which==='sidebar',f=this.config()[sidebar?'sidebarFilters':'playbackFilters'],{body}=this.dialog(sidebar?'Filter der Modellliste':'Filter des Wiedergabebestands');
      const set=(name,value)=>this.filterChange(which,name,value);
      const countries=[...new Set(this.models().map(m=>m.country).filter(Boolean))].sort();
      body.append(el('p',{class:'lc-muted',text:sidebar?'Diese Filter ändern nur die linke Liste. Laufende Kameras bleiben erhalten.':'Diese Filter bestimmen die angezeigten Kameras. Gespeicherte Plätze bleiben erhalten.'}),
        this.section('Suche und Status',input('Name, Notizen oder Tags',f.q,value=>set('q',value)),select('Status',f.status,statusChoices,value=>set('status',value)),select('Sortierung',f.sort,sortChoices,value=>set('sort',value))),
        this.section('Eigenschaften',select('Land',f.country,[['','Alle Länder'],...countries.map(c=>[c,c])],value=>set('country',value)),select('Geschlecht / Typ',f.gender,[['','Alle'],['weiblich','Frauen'],['männlich','Männer'],['paar','Paare'],['trans','Trans']],value=>set('gender',value)),
          input('Mindestalter',f.minAge,value=>set('minAge',value),'number',{min:18,max:99}),input('Höchstalter',f.maxAge,value=>set('maxAge',value),'number',{min:18,max:99}),input('Mindestens Zuschauer',f.minViewers,value=>set('minViewers',value),'number',{min:0}),input('Höchstens Zuschauer',f.maxViewers,value=>set('maxViewers',value),'number',{min:0})),
        this.section('Persönliche Auswahl',select('Persönliche Auswahl',f.personal,[['all','Alle'],['favorites','Favoriten'],['seen','Angesehen'],['never','Nie angesehen'],['notes','Mit Notizen']],value=>set('personal',value)),
          ...[['favorite','Nur Favoriten'],['following','Nur offiziell gefolgt'],['inGrid','Bereits im Arbeitsbereich'],['notes','Mit Notizen'],['favoritesFirst','Favoriten zuerst']].map(([name,label])=>check(label,f[name],value=>set(name,value)))),
        this.section('Tags und Nutzung',input('Tags einschließen',f.include,value=>set('include',value)),select('Tagverknüpfung',f.tagMode,[['any','Mindestens einen'],['all','Alle']],value=>set('tagMode',value)),input('Tags ausschließen',f.exclude,value=>set('exclude',value)),
          select('Angesehen',f.seen,[['all','Alle'],['seen','Angesehen'],['never','Nie angesehen']],value=>set('seen',value)),input('Mindestsehzeit in Minuten',f.minutes,value=>set('minutes',value),'number',{min:0}),input('Mindestsitzungen',f.sessions,value=>set('sessions',value),'number',{min:0}),input('In den letzten N Tagen angesehen',f.days,value=>set('days',value),'number',{min:0})),
        button('Filter zurücksetzen',()=>this.change(data=>{const c=data.workspaces.find(w=>w.id===this.workspaceId).settings;c[sidebar?'sidebarFilters':'playbackFilters']=D.filters();c[sidebar?'sidebarPage':'page']=0;})));
      const tags=[...new Set(this.models().flatMap(m=>m.tags||[]))].sort().slice(0,80);
      body.append(this.section('Tagvorschläge',...tags.map(tag=>button(tag,()=>{const inputNode=body.querySelector((globalThis.AppI18n?.selector || (s=>s))('input[aria-label="Tags einschließen"]'));inputNode.value=[...new Set([...D.tokens(inputNode.value),tag])].join(' ');set('include',inputNode.value);}))));
    }
    picker(position,identity=null){
      const {dialog,body}=this.dialog(identity?'Model in Platz einsetzen':'Model für Platz '+(position+1)+' wählen');
      if(identity){body.append(el('p',{text:D.room(identity).name,"data-i18n-content":""}),...this.visibleEntries().rows.map((row,index)=>button('Platz '+(index+1)+(row.identity?' · '+D.room(row.identity).name:' · frei'),this.command(async()=>{await this.place(identity,index);dialog.close();}))));return;}
      const search=el('input',{type:'search',placeholder:'Model oder Anbieter suchen','aria-label':'Model für Kameraplatz suchen'}),listNode=el('div',{class:'lc-picker'});
      const paint=()=>{const query=search.value.toLowerCase();const models=this.models().filter(m=>this.config().sites.includes(m.site)&&[m.name,m.site].join(' ').toLowerCase().includes(query));listNode.replaceChildren(...models.slice(0,100).map(m=>button(m.name+' · '+D.SITES.find(s=>s[0]===m.site)[1]+' · '+statusNames[D.stateOf(m)],this.command(async()=>{await this.place(D.key(m),position);dialog.close();}))));};
      search.oninput=paint;body.append(search,listNode,button('Exakten Namen hinzufügen',()=>this.addModelPanel(position)));paint();search.focus();
    }
    addModelPanel(position=null){
      const {dialog,body}=this.dialog('Model hinzufügen');let site=this.config().sites[0]||'stripchat';
      const name=el('input',{placeholder:'Exakter Modelname oder öffentliche Raum-URL','aria-label':'Modelname oder öffentliche Raum-URL'});
      body.append(select('Anbieter',site,D.SITES,value=>{site=value;}),name,button('Model speichern',this.command(async()=>{
        const item=D.parsePublicURL(name.value,site);if(!item)throw Error('Bitte einen gültigen Modelnamen oder einen regulären öffentlichen Raumlink eingeben.');
        const result=await this.ctx.post('/api/cam-library',{op:'model-save',...item});if(!result.ok)throw Error(result.error);
        this.saved.set(D.key(item),{...item,personal:{saved:true,created:Date.now()}});
        await this.change(data=>{data.models[D.key(item)]={...data.models[D.key(item)],saved:true,created:Date.now()};});
        if(position!=null)await this.place(D.key(item),position);dialog.close();
      })));
    }
    workspacePanel(){
      const {dialog,body}=this.dialog('Arbeitsbereiche');const w=this.workspace();
      body.append(input('Neuer Arbeitsbereich','',()=>{}),button('Anlegen',this.command(async()=>{
        const name=body.querySelector('input').value.trim();if(!name)throw Error('Bitte einen Namen eingeben.');let identity;
        await this.change(data=>{if(data.workspaces.length>=60)throw Error('Es sind bereits 60 Arbeitsbereiche gespeichert.');const next=D.workspace(name);identity=next.id;data.workspaces.push(next);data.active=identity;});this.workspaceId=identity;dialog.close();this.render();
      })),button('Arbeitsbereiche importieren',()=>this.importPanel()),button('Alle Arbeitsbereiche exportieren',()=>this.exportState(false)));
      for(const item of this.data.workspaces){
        const row=el('div',{class:'lc-workspace-row'},el('strong',{text:item.name+(item.archived?' · archiviert':'')}),el('small',{text:item.description||'Ohne Beschreibung',"data-i18n-content":""}));
        if(!item.archived)row.append(button('Öffnen',()=>{dialog.close();this.switchWorkspace(item.id);}),button('Eigenes Fenster',()=>this.openWindow(item.id)));
        row.append(button('Bearbeiten',()=>this.editWorkspace(item.id)),button('Duplizieren',this.command(async()=>{await this.change(data=>{if(data.workspaces.length>=60)throw Error('Höchstens 60 Arbeitsbereiche.');const copy=D.clone(data.workspaces.find(x=>x.id===item.id));copy.id=D.id();copy.name+=' Kopie';copy.archived=false;data.workspaces.push(copy);});dialog.close();this.workspacePanel();})),
          button('↑',this.command(async()=>{await this.reorderWorkspace(item.id,-1);dialog.close();this.workspacePanel();})),button('↓',this.command(async()=>{await this.reorderWorkspace(item.id,1);dialog.close();this.workspacePanel();})),button('Exportieren',()=>this.exportWorkspace(item.id)));
        if(item.id!=='default')row.append(button(item.archived?'Wiederherstellen':'Archivieren',this.command(async()=>{await this.change(data=>{data.workspaces.find(x=>x.id===item.id).archived=!item.archived;if(data.active===item.id)data.active='default';});if(this.workspaceId===item.id&&!item.archived)this.workspaceId='default';dialog.close();this.workspacePanel();this.render();})));
        if(item.archived&&item.id!=='default')row.append(button('Dauerhaft löschen',this.command(async()=>{if(!confirm('Archivierten Arbeitsbereich „'+item.name+'“ dauerhaft löschen? Die gespeicherten Models und Medien bleiben erhalten.'))return;await this.change(data=>{data.workspaces=data.workspaces.filter(x=>x.id!==item.id);if(data.active===item.id)data.active='default';});dialog.close();this.workspacePanel();})));
        body.append(row);
      }
    }
    async editWorkspace(identity){
      const w=this.data.workspaces.find(x=>x.id===identity),{dialog,body}=this.dialog('Arbeitsbereich bearbeiten'),name=el('input',{value:w.name,'aria-label':'Arbeitsbereichsname'}),description=el('textarea',{value:w.description,'aria-label':'Beschreibung'});
      body.append(name,description,button('Speichern',this.command(async()=>{await this.change(data=>{const target=data.workspaces.find(x=>x.id===identity);target.name=name.value.trim();target.description=description.value;});dialog.close();})));
    }
    reorderWorkspace(identity,delta){return this.change(data=>{const at=data.workspaces.findIndex(w=>w.id===identity),to=D.clamp(at+delta,0,data.workspaces.length-1);[data.workspaces[at],data.workspaces[to]]=[data.workspaces[to],data.workspaces[at]];});}
    async switchWorkspace(identity){this.saveUsage();this.stopRotation();this.replacement=null;this.flushDrafts();this.workspaceId=identity;await this.change(data=>{data.active=identity;});this.render();}
    openWindow(identity=this.workspaceId){root.open('/?page=cam-multi&workspace='+encodeURIComponent(identity),identity==='default'?'ah-cam-multi':'ah-cam-workspace-'+identity,'popup,width=1440,height=900');}
    exportWorkspace(identity){const w=this.data.workspaces.find(w=>w.id===identity);download(new Blob([JSON.stringify({kind:'ah-livecam-workspaces',schema:1,workspaces:[w]},null,2)],{type:'application/json'}),filename(w.name)+'.multicam.json');}
    exportState(full){
      const value=full?{kind:'ah-livecam-studio',state:this.data}:{kind:'ah-livecam-workspaces',schema:1,workspaces:this.data.workspaces};
      download(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}),'livecam-'+(full?'konfiguration':'arbeitsbereiche')+'.json');
      this.notify('Konfiguration exportiert. Medien und Anbietersitzungen sind nicht enthalten.');
    }
    importPanel(){
      const {dialog,body}=this.dialog('Multicam importieren · Vorschau'),area=el('textarea',{'aria-label':'Multicam-Importdaten',placeholder:'JSON aus einer Multicam-Sicherung einfügen'}),preview=el('div',{class:'lc-import-preview'});let staged=null;
      const file=el('input',{type:'file',accept:'.json,application/json','aria-label':'Multicam-Importdatei',onchange:this.command(async event=>{const chosen=event.target.files[0];if(chosen.size>12_000_000)throw Error('Die Importdatei ist zu groß.');area.value=await chosen.text();})});
      const apply=button('Geprüfte Arbeitsbereiche hinzufügen',this.command(async()=>{
        if(!staged)throw Error('Zuerst die Vorschau prüfen.');
        const previous=D.clone(this.data);
        await this.change(data=>{const incoming=staged.workspaces.filter(w=>!w.archived||w.id!=='default');if(data.workspaces.length+incoming.length>60)throw Error('Der Import würde mehr als 60 Arbeitsbereiche ergeben.');for(const item of incoming){const w=D.clone(item);w.id=D.id();w.name+=' (Import)';data.workspaces.push(w);}if(staged.cameras)for(const [identity,prefs] of Object.entries(staged.cameras))if(!data.cameras[identity])data.cameras[identity]=prefs;});
        this.rememberUndo(previous);dialog.close();this.notify('Import gespeichert. Vorhandene Arbeitsbereiche wurden erhalten.');
      }),{disabled:true});
      body.append(file,area,button('Vorschau prüfen',this.command(()=>{
        let raw;try{raw=JSON.parse(area.value);}catch{throw Error('Die Datei enthält kein gültiges JSON.');}
        if(raw.kind==='ah-livecam-studio')staged=D.recover(raw.state);
        else if(raw.kind==='ah-livecam-workspaces'&&raw.schema===1){const test=D.initial();test.workspaces=[...raw.workspaces.filter(w=>w.id!=='default'),raw.workspaces.find(w=>w.id==='default')||D.workspace('Standard','default')];test.active='default';staged=D.recover(test);}
        else throw Error('Keine unterstützte Multicam-Sicherung.');
        preview.replaceChildren(el('p',{text:staged.workspaces.length+' Arbeitsbereiche · '+staged.workspaces.reduce((n,w)=>n+w.slots.filter(Boolean).length,0)+' belegte Plätze. Es werden neue Kopien hinzugefügt.'}),...staged.workspaces.map(w=>el('p',{text:w.name+' · '+w.settings.capacity+' Plätze'})));apply.disabled=false;
      })),preview,apply);
    }
    scenePanel(){
      const {dialog,body}=this.dialog('Szenen und Layoutvorlagen'),w=this.workspace(),name=el('input',{'aria-label':'Name der Szene oder Vorlage',placeholder:'Name'}),description=el('input',{'aria-label':'Beschreibung der Vorlage',placeholder:'Beschreibung der Vorlage'});
      body.append(name,description,button('Aktuelle Szene speichern',this.command(async()=>{
        const title=name.value.trim();if(!title)throw Error('Bitte einen Szenennamen eingeben.');const existing=w.scenes.find(s=>s.name===title);if(existing&&!confirm('Szene „'+title+'“ mit der aktuellen Belegung ersetzen?'))return;
        const before=D.clone(this.data);await this.change(data=>{const target=data.workspaces.find(x=>x.id===this.workspaceId);if(!existing&&target.scenes.length>=24)throw Error('Höchstens 24 Szenen je Arbeitsbereich.');const scene={id:existing?.id||D.id(),name:title,...D.snapshot({...target,slots:this.currentSlots()})};target.scenes=target.scenes.filter(s=>s.id!==scene.id);target.scenes.push(scene);});this.rememberUndo(before);dialog.close();this.scenePanel();
      })),button('Layoutvorlage speichern',this.command(async()=>{const title=name.value.trim();if(!title)throw Error('Bitte einen Vorlagennamen eingeben.');const before=D.clone(this.data);await this.change(data=>{if(data.templates.length>=40)throw Error('Höchstens 40 Layoutvorlagen.');data.templates.push({id:D.id(),name:title,description:description.value,...D.snapshot(this.workspace(),false)});});this.rememberUndo(before);dialog.close();this.scenePanel();})),button('Letzte Änderung rückgängig',this.command(()=>this.undoLast()),{disabled:!this.undo.length}));
      for(const scene of w.scenes)body.append(el('div',{class:'lc-buttons'},el('strong',{text:scene.name,"data-i18n-content":""}),button('Anwenden',this.command(async()=>{await this.applyScene(scene);dialog.close();})),button('Umbenennen',this.command(async()=>{const title=prompt('Neuer Szenenname',scene.name);if(title)await this.change(data=>{data.workspaces.find(x=>x.id===this.workspaceId).scenes.find(s=>s.id===scene.id).name=title.slice(0,100);});dialog.close();this.scenePanel();})),button('Löschen',this.command(async()=>{const before=D.clone(this.data);await this.change(data=>{const target=data.workspaces.find(x=>x.id===this.workspaceId);target.scenes=target.scenes.filter(s=>s.id!==scene.id);});this.rememberUndo(before);dialog.close();this.scenePanel();}))));
      body.append(el('h4',{text:'Layoutvorlagen · ohne Models, Notizen oder Kontodaten'}));
      for(const template of this.data.templates)body.append(el('div',{class:'lc-buttons'},el('strong',{text:template.name,"data-i18n-content":""}),el('small',{text:template.description,"data-i18n-content":""}),button('Anwenden',this.command(async()=>{await this.applyTemplate(template);dialog.close();})),button('Löschen',this.command(async()=>{const before=D.clone(this.data);await this.change(data=>{data.templates=data.templates.filter(t=>t.id!==template.id);});this.rememberUndo(before);dialog.close();this.scenePanel();}))));
    }
    rememberUndo(previous){
      const patches=[];
      for(const w of this.data.workspaces){
        const before=previous.workspaces.find(x=>x.id===w.id);
        if(!before)patches.push({kind:'workspace-add',id:w.id,before:null,after:D.clone(w)});
        else if(JSON.stringify(before.scenes)!==JSON.stringify(w.scenes))patches.push({kind:'scenes',id:w.id,before:D.clone(before.scenes),after:D.clone(w.scenes)});
      }
      if(JSON.stringify(previous.templates)!==JSON.stringify(this.data.templates))patches.push({kind:'templates',before:D.clone(previous.templates),after:D.clone(this.data.templates)});
      if(patches.length)this.undo.push(patches);if(this.undo.length>20)this.undo.shift();
    }
    undoLast(){
      const patches=this.undo.at(-1);if(!patches)return;
      return this.change(data=>{
        for(const patch of patches){const w=data.workspaces.find(w=>w.id===patch.id);const current=patch.kind==='templates'?data.templates:patch.kind==='scenes'?w?.scenes:w;
          if(JSON.stringify(current)!==JSON.stringify(patch.after))throw Error('Zwischenzeitliche Änderungen bleiben geschützt. Diese ältere Änderung kann nicht mehr vollständig zurückgenommen werden.');}
        for(const patch of patches){if(patch.kind==='templates')data.templates=D.clone(patch.before);else if(patch.kind==='scenes')data.workspaces.find(w=>w.id===patch.id).scenes=D.clone(patch.before);else data.workspaces=data.workspaces.filter(w=>w.id!==patch.id);}
        if(!data.workspaces.some(w=>w.id===data.active))data.active='default';
      }).then(()=>this.undo.pop());
    }
    groupPanel(){
      const {dialog,body}=this.dialog('Gruppen in Multicam'),name=el('input',{'aria-label':'Neue Multicam-Gruppe',placeholder:'Gruppenname'});
      body.append(button('Vollständige Gruppenverwaltung',()=>{dialog.close();this.ctx.openGroups?.();}),name,button('Gruppe anlegen',this.command(async()=>{const result=await this.ctx.post('/api/cam-library',{op:'group-add',name:name.value});if(!result.ok)throw Error(result.error);await this.refreshData(false);dialog.close();this.groupPanel();})),button('Aktuelle Seite als Gruppe',this.command(async()=>{
        const title=name.value.trim();if(!title)throw Error('Bitte einen Gruppennamen eingeben.');const result=await this.ctx.post('/api/cam-library',{op:'group-add',name:title});if(!result.ok)throw Error(result.error);
        for(const entry of this.visibleEntries().rows)if(entry.identity){await this.ctx.post('/api/cam-library',{op:'model-save',...D.room(entry.identity)});await this.ctx.post('/api/cam-library',{op:'group-item',id:result.id,...D.room(entry.identity),on:true});}await this.refreshData(false);dialog.close();this.groupPanel();
      })));
      for(const group of this.groups.filter(g=>!g.systemRole))body.append(el('div',{class:'lc-buttons'},el('strong',{text:group.name+' · '+(group.items||[]).length}),button('Umbenennen',this.command(async()=>{const title=prompt('Gruppenname',group.name);if(title){const result=await this.ctx.post('/api/cam-library',{op:'group-rename',id:group.id,name:title});if(!result.ok)throw Error(result.error);await this.refreshData(false);dialog.close();this.groupPanel();}})),button('↑',this.command(async()=>{await this.reorderGroup(group.id,-1);dialog.close();this.groupPanel();})),button('↓',this.command(async()=>{await this.reorderGroup(group.id,1);dialog.close();this.groupPanel();})),button('Löschen',this.command(async()=>{if(!confirm('Gruppe „'+group.name+'“ löschen? Models und Medien bleiben erhalten.'))return;const result=await this.ctx.post('/api/cam-library',{op:'group-delete',id:group.id});if(!result.ok)throw Error(result.error);await this.refreshData(false);dialog.close();this.groupPanel();}))));
    }
    async reorderGroup(identity,delta){const groups=this.groups.filter(g=>!g.systemRole),at=groups.findIndex(g=>g.id===identity),to=D.clamp(at+delta,0,groups.length-1),order=groups.map(g=>g.id);[order[at],order[to]]=[order[to],order[at]];const result=await this.ctx.post('/api/cam-library',{op:'group-order',items:order});if(!result.ok)throw Error(result.error);await this.refreshData(false);}
    modelPanel(identity){
      const model=this.model(identity),meta=model.personal||{},{dialog,body}=this.dialog('Model · '+model.name);
      const values=[['Benutzername',model.name],['Anbieter',D.SITES.find(s=>s[0]===model.site)[1]],['Anzeigename',model.displayName],['Raumstatus',statusNames[D.stateOf(model)]],['Thema',model.subject],['Land',model.country],['Ort',model.place],['Geschlecht',model.gender],['Alter',model.age],['Sprachen',(model.languages||[]).join(', ')],['Zuschauer',model.viewers],['Follower',model.followers],['Onlinedauer',model.seconds!=null?duration(model.seconds*1000):null],['Merkmale',[model.hd?'HD':'',...(model.badges||[])].filter(Boolean).join(', ')],['Tags',(model.tags||[]).join(', ')],['Gruppen',this.groups.filter(g=>(g.items||[]).includes(identity)).map(g=>g.name).join(', ')],['Favorit',model.fav?'Ja':'Nein'],['Offiziell gefolgt',model.accountFav?'Im gespeicherten Following-Bestand':'Nicht bestätigt'],['Gespeichert seit',meta.created?new Date(meta.created).toLocaleString():null],['Erster Besuch',meta.firstVisit?new Date(meta.firstVisit).toLocaleString():null],['Letzter Besuch',meta.lastVisit?new Date(meta.lastVisit).toLocaleString():null],['Sehzeit',meta.watchMs!=null?duration(meta.watchMs):null],['Sitzungen',meta.sessions],['Zuletzt online',meta.lastOnline?new Date(meta.lastOnline).toLocaleString():null],['Archiviert',meta.archived?'Ja':'Nein'],['Ausgeblendet bis',meta.hiddenUntil?new Date(meta.hiddenUntil).toLocaleString():null],['Pausiert bis',meta.pauseUntil?new Date(meta.pauseUntil).toLocaleString():null]];
      const table=el('dl',{class:'lc-info'});for(const [label,value] of values)table.append(el('dt',{text:label}),el('dd',{text:value==null||value===''?'Unbekannt':value}));
      const notes=el('textarea',{value:meta.notes||'','aria-label':'Modelnotizen'}),tags=el('input',{value:(meta.tags||[]).join(' '),'aria-label':'Persönliche Tags'}),rating=el('input',{type:'number',min:0,max:5,value:meta.rating||0,'aria-label':'Bewertung'}),priority=el('input',{type:'number',min:0,max:10,value:meta.priority||0,'aria-label':'Priorität'});
      body.append(table,this.section('Persönliche Daten',el('label',{},'Notizen',notes),el('label',{},'Eigene Tags',tags),el('label',{},'Bewertung 0–5',rating),el('label',{},'Priorität 0–10',priority),button('Persönliche Daten speichern',this.command(async()=>{const values={notes:notes.value,tags:D.tokens(tags.value),rating:D.clamp(rating.value,0,5),priority:D.clamp(priority.value,0,10),saved:true,created:meta.created||Date.now()};await this.ctx.post('/api/cam-library',{op:'model-save',...D.room(identity),...values});await this.change(data=>{data.models[identity]={...data.models[identity],...values};});this.notify('Modeldaten gespeichert.');}))),
        button(model.fav?'Favorit entfernen':'Als Favorit merken',this.command(async()=>{await this.ctx.post('/api/cam-library',{op:'fav',...D.room(identity),on:!model.fav});if(model.fav)this.favorites.delete(identity);else this.favorites.add(identity);this.renderSidebar();})),
        button('Gruppenmitgliedschaften',()=>this.membershipPanel(identity)),button('In Kameraplatz einsetzen',()=>this.chooseModel(identity)),button('Einzelansicht',()=>this.ctx.openSingle(model)),button('Offizielles Profil öffnen',()=>root.open(D.publicURL(identity),'_blank','noopener')),button('Benutzername kopieren',this.command(()=>navigator.clipboard.writeText(model.name))),button('Modelmedien',()=>this.galleryPanel(identity)),
        button('Nur in Favoriten verschieben',this.command(async()=>{await this.ctx.post('/api/cam-library',{op:'fav',...D.room(identity),on:true});for(const g of this.groups.filter(g=>(g.items||[]).includes(identity)))await this.ctx.post('/api/cam-library',{op:'group-item',id:g.id,...D.room(identity),on:false});this.favorites.add(identity);await this.refreshData(false);dialog.close();})),
        button('Gespeichertes Model dauerhaft löschen',this.command(async()=>{if(!confirm('„'+model.name+'“ aus gespeicherten Models, Gruppen und Multicam-Belegungen entfernen? Eigene Medien bleiben erhalten.'))return;await this.ctx.post('/api/cam-library',{op:'model-delete',...D.room(identity)});await this.change(data=>{delete data.models[identity];delete data.cameras[identity];for(const w of data.workspaces)w.slots=w.slots.map(k=>k===identity?null:k);});this.saved.delete(identity);this.favorites.delete(identity);dialog.close();this.render();})));
    }
    membershipPanel(identity){
      const {body}=this.dialog('Gruppen · '+D.room(identity).name);
      for(const group of this.groups.filter(g=>!g.systemRole&&g.kind!=='smart'&&!g.archived))body.append(check(group.name,(group.items||[]).includes(identity),this.command(async on=>{await this.ctx.post('/api/cam-library',{op:'model-save',...D.room(identity)});await this.ctx.post('/api/cam-library',{op:'group-item',id:group.id,...D.room(identity),on});if(on)group.items=[...new Set([...(group.items||[]),identity])];else group.items=group.items.filter(k=>k!==identity);this.renderSidebar();})));
      if(!this.groups.length)body.append(el('p',{text:'Noch keine eigenen Gruppen.'}));body.append(button('Gruppen verwalten',()=>this.groupPanel()));
    }
    cameraPanel(identity){
      const player=this.players.get(identity),prefs=this.prefs(identity),model=this.model(identity),{dialog,body}=this.dialog('Kameramenü · '+model.name);
      const set=(name,value)=>this.cameraSetting(identity,name,value);
      const levels=player?.hls?.levels||[],heights=[...new Set(levels.map(l=>l.height).filter(Boolean))].sort((a,b)=>a-b);
      body.append(this.section('Modelinformationen',el('p',{text:D.SITES.find(s=>s[0]===model.site)[1]+' · '+statusNames[D.stateOf(model)]+' · '+(model.subject||'Thema unbekannt')}),button('Alle Modelinformationen und Notizen',()=>this.modelPanel(identity))),
        this.section('Ansicht und Wiedergabe',button('Model auf diesem Platz ersetzen',()=>this.picker(this.currentPosition(identity))),button('Fokus / Raster',()=>this.focus(identity)),button('Einzelansicht',()=>this.ctx.openSingle(model)),button('Vorschau anheften',()=>this.previewStart(identity,player?.cell||body,true)),
          button('Vollbild',this.command(async()=>{if(!player?.cell.requestFullscreen)throw Error('Vollbild ist hier nicht verfügbar.');await player.cell.requestFullscreen();})),
          button('Bild-in-Bild',this.command(async()=>{if(!player?.video.requestPictureInPicture||!document.pictureInPictureEnabled||player.video.readyState<2)throw Error('Bild-in-Bild benötigt ein geladenes, unterstütztes Video.');await player.video.requestPictureInPicture();}),{disabled:!player?.video.requestPictureInPicture||!document.pictureInPictureEnabled,title:'Benötigt ein geladenes Video und Browserunterstützung'}),
          button(prefs.paused?'Fortsetzen':'Pausieren',()=>this.pause(identity)),button('Neu verbinden',()=>this.reconnect(identity)),button('Aus Platz entfernen',()=>{this.removeRoom(identity);dialog.close();}),
          button('Screenshot · Original-PNG',this.command(()=>this.capture.screenshot(identity)),{disabled:!player||this.data.private}),button(this.capture.jobs.has(identity)?'Aufnahme stoppen und speichern':'Aufnahme starten …',this.command(async()=>{if(this.capture.jobs.has(identity))await this.capture.stop(identity);else if(confirm('Öffentlichen Stream „'+model.name+'“ aufnehmen und in der lokalen Modelgalerie speichern?'))await this.capture.start(identity);}),{disabled:!root.MediaRecorder||!player?.video.captureStream||this.data.private})),
        this.section('Audio',check('Ton eingeschaltet',!prefs.muted,on=>{this.unlockAudio();set('muted',!on);}),slider('Kameralautstärke',prefs.volume,0,100,1,value=>{this.unlockAudio();set('volume',value);}),button('Lautstärke auf 100 %',()=>set('volume',100)),
          button('Als Solo-Model festlegen',()=>{this.unlockAudio();this.change(data=>{const c=data.workspaces.find(w=>w.id===this.workspaceId).settings;c.audio='solo';c.solo=identity;c.muteAll=false;});}),select('Audiopegel',prefs.meter,[['global','Globale Vorgabe'],['on','Gemessen anzeigen'],['off','Ausblenden']],value=>{this.unlockAudio();set('meter',value);}),el('p',{class:'lc-muted',text:'Pegel werden nur bei zugänglicher Audioanalyse gemessen. Eine Ausgabelautstärke ist kein Messwert.'})),
        this.section('Qualität und Bildausschnitt',select('Kameraqualität',prefs.quality,[['global','Globale Vorgabe'],['auto','Automatisch'],...D.HEIGHTS.map(h=>[h,h+'p als Obergrenze'])],value=>set('quality',value)),el('p',{class:'lc-muted',text:'Angebotene Stufen: '+(heights.length?heights.map(h=>h+'p').join(', '):'Noch unbekannt')+'. Die globale Obergrenze gilt zusätzlich.'}),
          slider('Zoom %',prefs.zoom,100,2000,5,value=>set('zoom',value)),slider('Horizontaler Ausschnitt px',prefs.x,-5000,5000,10,value=>set('x',value)),slider('Vertikaler Ausschnitt px',prefs.y,-5000,5000,10,value=>set('y',value)),button('Zoom und Ausschnitt zurücksetzen',()=>this.resetTransform(identity))),
        this.section('Bildfilter',...[
          ['brightness','Helligkeit %',25,250,1],['contrast','Kontrast %',25,250,1],['saturation','Sättigung %',0,300,1],['hue','Farbton °',-180,180,1],['sepia','Sepia %',0,100,1],['grayscale','Graustufen %',0,100,1],['invert','Invertieren %',0,100,1],['blur','Unschärfe',0,12,.1]
        ].map(([name,label,min,max,step])=>slider(label,prefs[name],min,max,step,value=>set(name,value))),check('Horizontal spiegeln',prefs.flipX,value=>set('flipX',value)),check('Vertikal spiegeln',prefs.flipY,value=>set('flipY',value)),select('Drehen',prefs.rotate,[[0,'0°'],[90,'90°'],[180,'180°'],[270,'270°']],value=>set('rotate',Number(value))),
          ...['Original','Kino','Lebendig','Monochrom'].map(name=>button(name,()=>this.imagePreset(identity,name))),button('Bild zurücksetzen',()=>{for(const [name,value] of Object.entries(D.camera()))if(!['muted','volume','quality','paused','meter'].includes(name))set(name,value);})),
        this.section('Organisieren',button(model.fav?'Favorit entfernen':'Als Favorit merken',this.command(async()=>{await this.ctx.post('/api/cam-library',{op:'fav',...D.room(identity),on:!this.favorites.has(identity)});if(this.favorites.has(identity))this.favorites.delete(identity);else this.favorites.add(identity);this.renderSidebar();})),button('Gruppenmitgliedschaften',()=>this.membershipPanel(identity)),button('Notizen und persönliche Daten',()=>this.modelPanel(identity)),button('Benutzername kopieren',this.command(()=>navigator.clipboard.writeText(model.name))),button('Offiziellen Raum öffnen',()=>root.open(D.publicURL(identity),'_blank','noopener'))));
      const original=button('Original gedrückt halten',()=>{});original.addEventListener('pointerdown',()=>{if(player){player.video.style.filter='none';player.video.style.transform='none';}});const restore=()=>this.applyPlayer(player);original.addEventListener('pointerup',restore);original.addEventListener('pointerleave',restore);original.addEventListener('keydown',event=>{if(event.key===' '&&player){event.preventDefault();player.video.style.filter='none';player.video.style.transform='none';}});original.addEventListener('keyup',restore);body.append(original);
    }
    imagePreset(identity,name){const base=D.camera(),values={brightness:base.brightness,contrast:base.contrast,saturation:base.saturation,hue:0,sepia:0,grayscale:0,invert:0,blur:0};if(name==='Kino')Object.assign(values,{brightness:95,contrast:115,saturation:90});if(name==='Lebendig')Object.assign(values,{contrast:110,saturation:135});if(name==='Monochrom')values.grayscale=100;for(const [field,value] of Object.entries(values))this.cameraSetting(identity,field,value);}
    layoutPanel(){
      const c=this.config(),{body}=this.dialog('Layout und Werkzeuge'),set=(name,value)=>this.setting(name,value);
      body.append(this.section('Raster und Fokus',select('Darstellung',c.layout,[['mosaic','Mosaik · ohne zusätzliche Seitenbalken'],['grid','Raster · gleiche Plätze'],['focus','Fokus'],['custom','Eigenes Raster']],value=>set('layout',value)),
        select('Seitenverhältnis',c.aspect,[['auto','Automatisch je Video'],['16:9','16:9'],['4:3','4:3'],['21:9','21:9'],['1:1','1:1'],['9:16','9:16']],value=>set('aspect',value)),select('Bildanpassung im festen Raster',c.fit,[['contain','Ganzes Bild'],['cover','Fläche ausfüllen / beschneiden']],value=>set('fit',value)),
        slider('Rastergrößenpräferenz px',c.tileSize,220,900,10,value=>set('tileSize',value)),slider('Fokusbreite %',c.focusWidth,45,94,1,value=>set('focusWidth',value)),slider('Fokushöhe %',c.focusHeight,40,90,1,value=>set('focusHeight',value)),slider('Miniaturengröße px',c.thumbSize,80,320,10,value=>set('thumbSize',value)),check('Fokusminiaturen',c.thumbnails,value=>set('thumbnails',value)),
        button('Eigenes Raster',()=>this.customGridPanel()),button('Vorheriger Fokus',()=>this.nextFocus(-1)),button('Nächster Fokus',()=>this.nextFocus(1)),button('Fokusmanager',()=>this.focusPanel())),
        this.section('Oberfläche und Listen',select('Modus',c.mode,[['normal','Normal'],['viewer','Zuschauermodus'],['pure','Clean / Pure']],value=>set('mode',value)),check('Werkzeugleiste',c.toolbar,value=>set('toolbar',value)),check('Modellleiste',c.sidebar,value=>set('sidebar',value)),slider('Breite der Modellleiste px',c.sidebarWidth,180,460,10,value=>set('sidebarWidth',value)),select('Listenhöhe px',c.listHeight,[200,320,480,640,800,1000],value=>set('listHeight',Number(value))),select('Listenzeilen',c.density,[['compact','Kompakt'],['comfortable','Komfortabel']],value=>set('density',value))),
        this.section('Audio und Leistung',slider('Gesamtlautstärke %',c.volume,0,100,1,value=>{this.unlockAudio();set('volume',value);}),select('Audioverteilung',c.audio,[['manual','Manuell'],['solo','Nur Solo-Model'],['followFocus','Fokus']],value=>set('audio',value)),select('Solo-Model',c.solo||'',[['','Keines'],...this.visibleEntries().rows.filter(e=>e.identity).map(e=>[e.identity,e.model.name])],value=>set('solo',value||null)),
          select('Gemessene Pegel',c.meterMode,[['individual','Individuell'],['all','Alle zeigen'],['none','Alle ausblenden']],value=>{this.unlockAudio();set('meterMode',value);}),check('Pegel für neue Kameras',c.meterDefault,value=>{this.unlockAudio();set('meterDefault',value);}),check('Freies Zoomen mit Strg/Cmd + Mausrad',c.freeZoom,value=>set('freeZoom',value)),select('Aktive Player',c.activeLimit,[[4,'Höchstens vier'],[20,'Alle sichtbaren Plätze']],value=>set('activeLimit',Number(value))),
          button('Alle sichtbaren pausieren',()=>this.pauseAll(true)),button('Alle sichtbaren fortsetzen',()=>this.pauseAll(false)),button(c.muteAll?'Audiostand wiederherstellen':'Alle stumm',()=>set('muteAll',!c.muteAll))),
        this.section('Weitere Werkzeuge',button('Szenen und Vorlagen',()=>this.scenePanel()),button('Rotation und Ersatz',()=>this.rotationPanel()),button('Aufnahmezentrale',()=>this.capturePanel()),button('Erweiterte Rasterfilter',()=>this.filterPanel('playback')),button('Modellaktionen',()=>this.groupPanel()),button('Temporäre Raum-URLs',()=>this.urlPanel()),button('Tastenkombinationen',()=>this.shortcutPanel())));
    }
    customGridPanel(){
      const c=this.config(),{dialog,body}=this.dialog('Eigenes Raster');let rows=c.rows,cols=c.cols;
      const info=el('p',{text:rows+' × '+cols+' = '+rows*cols+' Plätze'}),update=()=>{info.textContent=rows+' × '+cols+' = '+rows*cols+' Plätze'+(rows*cols>20?' · maximal 20 erlaubt':'');};
      body.append(select('Zeilen',rows,[1,2,3,4,5],value=>{rows=Number(value);update();}),select('Spalten',cols,[1,2,3,4,5],value=>{cols=Number(value);update();}),info,button('Raster anwenden',this.command(async()=>{if(rows*cols>20)throw Error('Das eigene Raster darf höchstens 20 Plätze haben.');await this.change(data=>{const c=data.workspaces.find(w=>w.id===this.workspaceId).settings;Object.assign(c,{rows,cols,capacity:rows*cols,layout:'custom'});});dialog.close();})));
    }
    focusPanel(){const {body}=this.dialog('Fokusmanager');for(const entry of this.visibleEntries().rows)if(entry.identity)body.append(button(entry.model.name+' · '+entry.model.site,()=>{this.setting('focus',entry.identity);this.setting('layout','focus');}));body.append(button('Vorheriger Fokus',()=>this.nextFocus(-1)),button('Nächster Fokus',()=>this.nextFocus(1)),button('Zur Rasteransicht',()=>this.setting('layout','grid')));}
    pauseAll(paused){return this.change(data=>{for(const identity of this.players.keys())data.cameras[identity]={...D.camera(),...data.cameras[identity],paused};});}
    async fillWindow(){
      if(document.fullscreenElement){await document.exitFullscreen();return;}
      if(this.root.requestFullscreen)try{await this.root.requestFullscreen();this.scheduleLayout();}catch(error){this.error(error);}else this.notify('Vollbild ist in diesem Browser nicht verfügbar.',true);
    }
    controlPanel(){
      const c=this.config(),{dialog,body}=this.dialog('Multicam-Kontrollzentrum'),table=el('div',{class:'lc-health'});
      const update=()=>{table.replaceChildren(...[...this.players.values()].map(p=>{
        let buffered=null;for(let i=0;i<p.video.buffered.length;i++)if(p.video.currentTime>=p.video.buffered.start(i)&&p.video.currentTime<=p.video.buffered.end(i))buffered=p.video.buffered.end(i)-p.video.currentTime;
        const values=[p.room.name,p.room.site,statusNames[p.phase]||p.phase,'Puffer: '+(buffered==null?'unbekannt':buffered.toFixed(1)+' s'),'Präsentierte Frames: '+(p.presented??(p.frames||'unbekannt')),'Dekodiert: '+(p.decoded??'unbekannt'),'Verworfen: '+(p.dropped??'unbekannt'),'Startzeit: '+(p.firstFrame==null?'unbekannt':Math.round(p.firstFrame)+' ms'),'Unterbrechungen: '+p.stalls,'Unterbrechungszeit: '+duration(p.stallMs),'Neuverbindungen: '+p.reconnects,'Quelle: '+(p.video.videoWidth?p.video.videoWidth+' × '+p.video.videoHeight:'unbekannt')];
        return el('section',{},el('strong',{text:values.shift()}),...values.map(value=>el('div',{text:value})),button('Neu verbinden',()=>this.reconnect(p.identity)));
      }));};
      this.updateHealth=update;dialog.onCleanup=()=>{if(this.updateHealth===update)this.updateHealth=null;};
      body.append(this.section('Qualitätsbudget und Leistung',select('Leistungsprofil',c.performance,[['economy','Sparsam · höchstens 4 / 480p'],['balanced','Ausgewogen · bis 8'],['performance','Leistung · bis 16'],['custom','Benutzerdefiniert · bis 20']],value=>this.change(data=>{const c=data.workspaces.find(w=>w.id===this.workspaceId).settings;c.performance=value;c.activeLimit={economy:4,balanced:8,performance:16,custom:20}[value];})),
        slider('Summiertes Auflösungsziel',c.qualityBudget,0,21600,120,value=>this.setting('qualityBudget',value)),check('Fokusqualität bevorzugen',c.prioritizeFocus,value=>this.setting('prioritizeFocus',value)),check('Adaptive Qualität',c.adaptive,value=>this.setting('adaptive',value)),el('p',{class:'lc-muted',text:'Das Auflösungsziel ist eine Summe von Zielhöhen, keine gemessene Bandbreite oder CPU-Auslastung. Fehlende Messwerte bleiben unbekannt.'}),button('Layout und Audio einstellen',()=>this.layoutPanel())),table);update();
    }
    morePanel(){
      const {body}=this.dialog('Multicam · Mehr'),c=this.config();
      body.append(this.section('Oberfläche',button('Layout und Werkzeuge',()=>this.layoutPanel()),button('Fokusmanager',()=>this.focusPanel()),button('Kontrollzentrum',()=>this.controlPanel()),button('Aufnahmezentrale',()=>this.capturePanel()),button('Mediengalerie',()=>this.galleryPanel()),
        button('Modellleiste umschalten',()=>this.setting('sidebar',!this.config().sidebar)),button('Werkzeugleiste umschalten',()=>this.setting('toolbar',!this.config().toolbar)),select('Ansichtsmodus',c.mode,[['normal','Normal'],['viewer','Zuschauer'],['pure','Clean / Pure']],value=>this.setting('mode',value)),el('p',{class:'lc-muted',text:'Tip-Sounds: aus. Multicam spielt keine zusätzlichen Hinweistöne ab.'})),
        this.section('Wiedergabe',button('Alle pausieren',()=>this.pauseAll(true)),button('Alle fortsetzen',()=>this.pauseAll(false)),button('Stumm / Audiostand wiederherstellen',()=>this.setting('muteAll',!this.config().muteAll)),button('Alle neu verbinden',()=>this.reconnectAll()),button('Aktuelle Räume öffnen …',()=>this.openRoomsPanel()),button('Aktuelle Seite als Gruppe',()=>this.groupPanel()),button('Rotation, Ersatz und Gruppenregeln',()=>this.rotationPanel())),
        this.section('Fenster und Verknüpfungen',button('Eigenes Arbeitsbereichsfenster',()=>this.openWindow()),button('Fenster ausfüllen',()=>this.fillWindow()),button('Multicam-Statistik',()=>this.statisticsPanel()),button('Live-Cam-Einstellungen',()=>this.settingsPanel()),button('Following manuell synchronisieren',this.command(()=>this.refreshFollowing())),check('Following alle 10 Minuten aktualisieren',c.autoFollowing,value=>this.setting('autoFollowing',value)),button('Verfügbare Zusatzwerkzeuge',()=>this.capabilityPanel())),
        this.section('Daten',button('Arbeitsbereich exportieren',()=>this.exportWorkspace(this.workspaceId)),button('Alle Arbeitsbereiche exportieren',()=>this.exportState(false)),button('Multicam-Konfiguration sichern',()=>this.exportState(true)),button('Import / Wiederherstellung mit Vorschau',()=>this.importPanel()),button('Datenprüfung und Reparaturvorschau',()=>this.repairPanel()),button('Modelnamen importieren',()=>this.namesPanel()),button('Aktuelle Benutzernamen kopieren',this.command(()=>navigator.clipboard.writeText(this.visibleEntries().rows.filter(e=>e.identity).map(e=>e.model.site+':'+e.model.name).join('\n')))),button('Aktuelle Benutzernamen als TXT',()=>download(new Blob([this.visibleEntries().rows.filter(e=>e.identity).map(e=>e.model.site+':'+e.model.name).join('\n')],{type:'text/plain;charset=utf-8'}),'multicam-models.txt')),button('Statusverlauf',()=>this.historyPanel()),button('Temporäre öffentliche Raumlinks',()=>this.urlPanel()),button('Ansicht als öffentlichen Link teilen',this.command(()=>this.sharePanel()))),
        this.section('Sprache und Hilfe',button('Tastenkombinationen',()=>this.shortcutPanel()),button('Multicam-Hilfe',()=>this.helpPanel()),el('p',{class:'lc-muted',text:'Oberflächensprache: Deutsch.'})));
    }
    settingsPanel(){
      const {body}=this.dialog('Live-Cam · Multicam-Einstellungen');
      body.append(button('Wiedergabe, Bild, Ton und Listen',()=>this.layoutPanel()),button('Leistung und Messwerte',()=>this.controlPanel()),button('Rotation und automatische Ersatzregeln',()=>this.rotationPanel()),button('Aufnahme und Galerie',()=>this.capturePanel()),button('Arbeitsbereiche und Sicherungen',()=>this.workspacePanel()),button('Tastatur',()=>this.shortcutPanel()),
        select('Multicam-Farbschema',this.data.theme,[['inherit','Vorhandenes Design'],['dark','Dunkel'],['light','Hell']],value=>this.change(data=>{data.theme=value;})),
        check('Private Multicam-Sitzung · keine Aufnahmen / Nutzungsaufzeichnung',this.data.private,value=>{if(value)this.capture.stopAll();this.change(data=>{data.private=value;data.privateUntil=0;});}));
    }
    capabilityPanel(){
      const {body}=this.dialog('Verfügbare Zusatzwerkzeuge');
      for(const [label,available] of [['Bild-in-Bild',!!document.pictureInPictureEnabled],['Vollbild',!!this.root.requestFullscreen],['Videoaufnahme',!!root.MediaRecorder&&!!document.createElement('video').captureStream],['Audioanalyse',!!(root.AudioContext||root.webkitAudioContext)],['Lokale Galerie',!!this.store.db]])body.append(el('p',{text:label+': '+(available?'verfügbar':'in diesem Browser nicht verfügbar')}));
      body.append(button('Aufnahmezentrale',()=>this.capturePanel()),button('Galerie',()=>this.galleryPanel()),button('Pegel und Audiowerkzeuge',()=>this.layoutPanel()));
    }
    openRoomsPanel(){const {body}=this.dialog('Räume der aktuellen Seite öffnen');for(const e of this.visibleEntries().rows)if(e.identity)body.append(button(e.model.name+' · '+e.model.site,()=>this.ctx.openSingle(e.model)),el('a',{href:D.publicURL(e.identity),target:'_blank',rel:'noopener',text:'Offizieller Raum'}));}
    async sharePanel(){
      const share=D.share(this.workspace(),this.visibleEntries().rows.map(e=>e.identity)),url=new URL(location.origin+'/?page=cam-multi');url.hash='view='+encodeURIComponent(JSON.stringify(share));
      const {body}=this.dialog('Öffentliche Multicam-Ansicht teilen');body.append(el('p',{text:'Der Link enthält nur öffentliche Raumnamen, Anbieter und Layout. Notizen, Konten und Medienadressen werden nicht geteilt.'}),el('textarea',{value:url.href,readOnly:true,'aria-label':'Öffentlicher Multicam-Link'}),button('Link kopieren',this.command(()=>navigator.clipboard.writeText(url.href))));
    }
    async sharedView(){
      const params=new URLSearchParams(location.hash.slice(1)),value=params.get('view');if(!value||this.sharedApplied)return;this.sharedApplied=true;
      let parsed;try{parsed=JSON.parse(value);}catch{this.notify('Der geteilte Link ist unlesbar.',true);return;}
      if(parsed.version!==1||!Array.isArray(parsed.rooms)||parsed.rooms.length>20||parsed.rooms.some(r=>!D.key(r))){this.notify('Der geteilte Link enthält ungültige öffentliche Räume.',true);return;}
      const {dialog,body}=this.dialog('Geteilte öffentliche Ansicht');body.append(el('p',{text:parsed.rooms.length+' öffentliche Räume als neuen Arbeitsbereich hinzufügen?'}),...parsed.rooms.map(r=>el('p',{text:r.site+': '+r.name})),button('Als neuen Arbeitsbereich öffnen',this.command(async()=>{let identity;await this.change(data=>{if(data.workspaces.length>=60)throw Error('Höchstens 60 Arbeitsbereiche.');const w=D.workspace('Geteilte Ansicht');identity=w.id;w.slots=parsed.rooms.map(D.key);while(w.slots.length<20)w.slots.push(null);w.settings.capacity=D.clamp(parsed.capacity,1,20,4);w.settings.layout=['mosaic','grid','focus','custom'].includes(parsed.layout)?parsed.layout:'mosaic';w.settings.aspect=['auto','16:9','4:3','21:9','1:1','9:16'].includes(parsed.aspect)?parsed.aspect:'auto';data.workspaces.push(w);data.active=w.id;});this.workspaceId=identity;dialog.close();this.render();})));
    }
    repairPanel(){
      const {body}=this.dialog('Multicam-Datenprüfung'),current=D.clone(this.data);let message;
      try{D.validate(current);message='Die aktuelle Konfiguration ist gültig. '+current.workspaces.length+' Arbeitsbereiche, '+Object.keys(current.cameras).length+' persönliche Kameraeinstellungen.';}catch(error){message=error.message;}
      const duplicates=[];for(const w of current.workspaces){const seen=new Set();w.slots.forEach((value,index)=>{if(value&&seen.has(value))duplicates.push(w.name+': Platz '+(index+1));if(value)seen.add(value);});}
      body.append(el('p',{text:message}),el('p',{text:duplicates.length?'Doppelte Plätze: '+duplicates.join(', '):'Keine doppelten Platzbelegungen gefunden.'}),button('Unveränderte Konfiguration sichern',()=>this.exportState(true)),button('Importierte Sicherung prüfen',()=>this.importPanel()));
    }
    namesPanel(){
      const {dialog,body}=this.dialog('Modelnamen importieren');let site=this.config().sites[0]||'stripchat';const area=el('textarea',{'aria-label':'Modelnamen importieren',placeholder:'stripchat:Name\nchaturbate:Name\noder öffentliche Raum-URLs'}),preview=el('div');let names=[];
      const apply=button('Geprüfte Models speichern',this.command(async()=>{for(const identity of names){await this.ctx.post('/api/cam-library',{op:'model-save',...D.room(identity)});this.saved.set(identity,{...D.room(identity),personal:{saved:true}});}await this.change(data=>{for(const identity of names)data.models[identity]={...data.models[identity],saved:true,created:Date.now()};});dialog.close();this.render();}),{disabled:true});
      body.append(select('Anbieter für Namen ohne Präfix',site,D.SITES,value=>{site=value;}),area,button('Vorschau',this.command(()=>{names=this.parseNames(area.value,site);if(!names.length)throw Error('Keine gültigen Modelnamen gefunden.');preview.textContent=names.length+' Models: '+names.join(', ');apply.disabled=false;})),preview,apply);
    }
    parseNames(value,site){const names=[];for(const raw of text(value).split(/[\s,;]+/).filter(Boolean)){const item=D.room(raw)||D.parsePublicURL(raw,site);if(!item)throw Error('Kein gültiger Modelname oder öffentlicher Raumlink: '+raw);const identity=D.key(item);if(!names.includes(identity))names.push(identity);}if(names.length>200)throw Error('Höchstens 200 Models je Liste.');return names;}
    historyPanel(){const {body}=this.dialog('Beobachteter Raumstatusverlauf');body.append(el('p',{class:'lc-muted',text:'Nur tatsächlich beobachtete Zustände. Ein fehlender Katalogeintrag gilt nicht als offline.'}),...this.history.slice(0,250).map(item=>el('p',{text:new Date(item.at).toLocaleString()+' · '+item.identity+' · '+statusNames[item.state]})));}
    statisticsPanel(){const {body}=this.dialog('Multicam-Nutzung');const rows=Object.entries(this.data.models).filter(([,m])=>m.watchMs||m.sessions).sort((a,b)=>(b[1].watchMs||0)-(a[1].watchMs||0));body.append(el('p',{class:'lc-muted',text:'Lokal gemessene Multicam-Nutzung. Keine Anbieter-Kontostatistik.'}),...rows.slice(0,250).map(([identity,m])=>el('p',{text:identity+' · '+duration(m.watchMs||0)+' · '+(m.sessions||0)+' Sitzungen'})));}
    helpPanel(){const {body}=this.dialog('Multicam-Hilfe');body.append(...['Mosaik verwendet die tatsächlichen Hochkant- und Querformate. So entstehen keine zusätzlichen Balken innerhalb gleich breiter Kästen. Im festen Raster kannst du ganzes Bild oder Beschnitt wählen.','Ziehen am Kamerakopf tauscht Kameraplätze. Aus der Modellliste kannst du Models auf einen Platz ziehen. Eine Suche links verändert keine laufenden Kameras.','Arbeitsbereiche speichern Belegung und Einstellungen getrennt. Verkleinern entfernt keine versteckten Plätze. Szenen enthalten Belegung und Ansichts-/Audiooptionen; Vorlagen enthalten das Layout.','Strg/Cmd + Mausrad zoomt. Vergrößerte Bilder lassen sich mit der linken Maustaste verschieben; Doppelklick setzt den Ausschnitt zurück.','Aufnahmen benötigen echte zugängliche Videospuren. Sie werden abschnittsweise in der lokalen Galerie gespeichert. Geschlossene Browser können nicht weiter aufnehmen.','Tastatur- und Anbieterauswahl gelten innerhalb der Live-Cam-Sektion. Privat, offline, unbekannt und Medienfehler werden getrennt behandelt.'].map(value=>el('p',{text:value})),el('a',{href:'https://developer.mozilla.org/en-US/docs/Web/API/HTMLMediaElement/captureStream',target:'_blank',rel:'noopener',text:'Browserunterstützung für Videoaufnahmen'}));}
    urlPanel(){
      const {dialog,body}=this.dialog('Temporäre öffentliche Räume'),url=el('input',{'aria-label':'Öffentliche Raum-URL',placeholder:'https://…/Modelname/'});
      body.append(url,button('Nur für diese Sitzung hinzufügen',this.command(()=>{const item=D.parsePublicURL(url.value);if(!item)throw Error('Bitte eine reguläre öffentliche Raum-URL eines der unterstützten Anbieter eingeben. Keine Medienadresse oder Sitzungsparameter.');if(!this.temporary.some(r=>D.key(r)===D.key(item)))this.temporary.push(item);this.renderSidebar();dialog.close();})),button('Raumlink dauerhaft speichern',this.command(async()=>{const item=D.parsePublicURL(url.value);if(!item)throw Error('Ungültiger öffentlicher Raumlink.');await this.change(data=>{if(data.urls.length>=100)throw Error('Höchstens 100 Raumlinks.');if(!data.urls.some(r=>D.key(r)===D.key(item)))data.urls.push(item);});dialog.close();this.urlPanel();})));
      for(const item of [...this.temporary,...this.data.urls])body.append(el('div',{class:'lc-buttons'},el('span',{text:D.publicURL(item)}),button('Einsetzen',()=>this.chooseModel(D.key(item))),button('Entfernen',this.command(async()=>{this.temporary=this.temporary.filter(r=>D.key(r)!==D.key(item));await this.change(data=>{data.urls=data.urls.filter(r=>D.key(r)!==D.key(item));});dialog.close();this.urlPanel();}))));
    }
    rotationPanel(){
      const c=this.config(),r=c.rotation,{dialog,body}=this.dialog('Rotation, Verfügbarkeit und Ersatz'),set=async(name,value)=>{await this.change(data=>{data.workspaces.find(w=>w.id===this.workspaceId).settings.rotation[name]=value;});if(['queue','windows','targets','targetsAll'].includes(name)&&dialog.open){dialog.close();this.rotationPanel();}};
      const status=el('p',{class:'lc-rotation-state'});this.rotationStatusNode=status;dialog.onCleanup=()=>{if(this.rotationStatusNode===status)this.rotationStatusNode=null;};
      body.append(this.section('Automatischer Ersatz',check('Nicht verfügbare Kameras automatisch ersetzen',c.autoReplace,value=>this.setting('autoReplace',value)),input('Ersatzverzögerung Sekunden',c.replaceDelay,value=>this.setting('replaceDelay',D.clamp(value,0,600)),'number',{min:0,max:600}),select('Ersatzgruppe',c.replaceGroup,[['','Alle passenden Live-Models'],...this.groups.map(g=>[g.id,g.name])],value=>this.setting('replaceGroup',value)),input('Bevorzugte Models mit Anbieterpräfix',c.preferred.join(' '),value=>this.setting('preferred',this.parseNames(value,c.sites[0]||'stripchat'))),button('Geeigneten Ersatz vorschlagen',()=>this.replacementPreview())),
        this.section('Rotationskandidaten',select('Kandidatenquelle',r.source,[['favorites','Favoriten'],['following','Offiziell gefolgt'],['group','Eigene Gruppe'],['feed','Öffentlicher Katalog / Filterbestand']],value=>set('source',value)),select('Kandidatengruppe',r.group,[['','Keine Gruppe'],...this.groups.map(g=>[g.id,g.name])],value=>set('group',value)),select('Kandidatenreihenfolge',r.order,[['catalog','Katalogreihenfolge'],['group','Gruppenreihenfolge'],['leastUsage','Geringste Nutzung'],['shuffle','Stabil gemischt']],value=>set('order',value)),select('Nicht verfügbare Räume',r.unavailable||'skip',[['mark','Markieren'],['suggest','Ersatz vorschlagen'],['skip','Überspringen']],value=>set('unavailable',value)),select('Rotationsmodus',r.mode,[['off','Ausgeschaltet'],['manual','Manuell'],['session','Laufende Sitzung']],value=>set('mode',value)),select('Intervall Minuten',r.minutes,[1,5,10,15],value=>set('minutes',Number(value))),select('Warteschlange',r.queueMode,[['dynamic','Dynamisch'],['fixed','Feste Liste']],value=>set('queueMode',value)),select('Pro Schritt',r.step,[['all','Alle Zielplätze'],['one','Einen Zielplatz']],value=>set('step',value)),check('Stabil mischen',r.shuffle,value=>set('shuffle',value))),
        this.section('Feste Liste und Ausschlüsse',input('Models zur festen Liste hinzufügen','',value=>set('queue',[...new Set([...this.config().rotation.queue,...this.parseNames(value,c.sites[0]||'stripchat')])].slice(0,200))),input('Ausgeschlossene Models',r.excluded.join(' '),value=>set('excluded',this.parseNames(value,c.sites[0]||'stripchat'))),...r.queue.map((identity,index)=>el('div',{class:'lc-buttons'},el('span',{text:identity+' · '+statusNames[D.stateOf(this.model(identity))]}),button('↑',()=>set('queue',this.moveList(r.queue,index,-1))),button('↓',()=>set('queue',this.moveList(r.queue,index,1))),button('Entfernen',()=>set('queue',r.queue.filter(k=>k!==identity)))))),
        this.section('Zielplätze',button('Alle Plätze',async()=>{await this.change(data=>{const rule=data.workspaces.find(w=>w.id===this.workspaceId).settings.rotation;rule.targetsAll=true;rule.targets=[];});dialog.close();this.rotationPanel();}),...Array.from({length:c.capacity},(_,slot)=>check('Platz '+(slot+1),this.rotationTargets().includes(slot),async on=>{await this.change(data=>{const rule=data.workspaces.find(w=>w.id===this.workspaceId).settings.rotation,slots=rule.targetsAll!==false&&!rule.targets.length?Array.from({length:c.capacity},(_,i)=>i):rule.targets;rule.targetsAll=false;rule.targets=on?[...new Set([...slots,slot])]:slots.filter(i=>i!==slot);});}))),
        this.section('Wochenzeitfenster',select('Zeitplan',r.schedule,[['anytime','Jederzeit'],['windows','Nur in Wochenzeitfenstern']],value=>set('schedule',value)),button('Zeitfenster hinzufügen',()=>this.schedulePanel(()=>{dialog.close();this.rotationPanel();})),...r.windows.map((w,index)=>el('div',{class:'lc-buttons'},el('span',{text:w.days.map(day=>['So','Mo','Di','Mi','Do','Fr','Sa'][day]).join(', ')+' '+this.minuteText(w.start)+'–'+this.minuteText(w.end)}),button('Entfernen',()=>set('windows',r.windows.filter((_,i)=>i!==index)))))),
        status,el('div',{class:'lc-buttons'},button('Rotation starten',()=>this.startRotation()),button('Pausieren / fortsetzen',()=>{if(this.rotation){this.rotation.paused=!this.rotation.paused;this.rotation.deadline=Date.now()+this.config().rotation.minutes*60000;this.rotationTick();}}),button('Nächster Schritt',()=>this.rotationStep()),button('Neu starten',()=>this.startRotation()),button('Stoppen',()=>{this.stopRotation();this.reconcile();}),button('Aktuelle Rotation übernehmen …',()=>this.rotationPreview())));
      this.rotationTick();
    }
    minuteText(value){return String(Math.floor(value/60)).padStart(2,'0')+':'+String(value%60).padStart(2,'0');}
    moveList(items,index,delta){const next=[...items],target=D.clamp(index+delta,0,next.length-1);[next[index],next[target]]=[next[target],next[index]];return next;}
    schedulePanel(onSaved){
      const {dialog,body}=this.dialog('Wochenzeitfenster hinzufügen'),days=new Set([1,2,3,4,5]),start=el('input',{type:'time',value:'18:00','aria-label':'Von Uhrzeit'}),end=el('input',{type:'time',value:'23:00','aria-label':'Bis Uhrzeit'});
      body.append(...['Sonntag','Montag','Dienstag','Mittwoch','Donnerstag','Freitag','Samstag'].map((name,index)=>check(name,days.has(index),on=>{if(on)days.add(index);else days.delete(index);})),el('label',{},'Von',start),el('label',{},'Bis',end),el('p',{class:'lc-muted',text:'Ein Ende vor dem Beginn läuft über Mitternacht. Diese Fenster steuern Rotation, keine geplanten Aufnahmen.'}),button('Zeitfenster speichern',this.command(async()=>{const minute=value=>{const [h,m]=value.split(':').map(Number);return h*60+m;};const window={days:[...days].sort(),start:minute(start.value),end:minute(end.value)};const windows=[...this.config().rotation.windows,window];D.validateWindows(windows);await this.change(data=>{data.workspaces.find(w=>w.id===this.workspaceId).settings.rotation.windows=windows;});dialog.close();onSaved?.();})));
    }
    playable(identity){const model=this.model(identity);return (this.players.get(identity)?.phase==='playing'||this.catalog.has(identity)&&Date.now()-this.catalog.get(identity)._observedAt<120000)&&D.stateOf(model)==='online';}
    rotationTargets(){const r=this.config().rotation;return (r.targetsAll!==false&&!r.targets.length?Array.from({length:this.config().capacity},(_,i)=>i):r.targets).filter(i=>i<this.config().capacity);}
    rotationCandidates(){
      const r=this.config().rotation,slots=this.currentSlots(),targets=this.rotationTargets(),blocked=new Set(slots.filter((value,index)=>value&&!targets.includes(index)));
      let rows=this.models().filter(m=>this.config().sites.includes(m.site)&&this.playable(D.key(m))&&!r.excluded.includes(D.key(m))&&!blocked.has(D.key(m)));
      if(r.source==='favorites')rows=rows.filter(m=>m.fav);if(r.source==='following')rows=rows.filter(m=>m.accountFav);if(r.source==='group')rows=rows.filter(m=>(this.groupMap()[r.group]||[]).includes(D.key(m)));if(r.source==='feed')rows=rows.filter(m=>D.matches(m,this.config().playbackFilters,{groups:this.groupMap(),occupied:new Set(slots)}));
      if(r.queueMode==='fixed')rows=r.queue.map(identity=>rows.find(m=>D.key(m)===identity)).filter(Boolean);
      else if(r.order==='leastUsage')rows.sort((a,b)=>(a.personal?.watchMs||0)-(b.personal?.watchMs||0));else if(r.order==='group'){const order=this.groupMap()[r.group]||[];rows.sort((a,b)=>order.indexOf(D.key(a))-order.indexOf(D.key(b)));}
      if(r.shuffle||r.order==='shuffle'){const hash=value=>{let h=2166136261;for(const char of value)h=Math.imul(h^char.charCodeAt(0),16777619);return h>>>0;};rows.sort((a,b)=>hash(this.workspaceId+D.key(a))-hash(this.workspaceId+D.key(b)));}
      return rows;
    }
    startRotation(){if(this.config().rotation.mode==='off'){this.notify('Zuerst einen manuellen oder laufenden Rotationsmodus wählen.',true);return;}this.rotation={workspace:this.workspaceId,context:this.contextKey(),slots:this.sessionSlots(),cursor:0,step:0,paused:false,deadline:Date.now()+this.config().rotation.minutes*60000};this.rotationStep();}
    stopRotation(){this.rotation=null;}
    rotationStep(){
      if(!this.rotation)this.rotation={workspace:this.workspaceId,context:this.contextKey(),slots:this.sessionSlots(),cursor:0,step:0,paused:true,deadline:Date.now()+this.config().rotation.minutes*60000};
      const r=this.config().rotation,available=this.rotationCandidates(),when=D.scheduleAt(r);if(!when.allowed||!available.length){this.rotation.waiting=true;this.rotationTick();return;}
      const targets=this.rotationTargets();if(!targets.length){this.rotation.waiting=true;this.rotationTick();return;}const selected=r.step==='one'?[targets[this.rotation.step%targets.length]]:targets;const previous=[...this.rotation.slots];
      for(const slot of selected){if(slot==null)continue;const next=available[this.rotation.cursor++%available.length];const identity=D.key(next),old=this.rotation.slots.indexOf(identity);if(old>=0)this.rotation.slots[old]=null;this.rotation.slots[slot]=identity;}
      if(JSON.stringify(previous)!==JSON.stringify(this.rotation.slots))this.workspaceEvent('rotation',{detail:'Rotationsschritt',automatic:r.mode==='session'});this.rotation.step++;this.rotation.waiting=false;this.rotation.deadline=Date.now()+r.minutes*60000;this.reconcile();this.rotationTick();
    }
    rotationTick(){
      if(!this.active||!this.data)return;const config=this.config(),r=config.rotation,when=D.scheduleAt(r),session=this.rotation;
      if(session&&!session.paused&&r.mode==='session'&&Date.now()>=session.deadline&&when.allowed){session.deadline=Date.now()+r.minutes*60000;this.rotationStep();return;}
      if(this.rotationStatusNode)this.rotationStatusNode.textContent=this.rotationCandidates().length+' spielbare Kandidaten · '+(!session?'Gestoppt':session.paused?'Pausiert':!when.allowed?'Wartet auf Zeitfenster':session.waiting?(!this.rotationTargets().length?'Keine Zielplätze gewählt':'Wartet auf spielbare Kandidaten'):r.mode==='manual'?'Manuell · nächster Schritt per Schaltfläche':'Läuft · nächster Schritt in '+Math.max(0,Math.ceil((session.deadline-Date.now())/1000))+' s')+(when.next?' · Nächstes Fenster: '+when.next.toLocaleString():'');
    }
    rotationPreview(){if(!this.rotation){this.notify('Es läuft keine Rotationssitzung.',true);return;}this.placementPreview('Rotation übernehmen',this.rotation.slots,()=>{const slots=D.clone(this.rotation.slots);return this.change(data=>{data.workspaces.find(w=>w.id===this.workspaceId).slots=slots;}).then(()=>{this.stopRotation();this.reconcile();});});}
    placementPreview(title,slots,apply){const {dialog,body}=this.dialog(title);this.workspace().slots.forEach((old,index)=>{if(old!==slots[index])body.append(el('p',{text:'Platz '+(index+1)+': '+(old||'frei')+' → '+(slots[index]||'frei')}));});body.append(button('Diese Belegung bestätigen',this.command(async()=>{await apply();dialog.close();})));}
    replacementCandidates(){const c=this.config(),occupied=new Set(this.currentSlots());let rows=this.models().filter(m=>c.sites.includes(m.site)&&this.playable(D.key(m))&&!occupied.has(D.key(m)));if(c.replaceGroup)rows=rows.filter(m=>(this.groupMap()[c.replaceGroup]||[]).includes(D.key(m)));const priorities=new Map(c.preferred.map((value,index)=>[value,index]));return rows.sort((a,b)=>(priorities.get(D.key(a))??999)-(priorities.get(D.key(b))??999));}
    replacementPreview(){const candidates=this.replacementCandidates(),slots=D.clone(this.workspace().slots);let cursor=0;for(let i=0;i<this.config().capacity;i++){const current=slots[i],state=D.stateOf(this.model(current));if(current&&['offline','private','away','denied'].includes(state)&&candidates[cursor])slots[i]=D.key(candidates[cursor++]);}if(!cursor){this.notify('Kein belegter Platz ist sicher als nicht verfügbar bekannt oder es gibt keinen geeigneten Live-Ersatz.');return;}this.placementPreview('Ersatzvorschlag prüfen',slots,()=>this.change(data=>{data.workspaces.find(w=>w.id===this.workspaceId).slots=slots;}));}
    replacementTick(){
      if(!this.config().autoReplace||this.rotation)return;
      for(const player of this.players.values()){
        const state=D.stateOf(this.model(player.identity));if(!['offline','private','away','denied'].includes(state)){player.unavailableAt=null;continue;}
        player.unavailableAt=player.unavailableAt||Date.now();if(Date.now()-player.unavailableAt<this.config().replaceDelay*1000)continue;
        const next=this.replacementCandidates()[0];if(!next)return;
        this.replacement=this.replacement||{workspace:this.workspaceId,context:this.contextKey(),slots:this.sessionSlots()};const slot=this.replacement.slots.indexOf(player.identity);if(slot>=0){this.workspaceEvent('replacement',{slot,from:player.identity,to:D.key(next),detail:state,automatic:true});this.replacement.slots[slot]=D.key(next);this.notify(player.room.name+' vorübergehend durch '+next.name+' ersetzt.');this.reconcile();}break;
      }
    }
    shortcutPanel(){
      const {body}=this.dialog('Multicam-Tastenkombinationen'),labels={search:'Globale Live-Cam-Suche',quick:'Wiedergabebestand durchsuchen',refresh:'Streams aktualisieren',grid:'Symmetrisches Raster',focus:'Fokusansicht',pure:'Pure-Modus',viewer:'Zuschauermodus',thumbs:'Fokusminiaturen'};
      for(const [name,label] of Object.entries(labels))body.append(input(label,this.data.shortcuts[name],value=>{
        const normalize=D.shortcut;const conflict=Object.entries(this.data.shortcuts).find(([other,key])=>other!==name&&normalize(key)===normalize(value));if(conflict){this.error(Error('Tastenkombination bereits vergeben: '+labels[conflict[0]]));return;}this.change(data=>{data.shortcuts[name]=value;});
      }));body.append(el('p',{text:'Schreibweise: Control+Shift+k, Alt+p oder /. Im Fokus: ← / → oder [ / ]; Leertaste pausiert. Texteingaben sind vor Buchstabenkürzeln geschützt.'}));
    }
    onKey(event){
      if(!this.active||this.dialogs.size)return;
      const editing=event.target.closest('input,textarea,select,[contenteditable="true"]'),code=[event.ctrlKey||event.metaKey?'Control':'',event.altKey?'Alt':'',event.shiftKey?'Shift':'',event.key].filter(Boolean).join('+').toLowerCase();
      const action=Object.entries(this.data.shortcuts).find(([,value])=>D.shortcut(value)===D.shortcut(code))?.[0];
      if(editing&&!(event.ctrlKey||event.metaKey))return;
      if(action){event.preventDefault();event.stopImmediatePropagation();if(action==='search'){this.setting('sidebar',true).then(()=>this.sidebar.querySelector('input[type="search"]')?.focus());}if(action==='quick')this.change(data=>{const c=data.workspaces.find(w=>w.id===this.workspaceId).settings;c.toolbar=true;c.mode='normal';c.panels={...D.settings().panels,...c.panels,quick:true};}).then(()=>this.quick.querySelector('input[type="search"]')?.focus());if(action==='refresh')this.reconnectAll();if(action==='grid')this.setting('layout','grid');if(action==='focus')this.setting('layout','focus');if(action==='pure')this.setting('mode',this.config().mode==='pure'?'normal':'pure');if(action==='viewer')this.setting('mode',this.config().mode==='viewer'?'normal':'viewer');if(action==='thumbs')this.setting('thumbnails',!this.config().thumbnails);return;}
      if(!editing&&this.config().layout==='focus'){if(['ArrowLeft','['].includes(event.key)){event.preventDefault();this.nextFocus(-1);}if(['ArrowRight',']'].includes(event.key)){event.preventDefault();this.nextFocus(1);}if(event.key===' '){event.preventDefault();const identity=this.config().focus||this.visibleEntries().rows.find(e=>e.identity)?.identity;if(identity)this.pause(identity);}}
    }
    capturePanel(){return this.capture.panel();}
    galleryPanel(identity){return this.capture.gallery(identity);}
  }
  class CaptureCenter {
    constructor(studio){this.studio=studio;this.jobs=new Map();this.update=null;this.folder=null;}
    supported(){return !!root.MediaRecorder&&!!document.createElement('video').captureStream;}
    async start(identity){
      const s=this.studio;
      if(s.data.private)throw Error('Screenshots und Aufnahmen sind in der privaten Multicam-Sitzung ausgeschaltet.');
      if(!this.supported())throw Error('Dieser Browser stellt keine aufnehmbaren Videospuren bereit.');
      if(!this.jobs.has(identity))this.jobs.set(identity,{identity,wanted:true,state:'waiting',started:Date.now(),segment:0,saved:0,bytes:0,error:'',recorder:null,pending:Promise.resolve(),pendingBytes:0});
      await this.sourceReady(identity);this.update?.();
    }
    mime(){return ['video/mp4;codecs=avc1.42E01E,mp4a.40.2','video/webm;codecs=vp8,opus','video/webm'].find(type=>MediaRecorder.isTypeSupported(type))||'';}
    async sourceReady(identity){
      const s=this.studio,job=this.jobs.get(identity),player=s.players.get(identity);
      if(!job||!job.wanted||job.recorder||job.starting||job.state==='saving'||s.data.private||!player||player.video.readyState<2||player.video.paused)return;
      job.starting=true;
      try{
        const stream=player.video.captureStream();
        if(!stream.getVideoTracks().some(track=>track.readyState==='live')){stream.getTracks().forEach(track=>track.stop());job.state='waiting';return;}
        const dimensions={width:player.video.videoWidth,height:player.video.videoHeight};const mime=this.mime();if(!mime)throw Error('Kein unterstütztes Aufnahmeformat verfügbar.');
        const recorder=new MediaRecorder(stream,{mimeType:mime,videoBitsPerSecond:s.data.capture.bitrate*1000000});
        const captureId='capture_'+D.id();job.captureId=captureId;job.segment++;job.part=0;job.segmentBytes=0;job.segmentAt=Date.now();job.format=mime.includes('mp4')?'mp4':'webm';job.pending=Promise.resolve();job.pendingBytes=0;job.rescue=[];job.error='';
        await s.store.put('media',{id:captureId,model:identity,created:job.segmentAt,mime,format:job.format,...dimensions,number:job.segment,size:0,duration:0,complete:false,recordingUntil:Date.now()+30000,parts:0,type:'video'});
        if(this.jobs.get(identity)!==job||!job.wanted||s.players.get(identity)!==player||player.closed||s.data.private||player.video.paused||!stream.getVideoTracks().some(track=>track.readyState==='live')){stream.getTracks().forEach(track=>track.stop());await s.store.removeMedia(captureId);job.state='waiting';return;}
        job.recorder=recorder;job.stream=stream;job.state='recording';
        job.finished=new Promise(resolve=>{job.resolveFinish=resolve;});
        recorder.addEventListener('dataavailable',event=>{
          if(!event.data.size)return;
          const rescue={blob:event.data,offset:0};job.rescue.push(rescue);
          job.pendingBytes+=event.data.size;
          if(job.pendingBytes>16*1024*1024){job.error='Der lokale Speicher ist zu langsam. Der vorhandene Abschnitt wird gesichert.';job.wanted=false;this.finish(job,false);}
          job.pending=job.pending.then(async()=>{
            for(let offset=0;offset<event.data.size;offset+=1024*1024){const blob=event.data.slice(offset,offset+1024*1024);await s.store.put('parts',{id:captureId+'/'+job.part,capture:captureId,part:job.part++,blob});job.segmentBytes+=blob.size;job.bytes+=blob.size;rescue.offset=offset+blob.size;}
            job.pendingBytes-=event.data.size;job.rescue=job.rescue.filter(item=>item!==rescue);
          }).catch(error=>{job.error='Speicherfehler: '+error.message;job.wanted=false;if(recorder.state!=='inactive')recorder.stop();throw error;});
          // Observe the rejection immediately; publication still waits for it.
          job.pending.catch(()=>{});
        });
        recorder.addEventListener('error',event=>{job.error=event.error?.message||'Die Aufnahmequelle ist nicht mehr verfügbar.';job.wanted=false;this.finish(job,false);});
        recorder.addEventListener('stop',async()=>{
          clearTimeout(job.segmentTimer);clearInterval(job.leaseTimer);job.state='saving';
          try{
            await job.pending;
            const entry={id:captureId,model:identity,created:job.segmentAt,mime,format:job.format,...dimensions,number:job.segment,size:job.segmentBytes,duration:Date.now()-job.segmentAt,complete:!job.error,parts:job.part,type:'video',error:job.error};
            await s.store.put('media',entry);job.saved++;s.onCaptureSaved?.(entry);
            if((s.data.capture.download||this.folder)&&entry.size){try{await this.downloadEntry(entry,false);}catch(error){s.error(Error('Der Abschnitt ist in der Galerie gespeichert. Die zusätzliche Dateiausgabe ist fehlgeschlagen: '+error.message));}}
          }catch(error){job.error='Abschnitt nicht vollständig gespeichert: '+error.message;s.error(error);if(s.onCaptureRescue){try{const parts=await s.store.parts(captureId),prefix=parts.map(part=>part.blob),pending=job.rescue.map(item=>item.blob.slice(item.offset));const blob=new Blob([...prefix,...pending],{type:mime});if(blob.size)s.onCaptureRescue({id:captureId,model:identity,created:job.segmentAt,mime,format:job.format,type:'video',number:job.segment,size:blob.size,duration:Date.now()-job.segmentAt,complete:false,error:job.error},blob);}catch{ /* The storage error remains visible; no successful rescue is claimed. */ }}}
          finally{
            stream.getTracks().forEach(track=>track.stop());job.recorder=null;job.state=job.error?'error':job.wanted?'waiting':'stopped';job.resolveFinish?.();
            if(!job.wanted&&!job.error)this.jobs.delete(identity);
            this.update?.();if(job.wanted&&!job.error)this.sourceReady(identity);
          }
        });
        for(const track of stream.getVideoTracks())track.addEventListener('ended',()=>this.sourceLost(identity),{once:true});
        recorder.start(1000);job.leaseTimer=setInterval(()=>s.store.mediaLease?.(captureId)?.catch(error=>s.error(error)),10000);job.segmentTimer=setTimeout(()=>this.finish(job,true),s.data.capture.minutes*60000);this.update?.();
      }catch(error){job.state='error';job.error=error.message;s.error(error);}finally{job.starting=false;}
    }
    finish(job,keepWanted){
      if(!keepWanted)job.wanted=false;
      if(job.recorder&&job.recorder.state!=='inactive'){job.state='saving';job.recorder.stop();}
    }
    sourceLost(identity){const job=this.jobs.get(identity);if(!job)return;this.finish(job,true);if(!job.recorder)job.state='waiting';this.update?.();}
    sourceLostAll(){for(const identity of this.jobs.keys())this.sourceLost(identity);}
    async stop(identity){const job=this.jobs.get(identity);if(!job)return;this.finish(job,false);if(job.recorder)await job.finished;else this.jobs.delete(identity);this.update?.();}
    async stopAll(){await Promise.allSettled([...this.jobs.keys()].map(identity=>this.stop(identity)));}
    async screenshot(identity){
      const s=this.studio,p=s.players.get(identity);
      if(s.data.private)throw Error('Screenshots sind in der privaten Sitzung ausgeschaltet.');
      if(!p||p.video.readyState<2||!p.video.videoWidth)throw Error('Ein Screenshot benötigt ein tatsächlich geladenes Videobild.');
      const canvas=document.createElement('canvas');canvas.width=p.video.videoWidth;canvas.height=p.video.videoHeight;
      let blob;
      try{canvas.getContext('2d').drawImage(p.video,0,0);blob=await new Promise((resolve,reject)=>canvas.toBlob(value=>value?resolve(value):reject(Error('Kein PNG-Bild erzeugt.')),'image/png'));}catch{throw Error('Der Browser gibt die Bilddaten dieser Quelle nicht für Screenshots frei.');}finally{canvas.width=canvas.height=0;}
      const identityId='png_'+D.id();await s.store.put('parts',{id:identityId+'/0',capture:identityId,part:0,blob});
      await s.store.put('media',{id:identityId,model:identity,created:Date.now(),mime:'image/png',format:'png',number:1,size:blob.size,duration:0,complete:true,parts:1,type:'image'});
      s.notify('PNG-Screenshot in der Modelgalerie gespeichert.');this.update?.();
    }
    tick(){if(this.update)this.update();for(const [identity,job] of this.jobs)if(job.wanted&&job.state==='waiting')this.sourceReady(identity);}
    panel(){
      const s=this.studio,{dialog,body}=s.dialog('Multicam-Aufnahmezentrale'),settings=s.data.capture,rows=el('div',{class:'lc-recordings'});let only=false;
      const setting=(name,value)=>s.change(data=>{data.capture[name]=value;});
      const update=()=>{rows.replaceChildren(...[...this.jobs.values()].filter(job=>!only||job.state==='recording').map(job=>el('section',{},el('strong',{text:job.identity}),el('p',{text:({waiting:'Wartet auf verfügbare Videoquelle',recording:'Aufnahme läuft',saving:'Speichert Abschnitt',stopped:'Gestoppt',error:'Fehler'}[job.state]||job.state)+(job.error?' · '+job.error:'')}),el('p',{text:duration(Date.now()-job.started)+' · Teil '+job.segment+' · '+job.saved+' Abschnitte gespeichert · '+bytes(job.bytes)+' · '+s.data.capture.bitrate+' Mbit/s · '+(job.format||'Format noch unbekannt')}),button('Stoppen und speichern',s.command(()=>this.stop(job.identity))),button('Model öffnen',()=>s.ctx.openSingle(s.model(job.identity))))));};
      this.update=update;dialog.onCleanup=()=>{if(this.update===update)this.update=null;};
      const bulk=async source=>{
        let identities=source==='page'?s.visibleEntries().rows.map(e=>e.identity).filter(Boolean):source==='group'?(s.groupMap()[s.config().playbackFilters.group]||[]):s.models().filter(m=>s.config().sites.includes(m.site)&&s.playable(D.key(m))).map(D.key);
        identities=[...new Set(identities)].filter(identity=>s.config().sites.includes(D.room(identity).site));
        if(!identities.length)throw Error(source==='group'?'Zuerst im Wiedergabebestand eine Gruppe auswählen.':'Keine passenden Models verfügbar.');
        if(!confirm(identities.length+' öffentliche Models aufnehmen? Quellen außerhalb der aktiven Kameras warten, bis ihr Video verfügbar wird.'))return;
        for(const identity of identities)await this.start(identity);update();
      };
      body.append(el('p',{class:'lc-muted',text:'Aufnahme benötigt zugängliche Videospuren. Abschnitte werden zuerst dauerhaft in der lokalen Modelgalerie gespeichert. Bei Quellenverlust wird der Abschnitt gesichert; die Aufnahmeabsicht wartet auf die zurückkehrende Quelle. Ein geschlossener Browser nimmt nicht weiter auf.'}),
        s.section('Aufnahmeeinstellungen',input('Abschnittslänge Minuten',settings.minutes,value=>setting('minutes',D.clamp(value,1,180)),'number',{min:1,max:180}),slider('Aufnahmebitrate Mbit/s',settings.bitrate,.5,20,.5,value=>setting('bitrate',value)),check('Vor Verlassen bei aktiven Aufnahmen warnen',settings.warn,value=>setting('warn',value)),check('Fertige Abschnitte zusätzlich herunterladen',settings.download,value=>setting('download',value))),
        el('div',{class:'lc-buttons'},button('Aktuelle Seite aufnehmen …',s.command(()=>bulk('page')),{disabled:!this.supported()||s.data.private}),button('Aktuelle Gruppe aufnehmen …',s.command(()=>bulk('group')),{disabled:!this.supported()||s.data.private}),button('Verfügbare Online-Models aufnehmen …',s.command(()=>bulk('online')),{disabled:!this.supported()||s.data.private}),button('Alle Aufnahmen stoppen',s.command(()=>this.stopAll())),button('Nur aufnehmende / alle zeigen',()=>{only=!only;update();}),button('Gespeicherte Medien',()=>this.gallery()),button('Ausgabeordner wählen',s.command(async()=>{if(!root.showDirectoryPicker)throw Error('Dieser Browser unterstützt keine Ordnerausgabe. Galerie und Download sind verfügbar.');this.folder=await root.showDirectoryPicker({mode:'readwrite'});s.notify('Ausgabeordner für diese Sitzung gewählt.');}),{disabled:!root.showDirectoryPicker})),rows);
      if(!this.supported())body.append(el('p',{class:'lc-error',text:'Dieser Browser unterstützt die benötigte Videoaufnahme nicht. Es werden keine wirkungslosen Aufnahmeaktionen gestartet.'}));
      if(s.data.private)body.append(el('p',{class:'lc-muted',text:'Private Multicam-Sitzung aktiv: Capture ist ausgeschaltet.'}));update();
    }
    async downloadEntry(entry,userGesture=true){
      const s=this.studio,parts=await s.store.parts(entry.id),name=filename(entry.model)+'_'+new Date(entry.created).toISOString().replace(/[:.]/g,'-')+'_Teil'+entry.number+'.'+entry.format;
      if(this.folder){const file=await this.folder.getFileHandle(name,{create:true}),writer=await file.createWritable();try{for(const part of parts)await writer.write(part.blob);await writer.close();}catch(error){await writer.abort();throw error;}}
      else download(new Blob(parts.map(part=>part.blob),{type:entry.mime}),name);
      return userGesture;
    }
    sharedGallery(){
      const s=this.studio;if(!this.mediaGallery){const owner={store:s.store,get data(){return s.data;},set data(value){s.data=value;},capture:this,identity:null,ctx:s.ctx,settings:()=>root.LiveCamSingleDomain.defaults(),model:()=>s.model(owner.identity)||D.room(owner.identity)||{},command:fn=>s.command(fn),notify:(...args)=>s.notify(...args),error:error=>s.error(error),dialog:title=>s.dialog(title),change:fn=>s.change(fn)};this.mediaGallery=new root.LiveCamGallery.Gallery(owner);}this.mediaGallery.owner.ctx=s.ctx;return this.mediaGallery;
    }
    async gallery(identity=null){const s=this.studio,{dialog,body}=s.dialog(identity?'Modelgalerie \u00b7 '+D.room(identity).name:'Live-Mediengalerie'),gallery=this.sharedGallery();gallery.owner.identity=identity;gallery.directory=this.folder;dialog.onCleanup=()=>gallery.detach();await gallery.mount(body,identity);return dialog;}

  }
  let instance=null,enterGeneration=0;
  async function ensure(ctx){
    if(!instance)instance=new Studio();instance.ctx=ctx;
    if(!instance.loading)instance.loading=instance.initialize().catch(error=>{instance.loading=null;throw error;});
    await instance.loading;return instance;
  }
  root.LiveCamStudio={
    createCapture(controller){return new CaptureCenter(controller);},
    async enter(panel,ctx){const generation=++enterGeneration,studio=await ensure(ctx);if(generation!==enterGeneration)return;await studio.enter(panel,ctx);if(generation===enterGeneration&&studio.active)await studio.sharedView();},
    leave(){enterGeneration++;instance?.leave();},
    sync(){return instance?.sync();},
    async addRoom(room,ctx){return (await ensure(ctx)).addRoom(room);},
    get instance(){return instance;}
  };
  if(typeof module==='object'&&module.exports)module.exports={Studio,CaptureCenter};
})(globalThis);
