"""Typed media boundary for the web library. No Kodi imports at module load.

Provider code supplies entries; this module describes their real media, adapts
mixed albums, and serves full-size files without the thumbnail cache's size cap.
Live-Cam code, profiles and stores are deliberately independent of this module.
"""
from __future__ import annotations

import ast
import collections
import html
from html.parser import HTMLParser
import json
import mimetypes
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

LIVE_SITES = frozenset({"chaturbate", "stripchat", "cam4", "xlovecam", "bongacams", "camsoda"})
EXTENSIONS = {
    "image": {"jpg", "jpeg", "png", "webp", "avif", "bmp", "svg", "jxl"},
    "animation": {"gif", "apng", "gifv"},
    "video": {"mp4", "m4v", "webm", "mkv", "mov", "avi", "wmv", "flv", "ts", "m3u8", "mpd"},
    "audio": {"mp3", "m4a", "aac", "ogg", "oga", "opus", "wav", "flac"},
    "document": {"pdf", "txt", "md", "csv", "json"},
    "file": {"zip", "rar", "7z", "tar", "gz", "epub", "cbz", "cbr", "psd", "blend"},
}
LABELS = {"image": "Bild", "animation": "Animation", "video": "Video", "audio": "Audio",
          "document": "Dokument", "file": "Datei", "gallery": "Galerie", "folder": "Sammlung", "live": "Live-Cam"}
PHOTO_SECTIONS = {"fapello": "/", "cherrygasp": "/albums/", "mylust": "/albums/", "feet9": "/photo/"}
_registry_lock = threading.Lock()
_registries = {}


def split_url(value):
    url, _, raw = str(value or "").partition("|")
    headers = dict(urllib.parse.parse_qsl(raw))
    return url, {k: v for k, v in headers.items() if k.lower() in ("referer", "origin", "cookie", "user-agent", "authorization") and "\r" not in v and "\n" not in v}


def target_url(value):
    """Unwrap a Kodi URL without ever treating its thumbnail as the media."""
    value = str(value or "")
    if value.startswith("plugin://") or value.startswith(("mode=", "?mode=")):
        query = value.partition("?")[2] if "?" in value else value.lstrip("?")
        return dict(urllib.parse.parse_qsl(query)).get("url", "")
    return value


def describe(value="", mime="", declared="", folder=False, provider="", info=None):
    url, _ = split_url(target_url(value))
    try: path = urllib.parse.urlsplit(url).path.lower()
    except ValueError: path = ""
    raw_extension = path.rsplit(".", 1)[-1] if "." in path.rsplit("/", 1)[-1] else ""
    kind = next((k for k, values in EXTENSIONS.items() if raw_extension in values), "")
    # Tube slugs often contain a dot. Only a real media suffix is a format.
    extension = raw_extension if kind else ""
    mime = str(mime or "").split(";", 1)[0].strip().lower()
    # Extensions override legacy adapters that label every attachment video/webm.
    if not kind:
        if mime in ("image/gif", "image/apng"): kind = "animation"
        elif mime.startswith("image/"): kind = "image"
        elif mime.startswith("audio/"): kind = "audio"
        elif mime.startswith("video/") or "mpegurl" in mime: kind = "video"
        elif mime == "application/pdf" or mime.startswith("text/") and mime != "text/html": kind = "document"
    if not kind and declared in LABELS: kind = declared
    if folder: kind = "gallery" if declared == "gallery" else "folder"
    if provider in LIVE_SITES and not folder: kind = "live"
    kind = kind or "file"
    real_mime = mimetypes.guess_type(url)[0] if extension else None
    if extension == "m3u8": real_mime = "application/vnd.apple.mpegurl"
    data = {"version": 1, "kind": kind, "label": LABELS[kind], "extension": extension,
            "mime": real_mime or mime, "provider": provider}
    info = info or {}
    if info.get("quality"):
        data["quality"] = str(info["quality"])[:80]
    for field in ("width", "height", "duration", "rating", "size"):
        try:
            number = float(info.get(field) or 0)
            if number > 0 and number < 10**15: data[field] = number
        except (TypeError, ValueError): pass
    for field in ("date", "dateadded", "premiered"):
        if info.get(field):
            data["date"] = str(info[field])[:40]
            break
    return data


