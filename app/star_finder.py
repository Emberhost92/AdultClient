"""Fast profile boundary, explicit enrichment and provenance for the Star Finder."""
from __future__ import annotations

import collections
import copy
import datetime
import hashlib
import io
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

import media_library
import star_filters
from star_sources import PublicSources, clean, normal
from star_runtime import SourceError


def source_rows(rec):
    return list((rec or {}).get("sources",{}).values())


def comparison(row):
    """Compare equivalent dates and metric sizes without inventing differences."""
    label=normal(row.get("label"));value=str(row.get("value") or "").strip()
    label={"geboren":"geburtsdatum","birth date":"geburtsdatum","karrierestart":"karrierebeginn"}.get(label,label)
    if label=="geburtsdatum":
        iso=re.search(r"(\d{4})-(\d{2})-(\d{2})",value)
        de=re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})",value)
        if iso:value="-".join(iso.groups())
        elif de:value=f"{int(de[3]):04}-{int(de[2]):02}-{int(de[1]):02}"
    if label=="grosse":
        size=re.fullmatch(r"([\d.,]+)\s*(cm|m|meter|metre|zentimeter)",value,re.I)
        if size:
            number=float(size[1].replace(",","."))*(100 if size[2].lower() in ("m","meter","metre") else 1)
            value=f"{number:g} cm"
    return label,normal(value)


def coverage(profile, rec=None, external=None):
    rec = rec or {}
    external = [row for row in (external or []) if row.get("ok")]
    image_count = len(set([url for url in rec.get("images",[]) if isinstance(url,str)] + [image["url"] for row in external for image in row.get("images",[]) if image.get("url")]))
    if profile.get("thumb") and not image_count:
        image_count = 1
    bits = {"facts":bool(profile.get("facts") or rec.get("facts") or any(row.get("facts") for row in external)),
            "text":bool(profile.get("bio") or rec.get("about") or any(row.get("description") for row in external)),
            "images":bool(image_count),"aliases":bool(profile.get("aliases") or rec.get("aliases")),
            "career":bool(rec.get("career") or any(f.get("label")=="Karrierestart" for f in profile.get("facts",[]))),
            "filmography":bool(profile.get("movies") or profile.get("movie_count") or profile.get("scene_count")),
            "sources":bool(external or rec.get("url"))}
    return {"sections":bits,"filled":sum(bits.values()),"total":len(bits),"images":image_count,"sources":len(external)+int(bool(rec.get("url")))+int(bool(profile.get("local")))}


def filter_catalog(cards, query, record, language):
    want = query.get("coverage") or ""
    source = query.get("source") or ""
    minimum = max(0,int(query.get("min_movies") or 0))
    result = []
    for card in cards:
        ident = str(card.get("id") or "")
        rec = record(ident) or {}
        if minimum and int(card.get("movies") or 0)<minimum:
            continue
        images = bool(card.get("thumb") or rec.get("images") or rec.get("external_images"))
        text = bool(rec.get("about") or card.get("has_bio") or rec.get("external_text"))
        translated = bool((language(ident) or {}).get("ok"))
        if want=="images" and not images or want=="no-images" and images or want=="text" and not text or want=="no-text" and text or want=="translated" and not translated or want=="no-translation" and translated:
            continue
        if want=="new" and float(card.get("first_seen") or 0)<time.time()-7*86400:
            continue
        origin = ident.split(':',2)[1] if ident.startswith('src:') else "babepedia" if ident.startswith("bp:") else "analvids" if ident.startswith("av:") else "library"
        if source and origin!=source:
            continue
        result.append(card)
    if query.get("sort") in ("updated","images","new"):
        field = query["sort"]
        reverse = query.get("rev") in ("1","true")
        def order(card):
            rec = record(str(card.get("id"))) or {}
            value = float(rec.get("at") or 0) if field=="updated" else float(card.get("first_seen") or 0) if field=="new" else len(rec.get("images") or [])+int(rec.get("external_images") or 0)
            return (not bool(value), value if reverse else -value,card.get("name_key",""))
        result.sort(key=order)
    return result


