"""Local, incremental Tube playback measurements. Never fetches or classifies media."""
import datetime
import json
import math
import os
import re
import sqlite3
import threading
import time
import urllib.parse

from media_library import LIVE_SITES


def text(value, limit=180):
    return str(value or '').strip()[:limit]


def number(value, low=0, high=1e12):
    try:
        result = float(value)
        return max(low, min(high, result)) if math.isfinite(result) else low
    except (TypeError, ValueError):
        return low


def labels(raw, limit=40):
    out, seen = [], set()
    for value in raw if isinstance(raw, list) else []:
        name = text((value.get('name') or value.get('title')) if isinstance(value, dict) else value, 100)
        if name and name.casefold() not in seen:
            out.append(name)
            seen.add(name.casefold())
        if len(out) == limit:
            break
    return out


def video(raw):
    if not isinstance(raw, dict):
        raise ValueError('Ungültiges Video.')
    raw_url = text(raw.get('query') or raw.get('url'), 3000)
    query = raw_url.split('?', 1)[-1] if raw_url.startswith('plugin:') else raw_url.lstrip('?')
    params = dict(urllib.parse.parse_qsl(query)) if not raw_url.startswith(('http:', 'https:')) else {}
    site = text(params.get('website') or raw.get('site'), 80).lower()
    if (site in LIVE_SITES or text(raw.get('site')).lower() in LIVE_SITES or raw.get('scope') == 'live'
            or raw.get('liveCam') or raw.get('source') == 'live' or raw.get('mediaType') == 'live'
            or raw.get('kind') in ('live', 'cam', 'multicam') or isinstance(raw.get('media'),dict) and raw['media'].get('kind') == 'live'):
        raise ValueError('Live-Cams führen eine eigene Statistik.')
    target = text(params.get('url') or raw.get('url'), 2200)
    parsed = urllib.parse.urlsplit(target)
    if not re.fullmatch(r'[a-z0-9_]+', site) or parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Keine reguläre Tube-Videoadresse.')
    if params and params.get('mode') != '4':
        raise ValueError('Nur feste Videos werden erfasst.')
    return {'key': site + '|' + target, 'site': site, 'url': 'plugin://plugin.video.adulthideout/?' + urllib.parse.urlencode({'mode': '4', 'website': site, 'url': target}), 'title': text(raw.get('title')) or 'Video'}


def ranges(raw, ceiling=1e12):
    valid = []
    for row in raw[:2048] if isinstance(raw, list) else []:
        if not isinstance(row, list) or len(row) != 2:
            continue
        try:
            if not all(math.isfinite(float(v)) for v in row):
                continue
        except (TypeError, ValueError):
            continue
        start, end = number(row[0], high=ceiling), number(row[1], high=ceiling)
        if end > start:
            valid.append([start, end])
    out = []
    for start, end in sorted(valid):
        if out and start <= out[-1][1] + .05:
            out[-1][1] = max(end, out[-1][1])
        else:
            out.append([start, end])
    return [[round(a, 3), round(b, 3)] for a, b in out[:512]]


def metadata(raw):
    result = video(raw)
    facts = raw.get('facts') if isinstance(raw.get('facts'), dict) else {}
    film = raw.get('film') if isinstance(raw.get('film'), dict) else {}
    result.update({
        'categories': labels(facts.get('categories') or raw.get('categories')),
        'tags': labels(facts.get('tags') or raw.get('tags')),
        'models': labels(facts.get('stars') or raw.get('models')),
        'studio': text(film.get('studio') or facts.get('studio') or raw.get('studio'), 120),
        'filmYear': int(number(film.get('year') or raw.get('filmYear'), high=2100)),
        'duration': number(raw.get('duration'), high=604800),
        'uploader': text(raw.get('uploader'), 120),
        'thumb': text(raw.get('thumb'), 1500),
    })
    if not result['thumb'].startswith(('https://', '/api/', 'http://127.0.0.1:')):
        result['thumb'] = ''
    return result


