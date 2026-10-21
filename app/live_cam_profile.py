"""Read public profile material as text. Never render upstream HTML or execute scripts."""
import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, parse_qs


def clean(value, limit=4000):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def public_url(value, base):
    try:
        result = urljoin(base, str(value or ""))
        parsed = urlsplit(result)
        if parsed.hostname and (parsed.hostname == "chaturbate.com" or parsed.hostname.endswith(".chaturbate.com")) and parsed.path == "/external_link/":
            result = parse_qs(parsed.query).get("url", [""])[0]
            parsed = urlsplit(result)
        if parsed.scheme in ("http", "https") and parsed.hostname and not parsed.username and not parsed.password:
            return result[:2000]
    except ValueError:
        pass
    return None


def catalog_facts(source):
    """Keep explicit public fields; never archive transport/session internals."""
    labels = {
        'display_name':'Anzeigename', 'displayName':'Anzeigename',
        'age':'Alter', 'gender':'Typ der Quelle', 'country':'Land der Quelle',
        'countryCode':'Ländercode', 'location':'Öffentlicher Ort', 'city':'Öffentliche Stadt',
        'spoken_languages':'Sprachen', 'languages':'Sprachen', 'lang':'Sprachen',
        'num_followers':'Follower', 'followers':'Follower', 'seconds_online':'Onlinezeit (Sekunden)',
        'broadcastTime':'Sendedauer (Sekunden)', 'resolution':'Videoauflösung', 'vq':'Videoqualität',
        'isHd':'HD', 'isNew':'Neu beim Anbieter', 'isVr':'VR', 'isMobile':'Mobil',
        'isLovense':'Lovense', 'isKiiroo':'Kiiroo', 'isNonNude':'Non-Nude-Kennzeichnung',
        'privateRate':'Privatpreis (Tokens/Minute)', 'spyRate':'Spy-Preis (Tokens/Minute)',
        'p2pRate':'Cam-to-Cam-Preis (Tokens/Minute)',
        'height':'Größe', 'weight':'Gewicht', 'hairColor':'Haarfarbe', 'eyeColor':'Augenfarbe',
        'ethnicity':'Ethnische Selbstangabe', 'orientation':'Orientierung (Selbstangabe)',
        'relationshipStatus':'Beziehungsstatus (Selbstangabe)', 'bodyType':'Körperbau (Selbstangabe)',
        'sexPreference':'Orientierung (Quellangabe)', 'maritalStatus':'Beziehungsstatus (Quellangabe)',
        'mainLanguage':'Hauptsprache', 'secondaryLanguages':'Weitere Sprachen',
        'occupation':'Öffentliche Berufsangabe', 'smoke':'Rauchen (Selbstangabe)',
        'drink':'Alkohol (Selbstangabe)', 'hairLength':'Haarlänge',
        'bodyHair':'Körperbehaarung', 'facialHair':'Gesichtsbehaarung',
        'bodyDecorations':'Tattoos / Körperschmuck', 'heightUnit':'Größeneinheit',
        'creationDate':'Profil angelegt', 'lastBroadcast':'Letzte Sendung (Quellangabe)',
        'psBroadcasterRating':'Öffentliche Broadcasterbewertung',
        'psBroadcasterRatingsCount':'Anzahl Broadcasterbewertungen',
        'countryId':'Länderkennung der Quelle',
    }
    result = []
    for key, label in labels.items():
        value = source.get(key)
        if value is None or value == '' or isinstance(value, dict):
            continue
        if isinstance(value, list):
            value = ', '.join(str(v) for v in value[:30] if isinstance(v,(str,int,float)))
        if isinstance(value, bool):
            value = 'Ja' if value else 'Nein'
        if isinstance(value, (str,int,float)):
            result.append({'label':label, 'value':clean(value,1000)})
    return result


