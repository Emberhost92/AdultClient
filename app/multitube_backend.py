"""Bounded VOD resolution in isolated processes, independent of Kodi's UI globals."""
import ast
import contextlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

LIVE = frozenset({'chaturbate', 'stripchat', 'bongacams', 'camsoda', 'cam4', 'xlovecam'})


def install_worker_proxy_exports(proxy_module):
    """A resolver child must export media, never a server owned by that child.

    The long-lived application's media gateway already forwards request headers,
    ranges and HLS resources. This adapter is installed only inside the isolated
    worker, before any provider imports these controller classes.
    """
    def source(controller, hls):
        upstream = controller if hls else controller.up
        url = str(upstream.master_url if hls else upstream.url)
        parsed = urllib.parse.urlsplit(url.split('|', 1)[0])
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Der Anbieter hat keine übertragbare Medienadresse geliefert.')
        session = getattr(upstream, 'session', None)
        headers = dict(getattr(session, 'headers', {}) or {})
        headers.update(getattr(upstream, 'headers', {}) or {})
        cookies = getattr(session, 'cookies', None)
        if cookies and not any(key.lower() == 'cookie' for key in headers):
            # Cookie selection must retain domain/path/secure restrictions.
            import requests
            prepared = session.prepare_request(requests.Request('GET', url))
            if prepared.headers.get('Cookie'): headers['Cookie'] = prepared.headers['Cookie']
        allowed = {'user-agent': 'User-Agent', 'referer': 'Referer', 'origin': 'Origin', 'cookie': 'Cookie'}
        forwarded = {allowed[key.lower()]: str(value) for key, value in headers.items()
                     if key.lower() in allowed and '\r' not in str(value) and '\n' not in str(value)}
        return url + ('|' + urllib.parse.urlencode(forwarded) if forwarded else '')
    proxy_module.HlsProxyController.start = lambda controller: source(controller, True)
    proxy_module.ProxyController.start = lambda controller: source(controller, False)


def validate_query(query, addon):
    if not isinstance(query, str) or len(query) > 16000:
        raise ValueError('Ungültiger Videoaufruf.')
    values = dict(urllib.parse.parse_qsl(query.lstrip('?')))
    site = values.get('website', '')
    if values.get('mode') != '4' or site in LIVE or not re.fullmatch(r'[a-zA-Z0-9_]+', site):
        raise ValueError('Multitube öffnet feste Videos. Live-Cams gehören in Multicam.')
    if not (Path(addon) / 'resources' / 'websites' / (site + '.py')).is_file():
        raise ValueError('Dieser Videoanbieter ist nicht installiert.')
    target = values.get('url', '').split('|', 1)[0]
    parsed = urllib.parse.urlsplit(target)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Bitte eine reguläre Videoseite angeben.')
    return urllib.parse.urlencode({'mode': '4', 'website': site, 'url': target})


