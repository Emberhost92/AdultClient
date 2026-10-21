"""Small, read-only provider samples. Never resolve a full video for hover."""
import threading
import time
import urllib.parse
from collections import OrderedDict


class SitePreviews:
    def __init__(self, browse, cached, enrich, busy=lambda: False, clock=time.monotonic):
        self.browse, self.cached, self.enrich, self.busy = browse, cached, enrich, busy
        self.clock = clock
        self.cache = OrderedDict()
        self.lock = threading.Lock()
        self.slot = threading.BoundedSemaphore(1)

    @staticmethod
    def candidates(items):
        found, seen = [], set()
        for item in items or []:
            kind = (item.get('media') or {}).get('kind')
            if item.get('role') in ('next', 'previous', 'search', 'sort') or kind == 'live':
                continue
            if item.get('folder') and kind not in ('gallery', 'image', 'animation'):
                continue
            if not item.get('url') or not item.get('thumb') or item['url'] in seen:
                continue
            seen.add(item['url'])
            found.append(dict(item))
            if len(found) == 6:
                break
        return found

    def get(self, name):
        with self.lock:
            hit = self.cache.get(name)
            if hit and self.clock() < hit[0]:
                self.cache.move_to_end(name)
                return {**hit[1], 'cached': True}
        if self.busy() or not self.slot.acquire(blocking=False):
            return {'ok': False, 'busy': True, 'items': [], 'error': 'Ein Anbieter wird gerade geladen. Bitte gleich erneut versuchen.'}
        try:
            query = urllib.parse.urlencode({'mode': '2', 'website': name, 'url': 'BOOTSTRAP'})
            data = self.cached(query) or self.browse(query)
            if data.get('busy'):
                return {'ok': False, 'busy': True, 'items': [], 'error': 'Der Anbieter wird gerade abgefragt. Bitte gleich erneut versuchen.'}
            items = self.candidates(data.get('items'))
            # Some adapters start with a directory. Follow at most two ordinary
            # listing links of this provider, never search/actions/video modes.
            if not items:
                followed = set()
                for entry in data.get('items') or []:
                    raw = str(entry.get('url') or '')
                    child = raw.partition('?')[2] if '?' in raw else raw.lstrip('?')
                    params = dict(urllib.parse.parse_qsl(child))
                    if not entry.get('folder') or entry.get('role') in ('next', 'search', 'sort') or params.get('mode') != '2' or params.get('website') != name or params.get('action') or not params.get('url') or child in followed:
                        continue
                    followed.add(child)
                    more = self.cached(child) or self.browse(child)
                    items = self.candidates(more.get('items'))
                    if items:
                        query = child
                        break
                    if more.get('busy') or len(followed) >= 2:
                        break
            if items and not any(item.get('clip') or len(item.get('preview') or []) > 1 for item in items):
                sample = {'items': items}
                try:
                    self.enrich(sample, dict(urllib.parse.parse_qsl(query)))
                except Exception:
                    pass  # A missing clip must not discard usable thumbnails.
                items = self.candidates(sample['items'])
            result = {'ok': True, 'site': name, 'items': items, 'cached': False}
            if not items:
                result['message'] = 'Für diesen Anbieter ist gerade keine Inhaltsvorschau verfügbar. Du kannst ihn weiterhin normal öffnen.'
            with self.lock:
                self.cache[name] = (self.clock() + (300 if items else 30), result)
                self.cache.move_to_end(name)
                while len(self.cache) > 32:
                    self.cache.popitem(last=False)
            return result
        except Exception:
            return {'ok': False, 'items': [], 'error': 'Die Inhaltsvorschau konnte gerade nicht geladen werden. Anbieter öffnen oder erneut versuchen.'}
        finally:
            self.slot.release()