class StarFinder:
    def __init__(self, app):
        self.app = app
        self.runtime = app._star_runtime_hub()
        self.sources = PublicSources(self.runtime)
        self.status = {}
        self.lock = threading.RLock()
        self.thumb_slots = threading.BoundedSemaphore(4)
        self.thumb_tokens = collections.OrderedDict()
        self.overview_cache = (0,{})
        self.last_thumb_trim = 0
        self.secondary = None
        self.filters = star_filters.FilterIndex(app)
        import star_stashbox
        self.boxes = star_stashbox.StashBox(self)
        self.sources.box_catalog = self.boxes.catalog
        from star_library import SourceLibrary
        self.library = SourceLibrary(self)

    def source_coverage(self,ident):
        with self.lock:
            if self.secondary is None:
                with self.runtime.store.lock:
                    rows=list(self.runtime.store.db.execute("SELECT key,payload FROM cache WHERE kind='source-coverage' AND expires>?", (time.time(),)))
                import zlib
                self.secondary={key:json.loads(zlib.decompress(raw[4:]) if isinstance(raw,bytes) and raw.startswith(b'AHZ1') else raw) for key,raw in rows}
            return self.secondary.get(ident,{})

    def save_source_coverage(self,ident,record):
        images=list(dict.fromkeys(image['url'] for source in source_rows(record) if source.get('ok') for image in source.get('images') or [] if image.get('url')))
        row={'images':len(images),'thumb':images[0] if images else '', 'text':any(source.get('ok') and source.get('description') for source in source_rows(record))}
        if not images and not row['text']:
            return
        self.runtime.store.cache('source-coverage',ident,row,10**12)
        self.source_coverage(ident)
        with self.lock:self.secondary[ident]=row

    def remember_thumbnail(self,url,headers,kind,title):
        key=hashlib.sha256(json.dumps([url,headers],sort_keys=True).encode()).hexdigest()
        now=time.monotonic()
        with self.lock:
            self.thumb_tokens[key]={"url":url,"headers":headers,"media":kind,"title":title,"expires":now+3600}
            self.thumb_tokens.move_to_end(key)
            while self.thumb_tokens and (len(self.thumb_tokens)>8192 or next(iter(self.thumb_tokens.values()))["expires"]<now):
                self.thumb_tokens.popitem(last=False)
        return key

    def overview(self):
        at,cached = self.overview_cache
        if time.monotonic()-at<20:
            return cached
        store = self.app._star_extra_load()
        with self.app._star_extra_lock:
            rows = list(store["profiles"].values())
            translated = sum(bool(row.get("ok")) for row in list(store["lang"].values()) if isinstance(row,dict))
        good = [row for row in rows if isinstance(row,dict) and row.get("ok")]
        cached = {"profiles":len(good),"texts":sum(bool(row.get("about")) for row in good),
                  "with_images":sum(bool(row.get("images")) for row in good),"images":sum(len(row.get("images") or []) for row in good),"translated":translated,
                  "people":len(store.get("people") or []),"local":self.app.star_index()["count"]}
        with self.runtime.store.lock:
            cached['source_profiles']=self.runtime.store.db.execute("SELECT count(DISTINCT profile) FROM source_catalog WHERE profile LIKE 'src:%'").fetchone()[0]
            cached['source_images']=self.runtime.store.db.execute('SELECT count(*) FROM source_gallery').fetchone()[0]
        cached['images']+=cached['source_images']
        self.overview_cache = (time.monotonic(),cached)
        return cached

    def catalog(self, query):
        query = {**query,"compact":"1"}
        result = self.app.star_catalog(query)
        gallery_counts=self.library.image_counts()
        for item in result["items"]:
            rec = self.app._star_extra_get(item["id"]) or {}
            item["image_count"] = max(int(bool(item.get("thumb"))),len(rec.get("images") or []))
            item["has_text"] = bool(rec.get("about") or item.get("about"))
            item["translated"] = bool((self.app._star_lang_get(item["id"]) or {}).get("ok"))
            item["updated"] = rec.get("at") or None
            extra=self.source_coverage(item['id'])
            item['image_count']=max(item['image_count'],len(rec.get('images') or [])+int(extra.get('images') or 0))
            item['image_count']=max(item['image_count'],gallery_counts.get(item['id'],0))
            item['has_text']=item['has_text'] or bool(extra.get('text'))
            if not item.get('thumb') and extra.get('thumb'):item['thumb']=extra['thumb']
            if item.get("thumb") and "/api/star-cover" not in item["thumb"]:
                original = self.app.star_portrait(item["id"]) or next(iter(rec.get("images") or []),"")
                if not original:
                    original = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(item["thumb"]).query)).get("url","") or extra.get('thumb')
                if original:
                    url,headers = media_library.split_url(original)
                    headers.setdefault("Referer",rec.get("url") or urllib.parse.urljoin(url,"/"))
                    headers.setdefault("User-Agent","Mozilla/5.0")
                    token = self.remember_thumbnail(url,headers,media_library.describe(url,declared="image"),item["name"])
                    item["thumb"] = "/api/star-finder/thumb?token="+token
        result["overview"] = self.overview()
        self.filters.warm_films()
        result["filters"] = self.filters.public()
        return result

    def _identity(self, query):
        return str(query.get("id") or "")[:100],str(query.get("name") or "")[:180]

    def get_profile(self, query):
        ident,name = self._identity(query)
        profile = self.app.star_profile(ident,name,False)
        if profile.get("underage"):
            return profile
        ident = profile.get("id") or ident
        raw = self.app._star_raw(ident,name) or {}
        if raw.get("bio"):
            profile["bio"] = raw["bio"]
        profile["birth_year"] = raw.get("birth_year") or profile.get('birth_year')
        profile["birth_date"] = raw.get("birth_date") or profile.get('birth_date')
        rec = self.app._star_extra_get(ident) or {}
        external = self.runtime.store.cached("sources",ident) or {"sources":{}}
        profile["sources"] = source_rows(external)+self.boxes.profile_sources(ident)
        profile["sources_due"] = self.sources_due(ident)
        aliases = list(profile.get("aliases") or []) + list(rec.get("aliases") or []) + [name for source in profile["sources"] if source.get("ok") for name in source.get("aliases") or []]
        profile["aliases"] = list(dict.fromkeys(name for name in aliases if isinstance(name,str) and normal(name)!=normal(profile.get("name"))))
        profile["quality_warnings"] = []
        if re.search(r"(?:gefeierter Star|renommierte Darstellerin).*(?:weltweit|Auszeichnungen)",profile.get("bio") or "",re.I):
            profile["quality_warnings"].append("Der ursprüngliche Kurztext enthält pauschale Aussagen ohne Einzelbelege. Ergänzende Quellen sind davon getrennt ausgewiesen.")
        profile["coverage"] = coverage(profile,rec,profile["sources"])
        portrait = self.app.star_portrait(ident) if profile.get("local") else ""
        originals = {value for value in rec.get("images") or [] if isinstance(value,str)} | {image["url"] for source in profile["sources"] if source.get("ok") for image in source.get("images") or [] if image.get("url")}
        if portrait:
            originals.add(portrait)
        originals.update(image['url'] for image in self.library.gallery(ident) if image.get('url'))
        if originals:
            profile["coverage"]["images"] = len(originals)
        profile["observed"] = rec.get("at")
        profile["note"] = self.runtime.store.cached("notes",ident) or {}
        profile["content"] = self.boxes.summary(ident)
        facts = []
        for row in profile.get("facts") or []:
            facts.append({**row,"source":"Lokale Bibliothek","at":self.app.star_index().get("stand")})
        for key,label in (("career_end_year","Karriereende"),("height_category","Größenkategorie"),("popularity","Popularitätswert (Bibliothek)")):
            if raw.get(key):facts.append({"label":label,"value":str(raw[key]),"source":"Lokale Bibliothek","at":self.app.star_index().get("stand")})
        for row in rec.get("facts") or []:
            facts.append({**row,"source":row.get("source") or ("Babepedia" if "babepedia.com" in str(rec.get("url")) else "Gespeichertes Zusatzprofil"),"url":row.get("url") or rec.get("url") or "","at":row.get("at") or rec.get("at")})
        if rec.get("real_name"):
            facts.append({"label":"Öffentlich hinterlegter Name","value":rec["real_name"],"source":"Gespeichertes Zusatzprofil","url":rec.get("url") or "","at":rec.get("at")})
        for source in profile["sources"]:
            if source.get("ok"):
                facts.extend(source.get("facts") or [])
        unique = []
        have = set()
        for row in facts:
            field,value = comparison(row)
            key = (field,value,row.get("source"))
            if key in have or not row.get("value"):
                continue
            have.add(key);unique.append({**row,"field":field,"comparison":value})
        profile["all_facts"] = unique
        groups = collections.defaultdict(set)
        for row in unique:
            groups[row["field"]].add(row["comparison"])
        profile["conflicts"] = [label for label,values in groups.items() if len(values)>1]
        with self.lock:
            profile["refresh"] = copy.deepcopy(self.status.get(ident,{"pending":False}))
        progress=self.runtime.store.cached('profile-refresh',ident)
        if progress:
            if progress.get('pending') and 'full-profile:'+ident not in self.runtime.pending:
                progress={**progress,'pending':False,'interrupted':True,'phase':'Durch Neustart unterbrochen. Erneut starten setzt mit gespeicherten Daten fort.'}
            profile['full_refresh']={**progress,'paused':bool(progress.get('pending') and self.runtime.paused(progress.get('job') or 'enrichment'))}
        return profile

    def full_refresh(self,query):
        profile=self.get_profile(query)
        if profile.get('underage') or not profile.get('name') or profile.get('error'):
            return {'ok':False,'error':'Dieses Profil ist nicht verfügbar.'}
        ident,name=profile['id'],profile['name']
        with self.lock:
            key='full-profile:'+ident
            if key in self.runtime.pending:return {'ok':True,'already':True,'id':ident}
            rows=[{'id':'base','name':'Basisprofil & Babepedia','state':'waiting'}]
            rows += [{'id':s['id'],'name':s['name'],'state':'waiting' if s.get('configured') else 'unconfigured'} for s in self.sources.catalog()]
            rows += [{'id':'gallery','name':'Alle veröffentlichten Galerieseiten','state':'waiting'},
                     {'id':'translation','name':'Deutsche Übersetzungen','state':'waiting'}]
            self.runtime.store.cache('profile-refresh',ident,{'pending':True,'started':time.time(),'phase':'Bevorzugter Abruf vorgemerkt','steps':rows,'done':0,'total':len(rows),'percent':0},10**12)
            future=self.runtime.submit(key,lambda:self._full_refresh(ident,name,rows),priority=True)
            if future is None:
                self.runtime.store.cache('profile-refresh',ident,{'pending':False,'error':'Die Warteschlange ist voll. Bitte erneut versuchen.'},10**12)
                return {'ok':False,'error':'Die Warteschlange ist voll. Bitte erneut versuchen.'}
        return {'ok':True,'pending':True,'id':ident}

    def _full_refresh(self,ident,name,steps):
        state=self.runtime.store.cached('profile-refresh',ident) or {}
        def publish(phase=None):
            done=sum(row['state'] not in ('waiting','running') for row in steps)
            state.update(steps=copy.deepcopy(steps),done=done,total=len(steps),percent=round(done/len(steps)*100),updated=time.time())
            if phase:state['phase']=phase
            self.runtime.store.cache('profile-refresh',ident,state,10**12)
        try:
            with self.runtime.fresh_requests():
                for row in steps:
                    if row['state']=='unconfigured':
                        row['note']='Nicht verbunden – Zugang oder API-Schlüssel fehlt';publish();continue
                    source=row['id'];state['job']='scenes' if source in ('stashdb','fansdb') else 'lang' if source=='translation' else 'enrichment'
                    row['state']='running';publish(row['name']+' wird geprüft')
                    self.runtime.wait(state['job'])
                    try:
                        if source=='base':
                            result=self.app._star_enrich(ident,name,force=True,log=False)
                            if result and result.get('last_error'):raise SourceError(result['last_error'])
                            if not result or not result.get('ok'):raise SourceError((result or {}).get('reason') or 'missing')
                        elif source in ('stashdb','fansdb'):
                            with self.runtime.key_lock('box:'+source+':'+ident):
                                saved=self.boxes.state(source,ident)
                                if saved.get('complete'):self.runtime.store.cache('box-state',source+':'+ident,{**saved,'refresh_requested':True},10**12)
                            while True:
                                self.runtime.wait('scenes')
                                complete=self.boxes.ingest(source,ident,name)
                                saved=self.boxes.state(source,ident)
                                row['note']=str(saved.get('total',0))+' Szenen laut Quelle · '+str(max(0,saved.get('page',1)-1))+' Seiten geprüft'
                                publish(row['name']+' · '+row['note'])
                                if complete:break
                        elif source=='gallery':
                            pages=0
                            while True:
                                self.runtime.wait('enrichment')
                                more=self.expand_images(ident,name);pages+=1
                                row['note']=str(pages)+' Galerie-Prüfschritte abgeschlossen'
                                publish(row['note'])
                                if not more:break
                        elif source=='translation':
                            result=self.app._star_lang_translate_stored(self.app.star_profile(ident,name,False))
                            if not self.translate_sources(ident) or result=='fail':raise SourceError('translation-pending')
                            if result=='skip':row['note']='Vorhandene Quelltexte geprüft; Basisprofil ohne Übersetzungsbedarf.'
                        else:
                            self.enrich_sources(ident,name,force=True,only=source)
                            saved=(self.runtime.store.cached('sources',ident) or {}).get('sources',{}).get(source,{})
                            error=saved.get('last_error') or (saved.get('status') if not saved.get('ok') else 'partial' if saved.get('partial') or saved.get('partial_errors') or saved.get('images_status')=='partial' else '')
                            if error:raise SourceError(error)
                            if not saved.get('ok'):raise SourceError('missing')
                        row['state']='done'
                    except SourceError as error:
                        row['state']=error.reason;row['note']=error.reason
                    except Exception:
                        row['state']='source-error';row['note']='Die Quelle konnte nicht vollständig geprüft werden.'
                    publish()
        except Exception:
            state['error']='Der Lauf wurde unterbrochen. Gespeicherte Angaben bleiben erhalten.'
        finally:
            state.update(pending=False,finished=time.time())
            incomplete=any(row['state']!='done' for row in steps)
            state['partial']=incomplete
            publish('Prüflauf beendet – einige Quellen bleiben offen' if incomplete else 'Alle erreichbaren Daten dieses Prüflaufs aktualisiert')

    def refresh(self, query):
        ident,name = self._identity(query)
        profile = self.get_profile(query)
        if profile.get("underage") or not profile.get("name"):
            return {"ok":False,"error":"Dieses Profil ist nicht verfügbar."}
        ident,name = profile["id"],profile["name"]
        self.boxes.enqueue(ident,name,True)
        with self.lock:
            if self.status.get(ident,{}).get("pending"):
                return {"ok":True,"already":True,"id":ident}
            self.status[ident] = {"pending":True,"phase":"Angaben werden im Hintergrund ergänzt","started":time.time()}
        future = self.runtime.submit("profile:"+ident,lambda:self._hydrate(ident,name,query.get("sources") is not False))
        if future is None:
            with self.lock:
                self.status[ident] = {"pending":False,"error":"Die Warteschlange ist voll. Bitte später erneut versuchen."}
            return {"ok":False,**self.status[ident]}
        return {"ok":True,"id":ident}

    def _hydrate(self, ident, name, external=True):
        try:
            profile = self.app.star_profile(ident,name,True)
            if profile.get("underage"):
                return
            raw = self.app._star_raw(ident,name) or {}
            profile.update({key:raw.get(key) or profile.get(key) for key in ("birth_year","birth_date")})
            if external:
                self.enrich_sources(ident,name,force=True)
                self.translate_sources(ident)
            self.app._star_more_schedule(ident,name,front=True)
        except Exception:
            with self.lock:
                self.status[ident] = {"pending":False,"error":"Eine Quelle hat nicht geantwortet. Gespeicherte Angaben bleiben erhalten.","finished":time.time()}
        finally:
            with self.lock:
                self.status[ident] = {**self.status.get(ident,{}),"pending":False,"finished":time.time()}

    def sources_due(self, ident):
        old = self.runtime.store.cached("sources",ident) or {}
        sources = old.get("sources") or {}
        for config in self.sources.catalog():
            if config['id'] in ('stashdb','fansdb'):
                continue
            if not config.get("configured"):
                continue
            row = sources.get(config["id"]) or {}
            status = row.get("last_error") or ("partial" if row.get("partial_errors") or row.get('partial') or row.get('images_status')=='partial' else row.get("status"))
            delay = 7*86400 if status in ("missing","ambiguous") else 3600 if status not in ("matched",None) else max(86400,self.runtime.interval())
            if time.time()-float(row.get("checked_at") or row.get("last_attempt") or row.get("at") or 0)>delay:
                return True
        return False

    def enrich_sources(self, ident, name, force=False, only=None):
        # Shared by the complete background catalogue and on-demand profiles.
        with self.runtime.key_lock("sources:"+ident):
            if not force and not self.sources_due(ident):
                return
            profile = self.get_profile({"id":ident,"name":name})
            if profile.get("underage"):
                return
            old = self.runtime.store.cached("sources",ident) or {"sources":{}}
            profile["source_ids"] = {key:row["entity"] for key,row in old["sources"].items() if row.get("ok") and row.get("entity")}
            with self.runtime.store.lock:
                profile['source_ids'].update(dict(self.runtime.store.db.execute('SELECT source,entity FROM source_catalog WHERE profile=?',(ident,))))
            # Source-published explicit IDs also corroborate subsequent providers.
            for source in profile.get('sources') or []:
                if source.get('ok') and source.get('entity'):profile['source_ids'][source['id']]=source['entity']
            for source in (self.sources.collect(profile,only=only) if only else self.sources.collect(profile)):
                previous = old["sources"].get(source["id"],{})
                checked = time.time()
                if previous.get("ok") and not source.get("ok"):
                    old["sources"][source["id"]] = {**previous,"last_error":source.get("status"),"last_attempt":checked,"checked_at":checked}
                else:
                    if source.get("ok") and source.get("description")==previous.get("description") and previous.get("description_de"):
                        source = {**source,"description_de":previous["description_de"],"translated_at":previous.get("translated_at")}
                    if source.get("ok"):
                        images={row["url"]:row for row in list(previous.get("images") or [])+list(source.get("images") or []) if row.get("url")}
                        source={**source,"images":list(images.values())}
                        if source.get('partial') and previous.get('metadata'):
                            metadata=dict(source.get('metadata') or {})
                            for field in ('filmography_entries','studio_entries','tag_entries'):
                                values={str(r.get('id') or r.get('url') or r.get('name') or r.get('title')):r for r in list(previous['metadata'].get(field) or [])+list(metadata.get(field) or [])}
                                if values:metadata[field]=list(values.values())
                            for field in ('filmography_titles','studios','tags'):
                                metadata[field]=list(dict.fromkeys(list(previous['metadata'].get(field) or [])+list(metadata.get(field) or [])))
                            source['metadata']=metadata
                        if source.get("partial_errors") and not source.get("description"):
                            for key in ("description","description_de","language","text_url","text_at","translated_at"):
                                if key in previous:source[key]=previous[key]
                    old["sources"][source["id"]] = {**source,"checked_at":checked}
            old["checked"] = time.time()
            old["name"] = name
            self.runtime.store.cache("sources",ident,old,10**12)
            self.save_source_coverage(ident,old)
            tags=set();studios=set();attributes=collections.defaultdict(set)
            for source in source_rows(old):
                if not source.get('ok'):continue
                attributes['sources'].add(source.get('name') or source['id'])
                metadata=source.get('metadata') or {}
                tags.update(metadata.get('tags') or []);studios.update(metadata.get('studios') or [])
            attributes['studios']=studios
            self.runtime.store.cache('metadata-features',ident,{'tags':sorted(tags),'attributes':{k:sorted(v) for k,v in attributes.items()}},10**12)
            self.filters.invalidate()

    def translation_targets(self):
        with self.runtime.store.lock:
            keys=[row[0] for row in self.runtime.store.db.execute("SELECT key FROM cache WHERE kind='sources'")]
        found=[]
        for ident in keys:
            record=self.runtime.store.cached("sources",ident) or {}
            if any(row.get("ok") and row.get("description") and row.get("language")!="de" and not row.get("description_de") for row in source_rows(record)):
                found.append((ident,record.get("name") or ""))
        return found

    def translate_sources(self, ident):
        with self.runtime.key_lock("sources:"+ident):
            record=self.runtime.store.cached("sources",ident) or {}
            changed=False
            for row in source_rows(record):
                if not row.get("ok") or not row.get("description") or row.get("language")=="de" or row.get("description_de"):
                    continue
                if self.app._tr_blocked():return False
                text=self.app._translate_en_de(row["description"],time.time()+45)
                if not text:
                    if changed:self.runtime.store.cache("sources",ident,record,10**12)
                    return False
                row["description_de"]=text;row["translated_at"]=time.time();changed=True
            if changed:self.runtime.store.cache("sources",ident,record,10**12)
        return True

    def images(self, query):
        ident,name = self._identity(query)
        profile = self.app.star_profile(ident,name,False)
        if profile.get("underage"):
            return {"ok":False,"items":[],"more":False}
        ident = profile.get("id") or ident
        rec = self.app._star_extra_get(ident) or {}
        originals = []
        if profile.get("local"):
            portrait = self.app.star_portrait(ident)
            if portrait: originals.append({"url":portrait,"source":"Lokale Bibliothek"})
        originals.extend({"url":url,"source":"Anbieter-Galerie"} for url in rec.get("images") or [] if isinstance(url,str))
        extra = self.runtime.store.cached("sources",ident) or {}
        originals.extend(image for source in source_rows(extra) if source.get("ok") for image in source.get("images") or [])
        originals.extend(image for source in self.boxes.profile_sources(ident) for image in source.get('images') or [])
        originals.extend(self.library.gallery(ident))
        unique = {};originals=[unique.setdefault(row["url"],row) for row in originals if row.get("url") and row["url"] not in unique]
        start = max(0,int(query.get("from") or 0));page = originals[start:start+24]
        items = []
        for index,row in enumerate(page,start+1):
            url,headers = media_library.split_url(row["url"])
            if not url.startswith(("http://","https://")):
                continue
            headers.setdefault("Referer",row.get("page") or rec.get("url") or urllib.parse.urlunsplit((*urllib.parse.urlsplit(url)[:2],"/","","")))
            headers.setdefault("User-Agent","Mozilla/5.0")
            kind = media_library.describe(url,declared="image",info=row)
            token = self.remember_thumbnail(url,headers,kind,profile["name"]+" · Bild "+str(index))
            target = url+"|"+urllib.parse.urlencode(headers)
            items.append({"title":profile["name"]+" · Bild "+str(index),"url":"plugin://plugin.video.adulthideout/?"+urllib.parse.urlencode({"mode":"4","website":"star_finder","url":target,"name":profile["name"]+" · Bild "+str(index)}),"thumb":"/api/star-finder/thumb?token="+token,"cover_token":token,"media":kind,"folder":False,"role":kind["kind"],"source":row.get("source"),"credit":row.get("credit"),"license":row.get("license"),"page":row.get("page")})
        more = start+len(page)<len(originals)
        state=self.status.get("images:"+ident,{})
        return {"ok":True,"items":items,"from":start,"next":start+len(page),"total":len(originals),"more":more,"remote_more":bool(rec.get("image_next")) or "image_next" not in rec or any(row.get("image_continue") for row in source_rows(extra)),"pending":state.get("pending",False),"error":state.get("error","")}

    def expand_images(self,ident,name):
        """One durable background turn, without a fixed lifetime page limit."""
        with self.runtime.key_lock('sources:'+ident):
            record=self.runtime.store.cached('sources',ident) or {}
            for source in source_rows(record):
                if source.get('id')=='wikidata' and source.get('ok') and source.get('image_continue'):
                    previous=source['image_continue']
                    page=self.sources.commons_images(source['entity'],previous)
                    if page.get('image_continue')==previous:raise SourceError('pagination')
                    images={r['url']:r for r in list(source.get('images') or [])+page['images'] if r.get('url')}
                    source.update(images=list(images.values()),image_continue=page.get('image_continue'))
                    self.runtime.store.cache('sources',ident,record,10**12);self.save_source_coverage(ident,record)
        rec=self.app._star_extra_get(ident) or {}
        if not rec or self.app._star_extra_stale(rec):
            self.app._star_enrich(ident,name,log=False)
            rec=self.app._star_extra_get(ident) or {}
        if not rec.get('ok'):
            self.app._star_more_one(ident,name,prefetch=0)
            rec=self.app._star_extra_get(ident) or {}
        if rec.get('ok') and (rec.get('gallery_rev')!=2 or time.time()-float(rec.get('gallery_index_at') or 0)>self.runtime.interval()):
            found=self.app._star_freeones_galleries(name)
            if found is None:raise SourceError('source-error')
            rec={**rec,'image_next':list(dict.fromkeys(list(rec.get('image_next') or [])+found)),
                 'image_pages_seen':[],'gallery_rev':2,'gallery_index_at':time.time()}
            self.app._star_extra_put(ident,rec,save=True)
        if rec.get('image_next'):
            previous=rec['image_next'];self.app._star_gallery_step(ident)
            rec=self.app._star_extra_get(ident) or {}
            if rec.get('image_next')==previous:raise SourceError('pagination')
        if rec.get('reason') in ('blocked','rate-limit','timeout','http'):raise SourceError(rec['reason'])
        return bool(rec.get('image_next')) or any(s.get('image_continue') for s in source_rows(record))

    def more_images(self, query):
        ident,name = self._identity(query)
        profile = self.app.star_profile(ident,name,False)
        if profile.get("underage"):
            return {"ok":False}
        ident = profile["id"]
        def work():
            try:
                with self.runtime.key_lock("sources:"+ident):
                    record=self.runtime.store.cached("sources",ident) or {}
                    for source in source_rows(record):
                        if source.get("id")=="wikidata" and source.get("ok") and source.get("image_continue"):
                            page=self.sources.commons_images(source.get("entity"),source["image_continue"])
                            images={row["url"]:row for row in list(source.get("images") or [])+page["images"] if row.get("url")}
                            source["images"]=list(images.values());source["image_continue"]=page.get("image_continue")
                            self.runtime.store.cache("sources",ident,record,10**12)
                            self.save_source_coverage(ident,record)
                self.app._star_more_one(ident,profile["name"],prefetch=0)
                for _ in range(2):
                    self.app._star_gallery_step(ident)
            except Exception:
                with self.lock:self.status["images:"+ident]={"pending":False,"error":"Die Bildquelle antwortet derzeit nicht. Vorhandene Bilder bleiben erhalten."}
            finally:
                with self.lock:self.status["images:"+ident]={**self.status.get("images:"+ident,{}),"pending":False}
        with self.lock:
            if self.status.get("images:"+ident,{}).get("pending"):
                return {"ok":True,"already":True}
            self.status["images:"+ident]={"pending":True}
        if self.runtime.submit("images:"+ident,work) is None:
            with self.lock:self.status["images:"+ident]={"pending":False}
            return {"ok":False,"error":"Die Warteschlange ist voll. Bitte später erneut versuchen."}
        return {"ok":True,"pending":True}

    def thumbnail(self, token):
        with self.lock:
            row = self.thumb_tokens.get(token)
        if not row or row["expires"]<time.monotonic():
            raise ValueError("Die Bildadresse ist abgelaufen.")
        key = token
        folder = os.path.join(self.app.CACHE_DIR,"star_images")
        path = os.path.join(folder,key+".webp")
        with self.runtime.key_lock("thumbnail:"+key):
            if os.path.isfile(path):
                os.utime(path,None)
                with open(path,"rb") as handle:return handle.read()
            if not self.thumb_slots.acquire(timeout=2):
                raise ValueError("Mehrere Bilder werden geladen. Bitte erneut versuchen.")
            try:
                with urllib.request.urlopen(urllib.request.Request(row["url"],headers=row["headers"]),timeout=12) as response:
                    raw = response.read(16_000_001)
                if len(raw)>16_000_000:raise ValueError("Das Bild überschreitet die Vorschaugrenze.")
                from PIL import Image,ImageOps
                with Image.open(io.BytesIO(raw)) as image:
                    if image.width*image.height>45_000_000:raise ValueError("Das Bild ist für eine Vorschau zu groß.")
                    image=ImageOps.exif_transpose(image);image.thumbnail((480,640));output=io.BytesIO();image.convert("RGB").save(output,"WEBP",quality=78)
                data=output.getvalue()
                if self.app.offline_keep("images"):
                    os.makedirs(folder,exist_ok=True)
                    temp=path+".tmp"
                    with open(temp,"wb") as handle:handle.write(data)
                    os.replace(temp,path)
                    if time.monotonic()-self.last_thumb_trim>300:
                        self.last_thumb_trim=time.monotonic()
                        self.runtime.submit("thumbnail-cache-trim",self.trim_thumbnails)
                return data
            finally:self.thumb_slots.release()

    def cover_bytes(self, token):
        with self.lock:row=self.thumb_tokens.get(token)
        if not row or row['expires']<time.monotonic():raise ValueError('url')
        url=self.app._star_cover_remote(row['url'])
        with urllib.request.urlopen(urllib.request.Request(url,headers=row['headers']),timeout=12) as response:
            data=response.read(8000001)
        return self.app._star_cover_bytes(data)[0]

    def trim_thumbnails(self):
        folder = os.path.join(self.app.CACHE_DIR,"star_images")
        try:
            files = [(entry.stat().st_mtime,entry.stat().st_size,entry.path) for entry in os.scandir(folder) if entry.is_file() and entry.name.endswith(".webp")]
        except OSError:
            return
        total = sum(row[1] for row in files)
        for _,size,path in sorted(files):
            if total<=1024**3:
                break
            try:os.remove(path);total-=size
            except OSError:pass