def entry_media(entry):
    item = entry.get("item") or {}
    info = (item.get("info") or {}).get("video") or {}
    props = item.get("properties") or {}
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(entry.get("url") or "").query))
    return describe(entry.get("url"), item.get("mimetype"), props.get("web_media_type") or info.get("mediatype") or "video",
                    bool(entry.get("isFolder")), query.get("website", ""), info)


def saved_kind(url, declared=None):
    declared = declared if isinstance(declared, str) and declared in LABELS else "video"
    return describe(url, declared=declared)["kind"]


def provider_capabilities(addon):
    """Inspect adapters and their shared engines without importing 400 websites."""
    folder = os.path.join(addon, "resources", "websites")
    try:
        files = [(e.name, e.stat().st_mtime_ns, e.stat().st_size) for e in os.scandir(folder) if e.name.endswith(".py") and e.name != "__init__.py"]
    except OSError: return {}
    stamp = tuple(sorted(files))
    with _registry_lock:
        cached = _registries.get(addon)
        if cached and cached[0] == stamp: return cached[1]
    result = {}
    for filename, _, _ in files:
        name = filename[:-3]
        try:
            with open(os.path.join(folder, filename), encoding="utf-8-sig") as handle: source = handle.read()
            tree = ast.parse(source)
        except (OSError, SyntaxError, UnicodeError):
            result[name] = {"mediaTypes": ["video"], "capabilitySource": "legacy"}
            continue
        bases = {ast.unparse(base) for node in tree.body if isinstance(node, ast.ClassDef) for base in node.bases}
        methods = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        images = bool(bases & {"BooruApiWebsite", "KemonoApiWebsite", "LeakWebsite"}) or bool(methods & {"_images", "_photos", "_photo", "_list_pages", "_photo_url"})
        kinds = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value in ("mediatype", "web_media_type") and isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value in LABELS:
                        kinds.add(value.value)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "setProperty" and len(node.args) >= 2:
                key, value = node.args[:2]
                if isinstance(key, ast.Constant) and key.value == "web_media_type" and isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value in LABELS:
                    kinds.add(value.value)
        if images: kinds.update(("image", "gallery"))
        if "BooruApiWebsite" in bases: kinds.update(("animation", "video"))
        if "KemonoApiWebsite" in bases: kinds.update(("video", "audio", "document", "file"))
        if not kinds or re.search(r"(?:\\\.|\.)mp4|(?:\\\.|\.)m3u8|def _videos\b|def _clips\b", source): kinds.add("video")
        if name in {"erome", "balbums", "leakgallery"} or name in PHOTO_SECTIONS: kinds.update(("image", "gallery"))
        if name == "balbums": kinds.update(("document", "file"))
        if name in LIVE_SITES: kinds = {"live"}
        result[name] = {"mediaTypes": sorted(kinds), "liveOnly": name in LIVE_SITES,
                        "capabilitySource": "adapter", "engine": next(iter(sorted(bases)), "BaseWebsite")}
    with _registry_lock: _registries[addon] = (stamp, result)
    return result


