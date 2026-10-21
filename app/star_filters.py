"""Local, source-backed multi-value inclusion/exclusion filters for Star Finder."""
from __future__ import annotations
import collections
import functools
import json
import os
from pathlib import Path
import re
import threading
import time

from star_sources import clean, normal

GROUPS=('hair','eyes','build','breast','orientation','tags','scenes','acts','categories','content',
        'studios','networks','directors','sources','gender','country','ethnicity','cup','birthyear','height','career_start','career_end','tattoos','piercings')
BLOCKED=frozenset({'teen','teens','underage','preteen','lolita','jailbait','child','children','incest'})
SCENE_LABELS={'solo':'Solo','boy girl':'Frau/Mann','girl girl':'Frau/Frau','special':'Spezial'}
ORIENTATION_LABELS={'straight':'Hetero','heterosexual':'Hetero','bisexual':'Bisexuell','pansexual':'Pansexuell','lesbian':'Lesbisch','gay':'Schwul'}
FACT_GROUPS={
    'haar':'hair','haarfarbe':'hair','haar babepedia':'hair','hair color':'hair','hair colour':'hair',
    'augen':'eyes','augenfarbe':'eyes','augen babepedia':'eyes','eye color':'eyes','eye colour':'eyes','eyes':'eyes',
    'figur':'build','figur babepedia':'build','korperbau':'build','build':'build','body type':'build','statur':'build',
    'brust':'breast','brust babepedia':'breast','breast':'breast','oberweite':'breast',
    'sexualitat':'orientation','sexuality':'orientation','orientation':'orientation',
}

@functools.lru_cache(maxsize=16384)
def allowed_label(value):
    tokens=re.split(r'[^0-9a-z]+', str(value or '').casefold())
    return not any(token in BLOCKED for token in tokens)

def split_acts(value):
    if isinstance(value,str):return [part.strip() for part in value.split(',') if part.strip()]
    return value

def labels(value):
    if isinstance(value,str):value=[value]
    if not isinstance(value,(list,tuple,set)):return []
    return [clean(v.get('name') or v.get('label')) if isinstance(v,dict) else clean(v) for v in value if isinstance(v,(str,dict))]

def rules_from(value):
    if isinstance(value,str):
        if len(value)>20000:raise ValueError('Zu viele Filter ausgewählt.')
        try:value=json.loads(value)
        except ValueError:raise ValueError('Die Merkmalsfilter sind ungültig.') from None
    if value is None:value={}
    if not isinstance(value,dict):raise ValueError('Die Merkmalsfilter sind ungültig.')
    result={}
    for group in GROUPS:
        row=value.get(group) or {}
        if not isinstance(row,dict):raise ValueError('Ungültige Filtergruppe.')
        target={}
        for key in ('include','exclude'):
            values=row.get(key) or []
            if not isinstance(values,list) or len(values)>64 or any(not isinstance(v,str) or len(v)>160 for v in values):raise ValueError('Ungültige Filterauswahl.')
            chosen=set();blocked=False
            for item in values:
                if not item.strip():continue
                if not allowed_label(item):
                    blocked=True;continue
                chosen.add(normal(item.replace('_',' ')))
            if blocked and key=='include':chosen.add('\x00')
            target[key]=chosen
        target['match']='all' if row.get('match')=='all' else 'any'
        target['unknown']=row.get('unknown') if row.get('unknown') in ('known','unknown') else 'keep'
        result[group]=target
    return result

def matches(values,rules):
    for group,row in rules.items():
        have=values.get(group,set())
        if row['unknown']=='known' and not have or row['unknown']=='unknown' and have:return False
        if have & row['exclude']:return False
        if row['include'] and (not row['include']<=have if row['match']=='all' else not have & row['include']):return False
    return True

