"""Read-only StashDB/FansDB integration with durable scene pages and provenance."""
from __future__ import annotations

import base64
import collections
import ctypes
import json
import os
from pathlib import Path
import re
import threading
import time
import urllib.parse

from star_runtime import SourceError
from star_sources import clean, identity, mature, normal

BOXES = {
    'stashdb': {'name':'StashDB','endpoint':'https://stashdb.org/graphql','url':'https://stashdb.org'},
    'fansdb': {'name':'FansDB','endpoint':'https://fansdb.cc/graphql','url':'https://fansdb.cc'},
}
SCHEMA_VERSION = 2
PERFORMER_FIELDS = '''id name disambiguation aliases birth_date gender ethnicity country hair_color eye_color height
 cup_size band_size waist_size hip_size breast_type career_start_year career_end_year scene_count deleted
 tattoos { location description } piercings { location description }
 studios { studio { id name } scene_count } urls { url } images { url width height } created updated'''
FIND = 'query StarFinder($id: ID!) { findPerformer(id:$id) { '+PERFORMER_FIELDS+' } }'
SEARCH = 'query StarFinder($name: String!) { searchPerformer(term:$name,limit:20) { '+PERFORMER_FIELDS+' } }'
SCENES = '''query StarScenes($input: SceneQueryInput!) { queryScenes(input:$input) {
 count scenes { id title details release_date duration deleted director code created updated
 studio { id name urls { url } parent { id name } } urls { url } images { url width height } performers { performer { id name } }
 tags { id name category { id name group } } } } }'''
PAGE_SIZE = 50
STATUS = {'missing':'Kein passender Eintrag','ambiguous':'Zuordnung muss bestätigt werden',
          'blocked':'Schlüssel oder Zugriff von der Quelle abgelehnt','rate-limit':'Abruflimit – wird später fortgesetzt',
          'timeout':'Quelle antwortet derzeit nicht','source-error':'Quelle meldet einen Fehler',
          'invalid-json':'Quellantwort nicht lesbar','pagination':'Seitenantwort unvollständig',
          'unconfigured':'API-Schlüssel fehlt','matched':'Zugeordnet','complete':'Quellbestand vollständig eingelesen',
          'partial':'Szenen werden ergänzt','queued':'Zum Abruf vorgemerkt'}


def crypt(raw, decrypt=False):
    """Windows user-bound DPAPI; no key appears in application settings or logs."""
    if os.name != 'nt':
        return raw
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
    buffer=ctypes.create_string_buffer(raw)
    source=Blob(len(raw),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)));target=Blob()
    fn=ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target)):
        raise OSError('Der Quellenschlüssel konnte nicht geschützt gelesen/gespeichert werden.')
    try:return ctypes.string_at(target.data,target.size)
    finally:ctypes.windll.kernel32.LocalFree(target.data)


class Credentials:
    def __init__(self, folder):
        self.path=Path(folder)/'star_source_credentials.json';self.lock=threading.RLock()

    def read(self):
        with self.lock:
            if not self.path.exists():return {}
            data=json.loads(self.path.read_text(encoding='utf-8'))
            return json.loads(crypt(base64.b64decode(data['protected']),True))

    def token(self, source, include_disabled=False):
        variable='AH_STASHDB_KEY' if source=='stashdb' else 'AH_FANSDB_KEY'
        row=self.read().get(source,{})
        if row.get('enabled') is False and not include_disabled:return ''
        return str(row.get('key') or os.environ.get(variable,'')).strip()

    def save(self, source, key=None, enabled=True):
        if source not in BOXES:raise ValueError('Unbekannte Szenenquelle.')
        with self.lock:
            rows=self.read();row=rows.setdefault(source,{})
            if key is not None:
                key=str(key).strip()
                if not 10<=len(key)<=8000 or re.search(r'[\s\x00-\x1f]',key):
                    raise ValueError('Bitte den vollständigen API-Schlüssel eintragen.')
                row['key']=key
            row['enabled']=bool(enabled)
            self.path.parent.mkdir(parents=True,exist_ok=True)
            temp=self.path.with_suffix('.tmp')
            raw=json.dumps(rows).encode()
            temp.write_text(json.dumps({'protection':'DPAPI-current-user' if os.name=='nt' else 'user-file',
                                       'protected':base64.b64encode(crypt(raw)).decode()}),encoding='utf-8')
            os.chmod(temp,0o600);os.replace(temp,self.path)