class MediaHTMLParser(HTMLParser):
    """Published full images, media and collection links; never upstream HTML UI."""
    VOID = {"img", "source", "meta", "br", "hr", "input", "link", "area", "base", "embed", "wbr", "track"}
    SKIP = re.compile(r"(?:^|[\s_/-])(?:advert\w*|ads?|banner|logo|icon|avatar|emoji|captcha|recommended|related|sidebar|footer|header|navigation)(?:$|[\s_/-])", re.I)

    def __init__(self, base, provider=""):
        super().__init__(convert_charrefs=True)
        self.base = base; self.provider = provider; self.stack = []; self.media = []; self.links = []; self.next_url = ""; self.seen = set()

    def collection(self, href):
        path = urllib.parse.urlsplit(href).path
        if re.search(r"/(?:a|albums?|g|models?|creators?|posts?)/|/[^/]+/\d+/?$", path, re.I): return True
        if self.provider == "feet9" and re.search(r"^/\d+/[^/]+/?$", path): return True
        if self.provider == "fapello" and re.fullmatch(r"/[\w.-]+/", path) and path not in ("/videos/", "/login/", "/register/", "/search/", "/dmca/", "/terms/", "/privacy/", "/contact/", "/popular/", "/trending/", "/new/"): return True
        return False

    def absolute(self, value):
        value = html.unescape(str(value or "")).strip().replace("\\/", "/")
        url = urllib.parse.urljoin(self.base, value)
        try:
            p = urllib.parse.urlsplit(url)
            if p.scheme in ("http", "https") and p.hostname and not p.username and not p.password: return url
        except ValueError: pass
        return ""

    def add(self, value, title="", thumb=""):
        url = self.absolute(value)
        if not url or url in self.seen or self.SKIP.search(urllib.parse.urlsplit(url).path): return
        media = describe(url)
        if media["kind"] == "file" and not media["extension"]: return
        self.seen.add(url)
        self.media.append({"url": url, "title": title or urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]) or media["label"], "thumb": self.absolute(thumb) or (url if media["kind"] in ("image", "animation") else ""), "media": media})

    def handle_starttag(self, tag, attrs):
        a = dict(attrs); marker = " ".join(a.get(k, "") for k in ("class", "id", "role"))
        ignored = tag in ("script", "style", "nav", "header", "footer", "aside", "noscript") or bool(self.SKIP.search(marker)) or bool(self.stack and self.stack[-1][1])
        self.stack.append((tag, ignored, a))
        if not ignored:
            title = a.get("alt") or a.get("title") or ""
            if tag == "a":
                href = self.absolute(a.get("href")); media = describe(href)
                if href and media["kind"] != "file" or href and media["extension"] in EXTENSIONS["file"]: self.add(href, title)
                elif href and urllib.parse.urlsplit(href).hostname == urllib.parse.urlsplit(self.base).hostname:
                    path = urllib.parse.urlsplit(href).path
                    if self.collection(href) and href != self.base: self.links.append({"url": href, "title": title or urllib.parse.unquote(path.strip("/").split("/")[-1]).replace("-", " "), "thumb": ""})
                if "next" in a.get("rel", "").lower().split() or re.search(r"(?:^|[\s_-])next(?:$|[\s_-])", marker, re.I) or a.get("aria-label", "").lower() in ("next", "next page", "nächste seite"):
                    self.next_url = href
                    self.links = [row for row in self.links if row["url"] != href]
            if tag in ("video", "audio", "source"):
                self.add(a.get("src"), title, a.get("poster", ""))
            if tag == "img":
                try: tiny = any(0 < int(a.get(k) or 0) < 100 for k in ("width", "height"))
                except ValueError: tiny = False
                if not tiny:
                    parent = next((x[2].get("href", "") for x in reversed(self.stack[:-1]) if x[0] == "a"), "")
                    full = self.absolute(parent)
                    collection = next((row for row in reversed(self.links) if row["url"] == full), None)
                    if collection is not None:
                        collection["thumb"] = self.absolute(a.get("data-original") or a.get("data-src") or a.get("src"))
                        if title: collection["title"] = title
                        if tag in self.VOID: self.stack.pop()
                        return
                    if describe(full)["kind"] not in ("image", "animation"):
                        full = next((a[k] for k in ("data-full", "data-original", "data-large", "data-src", "data-lazy-src", "src") if a.get(k)), "")
                        srcset = a.get("data-srcset") or a.get("srcset")
                        if srcset:
                            choices = [x.strip().split() for x in srcset.split(",") if x.strip()]
                            if choices: full = choices[-1][0]
                    self.add(full, title, a.get("src", ""))
        if tag in self.VOID: self.stack.pop()

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]; break


def extract_media(document, base, provider=""):
    parser = MediaHTMLParser(base, provider)
    parser.feed(document[:3_000_000])
    return parser


