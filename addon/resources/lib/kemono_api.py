# -*- coding: utf-8 -*-
"""Shared engine for Coomer / Kemono style archives.

Open JSON API under /api/v1, media served as plain files from /data/.
No downloader, no login, no browser automation.

Mirrors are walked in order because availability differs by country.
"""

import html
import os
import re
import time
import urllib.parse

import requests
import xbmc
import xbmcgui
import xbmcplugin

from resources.lib.base_website import BaseWebsite

PAGE_SIZE = 50
LATEST = "AH_LATEST"
SEARCH_MARKER = "AH_SEARCH|"
VIDEO_EXTENSIONS = (".mp4", ".webm", ".mkv", ".mov", ".m4v")
LIST_KEYS = ("posts", "items", "results", "data", "entries")

# True -> "url|headers" an den Player geben (Kodi-Format)
# False -> nackte URL, der Web-Player proxyt selbst
STREAM_WITH_HEADERS = False
# (site, kind) -> (monotonic time, host, path prefix). Empty host means the probe failed.
_MEDIA_HOST_CACHE = {}
_MEDIA_PROBE_TTL = 600


class KemonoApiWebsite(BaseWebsite):
    name = ""
    label = ""
    host = ""
    api_base = ""
    api_mirrors = ()
    default_service = "onlyfans"
    request_retries = 2
    cache_version = "2"
    # Hosts that return file bytes. The API host is not one of them.
    media_mirrors = ()

    # ---------- trace ----------

    def _trace(self, *parts):
        try:
            path = os.path.join(os.environ.get("TEMP", "."), "ah_trace.txt")
            with open(path, "a", encoding="utf-8") as handle:
                handle.write("[{}] {}\n".format(self.name, " | ".join(str(p) for p in parts)))
        except Exception:
            pass

    # ---------- init ----------

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name=self.name,
            base_url=self.host + "/",
            search_url=self.api_base + "/posts?q={}",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        )
        self.session = requests.Session()
        self.active_api = self.api_base
        self.active_host = self.host
        self._mirror_order = [self.api_base] + [m for m in self.api_mirrors if m]
        logo = os.path.join(
            self.addon.getAddonInfo("path"), "resources", "logos", self.name + ".png"
        )
        if os.path.exists(logo):
            self.icon = logo
        self.icons["default"] = self.icon
        self._trace("init ok", self.api_base)

    # ---------- helpers ----------

    def _headers(self, referer=None, accept="application/json"):
        return {
            "User-Agent": self.ua,
            "Referer": referer or (self.active_host + "/"),
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _stream_headers(self):
        return {"User-Agent": self.ua, "Referer": self.active_host + "/"}

    def _absolute(self, value):
        if not value:
            return ""
        return urllib.parse.urljoin(self.active_host + "/", html.unescape(value).strip())

    def _clean(self, value):
        value = re.sub(r"<[^>]+>", " ", value or "")
        return re.sub(r"\s+", " ", html.unescape(value)).strip()

    def _as_posts(self, payload, where=""):
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in LIST_KEYS:
                value = payload.get(key)
                if isinstance(value, list):
                    self._trace("payload wrapped in dict ->", key, len(value), where)
                    return value
            self._trace("dict payload, no list key. keys:", list(payload.keys())[:12], where)
        return None

    def _get_json(self, url):
        response = self.session.get(url, headers=self._headers(), timeout=25)
        if response.status_code == 200:
            return response.json()
        self._trace("HTTP", response.status_code, url)
        return None

    def _api(self, path, params=None):
        suffix = path
        if params:
            suffix += "?" + urllib.parse.urlencode(params)

        ordered = [self.active_api] + [m for m in self._mirror_order if m != self.active_api]
        self._trace("api call", suffix)

        for base in ordered:
            for attempt in range(1, self.request_retries + 1):
                try:
                    payload = self._get_json(base + suffix)
                    if payload is not None:
                        if base != self.active_api:
                            self.active_api = base
                            self.active_host = base.split("/api/")[0]
                            self._trace("mirror switched to", base)
                        self._trace("api ok", suffix, "type:", type(payload).__name__)
                        return payload
                    break
                except Exception as exc:
                    self._trace("api exception", base, type(exc).__name__, str(exc)[:90])
                    self.session = requests.Session()
                if attempt < self.request_retries:
                    xbmc.sleep(500 * attempt)

        self._trace("api FAILED all mirrors", suffix)
        return None

    def _get_html(self, url, referer=None):
        try:
            response = self.session.get(
                url, headers=self._headers(referer, accept="text/html,*/*"), timeout=20
            )
            return response.text if response.status_code == 200 else ""
        except Exception as exc:
            self._trace("html exception", type(exc).__name__)
            return ""

    def _media_kind(self, path):
        probe = str(path or "").lower().split("?", 1)[0]
        if probe.endswith(VIDEO_EXTENSIONS) or "/videos/" in probe:
            return "video"
        return "image"

    def _image_mirror(self):
        parsed = urllib.parse.urlparse(self.host or "")
        if not parsed.hostname:
            return ""
        return "{}://img.{}".format(parsed.scheme or "https", parsed.hostname)

    def _probe_one(self, host, prefix, path):
        url = urllib.parse.urljoin(host.rstrip("/") + "/", prefix + str(path).lstrip("/"))
        try:
            response = self.session.get(
                url,
                headers=dict(self._headers(accept="*/*"), **{"Range": "bytes=0-63"}),
                timeout=(3, 6),
                stream=True,
                allow_redirects=False,
            )
            try:
                chunk = next(response.iter_content(64), b"")
                ctype = (response.headers.get("Content-Type") or "").split(";")[0].lower()
                ok = response.status_code in (200, 206) and bool(chunk) and not ctype.startswith("text/")
                self._trace("media probe", host, response.status_code, "ok" if ok else "no")
                return ok
            finally:
                response.close()
        except Exception as exc:
            self._trace("media probe fail", host, type(exc).__name__)
            self.session = requests.Session()
            return False

    def _probe_media(self, path):
        """Return (host, prefix) for a mirror that served real bytes, or ("", "")."""
        kind = self._media_kind(path)
        key = (self.name, kind)
        found = _MEDIA_HOST_CACHE.get(key)
        now = time.monotonic()
        if found and now - found[0] < _MEDIA_PROBE_TTL:
            return found[1], found[2]
        candidates = []
        if kind == "image":
            image_host = self._image_mirror()
            if image_host:
                candidates.append((image_host, "/thumbnail/data/"))
        for mirror in self.media_mirrors or ():
            host = str(mirror or "").rstrip("/")
            if host:
                candidates.append((host, "/data/"))
        winner = ("", "")
        for host, prefix in candidates:
            if self._probe_one(host, prefix, path):
                winner = (host, prefix)
                break
        _MEDIA_HOST_CACHE[key] = (now, winner[0], winner[1])
        return winner

    def _media_url(self, path):
        if not path:
            return ""
        kind = self._media_kind(path)
        if kind == "image" or self.media_mirrors:
            host, prefix = self._probe_media(path)
            if host and prefix:
                traced = getattr(self, "_media_host_traced", None)
                if traced is None:
                    traced = set()
                    self._media_host_traced = traced
                if kind not in traced:
                    traced.add(kind)
                    self._trace("media host", kind, host)
                return urllib.parse.urljoin(host + "/", prefix + str(path).lstrip("/"))
        if kind == "video" and not getattr(self, "_video_fallback_traced", False):
            self._video_fallback_traced = True
            self._trace("media video fallback", self.active_host)
        return urllib.parse.urljoin(self.active_host + "/", "/data/" + str(path).lstrip("/"))

    def _creator_url(self, service, user_id):
        return "{}/{}/user/{}".format(self.active_host, service or self.default_service, user_id)

    def _post_creator(self, post):
        return str(post.get("user") or post.get("username") or "unknown")

    # ---------- mapping ----------

    def _post_items(self, post):
        if not isinstance(post, dict):
            return []
        creator = self._post_creator(post)
        service = post.get("service") or self.default_service
        display = str(post.get("username") or creator)
        title = self._clean(post.get("title") or "")
        content = self._clean(re.sub(r"<[^>]+>", " ", post.get("content") or ""))
        published = str(post.get("published") or post.get("added") or "")
        date_label = published[:10]
        fallback = title or content[:70] or "{} {}".format(display, date_label)

        candidates = []
        main_file = post.get("file") or {}
        if isinstance(main_file, dict) and main_file.get("path"):
            candidates.append((main_file.get("name") or fallback, main_file.get("path")))
        for attachment in post.get("attachments") or []:
            if isinstance(attachment, dict) and attachment.get("path"):
                candidates.append((attachment.get("name") or fallback, attachment.get("path")))
        if not candidates:
            return []

        # Thumbnail: erstes Bild im Post, sonst preview, sonst Logo
        thumb = ""
        for name, path in candidates:
            probe = (str(name) + str(path)).lower()
            if not (probe.endswith(VIDEO_EXTENSIONS) or "/videos/" in probe):
                thumb = self._media_url(path)
                break
        if not thumb:
            preview = post.get("preview")
            if isinstance(preview, str) and preview:
                thumb = self._media_url(preview)
        thumb = thumb or self.icon

        items = []
        total = len(candidates)
        for index, (name, path) in enumerate(candidates, 1):
            stream = self._media_url(path)
            if not stream:
                continue
            probe = (str(name) + str(path)).lower()
            is_video = probe.endswith(VIDEO_EXTENSIONS) or "/videos/" in probe
            label = fallback if total == 1 else "{} ({}/{})".format(fallback, index, total)
            info = {
                "title": label,
                "plot": content or name,
                "artist": display,
                "mediatype": "video" if is_video else "image",
            }
            if date_label:
                info["date"] = date_label.replace("-", ".")
            items.append((label, stream, is_video, info, creator, service, thumb))
        items.sort(key=lambda entry: not entry[2])
        return items

    def _add_items(self, entries):
        added = 0
        for label, stream, _is_video, info, creator, service, thumb in entries:
            self.add_link(
                label, stream, 4, thumb or self.icon, self.fanart,
                info_labels=info,
                uploader_name=creator,
                uploader_url=self._creator_url(service, creator),
            )
            added += 1
        self._trace("add_link count", added)
        return added

    def _render(self, entries, url, page):
        added = self._add_items(entries)
        if not added:
            self.notify_error("No {} results".format(self.label or self.name))
        elif url:
            self.add_dir("Next Page", url, 2, self.icons.get("default", self.icon), page=page + 1)
        self._trace("end_directory videos, added:", added)
        self.end_directory("videos")

    def _flatten(self, posts):
        entries = []
        for post in posts or []:
            entries.extend(self._post_items(post))
        self._trace("flatten posts:", len(posts or []), "-> entries:", len(entries))
        return entries

    # ---------- navigation ----------

    def get_start_url_and_label(self):
        return LATEST, "{} [COLOR yellow]Latest[/COLOR]".format(self.label or self.name)

    def _search_page_url(self, query, page):
        return "{}{}|{}".format(SEARCH_MARKER, urllib.parse.quote_plus(query), page)

    def _list_latest(self, page):
        self._trace("list_latest", page)
        self.add_dir("Search", "", 5, self.icons.get("search", self.icon))
        payload = self._api("/posts", {"o": max(0, page - 1) * PAGE_SIZE})
        posts = self._as_posts(payload, "latest")
        if posts is None:
            self.notify_error("{} API unreachable".format(self.label or self.name))
            return self.end_directory("videos")
        next_url = LATEST if len(posts) >= PAGE_SIZE else None
        self._render(self._flatten(posts), next_url, page)

    def _list_search(self, query, stored_page):
        payload = self._api("/posts", {"q": query, "o": max(0, int(stored_page) - 1) * PAGE_SIZE})
        posts = self._as_posts(payload, "search")
        if posts is None:
            self.notify_error("{} search failed".format(self.label or self.name))
            return self.end_directory("videos")
        next_url = (
            self._search_page_url(query, int(stored_page) + 1)
            if len(posts) >= PAGE_SIZE else None
        )
        self._render(self._flatten(posts), next_url, 1)

    def process_content(self, url, page=1):
        self._trace(">>> process_content", url, page)
        try:
            self._process_content(url, page)
        except Exception as exc:
            self._trace("!!! EXCEPTION", type(exc).__name__, str(exc)[:200])
            raise

    def _process_content(self, url, page=1):
        if not url or url == "BOOTSTRAP":
            url, _ = self.get_start_url_and_label()

        if url == LATEST:
            return self._list_latest(page)

        if url.startswith(SEARCH_MARKER):
            body = url[len(SEARCH_MARKER):]
            encoded, _, stored_page = body.rpartition("|")
            return self._list_search(urllib.parse.unquote_plus(encoded), stored_page or "1")

        path = urllib.parse.urlparse(url).path.rstrip("/")

        if path in ("", "/"):
            return self._list_latest(page)

        single = re.match(r"^/([a-z0-9_]+)/user/([^/]+)/post/([^/]+)$", path, re.IGNORECASE)
        if single:
            service, user_id, post_id = single.groups()
            payload = self._api("/{}/user/{}/post/{}".format(
                service, urllib.parse.quote(user_id), urllib.parse.quote(post_id)))
            if isinstance(payload, dict) and payload.get("post") and not payload.get("path"):
                payload = payload["post"]
            if not isinstance(payload, dict):
                self.notify_error("{} post unavailable".format(self.label or self.name))
                return self.end_directory("videos")
            return self._render(self._post_items(payload), None, 1)

        creator = re.match(r"^/([a-z0-9_]+)/user/([^/]+)$", path, re.IGNORECASE)
        if creator:
            service, user_id = creator.groups()
            payload = self._api(
                "/{}/user/{}/posts".format(service, urllib.parse.quote(user_id)),
                {"o": max(0, page - 1) * PAGE_SIZE},
            )
            posts = self._as_posts(payload, "creator")
            if posts is None:
                self.notify_error("{} creator unavailable".format(self.label or self.name))
                return self.end_directory("videos")
            next_url = url if len(posts) >= PAGE_SIZE else None
            return self._render(self._flatten(posts), next_url, page)

        return self._list_latest(page)

    def search(self, query):
        self._trace(">>> search", query)
        if not query or not query.strip():
            return self.end_directory("videos")
        self.process_content(self._search_page_url(query.strip(), 1))

    # ---------- playback ----------

    def resolve_recording_stream(self, url):
        if not url:
            return None
        extension = url.rsplit(".", 1)[-1].lower()
        return {"url": url, "headers": self._stream_headers(), "extension": extension}

    def play_video(self, url):
        self._trace(">>> play_video", url)
        if not url:
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return
        play_url = url
        if STREAM_WITH_HEADERS:
            play_url = "{}|{}".format(url, urllib.parse.urlencode(self._stream_headers()))
        item = xbmcgui.ListItem(path=play_url)
        item.setProperty("IsPlayable", "true")
        extension = url.rsplit(".", 1)[-1].lower()
        item.setMimeType("video/mp4" if extension in ("mp4", "m4v", "mov") else "video/webm")
        item.setContentLookup(False)
        self._trace("setResolvedUrl", play_url[:120])
        xbmcplugin.setResolvedUrl(self.addon_handle, True, item)