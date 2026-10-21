"""Account-scoped following views and separate, explicitly local list imports."""
import copy
import json
import os
import re
import time
import uuid
from collections import Counter


class FollowingHub:
    def __init__(self, models):
        self.h=models;self.b=models.b
        self.path=os.path.join(self.b['PROFILE'],'cam_following_imports.json')
        self.data=self.b['_cam_json_read'](self.path) or {'version':1,'sites':{}}
        self.previews={}

    def public(self):
        public=self.b['_cam_user_hub']().public()
        accounts={key:{k:copy.deepcopy(s.get(k)) for k in ('site','user','at','complete','warning','observedCount')}|{'count':len(s.get('items',[]))} for key,s in public.get('accounts',{}).items()}
        return {'ok':True,'connections':public.get('connections',{}),'accounts':accounts,
                'imports':{site:{k:copy.deepcopy(v) for k,v in row.items() if k!='ids'}|{'count':len(row.get('ids',[]))} for site,row in self.data['sites'].items()}}

    def scope(self,body):
        source=body.get('followingSource','official')
        if source not in ('official','saved','imported'):raise ValueError('Unbekannte Following-Quelle.')
        public=self.b['_cam_user_hub']().public();scopes={};used={}
        sites=body.get('filters',{}).get('sites',list(self.b['_CAM_SITES']))
        if not isinstance(sites,list) or any(s not in self.b['_CAM_SITES'] for s in sites):raise ValueError('Ungültige Hoster-Auswahl.')
        choices=body.get('accounts',{})
        if not isinstance(choices,dict):raise ValueError('Ungültige Kontoauswahl.')
        for site in sites:
            if source=='imported':
                row=self.data['sites'].get(site,{})
                ids=[key for key in row.get('ids',[]) if self.h.key(key) and key.startswith(site+':')]
                scopes.update({key:None for key in ids});used[site]={'source':'imported','count':len(ids),'at':row.get('at')}
                continue
            connection=public.get('connections',{}).get(site,{})
            key=site+':'+str(connection.get('user','')) if source=='official' and connection.get('on') else choices.get(site) if source=='saved' else None
            snap=public.get('accounts',{}).get(key)
            if not snap or snap.get('site')!=site:continue
            used[site]={'source':source,'user':snap['user'],'at':snap.get('at'),'complete':snap.get('complete'),'count':len(snap.get('items',[]))}
            for room in snap.get('items',[]):
                key=self.b['_cam_pair'](site,room.get('name'))
                if key:scopes[key]=room
        return scopes,used

    def query(self,body):
        scope,used=self.scope(body)
        # The library query retains paging, filtering, metrics and player identities.
        # Only the server-resolved account list may define membership.
        subset=body.get('localSubset','all')
        if subset not in ('all','favorites','seen','unseen','organized','unorganized','notes'):raise ValueError('Unbekannte lokale Following-Auswahl.')
        filters={**body.get('filters',{}),'view':'all'}
        if subset=='favorites':filters['view']='favorites'
        if subset in ('seen','unseen'):filters['seen']='yes' if subset=='seen' else 'no'
        if subset in ('organized','unorganized'):filters['source']='personal' if subset=='organized' else 'automatic'
        if subset=='notes':filters['notesState']='yes'
        request={**body,'filters':filters}
        result=self.h.query(request,scope=scope)
        result['following']=self.public();result['following']['used']=used
        result['following']['states']=dict(Counter(r['status'] for r in self.h.queries[result['query']][1]))
        return result

    def preview(self,body):
        site=body.get('site');mode=body.get('mode','append');text=body.get('text')
        if site not in self.b['_CAM_SITES'] or mode not in ('append','replace'):raise ValueError('Hoster oder Importart fehlt.')
        if not isinstance(text,str) or len(text)>1000000:raise ValueError('Die Namensliste darf höchstens 1 MB groß sein.')
        entries=[s.strip().lstrip('@') for s in re.split(r'[\s,;]+',text) if s.strip()]
        if len(entries)>10000:raise ValueError('Bitte höchstens 10000 Namen importieren.')
        ids=[];seen=set();invalid=[];duplicates=0
        for name in entries:
            key=self.b['_cam_pair'](site,name[len(site)+1:] if name.startswith(site+':') else name)
            if not key:invalid.append(name[:100])
            elif key in seen:duplicates+=1
            else:ids.append(key);seen.add(key)
        if not ids:raise ValueError('Keine gültigen Modelnamen gefunden. Es werden ausschließlich Namen importiert, keine Passwörter oder Sitzungen.')
        old=self.data['sites'].get(site,{});before=set(old.get('ids',[]));after=set(ids) if mode=='replace' else before|set(ids)
        if len(after)>60000:raise ValueError('Die lokale Liste darf höchstens 60000 Namen pro Hoster enthalten.')
        now=time.monotonic();self.previews={k:v for k,v in self.previews.items() if now-v['time']<600}
        while len(self.previews)>=12:self.previews.pop(next(iter(self.previews)))
        token=uuid.uuid4().hex;self.previews[token]={'time':now,'site':site,'mode':mode,'ids':sorted(after),'before':copy.deepcopy(old)}
        return {'ok':True,'preview':token,'valid':len(ids),'duplicates':duplicates,'invalid':invalid[:30],'invalidCount':len(invalid),
                'added':len(after-before),'removed':len(before-after),'unchanged':len(before&after),'total':len(after),'sample':ids[:12]}

    def commit(self,body):
        item=self.previews.get(str(body.get('preview')))
        if not item or time.monotonic()-item['time']>600:raise ValueError('Die Importvorschau ist abgelaufen. Bitte erneut prüfen.')
        if item['mode']=='replace' and body.get('complete') is not True:raise ValueError('Ersetzen benötigt eine ausdrücklich als vollständig bestätigte Liste.')
        site=item['site']
        if self.data['sites'].get(site,{})!=item['before']:raise ValueError('Die lokale Liste wurde inzwischen geändert. Bitte erneut prüfen.')
        updated=copy.deepcopy(self.data);updated['sites'][site]={'ids':item['ids'],'at':int(time.time()*1000),'source':'local-import','completeConfirmed':bool(body.get('complete'))}
        backup=os.path.join(self.b['PROFILE'],'cam_following_before_'+uuid.uuid4().hex+'.json')
        self.b['_cam_json_write'](backup,self.data)
        self.b['_cam_json_write'](self.path,updated)
        self.data=updated;self.previews.pop(str(body.get('preview')),None)
        return {'ok':True,'count':len(item['ids']),'backup':os.path.basename(backup)}

    def handle(self,body):
        op=body.get('op')
        if op=='following-read':return self.public()
        if op=='following-query':return self.query(body)
        if op=='following-import-preview':return self.preview(body)
        if op=='following-import-commit':return self.commit(body)
        raise ValueError('Unbekannte Following-Aktion.')
