"""Public encyclopedic metadata, separate from provider and personal records.

Names produce suggestions only. Automatic identity needs an exact published
profile link. Confirmed entity IDs stay stable when stage names change.
"""
import copy
from collections import deque
import hashlib
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit, unquote

from star_sources import PublicSources, clean, normal, values, mature
from star_runtime import SourceError

QID = re.compile(r'Q[1-9]\d{0,11}')
API = 'https://www.wikidata.org/w/api.php?'
DAY = 86400


def canonical(url):
    try:
        p = urlsplit(str(url))
        if p.scheme not in ('https', 'http') or p.username or p.password or not p.hostname:
            return ''
        host = p.hostname.lower().removeprefix('www.')
        path = unquote(p.path).rstrip('/')
        return host + path if path else ''
    except ValueError:
        return ''


class BiographyService:
    def __init__(self, backend):
        self.b = backend
        self.lock = threading.RLock()
        self.work_lock = threading.Lock()
        self.folder = Path(backend['PROFILE']) / 'cam_biographies'
        self.cache = {}
        self.sources = None
        self.next_scan = 0
        self.keys = deque()
        self.keys_at = 0

    def source(self):
        if self.sources is None:
            self.sources = PublicSources(self.b['_star_runtime_hub']())
        return self.sources

    def path(self, key):
        return self.folder / (hashlib.sha256(key.encode()).hexdigest() + '.json')

    def read(self, key):
        with self.lock:
            if key not in self.cache:
                self.cache[key] = self.b['_cam_json_read'](str(self.path(key))) or {}
            return copy.deepcopy(self.cache[key])

    def public(self, key):
        row = self.read(key)
        return {k: v for k, v in row.items() if k not in ('nextAt', 'rejected')} | {
            'id': key, 'status': row.get('status', 'pending'), 'revision': row.get('revision', 0)}

    def model(self, key):
        if not isinstance(key, str) or ':' not in key or self.b['_cam_pair'](*key.split(':', 1)) != key:
            raise ValueError('Ungültiges Model.')
        library = self.b['_cam_library_load']()
        with self.b['_cam_lib_lock']:
            if key not in library['models']:
                raise ValueError('Model nicht im Bestand.')
            return copy.deepcopy(library['models'][key])

    def save(self, key, row, expected):
        with self.lock:
            if self.read(key).get('revision', 0) != expected:
                return False
            row = {**row, 'revision': expected + 1}
            self.b['_cam_json_write'](str(self.path(key)), row)
            self.cache[key] = copy.deepcopy(row)
        library = self.b['_cam_library_load']()
        with self.b['_cam_lib_lock']:
            if key in library['models']:
                library['models'][key].update(biographyStatus=row.get('status'), biographyAt=row.get('checkedAt'),
                                              biographyEntity=row.get('entity', '') if row.get('data') else '')
        self.b['_cam_library_save'](False)
        return True

    def handle(self, body):
        key = body.get('id')
        model = self.model(key)
        op = body.get('op')
        if op == 'biography-read':
            return {'ok': True, 'biography': self.public(key)}
        old = self.read(key)
        revision = old.get('revision', 0)
        if type(body.get('revision')) is not int or body['revision'] != revision:
            raise ValueError('Die Zuordnung wurde inzwischen geändert. Bitte den aktuellen Stand laden.')
        if op == 'biography-refresh':
            name = clean(body.get('search') or model.get('displayName') or model['name'])[:120]
            row = {**old, 'search': name, 'nextAt': 0, 'enabled': True, 'status': 'pending', 'error': ''}
            if name != (old.get('search') or model.get('displayName') or model['name']):
                for field in ('entity', 'match', 'data', 'candidates'):
                    row.pop(field, None)
            self.next_scan = 0
        elif op == 'biography-unlink':
            row = {'status': 'paused', 'enabled': False, 'checkedAt': int(time.time()*1000), 'nextAt': 0}
        elif op == 'biography-confirm':
            entity = body.get('entity')
            if not isinstance(entity, str) or not QID.fullmatch(entity) or entity not in [r['entity'] for r in old.get('candidates', [])]:
                raise ValueError('Bitte zuerst einen vorgeschlagenen Datenbanktreffer prüfen.')
            row = self.fetch(key, model, {**old, 'entity': entity, 'match': 'confirmed', 'enabled': True})
            if row.get('status') != 'matched':
                raise ValueError(row.get('error') or 'Der Datenbankeintrag konnte nicht bestätigt werden. Bitte erneut versuchen.')
        else:
            raise ValueError('Unbekannte Biografieaktion.')
        if not self.save(key, row, revision):
            raise ValueError('Die Zuordnung wurde inzwischen geändert. Bitte erneut laden.')
        return {'ok': True, 'biography': self.public(key)}

    def entities(self, model, old):
        runtime = self.source().runtime
        name = old.get('search') or model.get('displayName') or model['name']
        params = {'action': 'wbsearchentities', 'search': name, 'language': 'en', 'uselang': 'de',
                  'type': 'item', 'limit': 5, 'format': 'json', 'maxlag': 5}
        result = runtime.json(API + urlencode(params))
        ids = [r['id'] for r in result.get('search', []) if QID.fullmatch(str(r.get('id') or ''))]
        # A link explicitly published inside the provider profile is stronger
        # than the profile handle, which often differs from an article title.
        explicit = set()
        for link in model.get('publicLinks', []):
            try:
                p = urlsplit(link)
                if p.scheme == 'https' and p.hostname in ('www.wikidata.org', 'wikidata.org') and not p.username:
                    entity = p.path.removeprefix('/wiki/')
                    if QID.fullmatch(entity):
                        explicit.add(entity)
            except ValueError:
                continue
        ids = list(dict.fromkeys([*sorted(explicit), *ids]))[:10]
        if not ids:
            return [], explicit
        params = {'action': 'wbgetentities', 'ids': '|'.join(ids), 'props': 'labels|aliases|descriptions|claims',
                  'languages': 'de|en', 'format': 'json', 'maxlag': 5}
        data = runtime.json(API + urlencode(params))
        return list(data.get('entities', {}).values()), explicit

    def fetch(self, key, model, old):
        now = time.time()
        row = {**old, 'checkedAt': int(now*1000), 'profileVersion': model.get('profileAt', 0), 'error': ''}
        try:
            entity = old.get('entity') if old.get('match') in ('confirmed', 'published-link') else None
            if not entity:
                entities, explicit = self.entities(model, old)
                expected = {normal(old.get('search')), normal(model.get('displayName')), normal(model['name'])} - {''}
                candidates, automatic = [], []
                profile = canonical(model.get('profileSource'))
                for candidate in entities:
                    ident = candidate.get('id', '')
                    if not QID.fullmatch(ident) or not any(isinstance(v, dict) and v.get('id') == 'Q5' for v in values(candidate, 'P31')):
                        continue
                    dates = values(candidate, 'P569')
                    if any(isinstance(v, dict) and not mature(v.get('time')) for v in dates):
                        continue
                    names = [v.get('value', '') for v in candidate.get('labels', {}).values()]
                    names += [v.get('value', '') for variants in candidate.get('aliases', {}).values() for v in variants]
                    linked = ident in explicit or bool(profile and profile in {canonical(v) for v in values(candidate, 'P856') if isinstance(v, str)})
                    if not linked and not expected.intersection(normal(v) for v in names):
                        continue
                    label = (candidate.get('labels', {}).get('de') or candidate.get('labels', {}).get('en') or {}).get('value', ident)
                    description = (candidate.get('descriptions', {}).get('de') or candidate.get('descriptions', {}).get('en') or {}).get('value', '')
                    candidates.append({'entity': ident, 'name': clean(label), 'description': clean(description),
                                       'url': 'https://www.wikidata.org/wiki/'+ident})
                    if linked:
                        automatic.append(ident)
                row['candidates'] = candidates[:10]
                if len(automatic) != 1:
                    row.update(status='suggestions' if candidates else 'missing', nextAt=now+14*DAY)
                    return row
                entity = automatic[0]
                row.update(entity=entity, match='published-link')
            result = self.source().wikidata({'name': model['name'], 'source_ids': {'wikidata': entity}},
                                            entity_id=entity, text_only=True)
            if not result.get('ok'):
                row.update(status='error', error='Der bestätigte Eintrag ist derzeit nicht als passende Person verfügbar.', nextAt=now+DAY)
                return row
            # Keep this section bibliographical; never project it into provider
            # age, identity, interests, private notes or local usage statistics.
            facts = [f for f in result.get('facts', []) if f.get('label') in
                     ('Beruf', 'Auszeichnung', 'Nominierung', 'Karrierebeginn', 'Karriereende', 'Staatsangehörigkeit')]
            row.update(status='matched', entity=entity, nextAt=now+7*DAY,
                       data={'facts': facts, 'description': result.get('description', '')[:30000],
                             'language': result.get('language', ''), 'url': result['url'],
                             'textUrl': result.get('text_url', ''), 'at': int(result['at']*1000),
                             'textAt': int(result.get('text_at', result['at'])*1000),
                             'attribution': 'Wikipedia: CC BY-SA; strukturierte Wikidata-Daten: CC0',
                             'partial': bool(result.get('partial_errors'))})
            previous = old.get('data') or {}
            if not row['data']['description'] and previous.get('description') and old.get('entity') == entity:
                for name in ('description', 'language', 'textUrl', 'textAt'):
                    row['data'][name] = previous.get(name)
                row['data']['partial'] = True
            return row
        except (SourceError, OSError, ValueError, TypeError, KeyError) as error:
            row.update(status='error', error='Die öffentliche Datenquelle ist vorübergehend nicht erreichbar. Gespeicherte Angaben bleiben erhalten.',
                       nextAt=max(now+3600, getattr(error, 'retry_at', 0)))
            return row

    def step(self, priorities=()):
        if not self.work_lock.acquire(blocking=False):
            return
        try:
            now = time.time()
            if now < self.next_scan:
                return
            self.next_scan = now + 5
            library = self.b['_cam_library_load']()
            with self.b['_cam_lib_lock']:
                if now >= self.keys_at:
                    self.keys = deque(library['models'])
                    self.keys_at = now + 60
            chosen = None
            keys = list(dict.fromkeys(priorities))[:24]
            # Bound each scan, including when every existing record is fresh.
            for _ in range(min(120, len(self.keys))):
                key = self.keys.popleft()
                self.keys.append(key)
                keys.append(key)
            for key in keys:
                if ':' not in key or self.b['_cam_pair'](*key.split(':', 1)) != key:
                    continue
                old = self.read(key)
                with self.b['_cam_lib_lock']:
                    model = library['models'].get(key)
                    if model is None:
                        continue
                    changed = model.get('profileAt', 0) != old.get('profileVersion', 0) and old.get('status') in ('missing', 'suggestions')
                    due = old.get('enabled', True) and (old.get('nextAt', 0) <= now or changed)
                    if due:
                        chosen = key, copy.deepcopy(model), old
                        break
            if chosen:
                key, model, old = chosen
                row = self.fetch(key, model, old)
                return self.save(key, row, old.get('revision', 0))
        finally:
            self.work_lock.release()
