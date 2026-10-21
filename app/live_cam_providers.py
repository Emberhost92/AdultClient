"""Public CAM4/XloveCam sources, using their currently published website data.

Only metadata enters the model library. Signed HLS addresses stay in memory and
are resolved through the same bounded transport as the other live providers.
"""
import html
import json
import re
import urllib.parse

SITES = ('stripchat', 'chaturbate', 'bongacams', 'camsoda', 'cam4', 'xlovecam')
ACCOUNT_SITES = SITES
FOLLOWING_SITES = SITES[:4]
HOSTS = dict(zip(SITES, ('stripchat.com', 'chaturbate.com', 'bongacams.com',
                        'camsoda.com', 'www.cam4.com', 'www.xlovecam.com')))
LABELS = dict(zip(SITES, ('Stripchat', 'Chaturbate', 'BongaCams', 'CamSoda', 'CAM4', 'XloveCam')))


def public_url(site, name):
    path = 'en/model/' if site == 'xlovecam' else ''
    return 'https://' + HOSTS[site] + '/' + path + urllib.parse.quote(name, safe='') + '/'


def objects(document):
    """Decode embedded JSON without depending on its key ordering."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r'\{\s*"(?:id|nickname|hlsPlaylist|profileImgId)"\s*:', document):
        try:
            row, _ = decoder.raw_decode(document, match.start())
        except ValueError:
            continue
        if isinstance(row, dict) and row.get('nickname') and 'hlsPlaylist' in row:
            yield row


def playlist(value, site):
    value = html.unescape(str(value or '')).replace('\\/', '/')
    try:
        url = urllib.parse.urlsplit(value)
    except ValueError:
        return ''
    hosts = ('cam4.com', 'xcdnpro.com') if site == 'cam4' else ('xlovecam.com', 'wlresources.com')
    if (url.scheme != 'https' or not url.hostname or url.username or url.password or url.port
            or not url.path.lower().endswith('.m3u8') or len(value) > 4000
            or any(c.isspace() or c in '\"\'<>' for c in value)
            or not any(url.hostname == host or url.hostname.endswith('.'+host) for host in hosts)):
        return ''
    return value


class PublicProviders:
    def __init__(self, backend):
        self.b = backend

    def read(self, site, url, limit=4_000_000, authenticated=False):
        headers = {'User-Agent': self.b['_CAM_UA'], 'Accept': 'application/json,text/html,*/*',
                   'Referer': 'https://' + HOSTS[site] + '/', 'Origin': 'https://' + HOSTS[site]}
        if authenticated and '_cam_jar' in self.b:
            jar, _ = self.b['_cam_jar'](site)
            status, raw = self.b['_cam_open'](url, headers, 8, limit, jar)
        else:
            status, raw = self.b['_cam_open'](url, headers, 8, limit)
        if status != 200:
            raise ValueError(LABELS[site] + ' antwortet derzeit mit HTTP ' + str(status) + '.')
        if len(raw) >= limit:
            raise ValueError('Die Antwort von ' + LABELS[site] + ' ist unvollständig.')
        return raw.decode('utf-8', 'replace')

    def room(self, site, row):
        name = str(row.get('username' if site == 'cam4' else 'nickname') or '').strip()
        if not self.b['_cam_pair'](site, name):
            return None
        age = row.get('age')
        if age is not None and not self.b['_cam_age_ok'](age):
            return None
        if site == 'cam4':
            if row.get('showType') != 'NORMAL' or row.get('privateRoom') is True:
                return None
            stream = playlist(row.get('hlsPreviewUrl'), site)
            gender = {'female':'f', 'male':'m', 'shemale':'t', 'trans':'t', 'couple':'c', 'couples':'c'}.get(str(row.get('gender') or '').lower(), '')
            subject = self.b['_cam_subject'](str(row.get('statusMessage') or ''))
            if subject is None:
                return None
            thumb = row.get('snapshotImageLink') or row.get('profileImageLink')
            tags = self.b['_cam_tag_list'](row.get('showTags'))
            resolution = re.fullmatch(r'(\d{2,5}):(\d{2,5})', str(row.get('resolution') or ''))
            hd = int(resolution[2]) >= 720 if resolution else None
        else:
            # 1 is the public free-show type observed in the official directory.
            if row.get('showType') != 1:
                return None
            stream = playlist(row.get('hlsPlaylist'), site)
            gender, subject, tags, hd = '', '', [], None
            thumb = row.get('profileImg') or row.get('liveImg')
        if not stream:
            return None
        room = {'site':site, 'name':name, 'online':True, 'show':'public',
                'viewers':self.b['_cam_number'](row.get('viewers'), 100_000_000) if row.get('viewers') is not None else None,
                'gender':gender, 'subject':subject, 'tags':tags, 'hd':hd,
                'thumb':self.b['_cam_image'](urllib.parse.urljoin('https://'+HOSTS[site]+'/',str(thumb or '')), 'https://'+HOSTS[site]+'/') if thumb else ''}
        if site == 'xlovecam':
            self.b['_cam_details'](room,row)
        if site == 'cam4':
            self.b['_cam_details'](room, {**row, 'country':row.get('countryCode'), 'seconds':row.get('broadcastTime')})
        return room

    def rows(self, site, offset=0):
        if site == 'cam4':
            page = offset // 60 + 1
            text = self.read(site, 'https://www.cam4.com/directoryCams?directoryJson=true&page='+str(page))
            data = json.loads(text)
            if isinstance(data, dict):
                data = next((v for v in data.values() if isinstance(v, list)), None)
            if not isinstance(data, list):
                raise ValueError('CAM4 hat keine lesbare Raumliste geliefert.')
            return [r for r in data if isinstance(r, dict)], len(data) >= 60
        text = self.read(site, 'https://www.xlovecam.com/en/')
        rows = list(objects(text))
        if not rows:
            raise ValueError('XloveCam liefert derzeit keine lesbare öffentliche Raumliste.')
        return rows, False

    def rooms(self, site, gender, offset):
        try:
            rows, paged = self.rows(site, offset)
            items, seen = [], set()
            for row in rows:
                room = self.room(site, row)
                if not room or room['name'].lower() in seen:
                    continue
                if site == 'cam4' and gender not in ('', 'all') and room['gender'] != gender:
                    continue
                seen.add(room['name'].lower())
                items.append(room)
            result = {'ok':True, 'site':site, 'items':items, 'paged':paged}
            if site == 'xlovecam':
                result['note'] = 'XloveCam: Ausschnitt der öffentlichen Startseite; Geschlecht, Zuschauerzahl und weitere Seiten werden von dieser Quelle nicht bestätigt. Der Geschlechtsfilter greift hier nicht.'
            return result
        except (OSError, ValueError, TimeoutError) as error:
            return {'ok':False, 'site':site, 'items':[], 'error':str(error)[:250]}

    def play(self, site, name):
        if site == 'cam4':
            base = 'https://www.cam4.com/rest/v1.0/profile/' + urllib.parse.quote(name, safe='')
            info = json.loads(self.read(site, base+'/info', 1_000_000, authenticated=True))
            if (not isinstance(info, dict) or str(info.get('username') or '').lower() != name.lower()
                    or info.get('online') is not True or not self.b['_cam_age_ok'](info.get('age'))):
                return {'ok':False, 'error':'Dieser CAM4-Raum ist derzeit nicht öffentlich verfügbar.'}
            data = json.loads(self.read(site, base+'/streamInfo', 100_000, authenticated=True))
            stream = playlist(data.get('cdnURL'), site) if isinstance(data, dict) and data.get('canUseCDN') is True else ''
        else:
            text = self.read(site, public_url(site, name), authenticated=True)
            row = next((r for r in objects(text) if str(r.get('nickname') or '').lower() == name.lower()), None)
            room = self.room(site, row) if row else None
            stream = playlist(row.get('hlsPlaylist'), site) if room else ''
        if not stream:
            return {'ok':False, 'error':'Der Raum nennt derzeit keinen freigegebenen öffentlichen Live-Stream.'}
        pack = {'User-Agent':self.b['_CAM_UA'], 'Referer':'https://'+HOSTS[site]+'/', 'Origin':'https://'+HOSTS[site]}
        path = self.b['_cam_pack'](stream, pack)
        return {'ok':True, 'title':name, 'path':path, 'sources':[{'label':'Live', 'path':path}], 'facts':{'site':LABELS[site]}}