def adapt_provider(site):
    """Web-only instance adapters. Installed Kodi source is never monkey-patched."""
    if not site or getattr(site, "_web_typed_media", False): return site
    site._web_typed_media = True
    if site.name == "xvideos" and callable(getattr(site, "make_request", None)) and callable(getattr(site, "add_link", None)):
        request, add_link = site.make_request, site.add_link
        qualities = {}
        def listing_request(url, *args, **kwargs):
            document = request(url, *args, **kwargs)
            qualities.clear()
            qualities.update(xvideos_listing_quality(document, url))
            return document
        def quality_link(*args, **kwargs):
            values = list(args)
            url = values[1] if len(values) > 1 else kwargs.get("url", "")
            label = qualities.get(urllib.parse.urlsplit(url).path)
            if label:
                info = dict((values[6] if len(values) > 6 else kwargs.get("info_labels")) or {})
                info["quality"] = label
                if len(values) > 6: values[6] = info
                else: kwargs["info_labels"] = info
            return add_link(*values, **kwargs)
        site.make_request, site.add_link = listing_request, quality_link
    if site.name == "erome" and hasattr(site, "process_album"):
        original = site.process_album
        def mixed_album(content, url):
            original(content, url)
            for n, row in enumerate(extract_media(content, url).media, 1):
                if row["media"]["kind"] in ("image", "animation"):
                    site.add_link(row["title"] or "Bild %s" % n, row["url"] + "|Referer=" + urllib.parse.quote(url, safe=""), 4, row["thumb"], site.fanart, info_labels={"mediatype": row["media"]["kind"]})
        site.process_album = mixed_album
    if site.name == "leakgallery" and hasattr(site, "_api_video_items"):
        original = site._api_video_items
        def mixed_posts(data):
            rows = original(data)
            for group in (data or {}).get("content", []):
                for media in group.get("medias", []):
                    if media.get("is_video"): continue
                    url = site._cdn_url(media.get("file_path"))
                    if describe(url)["kind"] not in ("image", "animation"): continue
                    user = str((media.get("profile") or {}).get("username") or "LeakGallery")
                    rows.append((user + " · Bild " + str(media.get("id") or ""), url, site._cdn_url(media.get("thumbnail_path")) or url, user, site.base_url + urllib.parse.quote(user) + "/Videos"))
            return rows
        site._api_video_items = mixed_posts
    if site.name == "balbums" and hasattr(site, "process_album"):
        original = site.process_album
        def mixed_files(content, url):
            original(content, url)
            _, rows = site._extract_file_items(content, url)
            for row in rows:
                if row.get("is_video"): continue
                site.add_link(row["title"], row["url"], 4, row.get("thumb") or site.icon, site.fanart, info_labels={"title": row["title"], "mediatype": describe(row["title"])["kind"]})
        site.process_album = mixed_files
    return site


def xvideos_listing_quality(document, base):
    """Read badges within their own card, without requesting individual films."""
    result = {}
    for card in re.split(r'<div\b[^>]*\bclass=[\"\'][^\"\']*\bthumb-block\b[^\"\']*[\"\']', document or "", flags=re.I)[1:]:
        link = re.search(r'<a\b[^>]*href=[\"\']([^\"\']*/video\.[^\"\']+)', card, re.I)
        badge = re.search(r'<span\b[^>]*class=[\"\'][^\"\']*\bvideo-hd-mark\b[^\"\']*[\"\'][^>]*>\s*([^<]{1,30})', card, re.I)
        if link and badge:
            label = html.unescape(badge.group(1)).strip()
            if re.fullmatch(r'(?:\d{3,4}p|[248]K|HD|FHD|UHD)', label, re.I):
                result[urllib.parse.urlsplit(urllib.parse.urljoin(base, html.unescape(link.group(1)))).path] = label
    return result


def virtual_directory(params, addon, loader=None):
    """Opt-in published photo sections for adapters that otherwise select /videos/."""
    value = params.get("url", "")
    if params.get("mode") != "2" or not value.startswith("AH_MEDIA|"): return False
    import xbmcgui
    import xbmcplugin
    name = params.get("website", "")
    url = value[len("AH_MEDIA|"):]
    if not name or name in LIVE_SITES: raise ValueError("Dieser Bereich gehört in das Live-Cam-Menü.")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password: raise ValueError("Ungültige Galerieadresse.")
    site = loader(name) if loader else None
    if site and callable(getattr(site, "_get", None)):
        document = site._get(url, referer=url)
        if not document: raise ValueError("Der Anbieter hat diesen Bildbereich nicht geliefert.")
        parser = extract_media(document, url, name)
    else:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": url})
        with urllib.request.urlopen(request, timeout=16) as response:
            parser = extract_media(response.read(3_000_001).decode("utf-8", "replace"), response.geturl(), name)
    root = "plugin://plugin.video.adulthideout/?"
    for row in parser.media:
        item = xbmcgui.ListItem(label=row["title"])
        item.setArt({"thumb": row["thumb"]}); item.setInfo("video", {"title": row["title"], "mediatype": row["media"]["kind"]})
        item.setProperty("IsPlayable", "true")
        target = row["url"] + "|Referer=" + urllib.parse.quote(url, safe="")
        xbmcplugin.addDirectoryItem(1, root + urllib.parse.urlencode({"mode": "4", "website": name, "url": target}), item, False)
    seen = set()
    for row in parser.links[:200]:
        if row["url"] in seen: continue
        seen.add(row["url"])
        item = xbmcgui.ListItem(label=row["title"] or "Galerie")
        if row.get("thumb"): item.setArt({"thumb": row["thumb"] + "|Referer=" + urllib.parse.quote(url, safe="")})
        item.setProperty("web_media_type", "gallery")
        xbmcplugin.addDirectoryItem(1, root + urllib.parse.urlencode({"mode": "2", "website": name, "url": "AH_MEDIA|" + row["url"]}), item, True)
    if parser.next_url:
        xbmcplugin.addDirectoryItem(1, root + urllib.parse.urlencode({"mode": "2", "website": name, "url": "AH_MEDIA|" + parser.next_url}), xbmcgui.ListItem(label="Next Page"), True)
    xbmcplugin.endOfDirectory(1)
    return True