def cam4_profile(data, name, observed_at):
    """The public CAM4 profile endpoint also works without a logged-in account."""
    if not isinstance(data,dict) or str(data.get('username','')).casefold()!=name.casefold():
        raise ValueError('Die Profilantwort gehört nicht zu diesem Model.')
    source = 'https://www.cam4.com/' + name + '/'
    parser = ProfileParser(source)
    parser.feed('<section class="profile-bio">' + str(data.get('htmlBio') or data.get('bio') or '')[:100000] + '</section>')
    bio = clean(' '.join(chunk for block in parser.blocks for chunk in block['chunks']))
    images = [public_url(data.get(field),source) for field in ('profileImageUrl','avatarUrl') if data.get(field)]
    links = []
    for field in ('socialNetworks','wishList'):
        for value in (data.get(field) or {}).values() if isinstance(data.get(field),dict) else []:
            if isinstance(value,str) and value.startswith(('https://','http://')):
                link = public_url(value,source)
                if link:
                    links.append(link)
    return {'id':'cam4:'+name, 'displayName':name, 'bio':bio, 'sections':[],
            'facts':catalog_facts(data), 'images':[v for v in images if v],
            'tags':[], 'links':links, 'sourceUrl':source,
            'observedAt':observed_at, 'parserVersion':2}


class ProfileParser(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.stack = []
        self.blocks = []
        self.links = []
        self.tags = []
        self.meta = {}
        self.json_parts = []
        self.json_depth = 0
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        marker = " ".join(str(a.get(k, "")) for k in ("id", "class", "data-testid", "itemprop"))
        inherited = bool(self.stack and self.stack[-1][1])
        profile = bool(re.search(r"room.?bio|roomTabs|bio-tab|about.?me|profile.?bio|bio.?content|description|biography|profile.?tabs", marker, re.I))
        ignored = tag in ("style", "script", "noscript", "svg", "nav", "footer", "header") or bool(self.stack and self.stack[-1][2])
        block = None
        if profile and tag not in ("meta", "script", "img", "link", "input"):
            block = {"label": clean(a.get("data-testid") or a.get("itemprop") or a.get("id") or "Profil", 100), "chunks": []}
            self.blocks.append(block)
        self.stack.append((tag, inherited or profile, ignored, block))
        if tag == "meta":
            self.meta[str(a.get("property") or a.get("name") or "").lower()] = clean(a.get("content"))
        if tag == "script" and a.get("type") == "application/ld+json":
            self.json_depth = len(self.stack)
            self.json_parts = []
        if tag == "a":
            href = public_url(a.get("href"), self.source)
            if href and (inherited or profile):
                host = urlsplit(href).hostname or ""
                if host != urlsplit(self.source).hostname and not host.endswith("." + (urlsplit(self.source).hostname or "")):
                    self.links.append(href)
            if href and re.search(r"/(tags?|hashtag)/", urlsplit(href).path, re.I):
                self.tags.append(urlsplit(href).path.strip("/").split("/")[-1][:50])
        if tag in ("meta", "img", "input", "link", "br", "hr", "source", "wbr", "area", "base", "embed", "param", "track"):
            self.stack.pop()

    def handle_endtag(self, tag):
        if tag == "script" and self.json_depth:
            try:
                self.scripts.append(json.loads("".join(self.json_parts)))
            except (ValueError, TypeError):
                pass
            self.json_depth = 0
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, value):
        if self.json_depth:
            self.json_parts.append(value)
        if self.stack and not self.stack[-1][2]:
            for _, _, _, block in self.stack:
                if block is not None and sum(map(len, block["chunks"])) < 10000:
                    block["chunks"].append(value)


