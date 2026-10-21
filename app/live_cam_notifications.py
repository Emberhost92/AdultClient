"""Persistent, in-app Live notifications. No browser permissions or account imports.

All evaluation is serialized by ModelsHub.lock, including across browser tabs.
Only explicit, fresh public observations are comparable. Catalog absence is never
an offline observation: the current providers expose partial catalogs.
"""
import copy
import hashlib
import json
import os
import re
import time
import uuid

DAY = 86400000
EVENTS = ('online', 'offline', 'profile', 'inactive', 'favorite')
MODES = {'off': 0, 'personal': 1, 'live': 2, 'always': 3}
TARGETS = ('official', 'details', 'workspace', 'multi')


def defaults(sites):
    return dict(enabled=False, sites=list(sites), scope='favorites', groups=[],
                events=['online'], delivery=True, position='right', density='comfortable',
                duration=8, maxVisible=3, target='details', workspace='default', anonymous=False,
                quiet=False, quietStart='22:00', quietEnd='08:00', cooldown=5,
                perCheck=5, perHour=30, favoriteThreshold=0, inactiveDays=0,
                modes=[], rules=[])


def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Ungültiger Wert: ' + label)
    return value


def quiet(settings, now):
    if not settings['quiet'] or settings['quietStart'] == settings['quietEnd']:
        return False
    local = time.localtime(now / 1000)
    at = '%02d:%02d' % (local.tm_hour, local.tm_min)
    start, end = settings['quietStart'], settings['quietEnd']
    return start <= at < end if start < end else at >= start or at < end


def profile(row):
    # Viewers, current topic and image URLs are volatile and are not profile edits.
    result={}
    for key in ('displayName','bio','age','country','place','languages','publicFacts','profileTags'):
        value=row.get(key)
        if key=='publicFacts' and isinstance(value,list):
            value=[v for v in value if isinstance(v,dict) and not re.search(r'viewers?|zuschauer|followers?|online|rank|rang|score|last.?seen|seconds|aktuell|zuletzt|zeit',str(v.get('label','')),re.I)]
        if value in (None,'',[],{}):continue
        if isinstance(value,list):value=sorted(value,key=lambda v:json.dumps(v,sort_keys=True,ensure_ascii=False))
        result[key]=hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]
    return result


def profile_changed(before, after):
    return any(before[key] != after[key] for key in before.keys() & after.keys())


