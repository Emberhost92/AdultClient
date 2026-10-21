/* Transactional, Live-Cam-only storage. No extension profile or tube data. */
(function (root) {
  'use strict';
  const D = root.LiveCamDomain;
  class StudioStore {
    constructor(database = 'adulthideout.livecam.studio') {
      this.database=database;this.db=null;this.value=null;this.listeners=new Set();this.mediaListeners=new Set();this.closed=false;
      this.channel=typeof BroadcastChannel==='function'?new BroadcastChannel(database):null;
      if(this.channel)this.channel.onmessage=event=>{
        if(!this.db||this.closed)return;
        const message=event?.data;
        if(message?.media){this.mediaChanged(false);return;}
        // Cache writes do not change the state revision. Reading the complete
        // state for each cache notification only multiplies IndexedDB work.
        if(message?.cache!=null&&message.revision==null)return;
        if(Number.isFinite(message?.revision)&&this.value&&message.revision<=this.value.revision)return;
        this.refresh().catch(error=>this.notifyError?.(error));
      };
    }
    close(){this.closed=true;this.db?.close();this.channel?.close();this.listeners.clear();this.mediaListeners.clear();}
    async open(seed) {
      this.db=await new Promise((resolve,reject)=>{
        const request=indexedDB.open(this.database,1);
        request.onupgradeneeded=()=>{
          const db=request.result;
          db.createObjectStore('state');
          const media=db.createObjectStore('media',{keyPath:'id'});media.createIndex('model','model');media.createIndex('created','created');
          const parts=db.createObjectStore('parts',{keyPath:'id'});parts.createIndex('capture','capture');
          db.createObjectStore('cache');
        };
        request.onerror=()=>reject(request.error);
        request.onblocked=()=>reject(Error('Eine andere Multicam-Version hält den Speicher geöffnet. Bitte diesen Tab neu laden.'));
        request.onsuccess=()=>resolve(request.result);
      });
      this.db.onversionchange=()=>{this.db.close();this.closed=true;this.notifyError?.(Error('Der Multicam-Speicher wurde aktualisiert. Bitte neu laden.'));};
      await this.transaction(current=>current?D.recover(current):D.validate(seed),false);
      return this.value;
    }
    transaction(change,increment=true) {
      if(!this.db||this.closed)return Promise.reject(Error('Der Multicam-Speicher ist nicht bereit.'));
      return new Promise((resolve,reject)=>{
        const tx=this.db.transaction('state','readwrite'),store=tx.objectStore('state');let next,error;
        const read=store.get('current');
        read.onsuccess=()=>{
          try {
            const current=read.result;
            if(current&&current.schema!==1)throw Error('Neuere Multicam-Daten bleiben geschützt. Bitte die neuere Anwendung verwenden.');
            next=change(current?D.clone(current):null);
            if(!next)throw Error('Der bisherige Multicam-Stand bleibt erhalten.');
            D.validate(next);
            next.revision=(current?.revision||0)+(increment?1:0);
            store.put(next,'current');
          } catch(e){error=e;tx.abort();}
        };
        tx.oncomplete=()=>{
          if(!this.value||next.revision>=this.value.revision){this.value=next;for(const callback of this.listeners){try{callback(next);}catch(error){this.notifyError?.(error);}}}
          this.channel?.postMessage({revision:next.revision});resolve(next);
        };
        tx.onerror=()=>reject(error||tx.error||Error('Multicam konnte nicht gespeichert werden.'));
        tx.onabort=()=>reject(error||tx.error||Error('Multicam-Speicherung abgebrochen. Der bestätigte Stand bleibt erhalten.'));
      });
    }
    mutate(change) {
      return this.transaction(current=>{if(!current)throw Error('Gespeicherter Multicam-Stand fehlt.');D.recover(current);change(current);return current;});
    }
    refresh() {
      if(this.refreshing){this.refreshAgain=true;return this.refreshing;}
      this.refreshing=(async()=>{
        do {
          this.refreshAgain=false;
          const value=await this.get('state','current');
          if(value&&(!this.value||value.revision>this.value.revision)){
            this.value=D.recover(value);
            for(const callback of this.listeners){try{callback(this.value);}catch(error){this.notifyError?.(error);}}
          }
          // An update arriving during the read needs one subsequent read.
          // Concurrent callers share this loop rather than starting more reads.
        } while(this.refreshAgain&&!this.closed);
        return this.value;
      })().finally(()=>{this.refreshing=null;});
      return this.refreshing;
    }
    subscribe(callback){this.listeners.add(callback);return()=>this.listeners.delete(callback);}
    subscribeMedia(callback){this.mediaListeners.add(callback);return()=>this.mediaListeners.delete(callback);}
    mediaChanged(broadcast=true){for(const callback of this.mediaListeners){try{callback();}catch(error){this.notifyError?.(error);}}if(broadcast)this.channel?.postMessage({media:true});}
    get(name,key){
      return new Promise((resolve,reject)=>{const tx=this.db.transaction(name),r=tx.objectStore(name).get(key);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
    }
    put(name,value,key){
      return new Promise((resolve,reject)=>{const tx=this.db.transaction(name,'readwrite');const store=tx.objectStore(name);if(key===undefined)store.put(value);else store.put(value,key);tx.oncomplete=()=>{if(name==='media')this.mediaChanged();resolve(value);};tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error||Error('Speichern abgebrochen.'));});
    }
    updateCache(key,change){
      return new Promise((resolve,reject)=>{const tx=this.db.transaction('cache','readwrite'),store=tx.objectStore('cache'),read=store.get(key);let value,error;read.onsuccess=()=>{try{value=change(read.result);store.put(value,key);}catch(e){error=e;tx.abort();}};tx.oncomplete=()=>{this.channel?.postMessage({cache:key});resolve(value);};tx.onerror=()=>reject(error||tx.error);tx.onabort=()=>reject(error||tx.error||Error('Live-Cam-Daten konnten nicht gespeichert werden.'));});
    }
    cacheEntries(prefix){
      return new Promise((resolve,reject)=>{const tx=this.db.transaction('cache'),store=tx.objectStore('cache'),range=IDBKeyRange.bound(prefix,prefix+'\uffff'),keys=store.getAllKeys(range),values=store.getAll(range);tx.oncomplete=()=>resolve(keys.result.map((key,i)=>[key,values.result[i]]));tx.onerror=()=>reject(tx.error);});
    }
    cacheKeys(prefix){
      return new Promise((resolve,reject)=>{const tx=this.db.transaction('cache'),request=tx.objectStore('cache').getAllKeys(IDBKeyRange.bound(prefix,prefix+'\uffff'));tx.oncomplete=()=>resolve(request.result);tx.onerror=()=>reject(tx.error);});
    }
    async media(){
      return new Promise((resolve,reject)=>{const tx=this.db.transaction('media'),r=tx.objectStore('media').index('created').getAll();r.onsuccess=()=>resolve(r.result.reverse());r.onerror=()=>reject(r.error);});
    }
    async mediaFor(identity){
      return new Promise((resolve,reject)=>{const tx=this.db.transaction('media'),r=tx.objectStore('media').index('model').getAll(identity);r.onsuccess=()=>resolve(r.result.sort((a,b)=>b.created-a.created));r.onerror=()=>reject(r.error);});
    }
    async putMedia(entry,parts){
      return new Promise((resolve,reject)=>{const tx=this.db.transaction(['media','parts','state'],'readwrite');let error;const state=tx.objectStore('state').get('current');state.onsuccess=()=>{if(state.result?.private){error=Error('Im Privatmodus werden keine Medien gespeichert.');tx.abort();return;}for(const part of parts)tx.objectStore('parts').put(part);tx.objectStore('media').put(entry);};tx.oncomplete=()=>{this.mediaChanged();resolve(entry);};tx.onerror=()=>reject(error||tx.error);tx.onabort=()=>reject(error||tx.error||Error('Das Medium wurde nicht gespeichert.'));});
    }
    async parts(capture){
      return new Promise((resolve,reject)=>{const tx=this.db.transaction('parts'),r=tx.objectStore('parts').index('capture').getAll(capture);r.onsuccess=()=>resolve(r.result.sort((a,b)=>a.part-b.part));r.onerror=()=>reject(r.error);});
    }
    async removeMedia(capture){
      const parts=await this.parts(capture);
      return new Promise((resolve,reject)=>{const tx=this.db.transaction(['media','parts'],'readwrite');tx.objectStore('media').delete(capture);for(const part of parts)tx.objectStore('parts').delete(part.id);tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error);});
    }
    mediaLease(id){return new Promise((resolve,reject)=>{const tx=this.db.transaction('media','readwrite'),store=tx.objectStore('media'),read=store.get(id);read.onsuccess=()=>{if(read.result?.complete===false)store.put({...read.result,recordingUntil:Date.now()+30000});};tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error);});}
    setMediaReference(id,kind,automatic=false){return new Promise((resolve,reject)=>{const tx=this.db.transaction(['state','media'],'readwrite'),state=tx.objectStore('state'),read=state.get('current');let next,error;read.onsuccess=()=>{next=read.result;const media=tx.objectStore('media').get(id);media.onsuccess=()=>{try{const entry=media.result;if(!next||next.private)throw Error('Im Privatmodus werden keine Bildzuordnungen gespeichert.');if(!entry||entry.trashedAt||entry.type!=='image')throw Error('Das Bild ist nicht mehr in der Galerie verfügbar.');if(kind==='cover'){if(automatic&&next.models[entry.model]?.cover&&next.models[entry.model]?.coverKind!=='public')return;next.models[entry.model]={...next.models[entry.model],cover:id,coverKind:automatic?'public':'custom'};}else if(['background','global-background'].includes(kind)){next.single=root.LiveCamSingleDomain.normalizeState(next.single);const spec={media:id,opacity:.35,blur:4,brightness:70,x:50,y:50,size:'cover'};next.single.settings.background='ambient';if(kind==='global-background')next.single.globalBackground=spec;else next.single.models[entry.model]={...next.single.models[entry.model],background:spec};}else throw Error('Unbekannte Bildzuordnung.');D.validate(next);next.revision++;state.put(next,'current');}catch(e){error=e;tx.abort();}};};tx.oncomplete=()=>{this.value=next;for(const callback of this.listeners){try{callback(next);}catch(e){this.notifyError?.(e);}}this.channel?.postMessage({revision:next.revision});resolve(next);};tx.onerror=()=>reject(error||tx.error);tx.onabort=()=>reject(error||tx.error);});}
    mediaAction(ids,action){
      if(Array.isArray(ids)&&ids.length>500)return Promise.reject(Error('Bitte h\u00f6chstens 500 Medien gleichzeitig bearbeiten.'));
      if(!['trash','restore','purge'].includes(action)||!Array.isArray(ids)||!ids.length||ids.length>500)return Promise.reject(Error('Ungültige Medienauswahl.'));
      ids=[...new Set(ids)];
      return new Promise((resolve,reject)=>{const tx=this.db.transaction(['media','parts','state'],'readwrite'),media=tx.objectStore('media'),state=tx.objectStore('state'),read=state.get('current');let next,error,changed=false,count=0,pending=ids.length;const finish=()=>{if(--pending===0&&changed){D.validate(next);next.revision++;state.put(next,'current');}};
        read.onsuccess=()=>{next=read.result;if(next?.private){error=Error('Im Privatmodus werden keine Medien verändert.');tx.abort();return;}for(const id of ids){const request=media.get(id);request.onsuccess=()=>{const entry=request.result;if(!entry){finish();return;}if(entry.recordingUntil>Date.now()){error=Error('Eine laufende Aufnahme ist ausgewählt. Bitte zuerst stoppen.');tx.abort();return;}if(action==='restore'){const copy={...entry};delete copy.trashedAt;media.put(copy);}else{
          if(action==='trash')media.put({...entry,trashedAt:Date.now()});else{if(!entry.trashedAt){error=Error('Dauerhaftes Löschen ist nur aus dem Papierkorb möglich.');tx.abort();return;}media.delete(id);const cursor=tx.objectStore('parts').index('capture').openCursor(IDBKeyRange.only(id));cursor.onsuccess=()=>{const row=cursor.result;if(row){row.delete();row.continue();}};}
          for(const model of Object.values(next?.models||{}))if(model.cover===id){delete model.cover;delete model.coverKind;changed=true;}
          if(next?.single?.globalBackground?.media===id){next.single.globalBackground=null;changed=true;}
          for(const model of Object.values(next?.single?.models||{}))if(model.background?.media===id){delete model.background;changed=true;}
        }count++;finish();};}};
        tx.oncomplete=()=>{if(changed){this.value=next;for(const callback of this.listeners){try{callback(next);}catch(e){this.notifyError?.(e);}}this.channel?.postMessage({revision:next.revision});}this.mediaChanged();resolve(count);};tx.onerror=()=>reject(error||tx.error);tx.onabort=()=>reject(error||tx.error||Error('Die Medienänderung wurde abgebrochen.'));
      });
    }
  }
  root.LiveCamStore=StudioStore;
  if(typeof module==='object'&&module.exports)module.exports=StudioStore;
})(globalThis);
