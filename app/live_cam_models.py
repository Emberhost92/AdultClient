"""Paged Live-Cam library; provider identities, explicit selections, durable edits.

The public index is cached between catalog revisions. Query snapshots keep pages
and inspector navigation stable, without returning the entire library to the UI.
"""
import copy
import hashlib
import json
import math
import os
import re
import threading
import time
import uuid
from urllib.parse import urlencode
from collections import Counter

SIZES = (12, 18, 24, 36, 48, 50, 72, 120, 240)
STATS = ('watchMs','sessions','firstVisit','lastVisit','longestSession','activeDays',
         'previews','infos','lastOnline','appearances','observations')
PERSONAL = ('notes','tags','rating','priority','bookmarked','archived','hiddenUntil','pauseUntil','suggestionHidden','saved','compare','savedAt')
SORTS = {'live-first':('liveRank',False),'last-active':('lastVisit',True),'longest-inactive':('lastVisit',False),
         'newest-saved':('savedAt',True),'oldest-saved':('savedAt',False),
         'watch-most':('watchMs',True),'watch-least':('watchMs',False),
         'rating-high':('rating',True),'rating-low':('rating',False),
         'priority-high':('priority',True),'priority-low':('priority',False),
         'viewers-high':('viewers',True),'viewers-low':('viewers',False),
         'followers-high':('followers',True),'online-longest':('seconds',True),
         'age-low':('age',False),'age-high':('age',True),'sessions-most':('sessions',True),
         'average-longest':('averageSession',True),'session-longest':('longestSession',True),
         'active-days-most':('activeDays',True),'appearances-most':('appearances',True),
         'samples-most':('observations',True),'last-live':('lastOnline',True),
         'first-seen':('firstSeen',False),'name-az':('name',False),'name-za':('name',True),
         'country-az':('country',False),'gender':('gender',False),
         'public-tags-most':('tagCount',True),'groups-most':('groupCount',True)}
PROFILE_FIELDS=('id','displayName','bio','sections','tags','links','sourceUrl','observedAt','parserVersion','facts','images')


def clean_profile(p,history=True):
    result={k:copy.deepcopy(v) for k,v in p.items() if k in PROFILE_FIELDS}
    result['facts']=[{'label':f['label'],'value':f['value']} for f in p.get('facts',[])]
    result['sections']=[{'label':s['label'],'text':s['text']} for s in p.get('sections',[])]
    if history:result['history']=[clean_profile(old,False) for old in p.get('history',[])]
    return result


def number(value):
    return value if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value >= 0 else None


def stamp(value):
    value=number(value)
    return value*1000 if value is not None and value<10_000_000_000 else value


def words(value):
    return [v.strip().casefold().lstrip('#') for v in re.split(r'[,\n]+',str(value or '')) if v.strip()][:100]


def status(row, now):
    if row.get('playbackAt') and 0<=now-row['playbackAt']<95_000:return 'live'
    if row.get('roomState')=='error':return 'error'
    if not row.get('seen') or now-stamp(row['seen'])>120_000:return 'unknown'
    if row.get('show') in ('private','privat','group','password'):return 'private'
    if row.get('show') in ('away','idle','abwesend'):return 'away'
    if row.get('online') is True:return 'live'
    if row.get('online') is False:return 'offline'
    return 'unknown'


def personal(row):
    return bool(row.get('fav') or row.get('groupIds') or any(row['personal'].get(k) for k in
                ('saved','bookmarked','notes','tags','rating','priority','archived','hiddenUntil','pauseUntil','suggestionHidden')))


def search_text(row):
    cached=row.get('_search')
    if isinstance(cached,str):return cached
    p=row.get('personal') or {}
    text=' '.join([row.get('name',''),row.get('subject',''),row.get('bio',''),row.get('displayName',''),' '.join(f.get('label','')+' '+f.get('value','') for f in row.get('publicFacts',[])),p.get('notes',''),*row.get('tags',[]),*row.get('profileTags',[]),*p.get('tags',[])]).casefold()
    row['_search']=text
    return text


def plain_active(f):
    """True when the only exclusions are site, archive, pause and hidden suggestions."""
    if f.get('view','active')!='active':return False
    if str(f.get('query') or '').strip():return False
    if f.get('source') not in (None,'','all') or f.get('profile') not in (None,'','any') or f.get('media') not in (None,'','all'):return False
    if any(f.get(key) for key in ('genders','statuses','countries','publicTags','localTags','groupIds')):return False
    if any(f.get(key) not in (None,'') for key in ('minAge','maxAge','minViewers','maxViewers','minFollowers','maxFollowers','minWatchMinutes','minOnlineMinutes','minSessions','minRating','minPriority','minAppearances','minSamples','activeWithinDays','weekday','hour')):return False
    if any(f.get(key) not in (None,'','any') for key in ('seen','localTagsState','groupsState','notesState')):return False
    return True


def matches(row, f, now):
    p=row['personal']; state=row['status']; view=f.get('view','active')
    sites=f.get('sites',[])
    if row['site'] not in sites:return False
    paused=max(p.get('pauseUntil') or 0,p.get('hiddenUntil') or 0)>now
    if view=='archive' and not p.get('archived'):return False
    if view not in ('archive','all') and p.get('archived'):return False
    if view=='active' and (paused or p.get('suggestionHidden')):return False
    if view=='collection' and not personal(row):return False
    if view=='remembered' and not (row.get('fav') or p.get('bookmarked')):return False
    if view=='favorite-watchlist' and not (row.get('fav') and p.get('bookmarked')):return False
    if view=='favorites' and not row.get('fav'):return False
    if view=='following' and not row.get('accountFav'):return False
    if view=='watchlist' and not p.get('bookmarked'):return False
    if view=='groups' and not row['groupIds']:return False
    if view=='paused' and not paused:return False
    if view=='live' and state!='live':return False
    if view=='notes' and not p.get('notes','').strip():return False
    text=str(f.get('query') or '').casefold().split()
    if text and any(w not in search_text(row) for w in text):return False
    for field,target in [('genders','gender'),('statuses','status'),('countries','country')]:
        values=f.get(field) or []
        if values and str(row.get(target) or 'unknown').casefold() not in [str(v).casefold() for v in values]:return False
    for field,available,mode in [('publicTags',row.get('tags',[]),'publicTagMode'),('localTags',p.get('tags',[]),'localTagMode'),('groupIds',row['groupIds'],'groupMode')]:
        wanted=set(str(v).casefold() for v in f.get(field) or [])
        found=set(str(v).casefold() for v in available)
        if wanted and not (wanted<=found if f.get(mode)=='all' else bool(wanted&found)):return False
    if f.get('source')=='personal' and not personal(row) or f.get('source')=='automatic' and personal(row):return False
    if f.get('profile')=='loaded' and not row.get('profileLoaded') or f.get('profile')=='missing' and row.get('profileLoaded'):return False
    media=f.get('media','all');hd=row.get('hd');gaming=row.get('gaming')
    if media=='hd' and hd is not True or media=='gaming' and gaming is not True or media=='both' and not(hd is True and gaming is True) or media=='neither' and not(hd is False and gaming is False):return False
    for key,value in [('seen',bool(row.get('watchMs') or row.get('sessions'))),('localTagsState',bool(p.get('tags'))),('groupsState',bool(row['groupIds'])),('notesState',bool(p.get('notes','').strip()))]:
        if f.get(key)=='yes' and not value or f.get(key)=='no' and value:return False
    limits=[('minAge','age',1,False),('maxAge','age',1,True),('minViewers','viewers',1,False),('maxViewers','viewers',1,True),
            ('minFollowers','followers',1,False),('maxFollowers','followers',1,True),('minWatchMinutes','watchMs',60000,False),
            ('minOnlineMinutes','seconds',60,False),('minSessions','sessions',1,False),('minRating','rating',1,False),
            ('minPriority','priority',1,False),('minAppearances','appearances',1,False),('minSamples','observations',1,False)]
    for filter_name,field,factor,maximum in limits:
        bound=f.get(filter_name)
        if bound is None or bound=='':continue
        value=number(row.get(field))
        if value is None or (value>float(bound)*factor if maximum else value<float(bound)*factor):return False
    days=f.get('activeWithinDays')
    if days not in (None,'') and (not row.get('lastVisit') or row['lastVisit']<now-float(days)*86400000):return False
    for key,array in [('weekday','byDay'),('hour','byHour')]:
        value=f.get(key)
        if value not in (None,''):
            index=int(value);values=row.get(array) or []
            if not 0<=index<len(values) or not values[index]:return False
    return True


