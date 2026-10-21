"""Live-Cam account snapshots. Credentials are never part of this document."""
import copy
import hashlib
import json
import math
import os
import re
import threading
import time
import uuid


class AccountHub:
    def __init__(self, backend):
        self.b = backend
        self.path = os.path.join(backend['PROFILE'], 'cam_user_snapshots.json')
        self.lock = threading.RLock()
        self.jobs = {}
        self.previews = {}
        self.generations = {}
        self.data = backend['_cam_json_read'](self.path) or {'version': 1, 'accounts': {}, 'stats': {}}
        self.data.setdefault('accounts', {})
        self.data.setdefault('stats', {})

    def save(self):
        self.b['_cam_json_write'](self.path, self.data)

    def public(self):
        with self.lock:
            return {'ok': True, 'connections': self.b['_cam_account_public'](), **copy.deepcopy(self.data)}

    @staticmethod
    def signature(library):
        return hashlib.sha256(json.dumps(library, sort_keys=True, ensure_ascii=True).encode()).hexdigest()

    @staticmethod
    def session_fingerprint(jar,user):
        cookies=sorted((c.domain,c.name,c.value,c.path) for c in jar)
        return hashlib.sha256(json.dumps([user,cookies],sort_keys=True).encode()).hexdigest()

    def refresh(self, body):
        site = self.b['_cam_site'](body.get('site'))
        if site in ('cam4', 'xlovecam'):
            raise ValueError('Die Kontoanmeldung ist verfügbar. Die offizielle Following-Liste dieses Anbieters lässt sich hier noch nicht zuverlässig abrufen. Bitte auf der offiziellen Website öffnen.')
        request_id = str(body.get('requestId') or '')[:80]
        if not site or not re.fullmatch(r'[a-zA-Z0-9_-]{8,80}', request_id):
            raise ValueError('Anbieter oder Abrufkennung fehlt.')
        cancel = threading.Event()
        with self.lock:
            if request_id in self.jobs:
                raise ValueError('Dieser Abruf läuft bereits.')
            self.jobs[request_id] = cancel
            generation = self.generations.get(site, 0)+1
            self.generations[site] = generation
        request=self.b.get('_cam_request')
        if request is not None:request.cancel=cancel
        try:
            jar, saved_user = self.b['_cam_jar'](site)
            if not saved_user:
                raise ValueError('Bitte zuerst dieses offizielle Website-Konto verbinden.')
            fingerprint=self.b.get('_cam_session_fingerprint',self.session_fingerprint)(jar,saved_user)
            who = self.b[{'stripchat':'_sc_who','chaturbate':'_cb_who','bongacams':'_bc_who','camsoda':'_cs_who'}[site]](jar)
            if not who:
                raise ValueError('Das angemeldete Konto konnte nicht bestätigt werden. Bitte die Website-Sitzung erneuern.')
            if cancel.is_set():
                raise ValueError('Abruf abgebrochen; der bisherige Kontostand bleibt erhalten.')
            rooms, warning = self.b[{'stripchat':'_sc_account_rooms','chaturbate':'_cb_account_rooms','bongacams':'_bc_account_rooms','camsoda':'_cs_account_rooms'}[site]](jar)
            if cancel.is_set():
                raise ValueError('Abruf abgebrochen; der bisherige Kontostand bleibt erhalten.')
            if warning and not rooms:
                raise ValueError(warning)
            # Bonga returns an online listing; CamSoda exposes a bounded user payload.
            complete = not warning and site in ('stripchat', 'chaturbate')
            if not complete and not warning:
                warning = 'Der Anbieter bestätigt keine vollständige Following-Liste. Angezeigt wird der tatsächlich verfügbare Ausschnitt.'
            key = site + ':' + who
            clean = {}
            for room in rooms[:10000]:
                identity = self.b['_cam_pair'](site, room.get('name'))
                if identity:
                    clean[identity] = {k: v for k, v in room.items() if k in ('site','name','online','show','viewers','hd','subject','tags','thumb','country','age','gender')}
            if len(rooms) > 10000:
                complete = False
                warning = 'Die Sicherheitsgrenze von 10000 Einträgen wurde erreicht; die Liste ist unvollständig.'
            with self.lock:
                if cancel.is_set() or self.generations.get(site)!=generation:
                    raise ValueError('Abruf abgebrochen oder durch einen neueren Abruf ersetzt; der bisherige Kontostand bleibt erhalten.')
                previous = self.data['accounts'].get(key, {})
                merged = {} if complete else {site+':'+r['name']:r for r in previous.get('items', [])}
                merged.update(clean)
                stamp = int(time.time()*1000)
                for row in clean.values():row['observedAt']=stamp
                history = previous.get('history', [])[-49:] + [{'at':stamp,'count':len(clean),'online':sum(r.get('online') is True for r in clean.values()),'complete':complete}]
                snapshot = {'site':site,'user':who,'id':uuid.uuid4().hex,'at':stamp,'items':list(merged.values()),'observedCount':len(clean),'complete':complete,'warning':warning,'history':history}
                if self.b.get('_cam_session_commit'):
                    self.b['_cam_session_commit'](site,fingerprint,who,jar)
                else:
                    current,current_user=self.b['_cam_jar'](site)
                    if self.session_fingerprint(current,current_user)!=fingerprint:
                        raise ValueError('Die Website-Sitzung wurde inzwischen geändert. Die neue Anmeldung bleibt erhalten.')
                    self.b['_cam_session_store'](site, who, jar)
                self.b['_cam_library_see'](list(clean.values()))
                library = self.b['_cam_library_load']()
                with self.b['_cam_lib_lock']:
                    library['account'][site] = list(merged)
                    library.setdefault('account_meta', {})[site] = {'user':who,'at':stamp//1000,'count':len(merged),'complete':complete}
                self.b['_cam_library_save'](True)
                old_snapshot=self.data['accounts'].get(key)
                self.data['accounts'][key] = snapshot
                try:self.save()
                except Exception:
                    if old_snapshot is None:self.data['accounts'].pop(key,None)
                    else:self.data['accounts'][key]=old_snapshot
                    raise
                return {'ok':True,'snapshot':copy.deepcopy(snapshot)}
        finally:
            if request is not None:request.cancel=None
            with self.lock:
                self.jobs.pop(request_id, None)

    def import_preview(self, body):
        with self.lock:
            key = str(body.get('account') or '')
            snapshot = self.data['accounts'].get(key)
            if not snapshot:
                raise ValueError('Diesen gespeicherten Kontostand gibt es nicht.')
            library = self.b['_cam_library_load']()
            with self.b['_cam_lib_lock']:
                version = self.signature(library)
                old = copy.deepcopy(library)
            token = uuid.uuid4().hex
            identities = [self.b['_cam_pair'](r['site'], r['name']) for r in snapshot['items']]
            existing = sum(bool(old['models'].get(k, {}).get('personal', {}).get('saved')) for k in identities)
            self.previews[token] = {'account':key,'snapshot':snapshot['id'],'version':version,'at':time.time()}
            self.previews = {k:v for k,v in self.previews.items() if time.time()-v['at']<600}
            return {'ok':True,'preview':token,'count':len(identities),'alreadySaved':existing,'newlySaved':len(identities)-existing,'complete':snapshot['complete'],'sample':identities[:12]}

    def import_commit(self, body):
        with self.lock:
            preview = self.previews.pop(str(body.get('preview') or ''), None)
            if not preview or time.time()-preview['at']>600:
                raise ValueError('Die Übernahmevorschau ist abgelaufen. Bitte neu prüfen.')
            snapshot = self.data['accounts'].get(preview['account'])
            if not snapshot or snapshot['id'] != preview['snapshot']:
                raise ValueError('Der Kontostand wurde verändert. Bitte eine neue Vorschau erstellen.')
            library = self.b['_cam_library_load']()
            with self.b['_cam_lib_lock']:
                if self.signature(library) != preview['version']:
                    raise ValueError('Die Bibliothek wurde zwischenzeitlich geändert. Bitte eine neue Vorschau erstellen.')
                old = copy.deepcopy(library)
                backup = os.path.join(self.b['PROFILE'], 'cam_user_backups', time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]+'.json')
                os.makedirs(os.path.dirname(backup), exist_ok=True)
                self.b['_cam_json_write'](backup, old)
                for room in snapshot['items']:
                    identity = self.b['_cam_pair'](room['site'],room['name'])
                    row = library['models'].setdefault(identity, copy.deepcopy(room))
                    row.setdefault('personal', {})['saved'] = True
            try:
                self.b['_cam_library_save'](True)
            except Exception:
                with self.b['_cam_lib_lock']:
                    library.clear();library.update(old)
                raise ValueError('Die Bibliothek konnte nicht gespeichert werden; der vorherige Stand wurde wiederhergestellt.')
            return {'ok':True,'count':len(snapshot['items']),'backup':os.path.basename(backup)}

    def statistics(self, body):
        if body.get('site') != 'chaturbate':
            raise ValueError('Für diesen Anbieter ist keine verifizierte offizielle Statistik-Schnittstelle angebunden. Lokale Nutzung und Following sind separat verfügbar.')
        user, token = str(body.get('username') or '').strip(), str(body.get('token') or '').strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{2,40}', user) or not re.fullmatch(r'[A-Za-z0-9]{24}',token):
            raise ValueError('Bitte den Benutzernamen und den 24-stelligen offiziellen Statistikschlüssel angeben. Ein Events-API-Link ist kein Statistikschlüssel.')
        url = 'https://chaturbate.com/statsapi/?'+self.b['urllib'].parse.urlencode({'username':user,'token':token})
        jar = self.b['http'].cookiejar.CookieJar()
        status, raw = self.b['_cam_exchange'](url, {'User-Agent':self.b['_CAM_UA'],'Accept':'application/json'}, None, 10, 65536, jar)
        if status != 200:
            raise ValueError('Die offizielle Statistikverbindung wurde nicht bestätigt. Schlüssel und Kontoberechtigung auf der Website prüfen.')
        try:
            source = json.loads(raw)
        except (ValueError,TypeError):
            raise ValueError('Die Quelle hat keine lesbare Kontostatistik geliefert.')
        if not isinstance(source,dict) or str(source.get('username') or '').lower()!=user.lower():
            raise ValueError('Die Quelle bestätigt dieses Konto nicht. Der alte Stand bleibt erhalten.')
        user=str(source['username'])
        values={}
        for field in ('token_balance','tips_in_last_hour','votes_up','votes_down','satisfaction_score','time_online','num_followers','num_viewers','num_registered_viewers','num_tokened_viewers'):
            value=source.get(field)
            if value in (None,'',-1,'-1'):
                values[field]=None;continue
            if isinstance(value,bool):
                raise ValueError('Ungültige Kontostatistik von der Quelle.')
            try: number=float(value)
            except (TypeError,ValueError): raise ValueError('Ungültige Kontostatistik von der Quelle.')
            if not math.isfinite(number) or number<0 or field=='satisfaction_score' and number>100:
                raise ValueError('Ungültige Kontostatistik von der Quelle.')
            values[field]=number
        values['last_broadcast']=str(source.get('last_broadcast'))[:100] if source.get('last_broadcast') not in (None,-1,'-1','') else None
        snapshot={'id':uuid.uuid4().hex,'site':'chaturbate','user':user,'at':int(time.time()*1000),'source':'https://chaturbate.com/statsapi/','values':values}
        with self.lock:
            key='chaturbate:'+user
            old=self.data['stats'].get(key)
            self.data['stats'][key]=((old or [])+[snapshot])[-288:]
            try:self.save()
            except Exception:
                if old is None:self.data['stats'].pop(key,None)
                else:self.data['stats'][key]=old
                raise
        return {'ok':True,'snapshot':snapshot}

    def handle(self, raw):
        try:
            body=json.loads(raw.decode('utf-8'))
            if not isinstance(body,dict):raise ValueError('Unlesbare Anfrage.')
            op=body.get('op')
            if op=='refresh':return self.refresh(body)
            if op=='preview':return self.import_preview(body)
            if op=='commit':return self.import_commit(body)
            if op=='stats':return self.statistics(body)
            if op=='cancel':
                with self.lock:
                    job=self.jobs.get(str(body.get('requestId') or ''))
                    if job:job.set()
                return {'ok':True}
            if op=='clear-stats':
                with self.lock:
                    self.data['stats'].pop(str(body.get('account') or ''),None);self.save()
                return {'ok':True}
            raise ValueError('Unbekannte Nutzeraktion.')
        except ValueError as error:
            return {'ok':False,'error':str(error)}
        except Exception:
            return {'ok':False,'error':'Der Kontovorgang konnte nicht abgeschlossen werden. Vorhandene gespeicherte Daten bleiben erhalten.'}