def url_key(value):
    parsed=urllib.parse.urlsplit(str(value or ''))
    return parsed.netloc.lower().removeprefix('www.')+parsed.path.rstrip('/').lower()


class StashBox:
    def __init__(self, service):
        self.service=service;self.app=service.app;self.runtime=service.runtime;self.store=self.runtime.store
        self.credentials=Credentials(Path(self.store.path).parent)
        self.wake=threading.Event();self.stop=threading.Event();self.thread=None
        self.guard=threading.RLock();self.current='';self.seed_at=0
        self.threads=[];self.current_active={}
        with self.store.lock,self.store.db:
            self.store.db.executescript('''
              CREATE TABLE IF NOT EXISTS box_queue(source TEXT,profile TEXT,name TEXT,due REAL DEFAULT 0,
                priority INTEGER DEFAULT 0,state TEXT DEFAULT 'pending',PRIMARY KEY(source,profile));
              CREATE TABLE IF NOT EXISTS box_scenes(source TEXT,profile TEXT,id TEXT,payload TEXT,run TEXT,
                PRIMARY KEY(source,profile,id));
              CREATE INDEX IF NOT EXISTS box_queue_due ON box_queue(state,due,priority);
            ''')
            self.store.db.execute("UPDATE box_queue SET state='pending' WHERE state='running'")

    def catalog(self):
        return [dict(id=key,name=row['name'],url=row['url'],endpoint=row['endpoint'],kind='key',
                     configured=bool(self.credentials.token(key)),note='Profile und vollständige Szenenlisten mit Original-Tags und Quellkategorien.')
                for key,row in BOXES.items()]

    def graphql(self, source, query, variables, token=None):
        token=token or self.credentials.token(source)
        if not token:raise SourceError('unconfigured')
        data=json.dumps({'query':query,'variables':variables}).encode()
        response=self.runtime.request(BOXES[source]['endpoint'],{'ApiKey':token,'Content-Type':'application/json'},
                                      ttl=0,limit=8_000_000,timeout=25,data=data)
        try:body=json.loads(response['body'])
        except (ValueError,TypeError):raise SourceError('invalid-json') from None
        if body.get('errors'):
            messages=' '.join(str(row.get('message','')) for row in body['errors']).lower()
            reason='blocked' if any(word in messages for word in ('unauthorized','authentication','permission','access denied','api key')) else 'rate-limit' if 'rate' in messages or 'limit exceeded' in messages else 'source-error'
            raise SourceError(reason,time.time()+(300 if reason=='rate-limit' else 1800))
        if not isinstance(body.get('data'),dict):raise SourceError('invalid-json')
        return body['data']

    def configure(self, body):
        source=body.get('source')
        if source not in BOXES:raise ValueError('Unbekannte Szenenquelle.')
        key=body.get('key') or None
        available=key or self.credentials.token(source,True)
        if body.get('enabled',True) and not available:
            raise ValueError('Bitte zuerst den eigenen '+BOXES[source]['name']+'-API-Schlüssel eintragen.')
        if key or (body.get('enabled',True) and available):
            # Verify before replacing a previously working key.
            if key:
                with self.runtime.lock:
                    state=self.runtime.hosts.get(urllib.parse.urlsplit(BOXES[source]['endpoint']).hostname)
                    if state and state.get('error')=='blocked':state.update(cool=0,error='')
            data=self.graphql(source,'query StarConnection { me { id } }',{},str(available).strip())
            if not data.get('me'):raise SourceError('blocked')
        self.credentials.save(source,key,body.get('enabled',True))
        if key:
            with self.runtime.lock:
                state=self.runtime.hosts.get(urllib.parse.urlsplit(BOXES[source]['endpoint']).hostname)
                if state:state.update(cool=0,error='')
        self.seed_at=0;self.start();self.wake.set()
        return {'ok':True,'sources':self.catalog()}

    def profile_sources(self, ident):
        sources=[]
        labels={'birth_date':'Geburtsdatum','country':'Staatsangehörigkeit','hair_color':'Haarfarbe',
                'eye_color':'Augenfarbe','height':'Größe','career_start_year':'Karrierebeginn',
                'career_end_year':'Karriereende','scene_count':'Szenen in der Quelle',
                'gender':'Geschlecht','ethnicity':'Ethnische Herkunft','breast_type':'Brust',
                'cup_size':'Cup-Größe','band_size':'Unterbrustumfang','waist_size':'Taillenumfang',
                'hip_size':'Hüftumfang','death_date':'Verstorben','disambiguation':'Zusatz zur Namensunterscheidung'}
        for source,config in BOXES.items():
            state=self.state(source,ident);performer=state.get('performer') or {}
            library=getattr(self.service,'library',None)
            if library:
                latest,observed=library.box_performer(source,ident)
                if latest and (not performer or observed>float(state.get('at') or 0)):
                    performer={**performer,**latest};state={**state,'at':observed}
            if not performer:continue
            url=config['url']+'/performers/'+performer['id']
            facts=[{'label':label,'value':str(performer[key])+(' cm' if key=='height' else ''),
                    'source':config['name'],'url':url,'at':state.get('at'),'raw_field':key} for key,label in labels.items() if performer.get(key) is not None and performer[key]!='']
            translate=getattr(self.app,'_label_text',lambda key,value:value)
            for fact in facts:
                field={'hair_color':'hair','eye_color':'eyes','breast_type':'breast'}.get(fact['raw_field'],fact['raw_field'])
                if field in ('hair','eyes','breast','country','ethnicity','gender'):
                    fact['raw_value']=fact['value'];fact['value']=translate(field,fact['value'].lower()) or fact['value']
            for key,label in (('tattoos','Tätowierungen'),('piercings','Piercings')):
                for row in performer.get(key) or []:
                    text=' · '.join(clean(row.get(k)) for k in ('location','description') if clean(row.get(k)))
                    if text:facts.append({'label':label,'value':text,'source':config['name'],'url':url,'at':state.get('at')})
            sources.append({'id':source,'name':config['name'],'ok':True,'status':'matched','entity':performer['id'],
                            'at':state.get('at'),'url':url,'facts':facts,'aliases':performer.get('aliases') or [],
                            'images':[{'url':r['url'],'source':config['name'],'page':url} for r in performer.get('images') or []],
                            'links':[{'label':urllib.parse.urlsplit(r['url']).hostname or config['name'],'url':r['url']} for r in performer.get('urls') or []],
                            'performer':performer,'schema_version':state.get('schema_version',1)})
        return sources

    def state(self, source, ident):
        return self.store.cached('box-state',source+':'+ident) or {}

    def start(self):
        with self.guard:
            if self.thread and self.thread.is_alive():return
            self.threads=[threading.Thread(target=self.loop,args=(i,),name='star-box-scenes-'+str(i),daemon=True) for i in range(4)]
            self.thread=self.threads[0]
            for thread in self.threads:thread.start()

    def enqueue(self, ident, name='', force=False):
        if not ident:return
        with self.store.lock,self.store.db:
            for source in BOXES:
                if not self.credentials.token(source):continue
                if force:
                    state=self.state(source,ident)
                    if state.get('complete'):
                        self.store.cache('box-state',source+':'+ident,{**state,'refresh_requested':True},10**12)
                self.store.db.execute('''INSERT INTO box_queue(source,profile,name,priority) VALUES(?,?,?,10)
                  ON CONFLICT(source,profile) DO UPDATE SET name=excluded.name,
                  priority=10,due=CASE WHEN ? THEN 0 ELSE box_queue.due END,
                  state=CASE WHEN box_queue.state='running' OR (box_queue.due>? AND ?=0) THEN box_queue.state ELSE 'pending' END''',
                  (source,ident,name,int(force),time.time(),int(force)))
        self.start();self.wake.set()

    def seed(self):
        with self.guard:
            if time.monotonic()-self.seed_at<3600:return
            self.seed_at=time.monotonic()
        index=self.app.star_index()
        # More complete local profiles first, then the rest; no API request on the UI thread.
        cards=list(index['cards'])+list(self.app._star_people_cards())+list(self.app._star_trend_cards())
        if getattr(self.service,'library',None):cards+=self.service.library.cards()
        with self.store.lock,self.store.db:
            for source in BOXES:
                if not self.credentials.token(source):continue
                marker='box-schema:'+source
                if (self.store.cached('box-config',marker) or {}).get('version')!=SCHEMA_VERSION:
                    self.store.db.execute("UPDATE box_queue SET due=0,state='pending',priority=max(priority,1) WHERE source=? AND state!='running' AND state!='pending'",(source,))
                    self.store.cache('box-config',marker,{'version':SCHEMA_VERSION},10**12)
                self.store.db.executemany('INSERT OR IGNORE INTO box_queue(source,profile,name) VALUES(?,?,?)',
                                         ((source,str(row['id']),row['name']) for row in cards))

    def resolve(self, source, ident, name, state):
        library=getattr(self.service,'library',None)
        if library:
            performer,observed=library.box_performer(source,ident)
            if performer and not performer.get('deleted') and mature(performer.get('birth_date')):return performer
        profile=self.service.get_profile({'id':ident,'name':name})
        if profile.get('underage'):raise SourceError('missing')
        confirmed=(self.store.cached('box-mapping',source+':'+ident) or {}).get('entity')
        saved=state.get('entity')
        if saved or confirmed:
            row=self.graphql(source,FIND.replace('birth_date','birth_date death_date') if source=='stashdb' else FIND,{'id':confirmed or saved}).get('findPerformer')
            if row and not row.get('deleted') and mature(row.get('birth_date')):
                return row
            raise SourceError('missing')
        rows=self.graphql(source,SEARCH.replace('birth_date','birth_date death_date') if source=='stashdb' else SEARCH,{'name':profile.get('name') or name}).get('searchPerformer') or []
        links={url_key(row.get('url')) for row in (profile.get('extra') or {}).get('links') or []
               if row.get('url') and len(urllib.parse.urlsplit(row['url']).path.rstrip('/'))>1}
        matched=[];precise=[]
        for row in rows:
            if row.get('deleted') or not mature(row.get('birth_date')):continue
            same_links=links & {url_key(item.get('url')) for item in row.get('urls') or [] if item.get('url')}
            check=dict(profile)
            if same_links:check['source_ids']={source:row['id']}
            if identity(check,[row['name'],*(row.get('aliases') or [])],row.get('birth_date'),row['id'] if same_links else ''):
                matched.append(row)
                born=str(profile.get('birth_date') or '')
                if normal(row['name'])==normal(profile.get('name')) and re.fullmatch(r'\d{4}-\d{2}-\d{2}',born) and born==row.get('birth_date'):
                    precise.append(row)
        if len(precise)==1:matched=precise
        if len(matched)!=1:
            candidates=[{'id':r['id'],'name':r['name'],'birth_date':r.get('birth_date'),'scenes':r.get('scene_count'),
                         'url':BOXES[source]['url']+'/performers/'+r['id']} for r in rows if not r.get('deleted') and mature(r.get('birth_date'))]
            self.store.cache('box-state',source+':'+ident,{'status':'ambiguous' if rows else 'missing','candidates':candidates,'at':time.time()},10**12)
            raise SourceError('ambiguous' if rows else 'missing')
        return matched[0]

    def ingest(self, source, ident, name):
        key=source+':'+ident
        with self.runtime.key_lock('box:'+key):
            state=self.state(source,ident)
            current_schema=state.get('schema_version')==SCHEMA_VERSION
            if current_schema and state.get('complete') and not state.get('refresh_requested') and time.time()-state.get('at',0)<self.runtime.interval():
                if (self.store.cached('box-summary',ident) or {}).get('at',0)<state.get('at',0):self.summarize(ident)
                return True
            if not current_schema or not state.get('entity') or state.get('complete'):
                performer=self.resolve(source,ident,name,state)
                state={'entity':performer['id'],'performer':performer,'name':performer['name'],
                       'page':1,'run':str(time.time_ns()),'status':'partial','complete':False,'at':time.time(),'schema_version':SCHEMA_VERSION}
                self.store.cache('box-state',key,state,10**12)
            page=state.get('page',1);entity=state['entity']
            query=SCENES.replace('release_date','release_date production_date') if source=='stashdb' else SCENES
            result=self.graphql(source,query,{'input':{'performers':{'value':[entity],'modifier':'INCLUDES'},
                             'page':page,'per_page':PAGE_SIZE,'sort':'CREATED_AT','direction':'ASC'}}).get('queryScenes')
            if not isinstance(result,dict) or not isinstance(result.get('scenes'),list):raise SourceError('invalid-json')
            scenes=result['scenes'];total=int(result['count'])
            if (not scenes and (page-1)*PAGE_SIZE<total) or (len(scenes)<PAGE_SIZE and (page-1)*PAGE_SIZE+len(scenes)<total):
                raise SourceError('pagination')
            kept=[]
            for row in scenes:
                if row.get('deleted'):continue
                # Never trust an unexpected scene merely because it was returned by a filter.
                if entity not in {p.get('performer',{}).get('id') for p in row.get('performers') or []}:continue
                scene={'id':row['id'],'title':clean(row.get('title')) or 'Ohne Titel','date':row.get('release_date'),
                       'duration':row.get('duration'),'studio':(row.get('studio') or {}).get('name',''),
                       'director':clean(row.get('director')),'code':clean(row.get('code')),
                       'details':clean(row.get('details')),'production_date':row.get('production_date'),
                       'urls':[r for r in row.get('urls') or [] if r.get('url')],
                       'images':row.get('images') or [],'studio_info':row.get('studio') or {},
                       'created':row.get('created'),'updated':row.get('updated'),
                       'url':BOXES[source]['url']+'/scenes/'+row['id'],'source':source,'source_name':BOXES[source]['name'],
                       'tags':[{'id':t['id'],'name':clean(t['name']),'category':t.get('category')} for t in row.get('tags') or [] if t.get('id') and clean(t.get('name'))],
                       'performers':[{'id':p['performer']['id'],'name':clean(p['performer']['name'])} for p in row.get('performers') or [] if p.get('performer')],
                       'at':time.time()}
                kept.append(scene)
            complete=page*PAGE_SIZE>=total
            state.update(page=page+1,total=total,complete=complete,status='complete' if complete else 'partial',at=time.time())
            state.pop('error',None)
            # Page data and the resume cursor are committed together, including zero-scene performers.
            with self.store.lock,self.store.db:
                self.store.db.executemany('''INSERT INTO box_scenes VALUES(?,?,?,?,?) ON CONFLICT(source,profile,id)
                  DO UPDATE SET payload=excluded.payload,run=excluded.run''',
                  ((source,ident,r['id'],json.dumps(r,ensure_ascii=False),state['run']) for r in kept))
                if getattr(self.service,'library',None):
                    for scene in kept:
                        for picture in scene.get('images') or []:
                            if picture.get('url'):
                                image={**picture,'source':BOXES[source]['name']+' · Szenenbild','page':scene['url'],'kind':'scene','scene':scene['title']}
                                self.store.db.execute('INSERT OR REPLACE INTO source_gallery VALUES(?,?,?,?,?)',(ident,source,'scene:'+scene['id'],picture['url'],json.dumps(image)))
                if complete:
                    actual=self.store.db.execute('SELECT count(*) FROM box_scenes WHERE source=? AND profile=? AND run=?',(source,ident,state['run'])).fetchone()[0]
                    if actual!=total:
                        # Moving/deleted/duplicated source pages must not look complete.
                        # Keep good evidence and retry a fresh stable traversal later.
                        complete=False
                        state.update(complete=False,status='partial',error='pagination',page=1,run=str(time.time_ns()))
                    else:self.store.db.execute('DELETE FROM box_scenes WHERE source=? AND profile=? AND run!=?',(source,ident,state['run']))
                self.store.db.execute('INSERT INTO cache VALUES(?,?,?,?) ON CONFLICT(kind,key) DO UPDATE SET payload=excluded.payload,expires=excluded.expires',
                                      ('box-state',key,json.dumps(state),time.time()+10**12))
            self.summarize(ident)
            if state.get('error')=='pagination':raise SourceError('pagination')
            return complete

    def summarize(self, ident):
        tags={};categories={};counts=collections.Counter();studios=set();networks=set();directors=set()
        with self.store.lock:
            rows=list(self.store.db.execute('SELECT source,payload FROM box_scenes WHERE profile=?',(ident,)))
        for source,raw in rows:
            scene=json.loads(raw);counts[source]+=1
            if scene.get('studio'):studios.add(scene['studio'])
            network=((scene.get('studio_info') or {}).get('parent') or {}).get('name')
            if network:networks.add(network)
            if scene.get('director'):directors.add(scene['director'])
            for tag in {t['id']:t for t in scene['tags']}.values():
                key=source+':'+tag['id']
                entry=tags.setdefault(key,dict(tag,source=source,source_name=BOXES[source]['name'],count=0))
                entry['count']+=1
                category=tag.get('category') or {}
                if category.get('name'):
                    key=source+':'+category['id']
                    categories.setdefault(key,dict(category,source=source,source_name=BOXES[source]['name']))
        summary={'tags':sorted(tags.values(),key=lambda t:(-t['count'],t['name'].casefold())),
                 'categories':sorted(categories.values(),key=lambda t:t['name'].casefold()),'counts':dict(counts),'at':time.time(),
                 'studios':sorted(studios),'networks':sorted(networks),'directors':sorted(directors)}
        attributes=collections.defaultdict(set)
        fields={'hair_color':'hair','eye_color':'eyes','breast_type':'breast','gender':'gender','country':'country',
                'ethnicity':'ethnicity','cup_size':'cup','career_start_year':'career_start','career_end_year':'career_end'}
        for source in self.profile_sources(ident):
            p=source['performer'];attributes['sources'].add(source['name'])
            for key,group in fields.items():
                if p.get(key) is not None and str(p[key]).strip():attributes[group].add(str(p[key]).lower() if key in ('hair_color','eye_color','breast_type','gender','ethnicity') else str(p[key]))
            for key in ('tattoos','piercings'):
                for row in p.get(key) or []:
                    text=' · '.join(clean(row.get(k)) for k in ('location','description') if clean(row.get(k)))
                    if text:attributes[key].add(text)
            born=re.match(r'^\d{4}',p.get('birth_date') or '')
            if born:attributes['birthyear'].add(born[0])
            if p.get('height'):attributes['height'].add(str(p['height'])+' cm')
            for row in p.get('studios') or []:
                if (row.get('studio') or {}).get('name'):studios.add(row['studio']['name'])
        attributes.update(studios=studios,networks=networks,directors=directors)
        attributes['acts']={t['name'] for t in summary['tags'] if normal((t.get('category') or {}).get('name'))=='acts'}
        self.store.cache('box-summary',ident,summary,10**12)
        self.store.cache('box-features',ident,{'tags':[t['name'] for t in summary['tags']],
                                             'categories':[c['name'] for c in summary['categories']],
                                             'attributes':{k:sorted(v) for k,v in attributes.items()}},10**12)
        self.service.filters.invalidate()
        return summary

    def summary(self, ident):
        result=self.store.cached('box-summary',ident) or {'tags':[],'categories':[],'counts':{}}
        result['profiles']=self.profile_sources(ident)
        result['sources']=[dict(id=s,source_name=b['name'],configured=bool(self.credentials.token(s)),
                          **{k:v for k,v in self.state(s,ident).items() if k in ('status','at','total','complete','name','entity','error','candidates')})
                           for s,b in BOXES.items()]
        return result

    def content(self, query):
        ident=str(query.get('id') or '')[:100]
        source=str(query.get('source') or '')
        tag=str(query.get('tag') or '')
        search=normal(query.get('q'))
        offset=max(0,int(query.get('from') or 0));limit=25
        with self.store.lock:
            raw=list(self.store.db.execute('SELECT payload FROM box_scenes WHERE profile=? ORDER BY source,id',(ident,)))
        rows=[]
        for item, in raw:
            row=json.loads(item)
            if source and row['source']!=source:continue
            if tag and tag not in {t['id'] for t in row['tags']}:continue
            if search and search not in normal(' '.join([row['title'],row['studio'],*(t['name'] for t in row['tags'])])):continue
            rows.append(row)
        rows.sort(key=lambda r:(r.get('date') or '',r['id']),reverse=True)
        return {'ok':True,'items':rows[offset:offset+limit],'total':len(rows),'next':offset+limit,
                'more':offset+limit<len(rows),'summary':self.summary(ident)}

    def confirm(self, body):
        source=body.get('source');ident=str(body.get('id') or '')[:100];entity=str(body.get('entity') or '')
        if source not in BOXES or not ident:raise ValueError('Profil oder Quelle fehlt.')
        state=self.state(source,ident)
        if entity not in {r['id'] for r in state.get('candidates') or []}:raise ValueError('Bitte einen aktuell angebotenen Quelltreffer wählen.')
        self.store.cache('box-mapping',source+':'+ident,{'entity':entity,'confirmed_at':time.time()},10**12)
        self.store.discard_cache('box-state',source+':'+ident)
        self.enqueue(ident,body.get('name') or '',True)
        return {'ok':True,'pending':True}

    def job(self):
        with self.store.lock:
            groups=list(self.store.db.execute('SELECT source,state,count(*) FROM box_queue GROUP BY source,state'))
            scenes=self.store.db.execute('SELECT count(*) FROM box_scenes').fetchone()[0]
        configured={s['id'] for s in self.catalog() if s['configured']}
        counts=collections.Counter()
        for source,state,n in groups:
            if source in configured:counts[state]+=n
        total=sum(counts.values());done=counts['done']+counts['missing']+counts['ambiguous']
        return {'id':'scenes','title':'StashDB & FansDB · Szenen und Tags','running':bool(self.current),'done':done,'total':total,
                'paused':self.runtime.paused('scenes'),'what':self.current or ('Wartet auf API-Schlüssel' if not configured else 'Szenen und Quellzuordnungen werden gespeichert'),
                'note':f"{scenes:,} gespeicherte Szenenzuordnungen · {counts['done']:,} Profile eingelesen · {counts['ambiguous']:,} Zuordnungen offen · {counts['missing']:,} ohne Treffer · {counts['error']:,} Abrufe später erneut"}

    def run_now(self):
        with self.store.lock,self.store.db:
            self.store.db.execute("UPDATE box_queue SET due=0 WHERE state!='running'")
        self.seed_at=0;self.start();self.wake.set()

    def set_current(self,name):
        with self.guard:
            key=threading.get_ident()
            if name:self.current_active[key]=name
            else:self.current_active.pop(key,None)
            self.current=' · '.join(self.current_active.values())

    def loop(self,index=0):
        while not self.stop.is_set():
            row=None
            try:
                if not self.runtime.wait_worker('scenes',index,'scenes',self.stop):return
                self.seed()
                enabled=[s['id'] for s in self.catalog() if s['configured']]
                row=None
                with self.store.lock,self.store.db:
                    if enabled:
                        row=self.store.db.execute('SELECT source,profile,name FROM box_queue WHERE source IN ('+','.join('?'*len(enabled))+') AND due<=? AND state!=\'running\' ORDER BY priority DESC,due,profile LIMIT 1',(*enabled,time.time())).fetchone()
                    if row:self.store.db.execute("UPDATE box_queue SET state='running' WHERE source=? AND profile=?",row[:2])
                if not row:
                    self.wake.wait(3);self.wake.clear();continue
                source,ident,name=row;self.set_current(BOXES[source]['name']+' · '+name)
                try:
                    complete=self.ingest(source,ident,name)
                    status='done' if complete else 'pending';due=time.time()+(self.runtime.interval() if complete else 0)
                except SourceError as error:
                    status=error.reason if error.reason in ('missing','ambiguous') else 'error'
                    delay=7*86400 if status in ('missing','ambiguous') else 1800 if error.reason=='blocked' else 300
                    due=max(time.time()+delay,error.retry_at)
                    state=self.state(source,ident);state.update(error=error.reason,last_attempt=time.time())
                    self.store.cache('box-state',source+':'+ident,state|({'status':error.reason} if not state.get('entity') else {}),10**12)
                with self.store.lock,self.store.db:
                    self.store.db.execute('UPDATE box_queue SET state=?,due=?,priority=CASE WHEN ? THEN 0 ELSE priority END WHERE source=? AND profile=?',
                                          (status,due,int(status!='pending'),source,ident))
            except Exception:
                # No raw exception/HTTP text: credentials must not reach logs or the UI.
                if 'row' in locals() and row:
                    with self.store.lock,self.store.db:
                        self.store.db.execute("UPDATE box_queue SET state='error',due=? WHERE source=? AND profile=?",(time.time()+300,*row[:2]))
                    key=row[0]+':'+row[1];state=self.state(row[0],row[1])
                    self.store.cache('box-state',key,{**state,'error':'source-error','last_attempt':time.time()},10**12)
                self.stop.wait(2)
            finally:self.set_current('')
