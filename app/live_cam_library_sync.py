"""One bounded public-library collector per server, leased by open Live views.

Catalog discovery, persistent covers and profile enrichment never run on request
threads. Clients only renew a lease; multiple tabs share the same worker queue.
"""
import concurrent.futures
import copy
from contextlib import closing
import hashlib
import io
import os
from pathlib import Path
import re
import threading
import time
import urllib.parse


class LibrarySync:
    def __init__(self, backend, autostart=True, clock=time.monotonic):
        self.b = backend
        self.clock = clock
        self.autostart = autostart
        self.lock = threading.RLock()
        self.clients = {}
        self.priority = {}
        self.retry = {}
        self.busy = set()
        self.stop = threading.Event()
        self.thread = None
        self.pool = None
        self.folder = Path(backend['PROFILE']) / 'cam_covers'
        self.state_path = os.path.join(backend['PROFILE'], 'cam_library_sync.json')
        saved = backend['_cam_json_read'](self.state_path) or {}
        self.sites = {site: {'next': 0, 'head': 0, 'offset': 0, 'gender': 0,
                             'pages': 0, 'last': 0, 'error': '', 'round': 0}
                      for site in backend['_CAM_SITES']}
        for site, row in self.sites.items():
            old = saved.get('sites', {}).get(site, {})
            for key in ('offset', 'gender', 'pages', 'last', 'round'):
                if type(old.get(key)) is int and 0 <= old[key] <= 10**12:
                    row[key] = old[key]
        self.saved_at = 0
        self.enrich_at = 0
        self.biography_at = 0
        self.was_active = False
        self.pending_flush = False

    def active(self):
        now = self.clock()
        with self.lock:
            self.clients = {key: expiry for key, expiry in self.clients.items() if expiry > now}
            return bool(self.clients)

    def presence(self, token, enabled, priorities=()):
        if not isinstance(token, str) or not re.fullmatch('[a-f0-9]{32}', token):
            raise ValueError('Ungültige Live-Sitzung.')
        if not isinstance(enabled, bool) or not isinstance(priorities, list) or len(priorities) > 240:
            raise ValueError('Ungültiger Bibliotheksauftrag.')
        now = self.clock()
        with self.lock:
            if enabled:
                resumed = not any(expiry > now for expiry in self.clients.values())
                if resumed:
                    # Resume at current public heads, then continue saved discovery
                    # offsets. Do not bypass a failed provider's retry backoff.
                    for site, row in self.sites.items():
                        if not row['error'] and 'catalog:' + site not in self.busy:
                            row['head'] = 0
                            row['next'] = min(row['next'], now)
                self.clients[token] = now + 95
                for key in priorities:
                    if isinstance(key, str) and ':' in key and self.b['_cam_pair'](*key.split(':', 1)) == key:
                        self.priority[key] = now + 180
                if len(self.priority) > 1200:
                    self.priority = dict(list(self.priority.items())[-1200:])
                if self.autostart and (self.thread is None or not self.thread.is_alive()):
                    self.stop.clear()
                    self.thread = threading.Thread(target=self.run, name='cam-library', daemon=True)
                    self.thread.start()
            else:
                self.clients.pop(token, None)
        return self.status()

    def status(self):
        active = self.active()
        library = self.b['_cam_library_load']()
        with self.b['_cam_lib_lock']:
            rows = list(library['models'].values())
            total = len(rows)
            covers = sum(bool(r.get('coverAt')) for r in rows)
            profiles = sum(bool(r.get('profileAt')) for r in rows)
            biographies = sum(bool(r.get('biographyEntity')) for r in rows)
            suggestions = sum(r.get('biographyStatus') == 'suggestions' for r in rows)
        with self.lock:
            return {'ok': True, 'active': active, 'total': total, 'covers': covers,
                    'profiles': profiles, 'biographies': biographies, 'biographySuggestions': suggestions, 'pending': len(self.busy),
                    'sites': copy.deepcopy(self.sites)}

    def close(self):
        self.stop.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=20)

    def run(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.sites)+2, thread_name_prefix='cam-library-job') as pool:
            self.pool = pool
            while not self.stop.wait(0.75):
                if not self.active():
                    with self.lock:drained=not self.busy
                    if drained and (self.was_active or self.pending_flush):
                        try:
                            self.b['_cam_library_save'](True)
                            self.was_active=False;self.pending_flush=False
                        except OSError:
                            pass
                    continue
                self.was_active=True
                now = self.clock()
                with self.lock:
                    # Each provider owns one lane. A stalled host cannot queue the
                    # other five behind it; enrichment retains two separate slots.
                    available = len(self.sites) - sum(k.startswith('catalog:') for k in self.busy)
                    ready = sorted((s for s, r in self.sites.items()
                                    if r['next'] <= now and 'catalog:' + s not in self.busy),
                                   key=lambda s: self.sites[s]['next'])[:available]
                    for site in ready:
                        self.busy.add('catalog:' + site)
                        pool.submit(self.catalog, site)
                    if 'enrich' not in self.busy and now >= self.enrich_at:
                        self.busy.add('enrich')
                        pool.submit(self.enrich)
                    if callable(self.b.get('_cam_biography_service')) and 'biography' not in self.busy and now >= self.biography_at:
                        self.busy.add('biography')
                        pool.submit(self.biography)
                if now - self.saved_at > 60:
                    try:
                        with self.lock:
                            snapshot = {'version': 1, 'sites': copy.deepcopy(self.sites)}
                        self.b['_cam_json_write'](self.state_path, snapshot)
                        self.saved_at = now
                    except OSError:
                        pass
            self.pool = None
        self.b['_cam_library_save'](True)

    def biography(self):
        try:
            if self.active():
                with self.lock:
                    priorities = [key for key, expiry in self.priority.items() if expiry > self.clock()]
                if self.b['_cam_biography_service']().step(priorities):
                    self.pending_flush = True
        finally:
            with self.lock:
                self.biography_at = self.clock() + 5
                self.busy.discard('biography')

    def catalog(self, site):
        try:
            if not self.active():
                return
            with self.lock:
                row = self.sites[site]
                head = self.clock() >= row['head']
                genders = ('f', 'm', 't', 'c') if site in ('stripchat', 'bongacams') else ('all',)
                gender = 'all' if head else genders[row['gender'] % len(genders)]
                offset = 0 if head else row['offset']
            result = self.b['cam_rooms']({'site': site, 'gender': gender, 'offset': str(offset)})
            with self.lock:
                row['next'] = self.clock() + (5 if result.get('ok') else 120)
                row['error'] = '' if result.get('ok') else str(result.get('error') or 'Quelle derzeit nicht erreichbar.')[:240]
                if result.get('ok'):
                    row['last'] = int(time.time() * 1000)
                    row['pages'] += 1
                    if head:
                        row['head'] = self.clock() + 60
                    else:
                        row['offset'] = offset + 60
                        if not result.get('paged') or not result.get('items') or row['offset'] > 5000:
                            row['offset'] = 0
                            row['gender'] = (row['gender'] + 1) % len(genders)
                            if row['gender'] == 0:
                                row['round'] += 1
        except Exception as error:
            with self.lock:
                self.sites[site].update(next=self.clock() + 120, error=str(error)[:240])
        finally:
            with self.lock:
                self.busy.discard('catalog:' + site)

    def candidate(self):
        now = self.clock()
        with self.lock:
            priority = {k: v for k, v in self.priority.items() if v > now}
            self.priority = priority
            self.retry = {k: v for k, v in self.retry.items() if v > now}
            retries = set(self.retry)
        library = self.b['_cam_library_load']()
        wall = int(time.time() * 1000)
        with self.b['_cam_lib_lock']:
            candidates = [(key, row) for key, row in library['models'].items()
                          if key not in retries and
                          (not row.get('coverAt') or not row.get('profileAt') or
                           wall - row.get('profileAt', 0) > 86400000 or
                           wall - row.get('coverAt', 0) > 21600000)]
            if not candidates:
                return None
            key, row = min(candidates, key=lambda item: (
                0 if item[0] in priority else 1,
                0 if not item[1].get('coverAt') else 1,
                item[1].get('enrichedAt', 0), item[0]))
            return key, copy.deepcopy(row)

    def enrich(self):
        key = None
        try:
            if not self.active():
                return
            candidate = self.candidate()
            if not candidate:
                return
            key, row = candidate
            wall = int(time.time() * 1000)
            patch = {'enrichedAt': wall}
            if not row.get('firstSeen') and row.get('seen'):patch['firstSeen']=row['seen']
            profile = None
            if not row.get('profileAt') or wall - row['profileAt'] > 86400000:
                site, name = key.split(':', 1)
                result = self.b['_cam_single_profile']({'site': site, 'name': name, 'public_only': True})
                if result.get('ok'):
                    profile = result['profile']
                    hub = self.b['_cam_models_hub']()
                    with hub.lock:
                        hub.profile({'id': key, 'action': 'save', 'profile': profile})
                    patch.update(profileAt=profile['observedAt'], profileError='')
                    patch.update(self.profile_fields(profile))
                else:
                    patch['profileError'] = str(result.get('error') or 'Profil derzeit nicht erreichbar.')[:240]
            if not row.get('coverAt') or wall - row['coverAt'] > 21600000:
                sources = [row.get('portrait', '')] + (profile or {}).get('images', row.get('profileImages', [])) + [row.get('thumb', '')]
                patch['coverError']='Zurzeit kein öffentliches Bild erreichbar; ein vorhandenes Cover bleibt erhalten.'
                for source in dict.fromkeys(sources):
                    if not source:
                        continue
                    try:
                        self.save_cover(key, source)
                    except (OSError, ValueError, TimeoutError):
                        continue
                    patch.update(coverAt=wall, coverSource=source, coverError='')
                    break
            self.merge(key, patch)
            with self.lock:
                self.retry[key] = self.clock() + (3600 if patch.get('profileError') else 180)
        except Exception:
            if key:
                with self.lock:
                    self.retry[key] = self.clock() + 600
        finally:
            with self.lock:
                self.enrich_at = self.clock() + 1.5
                self.busy.discard('enrich')

    @staticmethod
    def profile_fields(profile):
        result = {'displayName': profile.get('displayName', ''),
                  'bio': profile.get('bio', ''), 'publicFacts': profile.get('facts', []),
                  'publicLinks': profile.get('links', []), 'profileImages': profile.get('images', []), 'profileSource': profile.get('sourceUrl', '')}
        for fact in profile.get('facts',[]):
            label=fact['label'].strip().casefold();value=fact['value'].strip()
            if label in ('alter','age') and re.fullmatch(r'\d{2}',value) and 18<=int(value)<=99:
                result['age']=int(value)
            elif label in ('follower','followers') and value.isdigit():
                result['followers']=int(value)
            elif label in ('sprachen','hauptsprache','languages') and value and not value.isdigit():
                result['languages']=[v.strip() for v in re.split('[,;/]',value) if v.strip()][:20]
        if profile.get('tags'):

            result['profileTags'] = profile['tags']
        # Structured public facts stay source-labelled; no guessed country,
        # birth year or follower value is manufactured from prose.
        return result

    def merge(self, key, patch):
        library = self.b['_cam_library_load']()
        with self.b['_cam_lib_lock']:
            if key not in library['models']:
                return
            library['models'][key].update(patch)
        self.pending_flush=True
        self.b['_cam_library_save'](False)

    def cover_path(self, key):
        return self.folder / (hashlib.sha256(key.encode()).hexdigest() + '.jpg')

    def read_cover(self, site, name):
        key = self.b['_cam_pair'](site, name)
        if not key:
            raise ValueError('Ungültiges Modelcover.')
        return self.cover_path(key).read_bytes()

    def save_cover(self, key, source):
        from PIL import Image, ImageOps
        if urllib.parse.urlsplit(source).path == '/api/image':
            source = urllib.parse.parse_qs(urllib.parse.urlsplit(source).query).get('url', [''])[0]
        url, headers = self.b['split_kodi_url'](source)
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port:
            raise ValueError('Ungültige Coverquelle.')
        from live_cam_http import open_cam_media
        if self.b.get('_cam_cover_fetch'):
            raw = self.b['_cam_cover_fetch'](url)
        else:
            with closing(open_cam_media(url, {'User-Agent': self.b['_CAM_UA'],
                                     **{k: v for k, v in headers.items() if k in ('Referer', 'Origin')}}, timeout=6)) as response:
                raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError('Cover ist zu groß.')
        with Image.open(io.BytesIO(raw)) as image:
            if image.width * image.height > 40_000_000:
                raise ValueError('Coverabmessungen sind zu groß.')
            image = ImageOps.exif_transpose(image).convert('RGB')
            image.thumbnail((640, 640))
            output = io.BytesIO()
            image.save(output, 'JPEG', quality=84)
        self.folder.mkdir(parents=True, exist_ok=True)
        target = self.cover_path(key)
        temporary = target.with_suffix('.tmp')
        temporary.write_bytes(output.getvalue())
        os.replace(temporary, target)
