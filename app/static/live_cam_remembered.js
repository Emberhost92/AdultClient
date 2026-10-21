/* Personal favorites and watchlist. Shares the model inspector and player scheduler. */
(function(root){
  'use strict';
  const D=root.LiveCamDomain,M=root.LiveCamModelsDomain;
  const SOURCES=[['remembered','Favoriten oder Merkliste'],['favorites','Nur Favoriten'],['watchlist','Nur Merkliste'],['favorite-watchlist','In beiden Listen']];
  const validSource=value=>SOURCES.some(([id])=>id===value)?value:'remembered';
  const el=(tag,attrs={},...children)=>{const n=document.createElement(tag);for(const [k,v] of Object.entries(attrs)){if(k==='text')n.textContent=v;else if(k==='class')n.className=v;else if(k.startsWith('on'))n.addEventListener(k.slice(2),v);else if(k in n)n[k]=v;else n.setAttribute(k,String(v));}for(const c of children.flat())if(c!=null)n.append(c);return n;};
  const txt=(tag,text,attrs={})=>el(tag,{text,...attrs}),btn=(text,fn,attrs={})=>txt('button',text,{type:'button',onclick:fn,...attrs});
  const select=(name,value,options,change)=>{const input=el('select',{'aria-label':name,onchange:e=>change(e.target.value)},...options.map(([v,t])=>txt('option',String(t),{value:v,selected:String(v)===String(value)})));M.decorateStatusSelect(input,name);return el('label',{},txt('span',name),input);};
  class Remembered extends root.LiveCamModels.Models{
    constructor(){super();this.filters.view='remembered';this.previewOpen=false;}
    async initialize(ctx){this.ctx=ctx;if(!this.loading)this.loading=(async()=>{
      await root.LiveCamAnalytics.start();this.store=root.LiveCamAnalytics.recorder.store;
      const prefs=await this.store.get('cache','remembered-preferences');
      if(prefs)try{this.filters=M.validateFilters(prefs.filters);this.filters.view=validSource(this.filters.view);this.look=M.validateAppearance(prefs.look);this.size=[12,18,24,36,48,72,120,240].includes(prefs.size)?prefs.size:36;this.page=Math.max(0,Number(prefs.page)||0);this.previewOpen=!!prefs.previewOpen;this.compare=(prefs.compare||[]).filter(id=>D.room(id)).slice(0,4);}catch{this.prefError='Die gespeicherte Favoritenansicht konnte nicht gelesen werden. Der gespeicherte Stand bleibt erhalten.';}
      this.store.subscribe(value=>{if(this.galleryOwner)this.galleryOwner.data=value;clearTimeout(this.metricTimer);this.metricTimer=setTimeout(()=>{if(this.active&&!document.querySelector('dialog[open]'))this.refresh(false);},1200);});
      this.changeBus=typeof BroadcastChannel==='function'?new BroadcastChannel('adulthideout.livecam.models'):null;
      if(this.changeBus)this.changeBus.onmessage=()=>{if(this.active&&!document.querySelector('dialog[open]'))this.refresh(false);};
    })().catch(error=>{this.loading=null;throw error;});await this.loading;}
    async prefs(){if(!this.store.value.private&&!this.prefError)await this.store.updateCache('remembered-preferences',()=>({filters:this.filters,look:this.look,size:this.size,page:this.page,compare:this.compare,previewOpen:this.previewOpen}));}
    async presence(extra=[]){return root.LiveCamModels.instance?.presence([...extra,...(this.active?[...this.cards.keys()]:[])]);}
    async refresh(reset=true){this.filters.view=validSource(this.filters.view);this.viewSelect?.querySelector('select')&&(this.viewSelect.querySelector('select').value=this.filters.view);return super.refresh(reset);}
    build(){this.releasePreviewMenu();this.panel.replaceChildren();this.panel.classList.add('lm-models');
      this.notice=txt('p','',{class:'lm-notice',hidden:true,role:'status'});this.providers=el('div',{class:'lm-providers','aria-label':'Hosterauswahl'});this.metrics=el('div',{class:'lm-summary'});
      this.viewSelect=select('Meine Listen',this.filters.view,SOURCES,v=>{this.filters.view=v;this.refresh();});
      this.search=el('input',{type:'search',id:'lr-search','aria-label':'Favoriten und Merkliste durchsuchen',placeholder:'Name, Thema, Tags oder private Notizen',value:this.filters.query,oninput:e=>{this.filters.query=e.target.value;clearTimeout(this.searchTimer);this.searchTimer=setTimeout(()=>this.refresh(),250);}});
      this.sort=select('Sortierung',this.filters.sort,M.SORTS,v=>{this.filters.sort=v;this.refresh();});this.filterButton=btn('Filter',()=>this.filterDialog());
      this.activeChips=el('div',{class:'lm-chips','aria-label':'Aktive Filter'});this.selectionNode=el('div',{class:'lm-selection'});this.loadingNote=txt('p','',{class:'lm-coverage',role:'status'});
      this.grid=el('div',{id:'cam-remembered-grid',class:'lm-grid',role:'list','aria-label':'Favoriten und Merkliste'});this.pager=el('div',{class:'lm-pager'});this.previewHost=el('section',{'aria-label':'Live-Vorschau einstellen'});this.undoButton=btn('Letzte Änderung rückgängig',this.command(()=>this.undo()),{disabled:!this.lastUndo});
      this.panel.append(el('div',{class:'lm-heading'},txt('h3','Favoriten & Merkliste'),btn('Status aktualisieren',this.command(()=>this.updateStatus())),btn('Neu lesen',this.command(()=>this.refresh(false)))),txt('p','Deine bewusst gemerkten Models über alle sechs Hoster. Favorit = gefällt mir; Merkliste = später ansehen. Ein Model kann in beiden Listen stehen. Offizielles Following bleibt getrennt. Archivierte Models findest du im Archiv der Modelbibliothek.',{class:'lm-intro'}),this.providers,this.metrics,
        el('div',{class:'lm-toolbar'},this.viewSelect,this.search,this.sort,select('Pro Seite',this.size,[12,18,24,36,48,72,120,240].map(n=>[n,n]),v=>{this.size=Number(v);this.refresh();}),this.filterButton,btn('Ansicht',()=>this.appearanceDialog()),btn('Live-Vorschau einstellen',()=>this.previewDialog())),this.activeChips,
        el('div',{class:'lm-actions'},btn('Models durchsuchen',()=>this.ctx.openModels()),btn('Vergleich (bis 4)',this.command(()=>this.comparison())),this.undoButton),this.previewHost,this.notice,this.selectionNode,this.loadingNote,this.grid,this.pager);
      this.providerBar();this.applyAppearance();this.attachPreviewMenu();
    }
    summary(){const s=this.result.summary;this.metrics.replaceChildren(...[['Favoriten · gewählte Hoster (inkl. Archiv)',s.favorites],['Merkliste · gewählte Hoster (inkl. Archiv)',s.watchlist],['Treffer nach allen Filtern',this.result.total]].map(([label,value])=>el('div',{},txt('strong',Number(value).toLocaleString((globalThis.AppI18n?.locale() || 'de-DE'))),txt('span',label))));}
    collectionsSelect(){} // Saved library searches never replace the personal list boundary.
    chips(){super.chips();const reset=[...this.activeChips.querySelectorAll('button')].find(n=>(globalThis.AppI18n?.original(n) ?? n.textContent)==='Filter zurücksetzen');if(reset)reset.replaceWith(btn('Filter zurücksetzen',()=>{const {sites,view,sort}=this.filters;this.filters={...M.defaults(),sites,view,sort};this.syncInputs();this.refresh();}));}
    pageData(data){super.pageData(data);if(!data.items.length){const note=this.grid.querySelector('.lm-empty');if(note)note.textContent=this.filters.sites.length?'Keine passenden gemerkten Models. In Räume oder Models mit „☆ Favorit“ oder „Merkliste“ hinzufügen; vorhandene Filter oben prüfen.':'Wähle mindestens einen Hoster.';}}
    async api(op,values={},signal){const result=await super.api(op,values,signal);if(op==='mutate'||op==='undo'){const meta=await this.ctx.get('/api/cam-library?part=meta').catch(()=>null);if(meta?.favs)this.ctx.favoritesChanged?.(meta.favs);}return result;}

    notify(value){super.notify(String(value).replace('unter „Weitere Aktionen“','über „Letzte Änderung rückgängig“'));}
    selectionBar(){super.selectionBar();if(this.undoButton)this.undoButton.disabled=!this.lastUndo;if(this.selectionNode)this.selectionNode.append(btn('Auswahl zur Multicam',()=>this.multiDialog(),{disabled:!this.selection.size}));}
    multiDialog(){const ids=[...this.selection];if(!ids.length)return;const {dialog,body}=this.dialog('Auswahl in Multicam öffnen');body.append(txt('p',ids.length+' ausgewählte Models werden in Arbeitsbereiche mit bis zu 20 Plätzen aufgeteilt. Die Auswahl bleibt beim Seitenwechsel erhalten.'),btn('Multicam öffnen',this.command(async()=>{this.assertWritable();let active;await this.store.mutate(data=>{const added=root.LiveCamGroupsDomain.selectionWorkspaces(ids,this.workspaceName||'Favoriten & Merkliste',D.SITES.map(r=>r[0]),60-data.workspaces.length);data.workspaces.push(...added);active=added[0].id;data.active=active;});dialog.close();this.ctx.openMulticam(active,false);})));}
    attachPreviewMenu(){const handle=this.ctx.mountPreviewMenu?.(this.previewHost,this.previewOpen);if(!handle)return;this.previewHandle=handle;this.previewToggle=()=>{this.previewOpen=handle.element.open;this.prefs().catch(e=>this.error(e));};handle.element.addEventListener('toggle',this.previewToggle);}
    releasePreviewMenu(){if(!this.previewHandle)return;this.previewHandle.element.removeEventListener('toggle',this.previewToggle);this.previewHandle.restore();this.previewHandle=null;}
    previewDialog(){if(!this.previewHandle)return super.previewDialog();this.previewHandle.element.open=true;this.previewHandle.element.scrollIntoView({block:'nearest'});}
    leave(){this.releasePreviewMenu();super.leave();}
    origin(){return {...super.origin(),view:'favs'};}
  }
  let instance;root.LiveCamRemembered={Remembered,SOURCES,validSource,async mount(panel,ctx){instance||=new Remembered();return instance.mount(panel,ctx);},leave(){instance?.leave();},get instance(){return instance;}};
})(typeof window==='object'?window:globalThis);