class ConsumptionStore:
    def __init__(self, profile):
        os.makedirs(profile, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(os.path.join(profile, 'tube_consumption.sqlite3'), timeout=10, check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS videos(key TEXT PRIMARY KEY, updated REAL, payload TEXT);
          CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, video_key TEXT, updated REAL, payload TEXT);
          CREATE INDEX IF NOT EXISTS sessions_updated ON sessions(updated);
          CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
        ''')
        self.db.commit()

    def enabled(self):
        with self.lock:
            row = self.db.execute("SELECT value FROM settings WHERE key='recording'").fetchone()
            return not row or row[0] != 'off'

    def write(self, body):
        if not isinstance(body, dict):
            raise ValueError('Ungültige Messdaten.')
        rows = body.get('sessions', [])
        if not isinstance(rows, list) or len(rows) > 24:
            raise ValueError('Höchstens 24 Videos pro Anfrage.')
        with self.lock, self.db:
            if 'recording' in body:
                if type(body['recording']) is not bool:
                    raise ValueError('Ungültiger Erfassungsschalter.')
                before = self.enabled()
                now = time.time()
                if before and not body['recording']:
                    self.db.execute("INSERT OR REPLACE INTO settings VALUES('paused_since',?)", (str(now),))
                elif not before and body['recording']:
                    since = self.db.execute("SELECT value FROM settings WHERE key='paused_since'").fetchone()
                    previous = self.db.execute("SELECT value FROM settings WHERE key='blocked'").fetchone()
                    blocked = json.loads(previous[0]) if previous else []
                    if since:
                        blocked.append([float(since[0]), now])
                    self.db.execute("INSERT OR REPLACE INTO settings VALUES('blocked',?)", (json.dumps(blocked),))
                    self.db.execute("DELETE FROM settings WHERE key='paused_since'")
                self.db.execute("INSERT OR REPLACE INTO settings VALUES('recording',?)", ('on' if body['recording'] else 'off',))
            if not self.enabled():
                return {'ok': True, 'recording': False, 'accepted': 0}
            accepted = 0
            now = time.time()
            blocked_row = self.db.execute("SELECT value FROM settings WHERE key='blocked'").fetchone()
            # Playback ranges use milliseconds; pause boundaries must use the same precision.
            blocked = [[round(a, 3), round(b, 3)] for a, b in json.loads(blocked_row[0])] if blocked_row else []
            for raw in rows:
                if not isinstance(raw, dict) or not re.fullmatch(r'[A-Za-z0-9_-]{12,90}', text(raw.get('id'), 100)):
                    raise ValueError('Ungültige Wiedergabekennung.')
                meta = metadata(raw.get('video'))
                ident = raw['id']
                previous = self.db.execute('SELECT payload FROM sessions WHERE id=?', (ident,)).fetchone()
                old = json.loads(previous[0]) if previous else {}
                source = raw.get('source')
                if source not in ('player', 'multitube') or old and (old['key'] != meta['key'] or old['source'] != source):
                    raise ValueError('Wiedergabe und Quelle passen nicht zusammen.')
                started = number(old.get('started') or raw.get('started'), now-366*86400, now+5)
                session = {'id': ident, 'key': meta['key'], 'source': source, 'started': started, 'updated': now}
                for field in ('playing', 'visible', 'focused'):
                    cleaned = ranges((old.get(field) or []) + (raw.get(field) if isinstance(raw.get(field), list) else []), now+5)
                    allowed = [[round(max(a, started),3), b] for a, b in cleaned if b > max(a, started)]
                    for off, on in blocked:
                        allowed = [part for a,b in allowed for part in ([[a,b]] if b<=off or a>=on else ([[a,off]] if a<off else [])+([[on,b]] if b>on else []))]
                    session[field] = allowed
                # An active interval must also have been visibly playing.
                def intersect(first, second):
                    out, i, j = [], 0, 0
                    while i < len(first) and j < len(second):
                        a,b=first[i];c,d=second[j]
                        if min(b,d)>max(a,c):out.append([max(a,c),min(b,d)])
                        if b<d:i+=1
                        else:j+=1
                    return ranges(out)
                session['visible'] = intersect(session['visible'], session['playing'])
                session['focused'] = intersect(session['focused'], session['visible'])
                if not session['playing']:
                    continue
                raw_playing = ranges(raw.get('playing'), now+5)
                overlaps_pause = any(min(b,on)>max(a,off) for a,b in raw_playing for off,on in blocked)
                extra_coverage = raw.get('coverage') if isinstance(raw.get('coverage'), list) and not overlaps_pause else []
                session['coverage'] = ranges((old.get('coverage') or []) + extra_coverage, 604800)
                session['coveragePartial'] = bool(old.get('coveragePartial') or overlaps_pause)
                for field in ('seeks', 'pauses', 'stalls'):
                    session[field] = int(max(number(old.get(field)), number(raw.get(field), high=100000)))
                session['duration'] = max(number(old.get('duration')), number(raw.get('duration'), high=604800))
                session['ended'] = bool(old.get('ended') or raw.get('ended'))
                session['finished'] = bool(old.get('finished') or raw.get('finished'))
                old_meta = self.db.execute('SELECT payload FROM videos WHERE key=?', (meta['key'],)).fetchone()
                merged = json.loads(old_meta[0]) if old_meta else {}
                # Empty resolver facts must never erase earlier useful metadata.
                merged.update({k:v for k,v in meta.items() if v})
                self.db.execute('INSERT OR REPLACE INTO videos VALUES(?,?,?)', (meta['key'], now, json.dumps(merged, ensure_ascii=False)))
                self.db.execute('INSERT OR REPLACE INTO sessions VALUES(?,?,?,?)', (ident, meta['key'], now, json.dumps(session)))
                accepted += 1
            self.db.execute('DELETE FROM sessions WHERE id IN (SELECT id FROM sessions ORDER BY updated DESC LIMIT -1 OFFSET 2000)')
            self.db.execute('DELETE FROM videos WHERE key IN (SELECT key FROM videos ORDER BY updated DESC LIMIT -1 OFFSET 4000)')
        return {'ok': True, 'recording': self.enabled(), 'accepted': accepted}

    def payload(self, lookup=None, events=()):
        with self.lock:
            sessions = [json.loads(row[0]) for row in self.db.execute('SELECT payload FROM sessions ORDER BY updated DESC LIMIT 2000')]
            videos = [json.loads(row[0]) for row in self.db.execute('SELECT payload FROM videos ORDER BY updated DESC LIMIT 4000')]
            recording = self.enabled()
        names = {name for row in videos for name in row.get('models', [])}
        # Older model-navigation events can be matched against the exact local catalog.
        names.update(text(e.get('performer'), 100) for e in events if isinstance(e, dict) and e.get('scope') != 'live' and e.get('performer'))
        names.update(name for e in events if isinstance(e, dict) and e.get('scope') != 'live' for name in labels(e.get('models')))
        models = {}
        for name in sorted(names)[:1000]:
            raw = lookup(name) if lookup else None
            if not isinstance(raw, dict):
                continue
            year = int(number(raw.get('birth_year'), high=2100))
            birth = text(raw.get('birth_date'), 20)
            models[name.lower()] = {key: text(raw.get(key), 150) for key in ('id', 'name', 'hair', 'eyes', 'build', 'height_cm', 'cup', 'breast_type')}
            models[name.lower()].update({'birthDate': birth, 'birthYear': year, 'thumb': text(raw.get('thumb'), 1500), 'source': 'Lokaler Modelkatalog'})
        return {'version': 1, 'recording': recording, 'sessions': sessions, 'videos': videos, 'models': models}