class PublicFactsParser(HTMLParser):
    """Read labelled public profile facts; never collect arbitrary JS state."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.kind = None
        self.chunks = []
        self.label = ''
        self.facts = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script','style','noscript'):
            self.ignored+=1;return
        if tag in ('dt', 'dd', 'th', 'td'):
            self.kind = tag
            self.chunks = []

    def handle_data(self, value):
        if self.kind and not self.ignored and sum(map(len, self.chunks)) < 4500:
            self.chunks.append(value)

    def handle_endtag(self, tag):
        if tag in ('script','style','noscript'):
            self.ignored=max(0,self.ignored-1);return
        if tag != self.kind:
            return
        value = clean(' '.join(self.chunks))
        if tag in ('dt', 'th'):
            self.label = value[:160]
        elif self.label and value and len(self.facts) < 80:
            self.facts.append({'label': self.label, 'value': value})
            self.label = ''
        self.kind = None


def parse_profile(document, source, identity, observed_at):
    if len(document) > 2 * 1024 * 1024:
        raise ValueError("Das öffentliche Profil ist zu groß.")
    parser = ProfileParser(source)
    parser.feed(document)
    fact_parser = PublicFactsParser()
    fact_parser.feed(document)
    facts = fact_parser.facts
    images = []
    for field in ('og:image', 'twitter:image', 'twitter:image:src'):
        image = public_url(parser.meta.get(field), source) if parser.meta.get(field) else None
        if image and not re.search(r'/favicon/|/logo[./_-]|/icons?/',image,re.I):
            images.append(image)
    sections, seen = [], set()
    for block in reversed(parser.blocks):
        text = clean(" ".join(block["chunks"]))
        if not text or text in seen:
            continue
        seen.add(text)
        label = re.sub(r"^bio-tab-|[-_]value$", "", block["label"])
        sections.append({"label": clean(re.sub(r"[-_]+", " ", label), 100), "text": text})
    description = parser.meta.get("og:description") or parser.meta.get("description") or ""
    name = parser.meta.get("og:title") or ""
    for data in parser.scripts:
        rows = data if isinstance(data, list) else [data]
        for row in rows[:100]:
            if not isinstance(row, dict):
                continue
            for item in ([row] + (row.get("@graph") if isinstance(row.get("@graph"), list) else [])):
                if not isinstance(item, dict) or item.get("@type") not in ("Person", "ProfilePage"):
                    continue
                person = item.get("mainEntity") if isinstance(item.get("mainEntity"), dict) else item
                description = clean(person.get("description")) or description
                name = clean(person.get("name"), 160) or name
                for field, label in [('gender','Geschlecht'), ('birthDate','Geburtsdatum'),
                                     ('nationality','Nationalität'), ('knowsLanguage','Sprachen'),
                                     ('height','Größe'), ('weight','Gewicht'),
                                     ('description','Beschreibung'), ('award','Auszeichnungen')]:
                    value = person.get(field)
                    if isinstance(value, dict):
                        value = value.get('name') or value.get('value')
                    if isinstance(value, list):
                        value = ', '.join(clean(v.get('name') if isinstance(v,dict) else v,160) for v in value[:20])
                    if isinstance(value, (str,int,float)) and str(value).strip():
                        facts.append({'label':label, 'value':clean(value)})
                picture = person.get('image')
                for value in picture if isinstance(picture,list) else [picture]:
                    if isinstance(value,dict):
                        value = value.get('url') or value.get('contentUrl')
                    image = public_url(value,source) if value else None
                    if image:
                        images.append(image)
                links = person.get("sameAs") or []
                for link in links if isinstance(links, list) else [links]:
                    url = public_url(link, source)
                    if url:
                        parser.links.append(url)
    bio = next((r["text"] for r in sections if re.search(r"about|bio|über|description", r["label"], re.I)), description)
    # Generic landing-page SEO is not a model biography.
    if not sections and not facts and identity.split(':')[-1].casefold() not in name.casefold() and not any(isinstance(p,dict) and p.get('@type') in ('Person','ProfilePage') for p in parser.scripts):
        raise ValueError('Die Quelle liefert derzeit nur eine allgemeine Seite, kein lesbares Modelprofil.')
    if not bio and not sections and not facts:
        raise ValueError("Auf dieser öffentlichen Seite wurde kein lesbarer Profilabschnitt gefunden. Die Quelle kann Anmeldung oder eine manuelle Freigabe verlangen.")
    unique_facts = {(r['label'].casefold(),r['value']):r for r in facts}
    return {"id": identity, "displayName": clean(name, 160), "bio": bio, "sections": sections[:16], "links": list(dict.fromkeys(parser.links))[:40], "tags": list(dict.fromkeys(parser.tags))[:80], "facts":list(unique_facts.values())[:80], "images":list(dict.fromkeys(images))[:12], "sourceUrl": source, "observedAt": observed_at, "parserVersion": 2}