def query_from_url(url, addon):
    if not isinstance(url, str) or len(url) > 8000:
        raise ValueError('Ungültige Videoseite.')
    if url.startswith(('plugin://', 'mode=', '?mode=')):
        raw = url.split('?', 1)[1] if url.startswith('plugin://') else url
        return validate_query(raw, addon)
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Bitte eine vollständige Videoseiten-Adresse angeben.')
    host = parsed.hostname.lower().removeprefix('www.')
    for source in sorted((Path(addon) / 'resources' / 'websites').glob('*.py')):
        if source.stem in LIVE:
            continue
        try:
            tree = ast.parse(source.read_text(encoding='utf-8-sig'))
        except (OSError, SyntaxError, UnicodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith(('https://', 'http://')):
                try:
                    candidate = urllib.parse.urlsplit(node.value).hostname
                    candidate = candidate.lower().removeprefix('www.') if candidate else ''
                except ValueError:
                    continue
                if candidate and (host == candidate or host.endswith('.' + candidate)):
                    return validate_query(urllib.parse.urlencode({'mode': '4', 'website': source.stem, 'url': url}), addon)
    raise ValueError('Für diese Adresse wurde kein installierter Tube-Anbieter gefunden. Das Video bitte über die Seitenliste öffnen.')


class Resolver:
    def __init__(self, addon, profile, limit=3, timeout=38, worker=None):
        self.addon, self.profile = str(addon), str(profile)
        self.slots = threading.BoundedSemaphore(limit)
        self.timeout = timeout
        self.worker = worker or [sys.executable, '-B', str(Path(__file__).resolve()), '--worker']
        self.lock = threading.Lock()
        self.jobs = {}
        self.cache = {}
        self.cancelled = {}

    def cancel(self, request_id):
        with self.lock:
            self.cancelled = {key: until for key, until in self.cancelled.items() if until > time.monotonic()}
            if len(self.cancelled) >= 500:
                self.cancelled.pop(next(iter(self.cancelled)))
            self.cancelled[request_id] = time.monotonic() + self.timeout
            job = self.jobs.get(request_id)
            if job:
                job.set()
        return {'ok': True}

    def resolve(self, query, request_id, fresh=False):
        query = validate_query(query, self.addon)
        if not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}', request_id):
            raise ValueError('Die Abrufkennung fehlt.')
        with self.lock:
            if self.cancelled.get(request_id, 0) > time.monotonic():
                return {'ok': False, 'cancelled': True, 'error': 'Abruf abgebrochen.'}
            cached = self.cache.get(query)
            if not fresh and cached and cached[0] > time.monotonic():
                return json.loads(json.dumps(cached[1]))
            if request_id in self.jobs:
                raise ValueError('Dieser Abruf läuft bereits.')
            cancel = threading.Event()
            self.jobs[request_id] = cancel
        process = None
        temporary = None
        acquired = False
        try:
            deadline = time.monotonic() + self.timeout
            while not acquired and time.monotonic() < deadline:
                if cancel.is_set():
                    return {'ok': False, 'cancelled': True, 'error': 'Abruf abgebrochen.'}
                acquired = self.slots.acquire(timeout=.15)
            if not acquired:
                return {'ok': False, 'error': 'Die Videoauflösung ist ausgelastet. Bitte erneut versuchen.'}
            # Provider caches/cookies written by a resolver never overwrite the UI profile.
            temporary = tempfile.TemporaryDirectory(prefix='ah-multitube-resolver-')
            if temporary:
                for name in ('settings.json', 'nm_cookies.jar', 'dns_cache.json'):
                    original = Path(self.profile) / name
                    if original.is_file():
                        shutil.copy2(original, Path(temporary.name) / name)
                env = {**os.environ, 'AH_ADDON': self.addon, 'AH_PROFILE': temporary.name, 'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1'}
                options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
                process = subprocess.Popen(self.worker, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, **options)
                payload = json.dumps({'query': query}).encode()
                while True:
                    if cancel.is_set():
                        return {'ok': False, 'cancelled': True, 'error': 'Abruf abgebrochen.'}
                    if time.monotonic() >= deadline:
                        return {'ok': False, 'error': 'Der Anbieter hat nicht rechtzeitig geantwortet. Die anderen Videos bleiben bedienbar.'}
                    try:
                        output, _ = process.communicate(payload, timeout=.15)
                        break
                    except subprocess.TimeoutExpired:
                        payload = None
                if process.returncode or len(output) > 2_000_000:
                    return {'ok': False, 'error': 'Der Anbieter konnte dieses Video nicht auflösen.'}
                try:
                    result = json.loads(output.decode('utf-8'))
                except (ValueError, UnicodeError):
                    return {'ok': False, 'error': 'Der Anbieter hat keine lesbare Videoquelle geliefert.'}
                if result.get('ok'):
                    with self.lock:
                        self.cache = {k: v for k, v in self.cache.items() if v[0] > time.monotonic()}
                        if len(self.cache) >= 80:
                            self.cache.pop(next(iter(self.cache)))
                        self.cache[query] = (time.monotonic() + 35, result)
                return result
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate()
            if temporary is not None:
                temporary.cleanup()
            if acquired:
                self.slots.release()
            with self.lock:
                self.jobs.pop(request_id, None)


def worker_main():
    incoming = json.loads(sys.stdin.buffer.read(20000))
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        import server
        from resources.lib import proxy_utils
        install_worker_proxy_exports(proxy_utils)
        query = validate_query(incoming.get('query'), server.ADDON)
        payload = server._execute_plugin(query)
        if payload.get('resolved'):
            server.enrich_tube_media(payload, dict(urllib.parse.parse_qsl(query)))
        resolved = payload.get('resolved') or {}
        if not isinstance(resolved.get('path'), str) or not resolved['path'].startswith(('http://', 'https://')):
            result = {'ok': False, 'error': 'Der Anbieter hat keine abspielbare Videoquelle geliefert.'}
        else:
            result = {'ok': True, 'resolved': resolved}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))


if __name__ == '__main__' and '--worker' in sys.argv:
    try:
        worker_main()
    except Exception:
        sys.stdout.buffer.write(b'{"ok":false,"error":"Die Videoquelle konnte nicht geladen werden."}')
