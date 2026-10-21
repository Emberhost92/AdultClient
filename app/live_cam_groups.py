"""Live-only groups: durable manual membership, computed groups and safe transfers."""
import base64
import copy
import hashlib
import io
import json
import os
import re
import time
import uuid
import xml.etree.ElementTree as ET
from collections import Counter

from live_cam_models import clean_filters, matches, number, search_text

LABELS = {'stripchat':'Stripchat','chaturbate':'Chaturbate','bongacams':'BongaCams',
          'camsoda':'CamSoda','cam4':'CAM4','xlovecam':'XloveCam'}
RULE_FIELDS=set(('query view sort sites genders statuses countries publicTags localTags groupIds publicTagMode localTagMode groupMode source profile media seen localTagsState groupsState notesState minAge maxAge minViewers maxViewers minFollowers maxFollowers minWatchMinutes minOnlineMinutes minSessions minRating minPriority activeWithinDays minAppearances minSamples weekday hour').split())


def editable(group):
    return not group.get('systemRole') and group.get('kind','manual') == 'manual'


def artwork(raw):
    """Validate and normalize uploads; never persist arbitrary HTML or image URLs."""
    if not isinstance(raw,str) or len(raw)>1_400_000:
        raise ValueError('Das Gruppenbild darf höchstens 1 MB groß sein.')
    try:
        data=base64.b64decode(raw,validate=True)
    except (ValueError,TypeError):raise ValueError('Das Gruppenbild ist unlesbar.')
    if not data or len(data)>1_048_576:raise ValueError('Das Gruppenbild darf höchstens 1 MB groß sein.')
    if data.lstrip().startswith(b'<'):
        if b'<!' in data:raise ValueError('SVG mit externen Definitionen ist nicht erlaubt.')
        try:tree=ET.fromstring(data)
        except ET.ParseError:raise ValueError('Das SVG ist unlesbar.')
        allowed={'svg','g','path','rect','circle','ellipse','line','polyline','polygon','text','tspan','defs','linearGradient','radialGradient','stop','clipPath','title','desc'}
        if tree.tag.split('}')[-1]!='svg':raise ValueError('Kein SVG-Bild.')
        for node in tree.iter():
            if node.tag.split('}')[-1] not in allowed:raise ValueError('SVG enthält nicht unterstützte aktive Elemente.')
            for name,value in node.attrib.items():
                name=name.split('}')[-1].lower()
                if name.startswith('on') or name in ('href','src','style') or re.search(r'javascript:|https?:|data:|url\(\s*(?!#)',value,re.I):
                    raise ValueError('SVG darf keine Skripte oder externen Inhalte enthalten.')
        return ET.tostring(tree,encoding='utf-8'),'svg'
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ('PNG','JPEG','WEBP') or image.width*image.height>20_000_000:raise ValueError('Bitte PNG, JPG, WebP oder SVG verwenden; maximal 20 Megapixel.')
            image.thumbnail((1200,1200));out=io.BytesIO();image.convert('RGB').save(out,'WEBP',quality=85)
            return out.getvalue(),'webp'
    except (OSError,SyntaxError):raise ValueError('Das Gruppenbild ist beschädigt oder hat ein unbekanntes Format.')