class NotificationsHub:
    def __init__(self, hub, clock=None):
        self.h, self.b = hub, hub.b
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.path = os.path.join(self.b['PROFILE'], 'cam_notifications.json')
        stored = self.b['_cam_json_read'](self.path)
        if not stored and os.path.exists(self.path):
            raise ValueError('Der Benachrichtigungsspeicher konnte nicht gelesen werden. Die vorhandene Datei bleibt unverändert.')
        self.data = stored or dict(version=1, revision=0, settings=defaults(self.b['_CAM_SITES']),
                                   baseline={}, history=[], cooldowns={}, hourly=[], lastCheck=0, settingsRevision=0)
        if self.data.get('version') != 1:
            raise ValueError('Neuere Benachrichtigungsdaten bleiben geschützt.')
        self.validate(self.data['settings'])

    def validate(self, raw):
        if not isinstance(raw, dict) or set(raw) - set(defaults(self.b['_CAM_SITES'])):
            raise ValueError('Ungültige Benachrichtigungseinstellungen.')
        s = {**defaults(self.b['_CAM_SITES']), **copy.deepcopy(raw)}
        for key in ('enabled', 'delivery', 'anonymous', 'quiet'):
            if type(s[key]) is not bool: raise ValueError('Ungültiger Schalter: ' + key)
        for key, values in dict(scope=('favorites', 'following', 'groups', 'intersection', 'rules'),
                                position=('header', 'center', 'right'), density=('compact', 'comfortable', 'detailed'),
                                target=TARGETS).items():
            if s[key] not in values: raise ValueError('Ungültige Auswahl: ' + key)
        if not isinstance(s['sites'], list) or len(s['sites']) > 6 or len(set(s['sites'])) != len(s['sites']) or any(v not in self.b['_CAM_SITES'] for v in s['sites']):
            raise ValueError('Ungültige Hoster-Auswahl.')
        if not isinstance(s['groups'], list) or len(s['groups']) > 400 or any(not isinstance(v, str) or not re.fullmatch(r'[\w-]{1,80}', v) for v in s['groups']):
            raise ValueError('Ungültige Gruppenauswahl.')
        if not isinstance(s['events'], list) or any(v not in EVENTS for v in s['events']): raise ValueError('Ungültige Ereignisse.')
        for key, low, high in [('maxVisible',1,4), ('cooldown',1,1440), ('perCheck',1,10), ('perHour',1,60), ('favoriteThreshold',0,100), ('inactiveDays',0,365)]:
            integer(s[key], low, high, key)
        if type(s['duration']) is not int or s['duration'] not in (0,3,5,8,12,20,30): raise ValueError('Ungültige Meldungsdauer.')
        for key in ('quietStart', 'quietEnd'):
            if not isinstance(s[key], str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', s[key]): raise ValueError('Ungültige Ruhezeit.')
        if not isinstance(s['workspace'], str) or not re.fullmatch(r'[\w-]{1,80}', s['workspace']): raise ValueError('Ungültiger Arbeitsbereich.')
        if not isinstance(s['modes'], list) or len(s['modes']) > 400 or not isinstance(s['rules'], list) or len(s['rules']) > 100:
            raise ValueError('Maximal 400 Modusregeln und 100 Ereignisregeln erlaubt.')
        identifiers = set()
        for kind in ('modes', 'rules'):
            for r in s[kind]:
                if not isinstance(r,dict) or not isinstance(r.get('id'),str) or not re.fullmatch(r'[\w-]{1,80}',r['id']) or r['id'] in identifiers:
                    raise ValueError('Ungültige oder doppelte Regelkennung.')
                identifiers.add(r['id'])
                if r.get('type') not in ('model','group') or not isinstance(r.get('key'),str) or (not self.h.key(r['key']) if r['type']=='model' else not re.fullmatch(r'[\w-]{1,80}', r['key'])):
                    raise ValueError('Model oder Gruppe der Regel fehlt.')
                if kind == 'modes':
                    if r.get('mode') not in MODES: raise ValueError('Ungültiger Regelmodus.')
                    integer(r.get('inactiveDays',0),0,3650,'Regel-Inaktivität')
                else:
                    if type(r.get('enabled')) is not bool or r.get('event') not in ('online','offline') or r.get('target') not in TARGETS or r.get('match') not in ('any','all','count'):
                        raise ValueError('Ungültige Ereignisregel.')
                    integer(r.get('count',1),1,1000,'Mitgliederzahl')
                    if not isinstance(r.get('workspace','default'),str) or not re.fullmatch(r'[\w-]{1,80}',r.get('workspace','default')): raise ValueError('Ungültiges Regelziel.')
        return s

    def persist(self, next_data):
        next_data['revision'] = self.data['revision'] + 1
        # Publish only after durable atomic write; failed saves preserve old state.
        self.b['_cam_json_write'](self.path, next_data)
        self.data = next_data

    def context(self):
        rows, groups = self.h.records()
        by_id = {row['id']:row for row in rows}
        from live_cam_following import FollowingHub
        following = getattr(self.h, 'following_hub', None) or FollowingHub(self.h)
        ids, used = following.scope({'filters':{'sites':self.data['settings']['sites']}})
        return by_id, [g for g in groups if not g.get('systemRole') and not g.get('archived')], set(ids), used

    def public(self, context=None):
        rows, groups, followed, used = context or self.context()
        s = self.data['settings']
        selected = self.selection(rows, groups, followed)
        observations = [self.observed(rows.get(identity, {}), self.clock()) for identity in selected]
        fresh = sum(value is not None for value in observations)
        return dict(ok=True, revision=self.data['revision'], settingsRevision=self.data.get('settingsRevision',0), settings=copy.deepcopy(s),
                    history=copy.deepcopy(self.data['history']), unread=sum(not r['read'] for r in self.data['history']),
                    lastCheck=self.data.get('lastCheck',0), sources=used,
                    groups=[dict(id=g['id'],name=g['name'],count=len(g.get('items',[]))) for g in groups],
                    monitored=len(selected), fresh=fresh, unknown=len(selected)-fresh,
                    online=sum(value is not None and value[0]=='online' for value in observations),
                    boundaries='Nur frische, ausdrücklich beobachtete Zustände. Fehlende Katalogeinträge bleiben unbekannt. Kein Monitoring bei geschlossenem oder verborgenem Live-Bereich.')

    def selection(self, rows, groups, followed, include_rules=True):
        s = self.data['settings']; selected_groups=set(s['groups'])
        members = {k for g in groups if g['id'] in selected_groups for k in g.get('items',[])}
        if s['scope']=='favorites': ids={k for k,r in rows.items() if r.get('fav')}
        elif s['scope']=='following': ids=followed
        elif s['scope']=='groups': ids=members
        elif s['scope']=='intersection': ids=members & followed
        else: ids=set()
        group_map={g['id']:set(g.get('items',[])) for g in groups}
        for rule in s['modes']+s['rules'] if include_rules else []:
            if rule.get('mode')=='off' or rule.get('enabled') is False: continue
            ids |= {rule['key']} if rule['type']=='model' else group_map.get(rule['key'],set())
        return {k for k in ids if k.split(':',1)[0] in s['sites']}

    @staticmethod
    def observed(row, now):
        at=row.get('seen') or 0
        if at<10**10: at*=1000
        if at>now+5000 or now-at>120000:return None
        show=str(row.get('show') or '').lower()
        if row.get('online') is True and show in ('public','online','live',''):
            return ('online',at)
        if row.get('online') is False and show in ('offline','off'):
            return ('offline',at)
        # Private, away, denied, fetch errors and old values are not offline.
        return None

    def tick(self, reset=False):
        now=self.clock();s=self.data['settings']
        if not s['enabled'] or not s['delivery']:return self.public()
        if not reset and now-self.data.get('lastCheck',0)<120000:return self.public()
        context=self.context();rows,groups,followed,used=context
        selected=self.selection(rows,groups,followed)
        next_data=copy.deepcopy(self.data)
        old=next_data['baseline']
        # Resuming after a long gap establishes a new initial observation.
        initial_comparison=reset or now-next_data.get('lastCheck',0)>300000
        base_ids=self.selection(rows,groups,followed,include_rules=False)
        group_map={g['id']:set(g.get('items',[])) for g in groups}
        model_modes={};group_modes={}
        for rule in s['modes']:
            (model_modes if rule['type']=='model' else group_modes).setdefault(rule['key'],[]).append(rule)
        candidates=[];changes={};next_base={}
        for identity in sorted(selected):
            row=rows.get(identity,{});previous=old.get(identity);seen=self.observed(row,now)
            account=used.get(identity.split(':')[0],{}).get('user','') if s['scope'] in ('following','intersection') else ''
            if previous and previous.get('account','')!=account:previous=None
            values=profile(row)
            if previous:
                observation=dict(previous)
            else:
                last=row.get('lastOnline') or 0
                if last<10**10:last*=1000
                observation=dict(state=None,at=0,lastOnline=last if 0<last<=now else 0,profile={},account=account)
            if seen and seen[1]>=observation['at']:
                state,at=seen
                # A first fresh online confirmation after an unknown observation
                # is useful too; partial catalog absence never becomes offline.
                if not initial_comparison and previous and state!=previous['state'] and at>previous['at'] and (previous['state'] or state=='online'):
                    changes[identity]=state
                observation.update(state=state,at=at)
                if state=='online':observation['lastOnline']=at
            elif not seen:
                observation['state']=None
            changed_profile=bool(not initial_comparison and previous and profile_changed(previous.get('profile',{}),values))
            observation['profile']={**observation.get('profile',{}),**values}
            next_base[identity]=observation
            applicable=model_modes.get(identity,[])+[r for group in row.get('groupIds',[]) for r in group_modes.get(group,[])]
            mode=max((MODES[r['mode']] for r in applicable),default=0)
            relevant=bool(row.get('fav') or row.get('personal',{}).get('rating',0)>=4 or row.get('personal',{}).get('priority',0)>=3 or row.get('personal',{}).get('tags'))
            allowed=set(s['events']) if identity in base_ids else set()
            if mode>=2 or mode==1 and relevant:allowed.add('online')
            if mode==3:allowed.update(('offline','profile'))
            event=changes.get(identity)
            if event=='online' and row.get('fav') and 'favorite' in allowed:event='favorite'
            if event in allowed:candidates.append(self.message(identity,event,row,s['target'],s['workspace'],now))
            if changed_profile and 'profile' in allowed:candidates.append(self.message(identity,'profile',row,s['target'],s['workspace'],now))
            threshold=max([s['inactiveDays'] if identity in base_ids and 'inactive' in allowed else 0]+[r.get('inactiveDays',0) for r in applicable if r['mode']!='off'])
            last=observation['lastOnline']
            if previous and threshold and last and now-last>=threshold*DAY and not (seen and seen[0]=='online'):
                m=self.message(identity,'inactive',row,s['target'],s['workspace'],now)
                m['text']=row.get('name',identity.split(':')[1])+' wurde seit mindestens '+str(threshold)+' Tagen nicht online beobachtet.'
                m['cooldownKey']=identity+':inactive:'+str(last);m['once']=True;candidates.append(m)
        for rule in s['rules']:
            if not rule['enabled']:continue
            members=({rule['key']} if rule['type']=='model' else group_map.get(rule['key'],set())) & selected
            matched=sorted(k for k in members if changes.get(k)==rule['event'])
            needed=len(members) if rule['match']=='all' else rule.get('count',1) if rule['match']=='count' else 1
            # Group aggregates require a fresh known observation for every member
            # in this comparison, not a collection of unrelated historical changes.
            complete=all(k in old and next_base.get(k,{}).get('at',0)>old[k].get('at',0) and self.observed(rows.get(k,{}),now) for k in members)
            if members and len(matched)>=needed and (rule['type']=='model' or complete):
                m=self.message(matched[0],rule['event'],rows.get(matched[0],{}),rule['target'],rule.get('workspace','default'),now)
                if rule['type']=='group':
                    name=next((g['name'] for g in groups if g['id']==rule['key']),rule['key'])
                    m.update(text=name+': '+str(len(matched))+' Models '+('sind jetzt live.' if rule['event']=='online' else 'sind offline gegangen.'),group=rule['key'],members=matched[:1000],memberCount=len(matched),sites=list(s['sites']))
                    m['cooldownKey']='group:'+rule['key']+':'+rule['event']
                candidates.insert(0,m)
        threshold=s['favoriteThreshold']
        favorites=[k for k in selected if rows.get(k,{}).get('fav') and self.observed(rows[k],now) and self.observed(rows[k],now)[0]=='online']
        if not initial_comparison and old and threshold and len(favorites)>=threshold and next_data.get('favoriteCount',0)<threshold:
            m=self.message(favorites[0],'threshold',rows[favorites[0]],s['target'],s['workspace'],now)
            m.update(text=str(len(favorites))+' ausgewählte Favoriten sind gleichzeitig live beobachtet.',cooldownKey='favorite-threshold',members=favorites[:100]);candidates.append(m)
        next_data.update(baseline=next_base,lastCheck=now,favoriteCount=len(favorites))
        next_data['hourly']=[t for t in next_data['hourly'] if now-3600000<t<=now]
        cooldowns=next_data['cooldowns']
        next_data['cooldowns']={k:v for k,v in cooldowns.items() if v>now-DAY or ':inactive:' in k and k.rsplit(':inactive:',1)[0] in next_base and k.endswith(':'+str(next_base[k.rsplit(':inactive:',1)[0]]['lastOnline']))}
        count=0;dedup=set()
        if not quiet(s,now):
            for m in candidates:
                event='online' if m['event']=='favorite' else m['event']
                key=m.pop('cooldownKey',m['identity']+':'+event);once=m.pop('once',False)
                signature=('group:'+m['group'] if m.get('group') else m['identity'],event)
                if signature in dedup:continue
                dedup.add(signature)
                last=next_data['cooldowns'].get(key)
                if last is not None and (once or now-last<s['cooldown']*60000):continue
                if count>=s['perCheck'] or len(next_data['hourly'])>=s['perHour']:break
                next_data['history'].insert(0,m);next_data['cooldowns'][key]=now;next_data['hourly'].append(now);count+=1
        next_data['history']=next_data['history'][:200]
        self.persist(next_data)
        return self.public(context)

    @staticmethod
    def message(identity,event,row,target,workspace,now):
        name=row.get('name') or identity.split(':')[1]
        texts=dict(online=name+' ist jetzt live.',offline=name+' ist offline gegangen.',
                   favorite='Dein Favorit '+name+' ist jetzt live.',profile='Öffentliche Profilinformationen von '+name+' wurden aktualisiert.')
        return dict(id=uuid.uuid4().hex,identity=identity,site=identity.split(':')[0],name=name,
                    event=event,text=texts.get(event,name),at=now,read=False,target=target,workspace=workspace,
                    cover=row.get('cover') or row.get('thumb') or '')

    def handle(self, body):
        op=body['op'];now=self.clock()
        if op=='notifications-read':return self.public()
        if op=='notifications-tick':
            if body.get('paused') is True:return self.public()
            resume=body.get('resumeAt',0)
            if not isinstance(resume,(int,float)) or isinstance(resume,bool) or not 0<=resume<=now+5000:raise ValueError('Ungültiger Zeitpunkt der Fortsetzung.')
            return self.tick(self.data.get('lastCheck',0)<resume)
        next_data=copy.deepcopy(self.data)
        if op=='notifications-save':
            if body.get('settingsRevision')!=self.data.get('settingsRevision',0):raise ValueError('Eine andere Ansicht hat die Einstellungen geändert. Bitte neu laden und erneut bearbeiten.')
            next_data['settings']=self.validate(body.get('settings'))
            next_data.update(baseline={},lastCheck=0,favoriteCount=0,settingsRevision=self.data.get('settingsRevision',0)+1)
        elif op=='notifications-claim':
            ids=body.get('ids',[])
            if not isinstance(ids,list) or len(ids)>200:raise ValueError('Ungültige Zustellauswahl.')
            claimed=[]
            for row in next_data['history']:
                if row['id'] in ids and not row.get('deliveredAt'):
                    row['deliveredAt']=now;claimed.append(copy.deepcopy(row))
            if claimed:self.persist(next_data)
            return dict(ok=True,claimed=claimed)
        elif op=='notifications-mark':
            wanted=body.get('ids')
            if wanted!='all' and (not isinstance(wanted,list) or len(wanted)>200):raise ValueError('Ungültige Meldungsauswahl.')
            for row in next_data['history']:
                if wanted=='all' or row['id'] in wanted:row['read']=True
        elif op=='notifications-clear':
            if body.get('confirm') is not True:raise ValueError('Bitte Löschen des Verlaufs bestätigen.')
            next_data['history']=[]
        elif op=='notifications-test':
            if not next_data['settings']['delivery']:raise ValueError('Bitte die Zustellung „In der Anwendung“ einschalten.')
            next_data['history'].insert(0,dict(id=uuid.uuid4().hex,identity='',site='',name='Testmeldung',event='test',text='Testmeldung: So erscheinen deine Live-Benachrichtigungen.',at=now,read=False,target='details',workspace='default',cover=''))
            next_data['history']=next_data['history'][:200]
        else:raise ValueError('Unbekannte Benachrichtigungsaktion.')
        self.persist(next_data)
        return self.public()