class FilterIndex:
    def __init__(self,app):
        self.app=app;self.lock=threading.RLock();self.at=0;self.data=None;self.warm_started=False;self.warming=False;self.dirty=False;self.generation=0
        self.refresh_gate=threading.Lock();self.refreshing=False

    def invalidate(self):
        # Writers must never wait for a complete catalogue projection. Multiple
        # source pages can arrive while the last published snapshot is in use.
        self.generation+=1;self.dirty=True

    def snapshot(self,force=False):
        with self.lock:
            if self.data is not None and time.monotonic()-self.at<30 and (not self.dirty or not force and len(self.data['records'])>10000):return self.data
            generation=self.generation
            app=self.app;index=app.star_index()
            cards=list(index['cards'])+list(app._star_people_cards())+list(app._star_trend_cards())
            service=getattr(app,'_star_service',lambda:None)()
            if service and getattr(service,'library',None):cards+=service.library.cards()
            blocked=getattr(app,'_star_face_blocked',lambda *args:False)
            cards=[card for card in cards if not blocked(card.get('id'),card.get('name'))]
            records={str(c['id']):collections.defaultdict(set) for c in cards}
            names=collections.defaultdict(set);display={group:{} for group in GROUPS}
            def put(ident,group,value):
                if ident not in records:return
                for label in labels(value):
                    label=label.replace('_',' ').strip()
                    if not label or not allowed_label(label):continue
                    source=normal(label)
                    if not source or source in ('unknown','unbekannt','none','null','n a','na'):continue
                    shown=label
                    key=source
                    if group in ('hair','eyes','build','breast'):
                        shown=app._label_text(group,label.casefold()) or shown
                        key=normal(shown)
                    elif group=='orientation':
                        shown=ORIENTATION_LABELS.get(source,shown)
                        key=normal(shown)
                    elif group=='scenes':
                        shown=SCENE_LABELS.get(source,shown)
                    elif group in ('gender','country','ethnicity'):
                        shown=app._label_text(group,label.lower()) or shown
                        key=normal(shown)
                    elif group=='acts':
                        shown=' '.join(part[:1].upper()+part[1:] for part in label.split())
                    if not key:continue
                    records[ident][group].add(key);display[group].setdefault(key,shown)
            def metadata(ident,row):
                put(ident,'hair',row.get('hair'))
                put(ident,'eyes',row.get('eyes'))
                put(ident,'build',row.get('build'))
                put(ident,'breast',row.get('breast_type') or row.get('breast'))
                put(ident,'tags',row.get('tags'))
                put(ident,'categories',row.get('categories') or row.get('genres'))
                for group in ('gender','country','ethnicity','cup'):put(ident,group,row.get(group))
                if row.get('year'):put(ident,'birthyear',str(row['year']))
                if row.get('height'):put(ident,'height',str(row['height'])+' cm')
                source={'stashdb':'StashDB','fansdb':'FansDB','tpdb':'ThePornDB','wikidata':'Wikidata'}.get(row.get('source'))
                if source:put(ident,'sources',source)
                for fact in row.get('facts') or []:
                    if not isinstance(fact,dict):continue
                    group=FACT_GROUPS.get(normal(fact.get('label')))
                    if group:put(ident,group,fact.get('value'))
                for film in row.get('films') or []:
                    if isinstance(film,dict):put(ident,'categories',film.get('categories') or film.get('genres'))
                for item in row.get('performances') or []:
                    if not isinstance(item,dict):continue
                    put(ident,'scenes',item.get('label'))
                    put(ident,'acts',split_acts(item.get('acts')))
            for card in cards:
                ident=str(card['id']);names[normal(card.get('name'))].add(ident);metadata(ident,card)
            for row in index.get('rows') or []:
                ident=str(row.get('id') or '')
                if ident not in records:continue
                metadata(ident,row)
                for alias in labels(row.get('aliases')):names[normal(alias)].add(ident)
            with app._star_extra_lock:extra=list(app._star_extra_load()['profiles'].items())
            for ident,row in extra:
                if isinstance(row,dict) and row.get('ok'):metadata(ident,row)
            film_count=0
            # Scene tags stay distinct from descriptive performer tags. Only
            # summaries built from confirmed performer/scene relations qualify.
            hub=getattr(app,'_star_runtime_hub',None)
            if hub:
                store=hub().store
                with store.lock:
                    summaries=list(store.db.execute("SELECT key,payload FROM cache WHERE kind IN ('box-features','metadata-features')"))
                for ident,payload in summaries:
                    if isinstance(payload,bytes) and payload.startswith(b'AHZ1'):
                        import zlib
                        payload=zlib.decompress(payload[4:])
                    summary=json.loads(payload)
                    put(ident,'content',summary.get('tags'))
                    put(ident,'categories',summary.get('categories'))
                    for group,values in (summary.get('attributes') or {}).items():
                        if group in GROUPS:put(ident,group,values)
            for path in Path(app.CACHE_DIR,'film').glob('*.json'):
                try:film=json.loads(path.read_text(encoding='utf-8'))
                except (OSError,ValueError):continue
                if not film.get('ok') or not (film.get('categories') or film.get('genres')):continue
                film_count+=1
                for performer in labels(film.get('cast')):
                    ids=names.get(normal(performer),set())
                    if len(ids)==1:put(next(iter(ids)),'categories',film.get('categories') or film.get('genres'))
            facets={};unknown={}
            for group in GROUPS:
                counts=collections.Counter(key for row in records.values() for key in row.get(group,()))
                facets[group]=[{'value':key,'label':display[group][key],'count':count} for key,count in sorted(counts.items(),key=lambda item:display[group][item[0]].casefold())]
                unknown[group]=sum(not row.get(group) for row in records.values())
            self.data={'records':records,'facets':facets,'unknown':unknown,'total':len(records),'film_count':film_count}
            self.at=time.monotonic();self.dirty=self.generation!=generation;return self.data

    def filter(self,cards,query):
        rules=rules_from(query.get('rules'))
        if not any(row['include'] or row['exclude'] or row['unknown']!='keep' for row in rules.values()):return cards
        data=self.snapshot(force=True)
        return [card for card in cards if matches(data['records'].get(str(card['id']),{}),rules)]

    def public(self):
        data=self.data
        index=self.app.star_index()
        large=len(index.get('cards') or [])>10000 or data is not None and data['total']>10000
        if not large:data=self.snapshot()
        elif data is None or time.monotonic()-self.at >= (30 if self.dirty else 300):
            if self.refresh_gate.acquire(blocking=False):
                self.refreshing=True
                def refresh():
                    try:
                        # This projects already saved records for an explicit
                        # local search. Pausing network jobs must not hide filters.
                        self.snapshot(force=True)
                    finally:self.refreshing=False;self.refresh_gate.release()
                threading.Thread(target=refresh,name='star-filter-snapshot',daemon=True).start()
        data=data or {'facets':{},'unknown':{},'total':0,'film_count':0}
        return {key:data[key] for key in ('facets','unknown','total','film_count')}|{'warming':self.refreshing or self.data is None,'films_pending':self.warming}

    def warm_films(self):
        """Enrich existing film records only; never crawl an entire film catalogue."""
        if self.warm_started:return
        with self.lock:
            if self.warm_started:return
            self.warm_started=True;self.warming=True
        def work():
            try:
                attempted=0
                for path in Path(self.app.CACHE_DIR,'film').glob('*.json'):
                    self.app._star_runtime_hub().wait('enrichment')
                    try:
                        old=json.loads(path.read_text(encoding='utf-8'))
                        if not old.get('ok') or 'categories' in old or time.time()-float(old.get('categories_checked') or 0)<86400:continue
                        url=old.get('url') or ''
                        if not url.startswith('https://www.adultempire.com/'):continue
                        if attempted>=10:break
                        attempted+=1
                        stamp=path.stat().st_mtime_ns
                        try:
                            final,page=self.app._film_read(url)
                            parsed=self.app._film_details(page,final,old.get('poster') or '')
                            if not parsed:raise ValueError('No confirmed film metadata')
                            categories=parsed.get('categories') or []
                            update={**old,'categories':categories,'categories_checked':time.time()}
                        except Exception:update={**old,'categories_checked':time.time()}
                        if path.stat().st_mtime_ns!=stamp:continue
                        temp=path.with_suffix('.filter-'+str(threading.get_ident())+'.tmp')
                        temp.write_text(json.dumps(update,ensure_ascii=False),encoding='utf-8');os.replace(temp,path)
                    except (OSError,ValueError):continue
            finally:self.warming=False;self.invalidate()
        if self.app._star_runtime_hub().submit('star-filter-film-metadata',work) is None:
            self.warm_started=False;self.warming=False
