"""Durable source-wide performer discovery and fair, recurring enrichment.

Catalogue pages are independent from scene imports. A source entity is never
merged by name alone; unresolved homonyms remain separate, usable profiles.
"""
from __future__ import annotations
import collections
import datetime
import json
import os
import re
import threading
import time
import urllib.parse

from star_sources import clean, mature, normal
from star_runtime import SourceError
from star_stashbox import BOXES, PERFORMER_FIELDS, SCHEMA_VERSION, url_key

SIZE=100
CATALOG_QUERY='query Library($input:PerformerQueryInput!){queryPerformers(input:$input){count performers{'+PERFORMER_FIELDS+'}}}'
PROVIDERS={**{key:row['name'] for key,row in BOXES.items()},'tpdb':'ThePornDB','wikidata':'Wikidata · Erwachsenenfilm-Darsteller','data18':'Data18'}


class SourceLibrary:
    def __init__(self,service):
        self.service=service;self.app=service.app;self.runtime=service.runtime;self.store=self.runtime.store
        self.guard=threading.RLock();self.stop=threading.Event();self.threads=[];self.current={};self.enrich_current=''
        self.card_gate=threading.RLock()
        self.card_refresh_gate=threading.Lock();self.card_built_at=0
        self.card_persisted_at=0
        self.revision=0;self.card_cache=None;self.card_at=0;self.identities=None;self.seed_at=0
        self.enrich_round=0
        self.enrich_active={}
        from star_models_sources import ModelSources
        self.models=getattr(getattr(service,'sources',None),'models',None) or ModelSources(self.runtime)
        with self.store.lock,self.store.db:
            self.store.db.executescript('''
              CREATE TABLE IF NOT EXISTS source_catalog(source TEXT,entity TEXT,profile TEXT,name TEXT,
                payload TEXT NOT NULL,first_seen REAL,checked REAL,seen_run TEXT,PRIMARY KEY(source,entity));
              CREATE INDEX IF NOT EXISTS source_catalog_profile ON source_catalog(profile);
              CREATE INDEX IF NOT EXISTS source_catalog_name ON source_catalog(name);
              CREATE INDEX IF NOT EXISTS source_catalog_counts ON source_catalog(source,profile);
              CREATE TABLE IF NOT EXISTS source_links(url TEXT,profile TEXT,PRIMARY KEY(url,profile));
              CREATE TABLE IF NOT EXISTS source_enrichment(profile TEXT PRIMARY KEY,name TEXT,due REAL DEFAULT 0,
                checked REAL DEFAULT 0,state TEXT DEFAULT 'pending',error TEXT DEFAULT '',attempts INTEGER DEFAULT 0);
              CREATE INDEX IF NOT EXISTS source_enrichment_due ON source_enrichment(due,state);
              CREATE TABLE IF NOT EXISTS source_gallery(profile TEXT,source TEXT,entity TEXT,url TEXT,payload TEXT,
                PRIMARY KEY(profile,source,entity,url));
              CREATE INDEX IF NOT EXISTS source_gallery_profile ON source_gallery(profile);
            ''')
            self.store.db.execute("UPDATE source_enrichment SET state='pending' WHERE state='running'")
        saved=self.store.cached('ui-source-cards','all') or {}
        if saved.get('version')==1 and isinstance(saved.get('cards'),list):
            self.card_cache=saved['cards'];self.card_at=-1

    def start(self):
        with self.guard:
            if self.threads:return
            tasks=[('star-catalogs-'+source,lambda source=source:self.catalog_loop(source)) for source in PROVIDERS]
            tasks += [('star-enrichment-'+str(i),lambda i=i:self.enrichment_loop(i)) for i in range(6)]
            for name,fn in tasks:
                thread=threading.Thread(target=fn,name=name,daemon=True);self.threads.append(thread);thread.start()

    def enabled(self):
        adapters={r['id'] for r in self.models.catalog() if r.get('configured') and r.get('catalogue')}
        return [key for key in PROVIDERS if key in adapters or key=='wikidata' or key=='tpdb' and os.environ.get('AH_TPDB_KEY') or key in BOXES and self.service.boxes.credentials.token(key)]

    def state(self,source):return self.store.cached('source-catalog-state',source) or {}

    def _identity_index(self):
        if self.identities is not None:return self.identities
        names=collections.defaultdict(list);urls={};index=self.app.star_index()
        raw={str(row.get('id')):row for row in index.get('rows') or [] if isinstance(row,dict)}
        cards=list(index['cards'])+list(self.app._star_people_cards())
        for card in cards:
            row=raw.get(str(card['id']),card)
            names[normal(card.get('name'))].append((str(card['id']),str(row.get('birth_date') or '')))
        # Existing confirmed mappings are stronger than names or birth years.
        with self.store.lock:
            keys=[r[0] for r in self.store.db.execute("SELECT key FROM cache WHERE kind='box-state'")]
        for key in keys:
            row=self.store.cached('box-state',key) or {}
            if row.get('entity'):urls[key.split(':',1)[0]+':'+row['entity']]=key.split(':',1)[1]
            for link in (row.get('performer') or {}).get('urls') or []:
                if self.person_link(link.get('url')):urls['url:'+url_key(link['url'])]=key.split(':',1)[1]
        self.identities=(names,urls);return self.identities

    def identity(self,source,row):
        with self.store.lock:
            saved=self.store.db.execute('SELECT profile FROM source_catalog WHERE source=? AND entity=?',(source,str(row['id']))).fetchone()
        if saved and saved[0]:return saved[0]
        names,confirmed=self._identity_index();exact=confirmed.get(source+':'+str(row['id']))
        if exact:return exact
        links=list(row.get('urls') or [])+([{'url':row['url']}] if row.get('url') else [])
        for link in links:
            if not self.person_link(link.get('url')):continue
            target=url_key(link['url']);known=confirmed.get('url:'+target)
            if known:return known
            with self.store.lock:matches=list(self.store.db.execute('SELECT profile FROM source_links WHERE url=?',(target,)))
            if len(matches)==1:return matches[0][0]
        # Cross-provider explicit profile URLs can safely link source identities.
        for link in row.get('urls') or []:
            parsed=urllib.parse.urlsplit(link.get('url',''))
            host=parsed.hostname or '';other='stashdb' if host=='stashdb.org' else 'fansdb' if host=='fansdb.cc' else 'tpdb' if host in ('theporndb.net','www.theporndb.net') else 'wikidata' if host in ('www.wikidata.org','wikidata.org') else ''
            if not other:continue
            entity=parsed.path.rstrip('/').rsplit('/',1)[-1]
            with self.store.lock:
                match=self.store.db.execute('SELECT profile FROM source_catalog WHERE source=? AND entity=?',(other,entity)).fetchone()
            if match:return match[0]
            if confirmed.get(other+':'+entity):return confirmed[other+':'+entity]
        born=str(row.get('birth_date') or '')
        candidates={ident for ident,date in names.get(normal(row['name']),[]) if re.fullmatch(r'\d{4}-\d{2}-\d{2}',born) and date==born}
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}',born):
            with self.store.lock:
                others=list(self.store.db.execute('SELECT profile,payload FROM source_catalog WHERE name=? AND profile!=?',(row['name'],'')))
            candidates.update(profile for profile,payload in others if json.loads(payload).get('birth_date')==born)
        return next(iter(candidates)) if len(candidates)==1 else 'src:'+source+':'+str(row['id'])

    @staticmethod
    def person_link(url):
        p=urllib.parse.urlsplit(str(url or ''));host=(p.hostname or '').removeprefix('www.')
        return host in ('stashdb.org','fansdb.cc','theporndb.net') and p.path.startswith('/performers/') or host=='wikidata.org' and bool(re.fullmatch(r'/wiki/Q\d+',p.path)) or host=='data18.com' and bool(re.fullmatch(r'/name/[^/]+',p.path)) or host=='iafd.com' and p.path.startswith('/person.rme/')

    def upsert(self,source,row,run=''):
        if not isinstance(row,dict) or not row.get('id') or not clean(row.get('name')):raise SourceError('invalid-json')
        entity=str(row['id']);name=clean(row['name']);now=time.time()
        allowed=not row.get('deleted') and mature(row.get('birth_date'))
        ident=self.identity(source,row) if allowed else ''
        previous=self.store.db.execute('SELECT profile,payload,first_seen FROM source_catalog WHERE source=? AND entity=?',(source,entity)).fetchone()
        payload=json.dumps(row,ensure_ascii=False,sort_keys=True);changed=not previous or previous[1]!=payload
        self.store.db.execute('''INSERT INTO source_catalog VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(source,entity)
          DO UPDATE SET profile=excluded.profile,name=excluded.name,payload=excluded.payload,checked=excluded.checked,seen_run=CASE WHEN excluded.seen_run='' THEN source_catalog.seen_run ELSE excluded.seen_run END''',
          (source,entity,ident,name,payload,previous[2] if previous else now,now,run))
        if not ident:return False
        for link in list(row.get('urls') or [])+([{'url':row['url']}] if row.get('url') else []):
            if self.person_link(link.get('url')):self.store.db.execute('INSERT OR IGNORE INTO source_links VALUES(?,?)',(url_key(link['url']),ident))
        self.store.db.execute('''INSERT INTO source_enrichment(profile,name) VALUES(?,?) ON CONFLICT(profile)
          DO UPDATE SET name=excluded.name,due=CASE WHEN ? AND state!='running' THEN 0 ELSE due END''',(ident,name,int(changed)))
        if source in BOXES:
            self.store.db.execute('''INSERT INTO box_queue(source,profile,name) VALUES(?,?,?) ON CONFLICT(source,profile)
              DO UPDATE SET name=excluded.name,due=CASE WHEN ? AND state!='running' THEN 0 ELSE due END''',(source,ident,name,int(changed)))
        for image in row.get('images') or []:
            if image.get('url'):
                record={**image,'source':PROVIDERS[source],'page':row.get('url') or (BOXES[source]['url']+'/performers/'+entity if source in BOXES else ''),'kind':'portrait'}
                self.store.db.execute('INSERT OR REPLACE INTO source_gallery VALUES(?,?,?,?,?)',(ident,source,entity,image['url'],json.dumps(record)))
        if changed:self.revision+=1
        return changed

    def box_performer(self,source,ident):
        with self.store.lock:
            row=self.store.db.execute('SELECT payload,checked FROM source_catalog WHERE source=? AND profile=? AND profile!=? ORDER BY checked DESC LIMIT 1',(source,ident,'')).fetchone()
        return (json.loads(row[0]),row[1]) if row else (None,0)

    def profile(self,ident):
        if not str(ident).startswith('src:'):return None
        with self.store.lock:
            item=self.store.db.execute('SELECT source,payload,first_seen FROM source_catalog WHERE profile=? ORDER BY checked DESC LIMIT 1',(ident,)).fetchone()
        if not item:return None
        source,raw,first=item;row=json.loads(raw)
        if row.get('deleted') or not mature(row.get('birth_date')):return {'underage':True,'id':ident,'name':row['name']}
        portrait=next((p['url'] for p in row.get('images') or [] if p.get('url')),'')
        if portrait and getattr(self.app,'media_url',None):portrait=self.app.media_url(portrait)
        return {'id':ident,'name':row['name'],'local':False,'thumb':portrait,'bio':row.get('description') or '',
                'aliases':row.get('aliases') or [],'tags':[],'facts':[],'source':PROVIDERS[source],
                'source_url':row.get('url') or (BOXES[source]['url']+'/performers/'+str(row['id']) if source in BOXES else ''),
                'birth_date':row.get('birth_date'),'birth_year':int(row['birth_date'][:4]) if re.match(r'^\d{4}',row.get('birth_date') or '') else 0,
                'scene_count':row.get('scene_count') or 0,'movie_count':0,'movies_query':'','first_seen':first}

    def cards(self):
        cached=self.card_cache
        if cached is not None and self.card_at==self.revision:return cached
        # A source page must not force every search to project 100,000 profiles
        # again. Publish a complete replacement, retaining the previous list.
        if cached is not None and len(cached)>10000:
            if time.monotonic()-self.card_built_at>=15 and self.card_refresh_gate.acquire(blocking=False):
                def refresh():
                    try:self._build_cards()
                    finally:self.card_refresh_gate.release()
                threading.Thread(target=refresh,name='source-card-refresh',daemon=True).start()
            return cached
        return self._build_cards()

    def _build_cards(self):
        with self.card_gate:
            if self.card_cache is not None and self.card_at==self.revision:return self.card_cache
            generation=self.revision
            rows=self.store.read_rows("SELECT profile,source,payload,min(first_seen) FROM source_catalog WHERE profile LIKE 'src:%' GROUP BY profile")
            cards=[];label=getattr(self.app,'_label_text',lambda k,v:v)
            for ident,source,raw,first in rows:
                row=json.loads(raw)
                if row.get('deleted') or not mature(row.get('birth_date')):continue
                name=clean(row['name']);born=str(row.get('birth_date') or '');thumb=next((p['url'] for p in row.get('images') or [] if p.get('url')),'')
                age=0
                try:
                    date=datetime.date.fromisoformat(born);today=datetime.date.today();age=today.year-date.year-((today.month,today.day)<(date.month,date.day))
                except ValueError:pass
                cards.append({'id':ident,'name':name,'name_key':name.casefold(),'blob':' '.join([name,*[str(n) for n in row.get('aliases') or []]]).casefold(),
                    'letter':name[:1].upper() if name[:1].isalpha() else '#','thumb':thumb,'photo':bool(thumb),'first_seen':first,
                    'country':label('country',str(row.get('country') or '').lower()),'gender':label('gender',str(row.get('gender') or '').lower()),
                    'hair':label('hair',str(row.get('hair_color') or '').lower()),'eyes':label('eyes',str(row.get('eye_color') or '').lower()),
                    'breast':label('breast',str(row.get('breast_type') or '').lower()),'ethnicity':label('ethnicity',str(row.get('ethnicity') or '').lower()),
                    'cup':row.get('cup_size') or '','year':int(born[:4]) if re.match(r'^\d{4}',born) else 0,'birth_date':born,'age':age,'height':int(str(row.get('height') or '0')) if str(row.get('height') or '0').isdigit() else 0,
                    'flag':'','rank':0,'movies':0,'scenes':row.get('scene_count') or 0,'fame':False,'source':source,'aliases':row.get('aliases') or []})
            self.card_cache=cards;self.card_at=generation;self.card_built_at=time.monotonic()
            if len(cards)>10000 and time.monotonic()-self.card_persisted_at>=120:
                try:
                    self.store.cache('ui-source-cards','all',{'version':1,'cards':cards},30*86400)
                    self.card_persisted_at=time.monotonic()
                except Exception:
                    # A derived list is expendable; the canonical source rows
                    # and the usable in-memory snapshot stay intact.
                    pass
            return cards

    def gallery(self,ident):
        with self.store.lock:rows=list(self.store.db.execute('SELECT payload FROM source_gallery WHERE profile=? ORDER BY source,entity,url',(ident,)))
        return [json.loads(r[0]) for r in rows]

    def image_counts(self):
        with self.guard:
            saved=getattr(self,'gallery_counts',(0,{}))
            if time.monotonic()-saved[0]<20:return saved[1]
            with self.store.lock:counts=dict(self.store.db.execute('SELECT profile,count(DISTINCT url) FROM source_gallery GROUP BY profile'))
            self.gallery_counts=(time.monotonic(),counts);return counts

    def fetch_page(self,source,state):
        page=state.get('page',1)
        if source=='data18':return self.models.fetch_page(source,state)
        if source in BOXES:
            query=CATALOG_QUERY.replace('birth_date','birth_date death_date') if source=='stashdb' else CATALOG_QUERY
            result=self.service.boxes.graphql(source,query,{'input':{'page':page,'per_page':SIZE,'sort':'NAME','direction':state.get('direction','ASC')}}).get('queryPerformers')
            if not isinstance(result,dict) or not isinstance(result.get('performers'),list):raise SourceError('invalid-json')
            return result['performers'],int(result['count']),page*SIZE>=int(result['count'])
        if source=='tpdb':
            token=os.environ.get('AH_TPDB_KEY','').strip()
            if not token:raise SourceError('unconfigured')
            result=self.runtime.json('https://api.theporndb.net/performers?'+urllib.parse.urlencode({'page':page,'per_page':SIZE,'orderBy':'REVERSE_CREATED'}),{'Authorization':'Bearer '+token},ttl=0)
            rows=result.get('data');meta=result.get('meta') or {}
            if not isinstance(rows,list) or 'last' not in meta:raise SourceError('pagination')
            return [self.normalize_tpdb(r) for r in rows],int(meta.get('total') or 0),page>=int(meta['last'])
        # Relevant adult-industry people only; no general-purpose human import.
        cursor=state.get('cursor') or '';after='FILTER(STR(?person) > '+json.dumps(cursor)+')' if cursor else ''
        # The discovery list never picks one of conflicting birth statements.
        # Precise dates are fetched as attributed facts during enrichment.
        query='SELECT DISTINCT ?person WHERE { ?person wdt:P31 wd:Q5; wdt:P106 wd:Q488111. '+after+' } ORDER BY ?person LIMIT '+str(SIZE)
        result=self.runtime.json('https://query.wikidata.org/sparql?'+urllib.parse.urlencode({'query':query,'format':'json'}),{'Accept':'application/sparql-results+json'},ttl=0)
        if not isinstance(result.get('results',{}).get('bindings'),list):raise SourceError('invalid-json')
        bindings=result['results']['bindings'];ids=[];uris={}
        for item in bindings:
            url=item['person']['value'];entity=url.rsplit('/',1)[-1]
            if not re.fullmatch(r'Q\d+',entity):raise SourceError('invalid-json')
            if entity not in uris:ids.append(entity);uris[entity]=url
        entities={}
        # Labels through the entity API avoid an expensive SPARQL label join.
        for start in range(0,len(ids),50):
            params={'action':'wbgetentities','ids':'|'.join(ids[start:start+50]),'props':'labels|aliases|claims','languages':'en|de','format':'json','maxlag':5}
            data=self.runtime.json('https://www.wikidata.org/w/api.php?'+urllib.parse.urlencode(params))
            if not isinstance(data.get('entities'),dict):raise SourceError('invalid-json')
            entities.update(data['entities'])
        rows=[]
        for entity in ids:
            item=entities.get(entity) or {};labels=item.get('labels') or {};name=(labels.get('en') or labels.get('de') or {}).get('value')
            if not name:raise SourceError('invalid-json')
            births={r.get('mainsnak',{}).get('datavalue',{}).get('value',{}).get('time','').lstrip('+')[:10] for r in item.get('claims',{}).get('P569',[]) if r.get('rank')!='deprecated'}
            births={date for date in births if re.fullmatch(r'\d{4}-\d{2}-\d{2}',date) and '-00' not in date}
            rows.append({'id':entity,'name':name,'birth_date':next(iter(births)) if len(births)==1 else None,
                         'aliases':list(dict.fromkeys(a['value'] for values in (item.get('aliases') or {}).values() for a in values)),
                         'url':'https://www.wikidata.org/wiki/'+entity,'urls':[{'url':'https://www.wikidata.org/wiki/'+entity}],'cursor':uris[entity]})
        return rows,0,len(bindings)<SIZE

    @staticmethod
    def normalize_tpdb(row):
        extra=row.get('extras') or {};posters=row.get('posters') or []
        images=[{'url':u} for u in [row.get('image'),*[(p or {}).get('url') for p in posters]] if isinstance(u,str) and u.startswith('https://')]
        return {'id':str(row['id']),'name':row['name'],'birth_date':extra.get('birthday'),'aliases':row.get('aliases') or [],'images':images,
                'url':'https://theporndb.net/performers/'+str(row.get('slug') or row['id']),'description':row.get('bio') or '',
                'urls':[{'url':v} for v in (extra.get('links') or {}).values() if isinstance(v,str) and v.startswith('https://')],
                'country':extra.get('nationality'),'gender':extra.get('gender'),'hair_color':extra.get('hair_colour'),'eye_color':extra.get('eye_colour'),
                'height':extra.get('height'),'cup_size':extra.get('cup'),'original':row}

    def step(self,source):
        state=self.state(source);now=time.time()
        if state.get('next',0)>now:return False
        if source in BOXES and state.get('sort_version')!=1:
            state={**state,'page':1,'complete':False,'seen':0,'run':str(time.time_ns()),'started':now,'sort_version':1,'direction':'ASC'}
        if state.get('complete'):
            state={**state,'page':1,'cursor':'','complete':False,'seen':0,'run':str(time.time_ns()),'started':now}
        if not state:state={'page':1,'run':str(time.time_ns()),'started':now,'seen':0}
        rows,total,finished=self.fetch_page(source,state)
        page=state['page']
        if source in BOXES and (not rows and (page-1)*SIZE<total or len(rows)<SIZE and (page-1)*SIZE+len(rows)<total):raise SourceError('pagination')
        if len({str(r.get('id')) for r in rows})!=len(rows):raise SourceError('pagination')
        self._identity_index()  # Build outside the database lock (legacy state has its own lock).
        with self.store.lock,self.store.db:
            for row in rows:self.upsert(source,row,state['run'])
            seen=self.store.db.execute('SELECT count(*) FROM source_catalog WHERE source=? AND seen_run=?',(source,state['run'])).fetchone()[0]
            if finished and total and seen!=total:
                if source in BOXES:
                    # Equal sort values and source edits may move records across
                    # page boundaries. Verify from the other end in the same run.
                    state.update(direction='DESC' if state.get('direction','ASC')=='ASC' else 'ASC',passes=state.get('passes',0)+1)
                    page=0;finished=False
                else:raise SourceError('pagination')
            if source=='wikidata' and rows and rows[-1].get('cursor')==state.get('cursor'):raise SourceError('pagination')
            state.update(page=page+1,total=total,seen=seen,complete=finished,at=now,error='',next=now+self.runtime.interval() if finished else 0,
                         cursor=rows[-1].get('cursor','') if rows else state.get('cursor',''))
            self.store.cache('source-catalog-state',source,state,10**12)
        self.service.filters.invalidate();return True

    def recent_step(self,source):
        """New/changed records get a separate lane during a long first import."""
        if source not in BOXES:return False
        state=self.store.cached('source-recent-state',source) or {}
        if state.get('next',0)>time.time():return False
        page=state.get('page',1);baseline=state.get('baseline','')
        query=CATALOG_QUERY.replace('birth_date','birth_date death_date') if source=='stashdb' else CATALOG_QUERY
        result=self.service.boxes.graphql(source,query,{'input':{'page':page,'per_page':SIZE,'sort':'UPDATED_AT','direction':'DESC'}}).get('queryPerformers')
        if not isinstance(result,dict) or not isinstance(result.get('performers'),list):raise SourceError('invalid-json')
        rows=result['performers'];total=int(result['count'])
        if len(rows)<SIZE and (page-1)*SIZE+len(rows)<total:raise SourceError('pagination')
        newest=state.get('newest') or (rows[0].get('updated') if rows else '') or ''
        finished=not baseline or page*SIZE>=total or any(str(row.get('updated') or '')<baseline for row in rows)
        self._identity_index()
        with self.store.lock,self.store.db:
            for row in rows:self.upsert(source,row)
            next_state={'page':1 if finished else page+1,'baseline':newest if finished else baseline,
                        'newest':'' if finished else newest,'next':time.time()+min(6*3600,self.runtime.interval()) if finished else 0,'at':time.time()}
            self.store.cache('source-recent-state',source,next_state,10**12)
        self.service.filters.invalidate();return True

    def seed_enrichment(self):
        with self.guard:
            if time.monotonic()-self.seed_at<600:return
            self.seed_at=time.monotonic()
        cards=list(self.app.star_index()['cards'])+list(self.app._star_people_cards())+list(self.app._star_trend_cards())
        with self.store.lock,self.store.db:
            self.store.db.executemany('INSERT OR IGNORE INTO source_enrichment(profile,name) VALUES(?,?)',((str(c['id']),c['name']) for c in cards))

    def enrich_step(self):
        self.seed_enrichment()
        with self.store.lock,self.store.db:
            scope="profile LIKE 'src:%'" if self.enrich_round%2==0 else "profile NOT LIKE 'src:%'"
            self.enrich_round+=1
            base="SELECT profile,name,attempts FROM source_enrichment WHERE due<=? AND state!='running'"
            row=self.store.db.execute(base+' AND '+scope+' ORDER BY checked,due,profile LIMIT 1',(time.time(),)).fetchone()
            if not row:row=self.store.db.execute(base+' ORDER BY checked,due,profile LIMIT 1',(time.time(),)).fetchone()
            if not row:return False
            self.store.db.execute("UPDATE source_enrichment SET state='running' WHERE profile=?",(row[0],))
        ident,name,attempts=row;self.enrich_status(name)
        try:
            self.service.enrich_sources(ident,name)
            more=self.service.expand_images(ident,name)
            sources=self.store.cached('sources',ident) or {}
            errors=[s.get('last_error') or ('partial' if s.get('partial') or s.get('partial_errors') or s.get('images_status')=='partial' else s.get('status') if not s.get('ok') else '') for s in sources.get('sources',{}).values()]
            errors=[e for e in errors if e and e not in ('missing','ambiguous','unconfigured')]
            if errors:raise SourceError(errors[0])
            due=time.time()+(0 if more else self.runtime.interval())
            state='pending' if more else 'done';error='';attempts=0
        except Exception as exc:
            attempts+=1;error=exc.reason if isinstance(exc,SourceError) else 'source-error';state='error'
            due=time.time()+min(86400,300*2**min(attempts,8))
        with self.store.lock,self.store.db:
            self.store.db.execute('UPDATE source_enrichment SET due=?,checked=?,state=?,error=?,attempts=? WHERE profile=?',(due,time.time(),state,error,attempts,ident))
        self.enrich_status('');return True

    def enrich_status(self,name):
        with self.guard:
            key=threading.get_ident()
            if name:self.enrich_active[key]=name
            else:self.enrich_active.pop(key,None)
            self.enrich_current=' · '.join(self.enrich_active.values())

    def run_now(self,job='all'):
        with self.store.lock,self.store.db:
            if job in ('catalogs','all'):
                for source in PROVIDERS:
                    state=self.state(source)
                    if state:self.store.cache('source-catalog-state',source,{**state,'next':0},10**12)
                    recent=self.store.cached('source-recent-state',source)
                    if recent:self.store.cache('source-recent-state',source,{**recent,'next':0},10**12)
            if job in ('enrichment','all'):self.store.db.execute("UPDATE source_enrichment SET due=0 WHERE state!='running'")
        self.start()

    def catalog_loop(self,only=None):
        while not self.stop.is_set():
            worked=False
            for source in self.enabled():
                if only and only!=source:continue
                if self.stop.is_set():return
                self.runtime.wait('catalogs')
                with self.guard:self.current[source]=PROVIDERS[source]
                try:
                    worked=self.recent_step(source) or worked
                    worked=self.step(source) or worked
                except Exception as exc:
                    state=self.state(source);error=exc.reason if isinstance(exc,SourceError) else 'source-error'
                    # Retain a failed page; inconsistent terminal pagination restarts
                    # a verification pass without deleting any imported profile.
                    if error=='pagination':state.update(page=1,cursor='',seen=0,run=str(time.time_ns()),complete=False)
                    self.store.cache('source-catalog-state',source,{**state,'error':error,'next':max(time.time()+600,getattr(exc,'retry_at',0))},10**12)
                finally:
                    with self.guard:self.current.pop(source,None)
            self.stop.wait(.1 if worked else 3)

    def enrichment_loop(self,index=0):
        while not self.stop.is_set():
            if not self.runtime.wait_worker('enrichment',index,'enrichment',self.stop):return
            try:worked=self.enrich_step()
            except Exception:worked=False;self.enrich_status('')
            self.stop.wait(.1 if worked else 3)

    def jobs(self):
        enabled=set(self.enabled());sources=[]
        with self.store.lock:
            counts=dict(self.store.db.execute('SELECT source,count(*) FROM source_catalog WHERE profile!="" GROUP BY source'))
            groups=dict(self.store.db.execute('SELECT state,count(*) FROM source_enrichment GROUP BY state'))
            images=self.store.db.execute('SELECT count(*) FROM source_gallery').fetchone()[0]
        for key,name in PROVIDERS.items():
            state=self.state(key);sources.append({'id':key,'name':name,'configured':key in enabled,'stored':counts.get(key,0),**state})
        sources.extend([
            {'id':'babepedia','name':'Babepedia','configured':True,'note':'Eigener Sitemap-Lauf „Neue Profile entdecken“; Zugriffsfehler bleiben dort offen.'},
            {'id':'analvids','name':'AnalVids','configured':True,'note':'Eigener vollständiger Namenskatalog-Lauf „AnalVids-Katalog“.'},
            *[{'id':key,'name':name,'configured':True,'note':'Ergänzung bestätigter/bekannter Profile; ein vollständiger Quellkatalog ist noch nicht angebunden.','scope':'profile-only'} for key,name in [('freeones','FreeOnes'),('iafd','IAFD'),('grokipedia','Grokipedia')]]])
        total=sum(s.get('total') or 0 for s in sources);seen=sum(s.get('seen') or 0 for s in sources)
        with self.guard:current=' · '.join(self.current.values())
        return [{'id':'catalogs','title':'Alle Quellkataloge · neue Stars','running':bool(current),'paused':self.runtime.paused('catalogs'),
                 'what':current or 'Quellkataloge werden regelmäßig vollständig geprüft','done':seen,'total':total,
                 'note':f'{sum(counts.values()):,} Quellprofile dauerhaft gespeichert · {images:,} Bildadressen aus Quellen und Szenen','sources':sources},
                {'id':'enrichment','title':'Alle Stars · Quellen & vollständige Galerien','running':bool(self.enrich_current),'paused':self.runtime.paused('enrichment'),
                 'what':self.enrich_current or 'Infos und veröffentlichte Galerieseiten aller gespeicherten Stars',
                 'done':groups.get('done',0),'total':sum(groups.values()),'note':f"{groups.get('pending',0):,} vorgemerkt · {groups.get('error',0):,} mit erneutem Abruf"}]
