"""Discovery searches the observed public catalog, with explicit partial coverage."""
import copy
import hashlib
import os
import re
import time
import uuid
from collections import Counter
from live_cam_models import clean_filters,number,stamp
from live_cam_groups import RULE_FIELDS

SIZES=(12,18,24,30,36,48,60,72,90,96,120,160,180,240)
SORT_FIELDS={'live':'liveRank','site':'site','viewers':'viewers','name':'name','online':'seconds','age':'age','followers':'followers','hd':'hd','gaming':'gaming','lastVisit':'lastVisit','sessions':'sessions','watch':'watchMs','saved':'savedAt','rating':'rating','firstSeen':'firstSeen'}
MODES=('all','hd','gaming','new','newSince','unseen','returning','observed','favorites','watchlist','following','saved','notes','popular','fresh','forYou','paused')
EXTRA_DEFAULTS={'languages':[],'languageMode':'any','excludeTags':[],'excludeLocalTags':[],'place':'','nameMode':'contains','mode':'all','since':0,'avoidToday':False,'lessTags':[],
                'hd':'any','gaming':'any','new':'any','image':'any','tags':'any','languageInfo':'any','minOnline':None,'maxOnline':None,'maxWatch':None,'maxSessions':None}

def languages(row):
    cached=row.get('_langs')
    if isinstance(cached,set):return cached
    value=row.get('languages') or []
    if isinstance(value,str):value=re.split(r'[,;| /]+',value)
    result={v.casefold() for v in value if isinstance(v,str) and v.strip()} if isinstance(value,list) else set()
    row['_langs']=result
    return result

def extra(value):
    if not isinstance(value,dict):raise ValueError('Ungueltige Entdecken-Filter.')
    out={**copy.deepcopy(EXTRA_DEFAULTS),**{k:copy.deepcopy(v) for k,v in value.items() if k in EXTRA_DEFAULTS}}
    for key in ('languages','excludeTags','excludeLocalTags','lessTags'):
        if not isinstance(out[key],list) or len(out[key])>100 or any(not isinstance(v,str) or len(v)>100 for v in out[key]):raise ValueError('Zu viele Filterwerte.')
        out[key]=list(dict.fromkeys(v.strip().casefold().lstrip('#') for v in out[key] if v.strip()))
    for key in ('hd','gaming','new','image','tags','languageInfo'):
        if out[key] not in ('any','yes','no'):raise ValueError('Ungueltiger Merkmalsfilter.')
    if out['languageMode'] not in ('any','all') or out['nameMode'] not in ('contains','exact','prefix') or out['mode'] not in MODES:raise ValueError('Ungueltige Entdecken-Auswahl.')
    if not isinstance(out['place'],str) or len(out['place'])>500:raise ValueError('Ortsfilter ist zu lang.')
    if type(out['avoidToday']) is not bool:raise ValueError('Ungueltiger Besuchsfilter.')
    for key in ('since','minOnline','maxOnline','maxWatch','maxSessions'):
        if out[key] is not None and (number(out[key]) is None or out[key]>1e15):raise ValueError('Ungueltiger Zahlenfilter.')
    if out['minOnline'] is not None and out['maxOnline'] is not None and out['minOnline']>out['maxOnline']:raise ValueError('Minimale Onlinezeit ist groesser als maximale Onlinezeit.')
    return out

def plain_discover(extra_value, filters):
    """Default start page: no per-room language, tag, place or name-mode work."""
    if extra_value['mode']!='all':return False
    if extra_value['languages'] or extra_value['excludeTags'] or extra_value['excludeLocalTags'] or extra_value['place'] or extra_value['avoidToday']:return False
    if extra_value['nameMode']!='contains' and str(filters.get('query') or '').strip():return False
    if any(extra_value[key]!='any' for key in ('hd','gaming','new','image','tags','languageInfo')):return False
    if any(extra_value[key] is not None for key in ('minOnline','maxOnline','maxWatch','maxSessions')):return False
    return True