class GroupsHub:
    def __init__(self,hub):
        self.h=hub;self.b=hub.b;self.cache=None

    def smart_members(self,rows,f,now):
        # Prepare common rules once, rather than walking every inactive filter
        # for each of up to 60,000 models and 40 groups.
        sites=set(f['sites']);words=str(f.get('query') or '').casefold().split()
        categories=[(field,set(str(v).casefold() for v in f.get(key,[]))) for key,field in
                    [('statuses','status'),('genders','gender'),('countries','country')] if f.get(key)]
        tags=[(key,set(str(v).casefold() for v in f.get(key,[])),f.get(mode)=='all') for key,mode in
              [('publicTags','publicTagMode'),('localTags','localTagMode')] if f.get(key)]
        bounds=[(field,f[key],maximum) for key,field,maximum in [('minViewers','viewers',False),('maxViewers','viewers',True),('minRating','rating',False)] if f.get(key) not in (None,'')]
        handled={'sites','sort','view','query','statuses','genders','countries','publicTags','publicTagMode','localTags','localTagMode','groupIds','groupMode','groupsState','minViewers','maxViewers','minRating'}
        simple=f.get('view','all')=='all' and not any(k not in handled and v not in (None,'','any','all',[]) for k,v in f.items())
        result=[]
        for r in rows:
            if r['site'] not in sites or (words and any(word not in search_text(r) for word in words)):continue
            if any(str(r.get(field) or 'unknown').casefold() not in values for field,values in categories):continue
            skip=False
            for key,wanted,all_tags in tags:
                found={str(t).casefold() for t in (r['personal'].get('tags',[]) if key=='localTags' else r.get('tags',[]))}
                if not (wanted<=found if all_tags else bool(wanted&found)):skip=True;break
            if skip:continue
            for field,bound,maximum in bounds:
                value=number(r.get(field))
                if value is None or (value>bound if maximum else value<bound):skip=True;break
            if not skip and (simple or matches(r,f,now)):result.append(r['id'])
        return result

    def effective(self,rows,raw,now,token=''):
        key=(self.h.index_epoch,self.h.config_epoch,token,self.h.metrics.get(token,(0,))[0])
        if self.cache and self.cache[0]==key and now-self.cache_at<10000:
            groups,members=self.cache[1:]
        else:
            groups=copy.deepcopy(raw);members={};by_id={r['id']:r for r in rows}
            for g in groups:
                g.setdefault('kind','manual');g.setdefault('revision',0);g.setdefault('description','');g.setdefault('parent','');g.setdefault('archived',False)
                if g['kind']=='smart':
                    f=clean_filters(g.get('filters',{}),self.b['_CAM_SITES'])
                    # Smart groups refer to model properties, never other computed groups.
                    f.update(groupIds=[],groupsState='any');g['items']=self.smart_members(rows,f,now)
                else:g['items']=list(dict.fromkeys(k for k in g.get('items',[]) if self.h.key(k)))
            library=self.b['_cam_library_load']()
            with self.b['_cam_lib_lock']:
                account=copy.deepcopy(library.get('account',{}));meta=copy.deepcopy(library.get('account_meta',{}))
            for site in self.b['_CAM_SITES']:
                values=account.get(site,[])
                items=list(dict.fromkeys(k for k in values if self.h.key(k) and k.startswith(site+':'))) if isinstance(values,list) else []
                g={'id':'following-'+site,'name':'Gefolgt · '+LABELS[site],'description':'Offiziell gefolgte Models dieses Kontos. Änderungen erfolgen beim Hoster oder unter „Mein Nutzer“.',
                   'kind':'system','systemRole':'following','site':site,'parent':'','archived':False,'revision':0,'items':items,'account':{k:v for k,v in meta.get(site,{}).items() if k in ('username','user','syncedAt','at','count','error','complete','source')}}
                groups.append(g)
            for g in groups:
                for identity in g['items']:members.setdefault(identity,[]).append(g['id'])
                known=[by_id[k] for k in g['items'] if k in by_id]
                g['count']=len(g['items']);g['live']=sum(r['status']=='live' for r in known)
                g['unknown']=len(g['items'])-sum(r['status']!='unknown' for r in known)
                g['providers']={site:sum(k.startswith(site+':') for k in g['items']) for site in self.b['_CAM_SITES']}
                g['cover']=('/api/cam-group-artwork?key='+g['artwork']) if g.get('artwork') else next((r.get('cover') or r.get('thumb') for r in known if r.get('cover') or r.get('thumb')),'')
            self.cache=(key,groups,members);self.cache_at=now
        # Reuse the projection instead of cloning every row. Rows without local
        # stats are the catalog index itself; group ids are reapplied when they differ.
        for row in rows:
            ids=members.get(row['id'],[])
            if row.get('groupIds')!=ids:
                row['groupIds']=list(ids);row['groupCount']=len(ids)
        return rows,groups

    def transaction(self,fn):
        library=self.b['_cam_library_load']()
        with self.b['_cam_lib_save_lock'],self.b['_cam_lib_lock']:
            updated={**library,'groups':copy.deepcopy(library.get('groups',[])),'models':dict(library['models'])}
            result=fn(updated)
            self.b['_cam_json_write'](self.b['CAM_LIBRARY'],updated)
            library.clear();library.update(updated);self.b['_cam_models_epoch']=self.b.get('_cam_models_epoch',0)+1
        self.cache=None
        return {'ok':True,**(result or {})}

    def find(self,library,identity,manual=False):
        group=next((g for g in library['groups'] if g['id']==identity),None)
        if not group or group.get('systemRole') or manual and not editable(group):
            raise ValueError('Diese Gruppe wird automatisch verwaltet und kann hier nicht geändert werden.' if str(identity).startswith('following-') or group else 'Die Gruppe existiert nicht mehr.')
        return group

    def definition(self,value,existing=None):
        if not isinstance(value,dict):raise ValueError('Ungültige Gruppendaten.')
        g=copy.deepcopy(existing or {'id':uuid.uuid4().hex[:12],'items':[],'created':int(time.time()*1000)})
        name=value.get('name',g.get('name',''))
        description=value.get('description',g.get('description',''))
        if not isinstance(name,str) or not 2<=len(name.strip())<=80:raise ValueError('Bitte einen Gruppennamen mit 2 bis 80 Zeichen eingeben.')
        if not isinstance(description,str) or len(description)>2000:raise ValueError('Die Beschreibung darf höchstens 2000 Zeichen haben.')
        kind=value.get('kind',g.get('kind','manual'))
        if kind not in ('manual','smart'):raise ValueError('Unbekannte Gruppenart.')
        if existing and kind!=existing.get('kind','manual'):raise ValueError('Die Gruppenart bleibt erhalten. Bitte eine neue Gruppe anlegen.')
        g.update(name=name.strip(),description=description,parent=value.get('parent',g.get('parent','')),kind=kind,archived=value.get('archived',g.get('archived',False)),revision=g.get('revision',0)+1)
        if not isinstance(g['parent'],str) or type(g['archived']) is not bool:raise ValueError('Ungültige Gruppeneinstellung.')
        if kind=='smart':
            f=clean_filters(value.get('filters',g.get('filters',{})),self.b['_CAM_SITES'])
            if set(f)-RULE_FIELDS:raise ValueError('Die Gruppenregel enthält unbekannte Datenfelder.')
            if f.get('groupIds') or f.get('groupsState','any')!='any' or f.get('view')=='groups':raise ValueError('Intelligente Gruppen verwenden Modelmerkmale, keine anderen Gruppen.')
            g['filters']=f;g['items']=[]
        return g

    def validate_tree(self,groups):
        by_id={g['id']:g for g in groups}
        for g in groups:
            parent=g.get('parent','');seen={g['id']}
            while parent:
                if parent in seen:raise ValueError('Eine Gruppe darf nicht ihre eigene Untergruppe sein.')
                if parent not in by_id or by_id[parent].get('systemRole'):raise ValueError('Die übergeordnete Gruppe existiert nicht mehr.')
                seen.add(parent);parent=by_id[parent].get('parent','')

    def handle(self,body):
        op=body['op'];identity=body.get('id','')
        if op=='groups-list':
            rows,groups=self.h.records(body.get('metrics',''));sites=body.get('sites',list(self.b['_CAM_SITES']))
            clean_filters({'sites':sites},self.b['_CAM_SITES']);selected=set(sites)
            live=Counter(gid for r in rows if r['site'] in selected and r['status']=='live' for gid in r['groupIds'])
            return {'ok':True,'groups':[{**{k:v for k,v in g.items() if k!='items'},'selectedCount':sum(g['providers'].get(site,0) for site in selected),
                'selectedLive':live[g['id']]} for g in groups],'epoch':self.b.get('_cam_models_epoch',0)}
        if op=='groups-query':
            f=copy.deepcopy(body.get('filters',{}));f.setdefault('view','all')
            group_ids=body.get('ids',[identity] if identity else [])
            if not isinstance(group_ids,list) or any(not isinstance(v,str) for v in group_ids):raise ValueError('Ungültige Gruppenauswahl.')
            _,groups=self.h.records(body.get('metrics',''));available={g['id'] for g in groups}
            if any(k not in available for k in group_ids):raise ValueError('Eine gewählte Gruppe existiert nicht mehr.')
            if body.get('descendants'):
                expanded=set(group_ids)
                for _ in groups:
                    new={g['id'] for g in groups if g.get('parent') in expanded};before=len(expanded);expanded|=new
                    if len(expanded)==before:break
                group_ids=list(expanded)
            f.update(groupIds=group_ids,groupMode='all' if body.get('mode')=='all' else 'any')
            return self.h.query({**body,'filters':f})
        if op=='groups-save':
            def save(lib):
                old=self.find(lib,identity) if identity else None
                if old and body.get('revision')!=old.get('revision',0):raise ValueError('Die Gruppe wurde in einem anderen Fenster geändert. Bitte neu laden; dein Entwurf bleibt offen.')
                if not old and len(lib['groups'])>=40:raise ValueError('Es sind höchstens 40 eigene Gruppen möglich.')
                g=self.definition(body.get('group'),old)
                lib['groups']=[g if old and item['id']==identity else item for item in lib['groups']]
                if not old:lib['groups'].append(g)
                self.validate_tree(lib['groups']);return {'group':g}
            return self.transaction(save)
        if op=='groups-order':
            def order(lib):
                g=self.find(lib,identity);siblings=[v for v in lib['groups'] if v.get('parent','')==g.get('parent','')]
                at=siblings.index(g);to=at+(-1 if body.get('direction')==-1 else 1)
                if 0<=to<len(siblings):
                    other=siblings[to];a=lib['groups'].index(g);b=lib['groups'].index(other);lib['groups'][a],lib['groups'][b]=lib['groups'][b],lib['groups'][a]
            return self.transaction(order)
        if op=='groups-delete':
            def delete(lib):
                g=self.find(lib,identity)
                if body.get('revision')!=g.get('revision',0):raise ValueError('Die Gruppe wurde inzwischen geändert. Bitte vor dem Löschen neu laden.')
                lib['groups']=[v for v in lib['groups'] if v['id']!=identity]
                for item in lib['groups']:
                    if item.get('parent')==identity:item['parent']=g.get('parent','');item['revision']=item.get('revision',0)+1
            return self.transaction(delete)
        if op=='groups-members':
            ids=body.get('ids');action=body.get('action');target=body.get('target');source=body.get('source')
            if not isinstance(ids,list) or not 1<=len(ids)<=5000 or len(set(ids))!=len(ids) or any(not self.h.key(k) for k in ids):raise ValueError('Bitte 1 bis 5000 konkrete Models auswählen.')
            if action not in ('copy','move','remove'):raise ValueError('Unbekannte Mitgliedsaktion.')
            if action=='move' and target==source:raise ValueError('Quelle und Ziel sind identisch.')
            def members(lib):
                dst=self.find(lib,target,True) if action!='remove' else None
                src=self.find(lib,source,True) if action!='copy' else None
                if dst and dst.get('archived'):raise ValueError('Bitte die Zielgruppe zuerst wiederherstellen.')
                if src and any(k not in src.get('items',[]) for k in ids):raise ValueError('Die Auswahl gehört nicht vollständig zur Quellgruppe. Bitte neu laden.')
                if dst:
                    dst['items']=list(dict.fromkeys(dst.get('items',[])+ids));dst['revision']=dst.get('revision',0)+1
                    if len(dst['items'])>60000:raise ValueError('Die Zielgruppe enthält zu viele Models.')
                    for key in ids:
                        if key not in lib['models']:
                            site,name=key.split(':',1);lib['models'][key]={'site':site,'name':name,'online':None,'show':'unknown','seen':0,'personal':{}}
                if src:
                    wanted=set(ids);src['items']=[k for k in src.get('items',[]) if k not in wanted];src['revision']=src.get('revision',0)+1
                return {'count':len(ids)}
            return self.transaction(members)
        if op=='groups-artwork':
            filename=''
            if body.get('data'):
                data,ext=artwork(body['data']);filename=hashlib.sha256(data).hexdigest()+'.'+ext
                folder=os.path.join(self.b['PROFILE'],'cam_group_artwork');os.makedirs(folder,exist_ok=True)
                path=os.path.join(folder,filename)
                if not os.path.exists(path):
                    with open(path+'.tmp','wb') as out:out.write(data)
                    os.replace(path+'.tmp',path)
            def save_art(lib):
                g=self.find(lib,identity)
                if body.get('revision')!=g.get('revision',0):raise ValueError('Die Gruppe wurde inzwischen geändert. Bitte neu laden.')
                g['artwork']=filename;g['revision']=g.get('revision',0)+1
            return self.transaction(save_art)
        if op=='groups-export':
            _,groups=self.h.records(body.get('metrics',''));ids=body.get('ids',[])
            if not isinstance(ids,list) or not 1<=len(ids)<=40 or any(k not in {g['id'] for g in groups} for k in ids):raise ValueError('Bitte 1 bis 40 Gruppen pro Exportdatei auswählen.')
            data=[]
            for g in groups:
                if g['id'] not in ids:continue
                item={k:copy.deepcopy(g[k]) for k in ('id','name','description','parent','kind','filters','items','archived') if k in g}
                if g.get('systemRole'):item.update(kind='manual',name=g['name']+' (Kopie)',parent='')
                if g.get('artwork'):
                    path=os.path.join(self.b['PROFILE'],'cam_group_artwork',g['artwork'])
                    if os.path.isfile(path):
                        with open(path,'rb') as image:item['image']=base64.b64encode(image.read()).decode('ascii')
                data.append(item)
            value={'kind':'ah-livecam-groups','schema':1,'groups':data}
            if len(json.dumps(value,ensure_ascii=False).encode('utf-8'))>15*1024*1024:raise ValueError('Diese Gruppenbilder ergeben eine Datei über 15 MB. Bitte weniger Gruppen gemeinsam exportieren.')
            return {'ok':True,'value':value}
        if op in ('groups-import-preview','groups-import-commit'):
            value=body.get('value')
            if not isinstance(value,dict) or value.get('kind')!='ah-livecam-groups' or value.get('schema')!=1:raise ValueError('Unbekanntes Gruppenformat.')
            incoming=value.get('groups')
            if not isinstance(incoming,list) or not 1<=len(incoming)<=40:raise ValueError('Bitte 1 bis 40 Gruppen importieren.')
            staged=[];mapping={}
            for raw in incoming:
                g=self.definition(raw);old=raw.get('id')
                if not isinstance(old,str) or old in mapping:raise ValueError('Doppelte oder fehlende Gruppenkennung.')
                mapping[old]=g['id'];items=raw.get('items',[])
                if not isinstance(items,list) or len(items)>60000 or any(not self.h.key(k) for k in items):raise ValueError('Ungültige Gruppenmitglieder.')
                g['items']=list(dict.fromkeys(items)) if g['kind']=='manual' else []
                if raw.get('image'):
                    data,ext=artwork(raw['image']);g['_image']=(data,ext)
                staged.append(g)
            for g in staged:g['parent']=mapping.get(g['parent'],'')
            self.validate_tree(staged)
            if op.endswith('preview'):return {'ok':True,'groups':[{'name':g['name'],'kind':g['kind'],'count':len(g['items'])} for g in staged]}
            def commit(lib):
                if len(lib['groups'])+len(staged)>40:raise ValueError('Der Import würde mehr als 40 eigene Gruppen ergeben.')
                initial_count=len(lib['models'])
                for g in staged:
                    g['name']=(g['name']+' (Import)')[:80]
                    image=g.pop('_image',None)
                    if image:
                        data,ext=image;folder=os.path.join(self.b['PROFILE'],'cam_group_artwork');os.makedirs(folder,exist_ok=True);filename=hashlib.sha256(data).hexdigest()+'.'+ext
                        with open(os.path.join(folder,filename),'wb') as out:out.write(data)
                        g['artwork']=filename
                    lib['groups'].append(g)
                    for key in g['items']:
                        if key not in lib['models']:
                            site,name=key.split(':',1);lib['models'][key]={'site':site,'name':name,'online':None,'show':'unknown','seen':0,'personal':{}}
                if len(lib['models'])-initial_count>60000:raise ValueError('Bitte höchstens 60000 neue Models je Gruppenimport übernehmen.')
                return {'count':len(staged)}
            return self.transaction(commit)
        raise ValueError('Unbekannte Gruppenaktion.')

    def legacy(self,body):
        """Older Singlecam/Multicam controls use the same protections and writes."""
        op=body['op'];identity=body.get('id','')
        if op=='group-add':return self.handle({'op':'groups-save','group':{'name':body.get('name','')}})
        if op=='group-item':
            key=self.h.key(str(body.get('site',''))+':'+str(body.get('name','')))
            return self.handle({'op':'groups-members','action':'copy' if body.get('on') else 'remove','ids':[key],'target':identity,'source':identity})
        library=self.b['_cam_library_load']()
        with self.b['_cam_lib_lock']:g=copy.deepcopy(self.find(library,identity)) if op!='group-order' else None
        if op=='group-delete':return self.handle({'op':'groups-delete','id':identity,'revision':g.get('revision',0)})
        if op=='group-rename':return self.handle({'op':'groups-save','id':identity,'revision':g.get('revision',0),'group':{'name':body.get('name')}})
        if op=='group-order':
            ids=body.get('ids',body.get('items',body.get('order',[])))
            if not isinstance(ids,list) or any(not isinstance(k,str) for k in ids):raise ValueError('Ungültige Reihenfolge.')
            def reorder(lib):
                by_id={g['id']:g for g in lib['groups']}
                if len(set(ids))!=len(ids) or any(k not in by_id for k in ids):raise ValueError('Ungültige Gruppenreihenfolge.')
                lib['groups']=[by_id[k] for k in ids]+[g for g in lib['groups'] if g['id'] not in ids]
            return self.transaction(reorder)
        raise ValueError('Unbekannte Gruppenaktion.')