def clean_filters(value, sites):
    if not isinstance(value,dict):raise ValueError('Ungültige Bibliotheksfilter.')
    f=copy.deepcopy(value)
    f.setdefault('sites',list(sites))
    if not isinstance(f['sites'],list) or len(f['sites'])>len(sites) or any(s not in sites for s in f['sites']):raise ValueError('Ungültige Anbieterauswahl.')
    if len(json.dumps(f))>24000:raise ValueError('Zu viele Filter.')
    if str(f.get('sort','last-active')) not in SORTS:raise ValueError('Unbekannte Sortierung.')
    choices={'view':('all','active','collection','groups','favorites','following','watchlist','remembered','favorite-watchlist','paused','live','notes','archive'),
             'source':('all','personal','automatic'),'profile':('any','loaded','missing'),'media':('all','hd','gaming','both','neither')}
    for key,values in choices.items():
        if key in f and f[key] not in values:raise ValueError('Unbekannter Filter: '+key)
    if not isinstance(f.get('query',''),str) or len(f.get('query',''))>5000:raise ValueError('Die Suchanfrage ist zu lang.')
    for key in ('genders','statuses','countries','publicTags','localTags','groupIds'):
        if key in f and (not isinstance(f[key],list) or len(f[key])>100 or any(not isinstance(v,str) or len(v)>100 for v in f[key])):raise ValueError('Ungültiger Mehrfachfilter.')
    for key,value in f.items():
        if key.startswith(('min','max')) or key in ('activeWithinDays','weekday','hour'):
            if value not in (None,'') and (number(value) is None or value>1e12):raise ValueError('Ungültiger Zahlenfilter: '+key)
    for lo,hi in [('minAge','maxAge'),('minViewers','maxViewers'),('minFollowers','maxFollowers')]:
        if f.get(lo) not in (None,'') and f.get(hi) not in (None,'') and f[lo]>f[hi]:raise ValueError('Der Mindestwert liegt über dem Höchstwert.')
    for key,maximum in [('weekday',6),('hour',23)]:
        if f.get(key) not in (None,'') and (type(f[key]) is not int or f[key]>maximum):raise ValueError('Ungültiger Zeitfilter.')
    return f