def sort_specs(value):
    if not isinstance(value,list) or not 1<=len(value)<=3:raise ValueError('Bitte ein bis drei Sortierkriterien waehlen.')
    if any(not isinstance(r,dict) or r.get('key') not in SORT_FIELDS or r.get('dir') not in ('asc','desc') for r in value):raise ValueError('Ungueltige Sortierung.')
    return [{'key':r['key'],'dir':r['dir']} for r in value]

class DiscoverHub:
    def __init__(self,hub):
        self.h=hub;self.b=hub.b;self.path=os.path.join(self.b['PROFILE'],'cam_discover_state.json')
        self.data=self.b['_cam_json_read'](self.path) or {'version':1,'revision':0,'profiles':[]};self.previews={}
    def definition(self,body):
        filters=clean_filters({k:v for k,v in body.get('filters',{}).items() if k in RULE_FIELDS},self.b['_CAM_SITES'])
        filters['view']='active';filters['sort']='name-az'
        if any(filters.get(key,'any') not in ('any','all') for key in ('publicTagMode','localTagMode','groupMode')):raise ValueError('Ungueltige UND/ODER-Verknuepfung.')
        seed=str(body.get('seed') or '')
        if len(seed)>100:raise ValueError('Mischkennung ist zu lang.')
        return {'filters':filters,'extra':extra(body.get('extra',{})),'sorts':sort_specs(body.get('sorts',[{'key':'live','dir':'asc'},{'key':'viewers','dir':'desc'}])),'seed':seed}
    def query(self,body):
        definition=self.definition(body);f=definition['filters'];e=definition['extra'];mode=e['mode'];now=int(time.time()*1000)
        day_start=body.get('dayStart')
        if number(day_start) is None or not now-48*3600000<=day_start<=now:day_start=now-24*3600000
        rows,groups=self.h.records(body.get('metrics',''),now);public=[r for r in rows if r.get('seen')]
        interests=Counter();preferred=set()
        if mode=='forYou':
            for r in public:
                if r['site'] in f['sites'] and (r.get('watchMs') or r.get('fav')):
                    weight=min(60,(r.get('watchMs') or 0)/60000)+(5 if r.get('fav') else 0)
                    for tag in r.get('tags',[]):interests[tag.casefold()]+=weight
            preferred={t for t,_ in interests.most_common(20)}-set(e['lessTags'])
        followed=set()
        if mode=='following' and self.b.get('_cam_user_hub'):
            accounts=self.b['_cam_user_hub']().public()
            for site,connection in accounts.get('connections',{}).items():
                snap=accounts.get('accounts',{}).get(site+':'+str(connection.get('user','')),{}) if connection.get('on') else {}
                followed.update(site+':'+v['name'] for v in snap.get('items',[]) if self.b['_cam_pair'](site,v.get('name')))
        if mode=='paused':f['view']='paused'
        def predicate(r):
            p=r['personal'];tags={str(t).casefold().lstrip('#') for t in r.get('tags',[])};own={str(t).casefold().lstrip('#') for t in p.get('tags',[])}
            spoken=languages(r)
            if e['languages'] and not (set(e['languages'])<=spoken if e['languageMode']=='all' else set(e['languages'])&spoken):return False
            if tags&set(e['excludeTags']) or own&set(e['excludeLocalTags']):return False
            if e['place'].casefold() not in str(r.get('place','')).casefold():return False
            q=f.get('query','').strip().casefold()
            if q and e['nameMode']=='exact' and r['name'].casefold()!=q:return False
            if q and e['nameMode']=='prefix' and not r['name'].casefold().startswith(q):return False
            new=r.get('new') if type(r.get('new')) is bool else None
            flags={'hd':r.get('hd'),'gaming':r.get('gaming'),'new':new,'image':bool(r.get('cover') or r.get('thumb')),'tags':bool(tags),'languageInfo':bool(spoken)}
            if any(e[k]!='any' and flags[k] is not (e[k]=='yes') for k in flags):return False
            for key,field,factor,maximum in [('minOnline','seconds',60,False),('maxOnline','seconds',60,True),('maxWatch','watchMs',60000,True),('maxSessions','sessions',1,True)]:
                if e[key] is not None:
                    v=number(r.get(field))
                    if v is None or (v>e[key]*factor if maximum else v<e[key]*factor):return False
            if e['avoidToday'] and r.get('lastVisit') and r['lastVisit']>=day_start:return False
            if mode=='hd' and r.get('hd') is not True or mode=='gaming' and r.get('gaming') is not True:return False
            if mode=='new' and new is not True:return False
            if mode=='newSince' and (not e['since'] or (r.get('firstSeen') or 0)<=e['since']):return False
            if mode=='unseen' and (r.get('sessions') or r.get('watchMs')):return False
            if mode=='returning' and (r.get('sessions') or 0)<2:return False
            if mode=='observed' and (r.get('observations') or 0)<5:return False
            if mode=='favorites' and not r.get('fav') or mode=='watchlist' and not p.get('bookmarked') or mode=='following' and r['id'] not in followed or mode=='saved' and not p.get('saved') or mode=='notes' and not p.get('notes'):return False
            if mode=='popular' and (r.get('viewers') or 0)<100:return False
            if mode=='fresh' and (r['status']!='live' or number(r.get('seconds')) is None or r['seconds']>3600):return False
            if mode=='forYou' and not tags&preferred:return False
            return True
        def ordering(items):
            default=definition['sorts']==[{'key':'live','dir':'asc'},{'key':'viewers','dir':'desc'}] and not definition['seed'] and mode!='forYou'
            if default:
                def rank(row):
                    viewers=row.get('viewers')
                    missing=type(viewers) not in (int,float)
                    return (row.get('liveRank')!=0,missing,0 if missing else -viewers,row['id'].casefold())
                return sorted(items,key=rank)
            items=sorted(items,key=lambda r:r['id'].casefold())
            for spec in reversed(definition['sorts']):
                field=SORT_FIELDS[spec['key']];known=[r for r in items if r.get(field) is not None];unknown=[r for r in items if r.get(field) is None]
                known.sort(key=lambda r:r[field].casefold() if isinstance(r[field],str) else r[field],reverse=spec['dir']=='desc');items=known+unknown
            if mode=='forYou':items.sort(key=lambda r:sum(interests[t.casefold()] for t in r.get('tags',[]) if t.casefold() in preferred),reverse=True)
            if definition['seed']:items.sort(key=lambda r:hashlib.blake2b((definition['seed']+r['id']).encode(),digest_size=8).digest())
            return items
        result=self.h.query({**body,'filters':f},predicate=None if plain_discover(e,f) else predicate,order=ordering,sizes=SIZES,include_config=False,prepared=(public,groups,now))
        chosen=[r for r in public if r['site'] in f['sites']]
        spoken=set();providers={site:{'count':0,'latest':0} for site in f['sites']};fresh=False
        for row in chosen:
            slot=providers[row['site']];slot['count']+=1
            seen=stamp(row.get('seen')) or 0
            if seen>slot['latest']:slot['latest']=seen
            spoken.update(languages(row))
            fresh=fresh or type(row.get('new')) is bool
        result['discover']={'profiles':copy.deepcopy(self.data['profiles']),'revision':self.data['revision'],
            'languages':sorted(spoken),'providers':providers,
            'states':dict(Counter(r['status'] for r in self.h.queries[result['query']][1])),
            'interestTags':sorted(preferred),'explanation':'Vorschlaege anhand deiner tatsaechlich lokal angesehenen oder favorisierten Tags.' if preferred else 'Noch keine belastbaren lokalen Interessen fuer persoenliche Vorschlaege.',
            'newFlagAvailable':fresh}
        return result
    def save(self,next_data):
        next_data['revision']=self.data['revision']+1;self.b['_cam_json_write'](self.path,next_data);self.data=next_data
        return {'ok':True,**copy.deepcopy(self.data)}
    def profiles(self,body):
        action=body.get('action','read')
        if action=='read':return {'ok':True,**copy.deepcopy(self.data)}
        if body.get('revision')!=self.data['revision']:raise ValueError('Suchprofile wurden inzwischen in einem anderen Fenster geaendert. Bitte neu lesen.')
        result=copy.deepcopy(self.data);items=result['profiles'];identity=body.get('id');old=next((p for p in items if p['id']==identity),None)
        if action=='delete':
            if not old:raise ValueError('Das Suchprofil existiert nicht mehr.')
            items.remove(old)
        elif action in ('save','rename'):
            name=body.get('name','').strip() if isinstance(body.get('name'),str) else ''
            if not name or len(name)>80:raise ValueError('Bitte einen Namen mit hoechstens 80 Zeichen waehlen.')
            if action=='rename':
                if not old:raise ValueError('Das Suchprofil existiert nicht mehr.')
                old['name']=name
            else:
                definition=self.definition(body)
                if old:items.remove(old)
                if len(items)>=50:raise ValueError('Es sind bereits 50 Suchprofile und Feeds gespeichert.')
                items.append({'id':identity if old else uuid.uuid4().hex,'name':name,'kind':'feed' if body.get('kind')=='feed' else 'profile','definition':definition})
        else:raise ValueError('Unbekannte Suchprofilaktion.')
        return self.save(result)
    def preview(self,body):
        doc=body.get('document')
        if not isinstance(doc,dict) or doc.get('format')!='AdultClient-Discover' or doc.get('version')!=1 or not isinstance(doc.get('profiles'),list) or not 1<=len(doc['profiles'])<=50:raise ValueError('Keine unterstuetzte Suchprofil-Sicherung.')
        profiles=[]
        for p in doc['profiles']:
            if not isinstance(p,dict) or not isinstance(p.get('name'),str) or not p['name'].strip() or len(p['name'])>80:raise ValueError('Ungueltiges Suchprofil.')
            profiles.append({'id':uuid.uuid4().hex,'name':p['name'].strip(),'kind':'feed' if p.get('kind')=='feed' else 'profile','definition':self.definition(p.get('definition',{}))})
        if len(self.data['profiles'])+len(profiles)>50:raise ValueError('Nach dem Import waeren mehr als 50 Suchprofile/Feeds vorhanden.')
        self.previews={k:v for k,v in self.previews.items() if v[0]>time.monotonic()}
        if len(self.previews)>=12:self.previews.pop(next(iter(self.previews)))
        token=uuid.uuid4().hex;self.previews[token]=(time.monotonic()+600,self.data['revision'],profiles)
        return {'ok':True,'preview':token,'count':len(profiles),'names':[p['name'] for p in profiles]}
    def handle(self,body):
        op=body.get('op')
        if op=='discover-query':return self.query(body)
        if op=='discover-profiles':return self.profiles(body)
        if op=='discover-export':return {'ok':True,'document':{'format':'AdultClient-Discover','version':1,'profiles':copy.deepcopy(self.data['profiles'])}}
        if op=='discover-import-preview':return self.preview(body)
        if op=='discover-import-commit':
            item=self.previews.get(str(body.get('preview')))
            if not item or item[0]<time.monotonic() or item[1]!=self.data['revision']:raise ValueError('Die Importvorschau ist abgelaufen oder der Bestand wurde geaendert. Bitte erneut pruefen.')
            backup=os.path.join(self.b['PROFILE'],'cam_discover_before_'+uuid.uuid4().hex+'.json');self.b['_cam_json_write'](backup,self.data)
            result=copy.deepcopy(self.data);result['profiles'].extend(item[2]);saved=self.save(result);self.previews.pop(str(body.get('preview')),None);return {**saved,'backup':os.path.basename(backup)}
        raise ValueError('Unbekannte Entdecken-Aktion.')