def photo_section(name, addon):
    if name not in PHOTO_SECTIONS: return None
    try:
        path = os.path.join(addon, "resources", "websites", name + ".py")
        with open(path, encoding="utf-8-sig") as handle: source = handle.read()
        match = re.search(r'base_url\s*=\s*[\"\'](https?://[^\"\']+)', source)
        if not match: return None
        url = urllib.parse.urljoin(match.group(1), PHOTO_SECTIONS[name])
        return {"title": "Bilder & Galerien", "folder": True, "role": "folder", "thumb": "/logos/%s.png" % name,
                "url": "plugin://plugin.video.adulthideout/?" + urllib.parse.urlencode({"mode": "2", "website": name, "url": "AH_MEDIA|" + url}),
                "media": describe(folder=True, declared="gallery", provider=name), "plot": "Den veröffentlichten Bildbereich öffnen"}
    except OSError: return None


class MediaService:
    def __init__(self, runner):
        self.runner = runner; self.tokens = collections.OrderedDict(); self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(12)

    def remember(self, url, headers, media, title):
        token = secrets.token_urlsafe(24)
        with self.lock:
            now = time.monotonic()
            self.tokens = collections.OrderedDict((k, v) for k, v in self.tokens.items() if v["expires"] > now)
            self.tokens[token] = {"url": url, "headers": headers, "media": media, "title": title, "expires": now + 3600}
            while len(self.tokens) > 512: self.tokens.popitem(last=False)
        return token

    def resolve(self, query):
        params = dict(urllib.parse.parse_qsl(str(query).lstrip("?")))
        if params.get("mode") != "4" or params.get("website") in LIVE_SITES:
            return {"ok": False, "error": "Bitte einen Medieneintrag öffnen. Live-Cams findest du im Live-Menü."}
        value = params.get("url", "")
        known = describe(value)
        resolved = {}
        if params.get("website") == "star_finder" and known["kind"] in ("image", "animation"):
            resolved = {"path":value}
        elif known["kind"] != "file" or known["extension"] in EXTENSIONS["file"]:
            # Keep provider-specific Referer/Cookie headers even for direct JPEGs.
            # A legacy module without a picture resolver may still return its
            # published direct file through the common fallback.
            result = self.runner(query, depth=1, priority=True)
            if result.get("busy"): return {"ok": False, "error": "Eine andere Anbieterabfrage läuft. Bitte erneut versuchen."}
            resolved = result.get("resolved") or {"path": value}
        else:
            result = self.runner(query, depth=1, priority=True)
            if result.get("busy"): return {"ok": False, "error": "Eine andere Anbieterabfrage läuft. Bitte erneut versuchen."}
            resolved = result.get("resolved") or {}
            if not resolved.get("path"):
                # A published file page (e.g. Bunkr) may contain an original image
                # even when its legacy play_video method only handles videos.
                raw, _ = split_url(value)
                if raw.startswith(("https://", "http://")):
                    try:
                        with urllib.request.urlopen(urllib.request.Request(raw, headers={"User-Agent": "Mozilla/5.0"}), timeout=15) as response:
                            content_type = response.headers.get("Content-Type", "")
                            if "html" not in content_type:
                                resolved = {"path": response.geturl(), "mime": content_type}
                            else:
                                parser = extract_media(response.read(3_000_001).decode("utf-8", "replace"), response.geturl())
                                if parser.media: resolved = {"path": parser.media[0]["url"] + "|Referer=" + urllib.parse.quote(raw, safe="")}
                    except (OSError, ValueError): pass
        url, headers = split_url(resolved.get("path", ""))
        try: parsed = urllib.parse.urlsplit(url)
        except ValueError: parsed = None
        if not parsed or parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            return {"ok": False, "error": "Der Anbieter hat keine zugängliche Mediendatei geliefert.", "detail": "Eine Anmeldung, eine entfernte Datei oder eine geänderte Anbieterseite kann den Abruf verhindern."}
        if not headers.get("Referer") and resolved.get("referer"): headers["Referer"] = resolved["referer"]
        headers.setdefault("User-Agent", "Mozilla/5.0")
        media = describe(url, resolved.get("mime", ""), provider=params.get("website", ""))
        # Content-Type resolves extensionless image/audio URLs; never sniff a
        # known film merely to open its existing player.
        if media["kind"] == "file" and not media["extension"]:
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={**headers, "Range": "bytes=0-0"}), timeout=12) as response:
                    media = describe(response.geturl(), response.headers.get("Content-Type", ""), provider=params.get("website", ""))
            except (OSError, ValueError): pass
        title = params.get("name") or resolved.get("title") or "Medium"
        token = self.remember(url, headers, media, title)
        return {"ok": True, "media": media, "title": title, "src": "/api/media/file?token=" + token,
                "download": "/api/media/file?token=" + token + "&download=1", "resolved": resolved if media["kind"] == "video" else None}

    def serve(self, handler, query, head=False):
        params = dict(urllib.parse.parse_qsl(query)); token = params.get("token", "")
        with self.lock: row = self.tokens.get(token)
        if not row or row["expires"] < time.monotonic():
            handler._send(410, "Die Medienadresse ist abgelaufen. Bitte den Eintrag erneut öffnen.", "text/plain; charset=utf-8"); return
        if not self.slots.acquire(timeout=1): handler._send(429, "Mehrere Medien werden geladen. Bitte erneut versuchen."); return
        response = None; started = False
        try:
            headers = dict(row["headers"])
            if handler.headers.get("Range"): headers["Range"] = handler.headers["Range"]
            request = urllib.request.Request(row["url"], headers=headers, method="HEAD" if head else "GET")
            response = urllib.request.urlopen(request, timeout=20)
            mime = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
            known = row["media"].get("mime") or "application/octet-stream"
            if not mime or mime == "application/octet-stream": mime = known
            if mime in ("text/html", "application/xhtml+xml"):
                handler._send(502, "Die Quelle lieferte eine Webseite statt der Mediendatei.", "text/plain; charset=utf-8"); return
            handler.send_response(response.status)
            handler.send_header("Content-Type", mime)
            handler.send_header("X-Content-Type-Options", "nosniff")
            if mime == "image/svg+xml": handler.send_header("Content-Security-Policy", "sandbox")
            handler.send_header("Cache-Control", "private, max-age=120")
            handler.send_header("Referrer-Policy", "no-referrer")
            for key in ("Content-Length", "Content-Range", "Accept-Ranges"):
                if response.headers.get(key): handler.send_header(key, response.headers[key])
            if params.get("download") == "1" or row["media"]["kind"] == "file":
                filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", row["title"])[:120]
                ext = row["media"].get("extension")
                if ext and not filename.lower().endswith("." + ext): filename += "." + ext
                handler.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(filename))
            handler._cors(); handler.end_headers(); started = True
            if not head:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk: break
                    handler.wfile.write(chunk)
        except urllib.error.HTTPError as error:
            if not started:
                if error.code == 416 and error.headers.get("Content-Range"):
                    handler.send_response(416); handler.send_header("Content-Range", error.headers["Content-Range"]); handler.send_header("Content-Length", "0"); handler._cors(); handler.end_headers()
                else: handler._send(502, "Die Mediendatei ist beim Anbieter derzeit nicht zugänglich.", "text/plain; charset=utf-8")
            error.close()
        except (OSError, ValueError):
            if not started: handler._send(502, "Die Quelle hat nicht rechtzeitig geantwortet.", "text/plain; charset=utf-8")
        finally:
            if response is not None: response.close()
            self.slots.release()