class ModelsHub:
    def __init__(self, backend):
        self.b=backend;self.lock=threading.RLock();self.queries={};self.metrics={};self.undo={};self.index=None;self.index_epoch=-1;self.projection=None;self.config_epoch=0;self.playback={};self.facets_cache={}
        self.path=os.path.join(backend['PROFILE'],'cam_models_state.json')
        self.config=backend['_cam_json_read'](self.path) or {'version':1,'collections':[],'rules':[],'profiles':{},'notices':[]}
        if self.config.get('version')!=1:raise ValueError('Neuere Modeldaten bleiben geschützt. Bitte die passende Anwendung verwenden.')
        for key,default in [('collections',[]),('rules',[]),('profiles',{}),('notices',[])]:self.config.setdefault(key,default)
        self.profile_generation=self.config.get('profileGeneration',0)
        self.base_profiles=dict(self.config['profiles'])
        self.profile_folder=os.path.join(backend['PROFILE'],'cam_profiles')
        if os.path.isdir(self.profile_folder):
            for entry in os.scandir(self.profile_folder):
                if not entry.name.endswith('.json') or not entry.is_file():continue
                stored=backend['_cam_json_read'](entry.path) or {}
                if stored.get('generation')!=self.profile_generation:continue
                profile=stored.get('profile',{});key=profile.get('id')
                try:self.validate_profile(self.key(key),profile)
                except (ValueError,TypeError,KeyError):continue
                current=self.config['profiles'].get(key)
                if not current or profile['observedAt']>=current['observedAt']:self.config['profiles'][key]=profile


    def key(self,value):
        if not isinstance(value,str) or ':' not in value:return ''
        site,name=value.split(':',1)
        return value if self.b['_cam_pair'](site,name)==value else ''

    def config_copy(self):
        return {**copy.deepcopy({k:v for k,v in self.config.items() if k!='profiles'}),'profiles':dict(self.config['profiles'])}

    def save_config(self,next_config,archive_reset=False):
        generation=self.profile_generation+(1 if archive_reset else 0)
        baseline=next_config['profiles'] if archive_reset else self.base_profiles
        disk={**next_config,'profiles':baseline,'profileGeneration':generation}
        self.b['_cam_json_write'](self.path,disk)
        self.config=next_config;self.config_epoch+=1
        if archive_reset:self.base_profiles=dict(baseline);self.profile_generation=generation

    def clean(self,row):return {k:copy.deepcopy(v) for k,v in row.items() if not k.startswith('_') and k!='stream'}

    def group_service(self):
        if not hasattr(self,'groups_hub'):
            from live_cam_groups import GroupsHub
            self.groups_hub=GroupsHub(self)
        return self.groups_hub

    def source(self):
        library=self.b['_cam_library_load']()
        with self.b['_cam_lib_lock']:
            epoch=self.b.get('_cam_models_epoch',0)
            if self.index is not None and self.index_epoch==epoch:return self.index
            models=dict(library.get('models') or {})
            favorites=set(library.get('favs') or [])
            followed={v for values in library.get('account',{}).values() for v in values if isinstance(values,list)}
            groups=copy.deepcopy(library.get('groups') or [])
        members={}
        for group in groups:
            for key in (group.get('items') or []) if group.get('kind','manual')=='manual' else []:members.setdefault(key,[]).append(group['id'])
        previous={old['id']:old for old in self.index[0]} if self.index else {}
        rows=[];fields=('site','name','displayName','tags','subject','thumb','hd','viewers','online','show','languages','followers','seconds','country','place','age','badges','seen','firstSeen','lastOnline','observations','appearances','gaming','personal','coverAt','coverError','profileImages','profileAt','profileError','enrichedAt','bio','publicFacts','publicLinks','profileTags','profileSource','catalogFacts','biographyStatus','biographyAt')
        for key,row in models.items():
            if not self.key(key) or not isinstance(row,dict):continue
            p=row.get('personal') if isinstance(row.get('personal'),dict) else {}
            sig=(id(row),row.get('seen'),row.get('viewers'),row.get('online'),row.get('show'),row.get('thumb'),row.get('hd'),row.get('age'),row.get('gender'),row.get('subject'),row.get('country'),row.get('place'),row.get('seconds'),row.get('followers'),row.get('firstSeen'),row.get('lastOnline'),row.get('observations'),row.get('appearances'),row.get('gaming'),row.get('coverAt'),row.get('profileAt'),row.get('biographyAt'),row.get('enrichedAt'),row.get('biographyStatus'),row.get('displayName'),id(row.get('tags')),id(row.get('languages')),id(row.get('bio')),id(row.get('publicFacts')),id(row.get('catalogFacts')),id(p),p.get('notesRevision'),p.get('lastVisit'),p.get('savedAt'),p.get('rating'),p.get('priority'),p.get('archived'),p.get('pauseUntil'),p.get('hiddenUntil'),p.get('bookmarked'),p.get('saved'),p.get('suggestionHidden'),tuple(p.get('tags') or ()),p.get('notes'))
            gids=list(members.get(key,[]));fav=key in favorites;account=key in followed
            old=previous.get(key)
            if old is not None and old.get('_sig')==sig:
                if old.get('fav')!=fav or old.get('accountFav')!=account or old.get('groupIds')!=gids:
                    old['fav']=fav;old['accountFav']=account;old['groupIds']=gids
                rows.append(old);continue
            r={k:row[k] for k in fields if k in row}
            if isinstance(r.get('personal'),dict):r['personal']=dict(r['personal'])
            if isinstance(r.get('tags'),list):r['tags']=list(r['tags'])
            r['cover']='/api/cam-model-cover?'+urlencode({'site':r['site'],'name':r['name'],'v':r['coverAt']}) if r.get('coverAt') else ''
            r.update(id=key,fav=fav,accountFav=account,groupIds=gids,_sig=sig);r.setdefault('personal',{})
            if number(r.get('age')) is None or not 18<=r['age']<=120:r['age']=None
            r['gender']={'weiblich':'f','female':'f','männlich':'m','male':'m','trans':'t','shemale':'t','paar':'c','couples':'c','couple':'c'}.get(str(row.get('gender','')).lower(),row.get('gender') or 'unknown')
            rows.append(r)
        known={r['id'] for r in rows}
        for key in sorted(followed-known):
            if not self.key(key):continue
            site,name=key.split(':',1);rows.append({'id':key,'site':site,'name':name,'personal':{},'groupIds':list(members.get(key,[])),'fav':key in favorites,'accountFav':True,'gender':'unknown','tags':[],'online':None,'seen':0})
        self.index=(rows,groups);self.index_epoch=epoch
        return self.index

    def records(self,token='',now=None):
        now=now or int(time.time()*1000);source,groups=self.source();usage=self.metrics.get(token,(0,{}))[1] if token in self.metrics else {}
        self.playback={token:{key:at for key,at in reports.items() if 0<=now-at<95_000} for token,reports in self.playback.items()}
        self.playback={token:reports for token,reports in self.playback.items() if reports}
        playing={}
        for reports in self.playback.values():
            for identity,at in reports.items():playing[identity]=max(at,playing.get(identity,0))
        # These short-lived observations stay in the projection, never in the
        # durable provider catalogue. Media errors do not manufacture offline.
        for row in source:
            if row['id'] in playing:row['playbackAt']=playing[row['id']]
            else:row.pop('playbackAt',None)
        cache_key=(self.index_epoch,token,self.metrics.get(token,(0,))[0],self.config_epoch)
        if self.projection and self.projection[0]==cache_key:
            rows=self.projection[1]
            for row in rows:
                if row['id'] in playing:row['playbackAt']=playing[row['id']]
                else:row.pop('playbackAt',None)
                row['status']=status(row,now);row['liveRank']=0 if row['status']=='live' else 1
            return self.group_service().effective(rows,groups,now,token)
        profiles=self.config['profiles'];rows=[]
        for raw in source:
            local=usage.get(raw['id']) if usage else None
            if local:
                # Local watch stats must not stick on the shared catalog row.
                r=dict(raw);r.pop('_search',None);r.pop('_derived',None)
                p={**{k:v for k,v in local.items() if k in PERSONAL},**(r.get('personal') or {})};r['personal']=p
                for key in STATS:r[key]=number(local.get(key,p.get(key,r.get(key))))
                for key in ('byDay','byHour'):r[key]=local.get(key,p.get(key))
                r['firstSeen']=stamp(raw.get('firstSeen'))
                for key in ('firstVisit','lastVisit','lastOnline'):r[key]=stamp(r.get(key))
                for key in ('rating','priority','savedAt'):r[key]=p.get(key)
                r['profileLoaded']=r['id'] in profiles or bool(local.get('profileLoaded'))
                r['averageSession']=r['watchMs']/r['sessions'] if r.get('sessions') and r.get('watchMs') is not None else None
            else:
                r=raw;p=r.get('personal') or {}
                if not r.get('_derived'):
                    for key in STATS:
                        value=p.get(key,r.get(key))
                        if value is not None:r[key]=number(value)
                    for key in ('byDay','byHour'):
                        if key in p:r[key]=p[key]
                    if r.get('firstSeen') is not None:r['firstSeen']=stamp(r.get('firstSeen'))
                    for key in ('firstVisit','lastVisit','lastOnline'):
                        if r.get(key) is not None:r[key]=stamp(r.get(key))
                    for key in ('rating','priority','savedAt'):
                        if key in p:r[key]=p[key]
                    sessions=r.get('sessions');watch=r.get('watchMs')
                    r['averageSession']=watch/sessions if sessions and watch is not None else None
                    r['tagCount']=len(r.get('tags') or []);r['_derived']=1
                r['profileLoaded']=r['id'] in profiles
            r['status']=status(r,now);r['liveRank']=0 if r['status']=='live' else 1
            r['tagCount']=len(r.get('tags') or []);r['groupCount']=len(r.get('groupIds') or [])
            rows.append(r)
        self.projection=(cache_key,rows)
        return self.group_service().effective(rows,groups,now,token)

    def sweep(self):
        now=time.monotonic()
        for cache in (self.queries,self.metrics,self.undo):
            for key in list(cache):
                if cache[key][0]<now:cache.pop(key,None)
        while len(self.queries)>12:self.queries.pop(next(iter(self.queries)))
        while len(self.metrics)>12:self.metrics.pop(next(iter(self.metrics)))
        while len(self.queries)>1 and sum(len(v[1]) for v in self.queries.values())>120000:self.queries.pop(next(iter(self.queries)))

    def query(self,body,scope=None,predicate=None,order=None,sizes=None,include_config=True,project=None,prepared=None):
        self.sweep();f=clean_filters(body.get('filters',{}),self.b['_CAM_SITES']);size=body.get('size',36)
        if size not in (sizes or SIZES):raise ValueError('Ungültige Seitengröße.')
        if prepared is None:
            now=int(time.time()*1000);rows,groups=self.records(body.get('metrics',''),now)
        else:
            rows,groups,now=prepared
        if scope is not None:
            rows=[r for r in rows if r['id'] in scope];known={r['id'] for r in rows}
            for key in scope.keys()-known:
                site,name=key.split(':',1)
                rows.append({'id':key,'site':site,'name':name,'personal':{},'groupIds':[],'tags':[],'gender':'unknown','status':'unknown','liveRank':1,'online':None,'seen':0,'fav':False,'accountFav':False,'_search':name.casefold()})
                if isinstance(scope[key],dict):rows[-1].update(scope[key])
        if project is not None:rows=[project(dict(r)) for r in rows]
        chosen_sites=set(f['sites']);all_rows=[r for r in rows if r['site'] in chosen_sites]
        if predicate is None and plain_active(f):
            matched=[r for r in all_rows if not r['personal'].get('archived') and not r['personal'].get('suggestionHidden') and max(r['personal'].get('pauseUntil') or 0,r['personal'].get('hiddenUntil') or 0)<=now]
        else:
            matched=[r for r in all_rows if matches(r,f,now) and (predicate is None or predicate(r))]
        if order is not None:matched=order(matched)
        else:
            field,reverse=SORTS[f.get('sort','last-active')]
            known=[r for r in matched if r.get(field) is not None and r.get(field)!=''];unknown=[r for r in matched if r.get(field) is None or r.get(field)=='']
            known.sort(key=lambda r:r['id'].casefold())
            known.sort(key=lambda r:r[field].casefold() if isinstance(r[field],str) else r[field],reverse=reverse);matched=known+sorted(unknown,key=lambda r:r['id'].casefold())
        query=uuid.uuid4().hex;self.queries[query]=(time.monotonic()+600,matched,size)
        # Facets describe the selected catalogue, not the current search. Reuse
        # them across searches/pages while retaining live state on every query.
        facet_key=(self.index_epoch,self.config_epoch,body.get('metrics',''),self.metrics.get(body.get('metrics',''),(0,))[0],tuple(sorted(chosen_sites)),prepared is not None)
        reusable=scope is None and project is None and not any(g.get('kind')=='smart' for g in groups)
        cached=self.facets_cache.get(facet_key) if reusable else None
        if cached is not None:
            summary,facets=cached
            summary=dict(summary)
        else:
            personal_n=fav_n=watch_n=notes_n=0;countries=set();public_tags=Counter();local_tags=Counter();local_seen=set()
            for r in all_rows:
                p=r['personal'];fav=r.get('fav');groups=r.get('groupIds')
                if fav or groups or p.get('saved') or p.get('bookmarked') or p.get('notes') or p.get('tags') or p.get('rating') or p.get('priority') or p.get('archived') or p.get('hiddenUntil') or p.get('pauseUntil') or p.get('suggestionHidden'):personal_n+=1
                fav_n+=bool(fav);watch_n+=bool(p.get('bookmarked'));notes_n+=bool(p.get('notes'))
                if r.get('country'):countries.add(r['country'])
                for tag in r.get('tags') or ():public_tags[tag]+=1
                own=p.get('tags') or ()
                if own:
                    local_seen.update(own)
                    for tag in own:local_tags[tag]+=1
            summary={'total':len(rows),'providers':dict(Counter(r['site'] for r in rows)),'selectedTotal':len(all_rows),
                     'personal':personal_n,'favorites':fav_n,'watchlist':watch_n,'notes':notes_n,'localTags':len(local_seen),'live':0}
            facets={'countries':sorted(countries),'publicTags':public_tags.most_common(150),'localTags':local_tags.most_common(150)}
            if reusable:
                if len(self.facets_cache)>=16:self.facets_cache.clear()
                self.facets_cache[facet_key]=(summary,facets)
            summary=dict(summary)
        summary['live']=sum(r['status']=='live' for r in all_rows)
        result=self.page({'query':query,'page':body.get('page',0)})
        result.update(summary=summary,facets=facets,groups=[{k:g[k] for k in ('id','name','kind','systemRole','archived','parent','count','revision') if k in g} for g in groups],config={k:copy.deepcopy(self.config[k]) if include_config else [] for k in ('collections','rules','notices')})
        for item in result['config']['collections']:
            cf=clean_filters(item['filters'],self.b['_CAM_SITES']);item['count']=sum(matches(r,cf,now) for r in rows)
        return result

    def page(self,body):
        key=str(body.get('query',''));cached=self.queries.get(key)
        if not cached or cached[0]<time.monotonic():raise ValueError('Diese Trefferansicht ist abgelaufen. Bitte aktualisieren.')
        _,rows,size=cached;pages=max(1,math.ceil(len(rows)/size));page=body.get('page',0)
        if not isinstance(page,int) or isinstance(page,bool):raise ValueError('Ungültige Seite.')
        page=max(0,min(pages-1,page))
        now=int(time.time()*1000)
        return {'ok':True,'query':key,'page':page,'pages':pages,'total':len(rows),'size':size,'epoch':self.b.get('_cam_models_epoch',0),
                'items':[{**self.clean(r),'status':status(r,now)} for r in rows[page*size:(page+1)*size]]}

    def upload_metrics(self,body):
        token=str(body.get('token') or '')
        if not re.fullmatch(r'[a-f0-9]{32}',token):raise ValueError('Ungültige lokale Statistikkennung.')
        values=body.get('items')
        if not isinstance(values,dict) or len(values)>60000:raise ValueError('Zu viele lokale Statistiken.')
        clean={}
        for key,raw in values.items():
            if not self.key(key) or not isinstance(raw,dict):raise ValueError('Ungültige lokale Modelstatistik.')
            item={field:raw[field] for field in STATS if field in raw and number(raw[field]) is not None}
            for field in ('byDay','byHour'):
                if field in raw:
                    a=raw[field];size=7 if field=='byDay' else 24
                    if not isinstance(a,list) or len(a)!=size or any(number(n) is None for n in a):raise ValueError('Ungültige Zeitverteilung.')
                    item[field]=a
            for field in PERSONAL:
                if field in raw:
                    if field=='priority' and type(raw[field]) is int and 0<=raw[field]<=10:item[field]=raw[field]
                    else:item[field]=self.clean_patch({field:raw[field]})[field]
            item['profileLoaded']=raw.get('profileLoaded') is True;clean[key]=item
        self.metrics[token]=(time.monotonic()+1800,clean);self.sweep()
        return {'ok':True,'metrics':token}

    def clean_patch(self,raw):
        if not isinstance(raw,dict) or any(k not in PERSONAL+('fav','addTags','removeTags','groupAdd','groupRemove') for k in raw):raise ValueError('Unbekannte Organisationsaktion.')
        patch={}
        for field,value in raw.items():
            if field=='notes':
                if not isinstance(value,str) or len(value)>10000:raise ValueError('Notizen dürfen höchstens 10000 Zeichen enthalten.')
            elif field in ('tags','addTags','removeTags','groupAdd','groupRemove'):
                if not isinstance(value,list) or len(value)>100 or any(not isinstance(t,str) or not t.strip() or len(t)>40 for t in value):raise ValueError('Ungültige Tags oder Gruppen.')
                value=list(dict.fromkeys(t.strip() for t in value))
            elif field in ('rating','priority'):
                if type(value) is not int or not 0<=value<=5:raise ValueError('Bewertung und Priorität liegen zwischen 0 und 5.')
            elif field in ('hiddenUntil','pauseUntil','savedAt'):
                if number(value) is None or value>10**15:raise ValueError('Ungültiger Zeitpunkt.')
            elif type(value) is not bool:raise ValueError('Ungültiger Schalter.')
            patch[field]=value
        return patch

    def mutate(self,body):
        ids=body.get('ids');patch=self.clean_patch(body.get('patch',{}))
        if not isinstance(ids,list) or not 1<=len(ids)<=5000 or len(set(ids))!=len(ids) or any(not self.key(v) for v in ids):raise ValueError('Bitte 1 bis 5000 konkrete Models auswählen.')
        if len(ids)>1 and ('notes' in patch or 'tags' in patch):raise ValueError('Vorhandene Notizen und Tags werden nicht über mehrere Models überschrieben. Bitte Tags ergänzen oder entfernen.')
        library=self.b['_cam_library_load']()
        with self.b['_cam_lib_save_lock'],self.b['_cam_lib_lock']:
            next_lib={**library,'models':dict(library['models']),'groups':copy.deepcopy(library['groups']),'favs':list(library['favs'])}
            groups={g['id']:g for g in next_lib['groups']}
            if any(g not in groups for g in patch.get('groupAdd',[])+patch.get('groupRemove',[])):raise ValueError('Eine gewählte Gruppe existiert nicht mehr.')
            from live_cam_groups import editable
            if any(not editable(groups[g]) or groups[g].get('archived') for g in patch.get('groupAdd',[])+patch.get('groupRemove',[])):raise ValueError('Diese Gruppe wird automatisch verwaltet oder ist archiviert.')
            snapshots={};after={}
            for key in ids:
                site,name=key.split(':',1);row=next_lib['models'].get(key)
                if row is None:
                    row={'site':site,'name':name,'online':None,'show':'unknown','seen':0,'personal':{}};next_lib['models'][key]=row
                row=copy.deepcopy(row);next_lib['models'][key]=row
                p=row.setdefault('personal',{});snapshots[key]=self.organization(next_lib,key)
                if ('notes' in patch or 'tags' in patch) and body.get('notesRevision')!=p.get('notesRevision',0):
                    return {'ok':False,'conflict':True,'error':'Notizen oder Tags wurden inzwischen geändert. Dein Entwurf bleibt erhalten.','personal':copy.deepcopy(p)}
                for field,value in patch.items():
                    if field in PERSONAL:p[field]=copy.deepcopy(value)
                if 'notes' in patch or 'tags' in patch:p['notesRevision']=p.get('notesRevision',0)+1
                if patch.get('saved') and not p.get('savedAt'):p['savedAt']=int(time.time()*1000)
                if 'addTags' in patch:p['tags']=list(dict.fromkeys(p.get('tags',[])+patch['addTags']))
                if 'removeTags' in patch:p['tags']=[v for v in p.get('tags',[]) if v not in patch['removeTags']]
                if len(p.get('tags',[]))>100:raise ValueError('Ein Model darf höchstens 100 eigene Tags haben.')
                if 'addTags' in patch or 'removeTags' in patch:p['notesRevision']=p.get('notesRevision',0)+1
                if 'fav' in patch:
                    favs=next_lib['favs']
                    if patch['fav'] and key not in favs:favs.append(key)
                    if not patch['fav'] and key in favs:favs.remove(key)
                for g in patch.get('groupAdd',[]):
                    if key not in groups[g].setdefault('items',[]):groups[g]['items'].append(key);groups[g]['revision']=groups[g].get('revision',0)+1
                for g in patch.get('groupRemove',[]):
                    if key in groups[g].get('items',[]):groups[g]['items'].remove(key);groups[g]['revision']=groups[g].get('revision',0)+1
                after[key]=self.organization(next_lib,key)
            self.b['_cam_json_write'](self.b['CAM_LIBRARY'],next_lib)
            library.clear();library.update(next_lib);self.b['_cam_models_epoch']=self.b.get('_cam_models_epoch',0)+1
            undo=uuid.uuid4().hex;self.undo[undo]=(time.monotonic()+1800,snapshots,after)
        self.index=None
        return {'ok':True,'count':len(ids),'undo':undo,'personal':copy.deepcopy(next_lib['models'][ids[0]]['personal']) if len(ids)==1 else None}

    @staticmethod
    def organization(library,key):
        row=library.get('models',{}).get(key,{})
        return {'personal':copy.deepcopy(row.get('personal',{})),'fav':key in library.get('favs',[]),
                'groups':[g['id'] for g in library.get('groups',[]) if key in g.get('items',[])]}

    def restore(self,token):
        item=self.undo.get(token)
        if not item or item[0]<time.monotonic():raise ValueError('Die Rücknahmefrist ist abgelaufen.')
        _,before,after=item[:3];new_groups=item[3] if len(item)>3 else [];library=self.b['_cam_library_load']()
        with self.b['_cam_lib_save_lock'],self.b['_cam_lib_lock']:
            for key,value in after.items():
                if self.organization(library,key)!=value:raise ValueError('Das Model wurde inzwischen weiter bearbeitet. Die neueren Änderungen bleiben erhalten.')
            next_lib=copy.deepcopy(library)
            for key,value in before.items():
                p=copy.deepcopy(value['personal']);p['notesRevision']=next_lib['models'][key].get('personal',{}).get('notesRevision',0)+1
                next_lib['models'][key]['personal']=p
                if value['fav'] and key not in next_lib['favs']:next_lib['favs'].append(key)
                if not value['fav'] and key in next_lib['favs']:next_lib['favs'].remove(key)
                for g in next_lib['groups']:
                    items=g.setdefault('items',[])
                    if g['id'] in value['groups'] and key not in items:items.append(key);g['revision']=g.get('revision',0)+1
                    if g['id'] not in value['groups'] and key in items:items.remove(key);g['revision']=g.get('revision',0)+1
            next_lib['groups']=[g for g in next_lib['groups'] if not any(g['id']==old['id'] and g.get('name')==old['name'] and not g.get('items') for old in new_groups)]
            self.b['_cam_json_write'](self.b['CAM_LIBRARY'],next_lib);library.clear();library.update(next_lib)
            self.b['_cam_models_epoch']=self.b.get('_cam_models_epoch',0)+1
        self.undo.pop(token);self.index=None
        return {'ok':True,'count':len(before),'items':[{'id':key,'personal':copy.deepcopy(next_lib['models'][key]['personal'])} for key in before]}

    def export(self,body):
        if body.get('query'):
            cached=self.queries.get(str(body['query']))
            if not cached or cached[0]<time.monotonic():raise ValueError('Trefferansicht abgelaufen.')
            rows=cached[1]
        else:
            ids=body.get('ids',[])
            if not isinstance(ids,list) or not 1<=len(ids)<=5000:raise ValueError('Bitte konkrete Models auswählen.')
            wanted=set(ids);rows=[r for r in self.records(body.get('metrics',''))[0] if r['id'] in wanted]
        own_groups=[g for g in self.source()[1] if not g.get('systemRole') and g.get('kind','manual')=='manual'];own_ids={g['id'] for g in own_groups}
        return {'ok':True,'document':{'format':'AdultClient-Models','version':1,'at':int(time.time()*1000),
                'groups':[{'id':g['id'],'name':g['name']} for g in own_groups],
                'models':[{'site':r['site'],'name':r['name'],'personal':{k:v for k,v in r['personal'].items() if k in PERSONAL and k!='compare'},
                           'favorite':r.get('fav',False),'groups':[gid for gid in r['groupIds'] if gid in own_ids]} for r in rows]}}

    def import_preview(self,body):
        doc=body.get('document')
        if not isinstance(doc,dict) or doc.get('format') not in ('AdultClient-Models','AdultHideout-Models') or doc.get('version')!=1 or not isinstance(doc.get('models'),list) or len(doc['models'])>60000:raise ValueError('Unbekanntes Modelbibliotheksformat.')
        rows={};library=self.b['_cam_library_load']();definitions=doc.get('groups',[])
        if not isinstance(definitions,list) or len(definitions)>40:raise ValueError('Ungültige Gruppen im Modelimport.')
        group_defs={}
        for group in definitions:
            if not isinstance(group,dict) or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',str(group.get('id') or '')) or not isinstance(group.get('name'),str) or not 1<=len(group['name'].strip())<=80:raise ValueError('Ungültige importierte Gruppe.')
            if group['id'].startswith('following-'):raise ValueError('Kontogruppen bitte im Gruppenmenü als eigene Kopien importieren.')
            group_defs[group['id']]={'id':group['id'],'name':group['name'].strip(),'items':[]}
        for row in doc['models']:
            if not isinstance(row,dict):raise ValueError('Ungültiges Model in der Importdatei.')
            key=self.b['_cam_pair'](row.get('site'),row.get('name'))
            if not key or key in rows:raise ValueError('Ungültige oder doppelte Hoster-Modelkennung.')
            raw_patch=copy.deepcopy(row.get('personal',{}));legacy=raw_patch.pop('priority',None) if isinstance(raw_patch,dict) else None
            patch=self.clean_patch(raw_patch);patch.pop('compare',None)
            if legacy is not None:
                if type(legacy) is not int or not 0<=legacy<=10:raise ValueError('Ungültige vorhandene Priorität.')
                patch['priority']=legacy
            groups=row.get('groups',[])
            if not isinstance(groups,list) or len(groups)>40 or any(not isinstance(v,str) for v in groups):raise ValueError('Ungültige Gruppenzuordnungen.')
            protected={g['id'] for g in library['groups'] if g.get('systemRole') or g.get('kind')=='smart'}
            rows[key]={'personal':patch,'favorite':row.get('favorite') is True,'groups':[g for g in groups if g not in protected and not g.startswith('following-')]}
        with self.b['_cam_lib_lock']:
            signature=hashlib.sha256(json.dumps(library,sort_keys=True).encode()).hexdigest()
            conflicts=sum(bool(library['models'].get(k,{}).get('personal')) for k in rows)
            new=sum(k not in library['models'] for k in rows)
        existing_groups={g['id'] for g in library['groups']};new_groups=[g for k,g in group_defs.items() if k not in existing_groups]
        if len(existing_groups)+len(new_groups)>40:raise ValueError('Mit diesem Import würden mehr als 40 Gruppen entstehen.')
        missing_groups={g for value in rows.values() for g in value['groups'] if g not in existing_groups and g not in group_defs}
        token=uuid.uuid4().hex;self.queries['models-import:'+token]=(time.monotonic()+600,rows,signature,new_groups)
        return {'ok':True,'preview':token,'count':len(rows),'new':new,'conflicts':conflicts,'newGroups':len(new_groups),'missingGroups':len(missing_groups)}

    def import_commit(self,body):
        token='models-import:'+str(body.get('preview'));item=self.queries.get(token)
        if not item or item[0]<time.monotonic():raise ValueError('Die Importvorschau ist abgelaufen.')
        library=self.b['_cam_library_load']()
        with self.b['_cam_lib_save_lock'],self.b['_cam_lib_lock']:
            if item[2]!=hashlib.sha256(json.dumps(library,sort_keys=True).encode()).hexdigest():raise ValueError('Der Bestand wurde seit der Vorschau geändert. Bitte den Import neu prüfen.')
            next_lib=copy.deepcopy(library)
            before={key:self.organization(library,key) for key in item[1]}
            next_lib['groups'].extend(copy.deepcopy(item[3]))
            for key,value in item[1].items():
                site,name=key.split(':',1);row=next_lib['models'].setdefault(key,{'site':site,'name':name,'online':None,'show':'unknown','seen':0})
                p=row.setdefault('personal',{});changed=False
                for field,v in value['personal'].items():
                    if field not in p:p[field]=copy.deepcopy(v);changed=True
                if changed:p['notesRevision']=p.get('notesRevision',0)+1
                if value['favorite'] and key not in next_lib['favs']:next_lib['favs'].append(key)
                for g in next_lib['groups']:
                    if g['id'] in value['groups'] and key not in g.setdefault('items',[]):g['items'].append(key)
            backup=os.path.join(self.b['PROFILE'],'cam_model_backups','models-'+uuid.uuid4().hex+'.json')
            self.b['_cam_json_write'](backup,library);self.b['_cam_json_write'](self.b['CAM_LIBRARY'],next_lib)
            library.clear();library.update(next_lib);self.b['_cam_models_epoch']=self.b.get('_cam_models_epoch',0)+1
            undo=uuid.uuid4().hex;self.undo[undo]=(time.monotonic()+1800,before,{key:self.organization(next_lib,key) for key in item[1]},copy.deepcopy(item[3]))
        self.queries.pop(token);self.index=None
        return {'ok':True,'count':len(item[1]),'backup':backup,'undo':undo}

    def configure(self,body):
        kind=body.get('kind')
        if kind not in ('collections','rules'):raise ValueError('Unbekannter Bibliotheksbereich.')
        next_config=self.config_copy();items=next_config[kind];key=body.get('id') or uuid.uuid4().hex
        if body.get('remove'):items[:]=[r for r in items if r['id']!=key]
        else:
            name=str(body.get('name') or '').strip()
            if not 1<=len(name)<=80:raise ValueError('Bitte einen Namen mit höchstens 80 Zeichen vergeben.')
            record={'id':key,'name':name,'filters':clean_filters(body.get('filters',{}),self.b['_CAM_SITES'])}
            if kind=='rules':
                action=body.get('action');target=body.get('target','')
                if action not in ('notice','favorite','group'):raise ValueError('Ungültige Regelaktion.')
                if action=='group' and target not in {g['id'] for g in self.source()[1] if not g.get('systemRole') and g.get('kind','manual')=='manual' and not g.get('archived')}:raise ValueError('Bitte eine vorhandene Zielgruppe wählen.')
                record.update(action=action,target=target,enabled=body.get('enabled') is True)
            found=next((i for i,r in enumerate(items) if r['id']==key),None)
            if found is None:
                if len(items)>=60:raise ValueError('Höchstens 60 Sammlungen beziehungsweise Regeln.')
                items.append(record)
            else:items[found]=record
        self.save_config(next_config);return {'ok':True,'config':{k:copy.deepcopy(self.config[k]) for k in ('collections','rules','notices')}}

    def run_rules(self,body):
        rows,_=self.records(body.get('metrics',''));now=int(time.time()*1000);counts=[]
        for rule in self.config['rules']:
            if not rule.get('enabled') or body.get('id') and body['id']!=rule['id']:continue
            selected=[r for r in rows if personal(r) and matches(r,rule['filters'],now)]
            if rule['action']=='favorite':selected=[r for r in selected if not r.get('fav')]
            if rule['action']=='group':selected=[r for r in selected if rule['target'] not in r['groupIds']]
            if not selected:continue
            if rule['action']!='notice':
                patch={'fav':True} if rule['action']=='favorite' else {'groupAdd':[rule['target']]}
                for i in range(0,len(selected),5000):self.mutate({'ids':[r['id'] for r in selected[i:i+5000]],'patch':patch})
            else:
                next_config=self.config_copy();signature=hashlib.sha256(json.dumps([rule['id'],sorted(r['id'] for r in selected)]).encode()).hexdigest()
                if any(n.get('signature')==signature and now-n['at']<3600000 for n in next_config['notices']):continue
                next_config['notices']=(next_config['notices']+[{'at':now,'rule':rule['name'],'count':len(selected),'signature':signature}])[-50:]
                self.save_config(next_config)
            counts.append({'name':rule['name'],'count':len(selected)})
        return {'ok':True,'results':counts,'notices':copy.deepcopy(self.config['notices'])}

    def profile(self,body):
        key=self.key(body.get('id'));op=body.get('action','read')
        if op=='read':return {'ok':True,'profile':copy.deepcopy(self.config['profiles'].get(key))}
        if op=='save':
            p=body.get('profile');self.validate_profile(key,p)
            old=self.config['profiles'].get(key)
            if old and old.get('observedAt')==p.get('observedAt'):return {'ok':True,'profile':old}
            clean=clean_profile(p,False)
            unchanged=old and {k:v for k,v in old.items() if k not in ('history','observedAt')}=={k:v for k,v in clean.items() if k!='observedAt'}
            history=old.get('history',[]) if unchanged else (old.get('history',[])+[{k:v for k,v in old.items() if k!='history'}])[-20:] if old else []
            clean['history']=history
            target=os.path.join(self.profile_folder,hashlib.sha256(key.encode()).hexdigest()+'.json')
            self.b['_cam_json_write'](target,{'generation':self.profile_generation,'profile':clean})
            self.config['profiles'][key]=clean;self.config_epoch+=1
            return {'ok':True,'profile':clean}
        raise ValueError('Unbekannte Profilaktion.')

    def validate_profile(self,key,p):
        if not key or not isinstance(p,dict) or p.get('id')!=key or len(json.dumps(p))>150000:raise ValueError('Ungültiges öffentliches Profil.')
        from live_cam_providers import HOSTS
        from urllib.parse import urlsplit
        try:url=urlsplit(p.get('sourceUrl',''));host=url.hostname or ''
        except ValueError:raise ValueError('Ungültige Profilquelle.')
        if url.scheme!='https' or host.removeprefix('www.')!=HOSTS[key.split(':')[0]].removeprefix('www.') or url.username or url.password or url.query or url.fragment or not url.path.rstrip('/').casefold().endswith('/'+key.split(':')[1].casefold()):raise ValueError('Die Profilquelle gehört nicht zum gewählten Anbieter und Model.')
        if not isinstance(p.get('bio',''),str) or number(p.get('observedAt')) is None:raise ValueError('Unlesbares Profil.')
        if not isinstance(p.get('displayName',''),str) or len(p.get('displayName',''))>500:raise ValueError('Ungültiger Profilname.')
        sections=p.get('sections',[])
        if not isinstance(sections,list) or len(sections)>100 or any(not isinstance(s,dict) or not isinstance(s.get('label'),str) or not isinstance(s.get('text'),str) for s in sections):raise ValueError('Ungültige Profilabschnitte.')
        for field in ('tags','links','images'):
            values=p.get(field,[])
            if not isinstance(values,list) or len(values)>200 or any(not isinstance(v,str) or len(v)>4000 for v in values):raise ValueError('Ungültige öffentliche Profilfelder.')
        facts=p.get('facts',[])
        if not isinstance(facts,list) or len(facts)>80 or any(not isinstance(f,dict) or not isinstance(f.get('label'),str) or not isinstance(f.get('value'),str) or len(f['label'])>160 or len(f['value'])>4000 for f in facts):raise ValueError('Ungültige öffentliche Profilangaben.')
        history=p.get('history',[])
        if not isinstance(history,list) or len(history)>20:raise ValueError('Zu viele Profilrevisionen.')
        for previous in history:
            if not isinstance(previous,dict) or 'history' in previous:raise ValueError('Ungültiger Profilverlauf.')
            self.validate_profile(key,previous)

    def archive(self,body):
        action=body.get('action','list');profiles=self.config['profiles']
        if action=='list':
            q=str(body.get('q') or '').casefold();sites=body.get('sites',list(self.b['_CAM_SITES']))
            rows=[p for k,p in profiles.items() if k.split(':')[0] in sites and q in (k+' '+p.get('bio','')).casefold()];rows.sort(key=lambda p:p['observedAt'],reverse=True)
            page=max(0,int(body.get('page') or 0));page=min(page,max(0,(len(rows)-1)//24))
            return {'ok':True,'total':len(rows),'page':page,'pages':max(1,math.ceil(len(rows)/24)),
                    'historyCount':sum(len(p.get('history',[])) for p in rows),'items':[{'id':p['id'],'displayName':p.get('displayName'),'observedAt':p['observedAt'],'revisions':len(p.get('history',[]))+1} for p in rows[page*24:page*24+24]]}
        if action=='export':return {'ok':True,'document':{'format':'AdultClient-PublicProfiles','version':1,'profiles':copy.deepcopy(profiles)}}
        if action=='preview':
            doc=body.get('document')
            if not isinstance(doc,dict) or doc.get('version')!=1 or doc.get('format') not in ('AdultClient-PublicProfiles','AdultHideout-PublicProfiles') or not isinstance(doc.get('profiles'),dict) or len(doc['profiles'])>60000:raise ValueError('Unbekanntes Profilarchivformat.')
            for key,p in doc['profiles'].items():self.validate_profile(key,p)
            token=uuid.uuid4().hex;self.queries['import:'+token]=(time.monotonic()+600,copy.deepcopy(doc['profiles']),hashlib.sha256(json.dumps(profiles,sort_keys=True).encode()).hexdigest())
            return {'ok':True,'preview':token,'count':len(doc['profiles']),'new':sum(k not in profiles for k in doc['profiles'])}
        if action in ('commit','clear'):
            next_config=self.config_copy()
            if action=='commit':
                item=self.queries.get('import:'+str(body.get('preview')))
                if not item or item[0]<time.monotonic() or item[2]!=hashlib.sha256(json.dumps(profiles,sort_keys=True).encode()).hexdigest():raise ValueError('Die Importvorschau ist abgelaufen oder der Bestand wurde geändert.')
                for key,p in item[1].items():
                    if key not in profiles or p['observedAt']>profiles[key]['observedAt']:
                        next_config['profiles'][key]=clean_profile(p)
            else:next_config['profiles']={}
            backup=os.path.join(self.b['PROFILE'],'cam_model_backups','profiles-'+uuid.uuid4().hex+'.json');self.b['_cam_json_write'](backup,{'format':'AdultClient-PublicProfiles','version':1,'profiles':self.config['profiles']})
            self.save_config(next_config,archive_reset=True);return {'ok':True,'backup':backup}
        raise ValueError('Unbekannte Archivaktion.')

    def handle(self,raw):
        try:
            body=json.loads(raw.decode('utf-8') or '{}')
            if not isinstance(body,dict):raise ValueError('Unlesbare Bibliotheksanfrage.')
            if isinstance(body.get('op'),str) and body['op'].startswith('biography-'):
                return self.b['_cam_biography_service']().handle(body)
            with self.lock:
                op=body.get('op')
                if isinstance(op,str) and op.startswith('notifications-'):
                    if not hasattr(self,'notifications_hub'):
                        from live_cam_notifications import NotificationsHub
                        self.notifications_hub=NotificationsHub(self)
                    return self.notifications_hub.handle(body)
                if isinstance(op,str) and op.startswith('statistics-'):
                    if not hasattr(self,'statistics_hub'):
                        from live_cam_statistics import StatisticsHub
                        self.statistics_hub=StatisticsHub(self)
                    return self.statistics_hub.handle(body)
                if isinstance(op,str) and op.startswith('groups-'):return self.group_service().handle(body)
                if isinstance(op,str) and op.startswith('discover-'):
                    if not hasattr(self,'discover_hub'):
                        from live_cam_discover import DiscoverHub
                        self.discover_hub=DiscoverHub(self)
                    return self.discover_hub.handle(body)
                if isinstance(op,str) and op.startswith('following-'):
                    if not hasattr(self,'following_hub'):
                        from live_cam_following import FollowingHub
                        self.following_hub=FollowingHub(self)
                    return self.following_hub.handle(body)
                if op=='collector':
                    playing=body.get('playing',[])
                    if not isinstance(playing,list) or len(playing)>240 or any(not self.key(k) for k in playing):raise ValueError('Ungültiger Wiedergabestatus.')
                    token=body.get('token');active=body.get('active')
                    result=self.b['_cam_library_sync']().presence(token,active,body.get('priorities',[]))
                    if active and playing:self.playback.setdefault(token,{}).update({key:int(time.time()*1000) for key in playing})
                    elif not active:self.playback.pop(token,None)
                    if hasattr(self,'groups_hub'):self.groups_hub.cache=None
                    return result
                if op=='collector-status':return self.b['_cam_library_sync']().status()
                if op=='query':return self.query(body)
                if op=='page':return self.page(body)
                if op=='metrics':return self.upload_metrics(body)
                if op=='mutate':return self.mutate(body)
                if op=='undo':return self.restore(str(body.get('undo')))
                if op=='config':return self.configure(body)
                if op=='config-read':return {'ok':True,'config':{k:copy.deepcopy(self.config[k]) for k in ('collections','rules','notices')}}
                if op=='rules-run':return self.run_rules(body)
                if op=='profile':return self.profile(body)
                if op=='archive':return self.archive(body)
                if op=='export':return self.export(body)
                if op=='import-preview':return self.import_preview(body)
                if op=='import-commit':return self.import_commit(body)
                if op=='select':
                    cached=self.queries.get(str(body.get('query')))
                    if not cached or cached[0]<time.monotonic():raise ValueError('Trefferansicht abgelaufen.')
                    if len(cached[1])>5000:raise ValueError('Mehr als 5000 Treffer. Bitte zuerst eingrenzen oder einzelne Seiten auswählen.')
                    return {'ok':True,'ids':[r['id'] for r in cached[1]]}
                if op=='epoch':return {'ok':True,'epoch':self.b.get('_cam_models_epoch',0)}
                if op=='records':
                    ids=body.get('ids',[])
                    if not isinstance(ids,list) or len(ids)>240:raise ValueError('Zu viele Detailabfragen.')
                    wanted=set(ids);rows,_=self.records(body.get('metrics',''))
                    selected={r['id']:r for r in rows if r['id'] in wanted}
                    # Historical/imported names can exist only in a scoped query.
                    # Keep their unknown-valued cards usable in details/comparison.
                    for _,snapshot,_ in reversed(list(self.queries.values())):
                        missing=wanted-selected.keys()
                        if not missing:break
                        selected.update({r['id']:r for r in snapshot if r['id'] in missing})
                    return {'ok':True,'items':[self.clean(r) for r in selected.values()]}
                if op=='neighbors':
                    cache=self.queries.get(str(body.get('query')))
                    if not cache:raise ValueError('Die Trefferansicht ist abgelaufen.')
                    rows=cache[1];index=next((i for i,r in enumerate(rows) if r['id']==body.get('id')),-1)
                    return {'ok':True,'previous':self.clean(rows[index-1]) if index>0 else None,'next':self.clean(rows[index+1]) if index>=0 and index+1<len(rows) else None}
                if op=='similar':
                    rows,_=self.records(body.get('metrics',''));current=next((r for r in rows if r['id']==body.get('id')),None)
                    if not current:raise ValueError('Model nicht im Bestand.')
                    ranked=[]
                    for r in rows:
                        if r['id']==current['id'] or r['site'] not in body.get('sites',self.b['_CAM_SITES']) or r['personal'].get('archived') or r['personal'].get('suggestionHidden'):continue
                        tags=sorted(set(r.get('tags',[]))&set(current.get('tags',[])));reasons=['Gemeinsame Tags: '+', '.join(tags)] if tags else []
                        if r.get('country') and r.get('country')==current.get('country'):reasons.append('Gleiches Land')
                        if r.get('gender')!='unknown' and r.get('gender')==current.get('gender'):reasons.append('Gleicher Typ')
                        if reasons:ranked.append((len(tags)*3+len(reasons),r,reasons))
                    ranked.sort(key=lambda v:(-v[0],v[1]['id']))
                    return {'ok':True,'items':[{**self.clean(r),'reasons':reasons} for _,r,reasons in ranked[:24]]}
                raise ValueError('Unbekannte Modelaktion.')
        except (ValueError,TypeError,KeyError,OSError) as error:
            return {'ok':False,'error':str(error)[:350]}
