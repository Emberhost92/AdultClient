#!/usr/bin/env python
# -*- coding: utf-8 -*-

import html
import re
import urllib.parse

import xbmc
import xbmcgui
import xbmcplugin

from resources.lib.kvs_tube import KVSTubeWebsite
from resources.lib.media_probe import UA, make_session

_BLOCKED = ("teen", "teens", "underage", "preteen", "lolita", "jailbait", "child", "children")
_AGE = re.compile(r"\b(?:1[0-7]|[1-9])\s*(?:yo|y\.o\.?|years?\s*old)\b", re.IGNORECASE)
_PREVIEW = ("trailer", "preview", "teaser", "sample")
_MIN_BYTES = 8000000
_VIDEO = re.compile(r'href="([^"]+)"', re.I)


def _skip(value):
    text = (value or "").replace("_", " ")
    words = re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
    if any(word in _BLOCKED for word in words):
        return True
    return bool(_AGE.search(text))


def _clean(value):
    text = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


class TheHun(KVSTubeWebsite):
    label = "TheHun"
    sort_options = ["Latest"]
    sort_paths = {"Latest": "/"}
    categories_path = None
    models_path = None
    next_page_full_count = 0
    use_playback_proxy = False

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="thehun",
            base_url="https://thehun.net/",
            search_url="https://search.thehun.net/?search={}",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.session = make_session()

    def _headers(self, referer=None, accept=None):
        headers = super()._headers(referer, accept)
        headers["User-Agent"] = UA
        return headers

    def _get(self, url, referer=None, max_retries=None):
        if max_retries is None:
            max_retries = self.request_retries
        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                response = self.session.get(url, headers=self._headers(referer), timeout=20)
                if response.status_code == 200 and response.text:
                    return response.text
                last_error = "HTTP {}".format(response.status_code)
            except Exception as exc:
                last_error = exc
                self.session = make_session()
            if attempt < max_retries:
                xbmc.sleep(650 * attempt)
        self.logger.error("%s failed to fetch listing page: %s", self.label, last_error)
        return ""

    def _same(self, url):
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        return host.endswith("thehun.net")

    def _video_url(self, href, base):
        full = urllib.parse.urljoin(base or self.base_url, html.unescape(href or ""))
        parsed = urllib.parse.urlparse(full)
        host = (parsed.hostname or "").lower()
        path = parsed.path or ""
        if not host.endswith("thehun.net"):
            return ""
        if re.search(r"/video/\d+/", path, re.I):
            return full
        if host.startswith("hosted.") and "/hosted/" in path.lower() and path.lower().endswith(".html"):
            return full
        return ""

    def _page_of(self, url):
        parsed = urllib.parse.urlparse(url or "")
        if "/video/" in (parsed.path or ""):
            return 0
        query = urllib.parse.parse_qs(parsed.query)
        for key in ("page", "p"):
            if query.get(key):
                try:
                    return int(query[key][0])
                except ValueError:
                    return 0
        match = re.search(r"/page/(\d+)/?$", parsed.path or "", re.I)
        if match:
            return int(match.group(1))
        if (parsed.path or "/") in ("", "/"):
            return 1
        return 0

    def _next_url(self, text, current):
        current_page = self._page_of(current) or 1
        found = []
        for href in re.findall(r'href="([^"]+)"', text or "", re.I):
            full = urllib.parse.urljoin(current, html.unescape(href))
            if not self._same(full):
                continue
            number = self._page_of(full)
            if number > current_page:
                found.append((number, full))
        if not found:
            return ""
        found.sort()
        return found[0][1]

    def _measured_size(self, stream_url, referer):
        low = (stream_url or "").lower()
        if not stream_url or any(token in low for token in _PREVIEW):
            return 0
        headers = self._headers(referer, accept="*/*")
        headers["Range"] = "bytes=0-1"
        try:
            response = self.session.get(stream_url, headers=headers, timeout=15, allow_redirects=True, stream=True)
        except Exception:
            return 0
        try:
            if response.status_code not in (200, 206):
                return 0
            ctype = (response.headers.get("Content-Type") or "").lower()
            if "video" not in ctype and "octet-stream" not in ctype:
                return 0
            match = re.search(r"/(\d+)", response.headers.get("Content-Range") or "")
            if match:
                return int(match.group(1))
            length = response.headers.get("Content-Length") or ""
            return int(length) if length.isdigit() and response.status_code == 200 else 0
        finally:
            response.close()

    def _stream(self, text, referer):
        raw = (text or "").replace("\\/", "/")
        ordered = re.findall(r'<source[^>]+src="([^"]+)"', raw, re.I)
        ordered.extend(re.findall(r"https?://[^\"'\s>]+\.mp4[^\"'\s>]*", raw, re.I))
        seen = set()
        best = ""
        best_size = 0
        probed = 0
        for value in ordered:
            stream = urllib.parse.urljoin(referer or self.base_url, html.unescape(value))
            if not stream.startswith("http") or stream in seen:
                continue
            seen.add(stream)
            if _skip(stream) or any(token in stream.lower() for token in _PREVIEW):
                continue
            probed += 1
            size = self._measured_size(stream, referer)
            if size > best_size:
                best, best_size = stream, size
            if size >= _MIN_BYTES or probed >= 4:
                break
        return best if best_size >= _MIN_BYTES else ""

    def _list(self, url, text):
        shown = 0
        seen = set()
        rows = []
        for match in _VIDEO.finditer(text or ""):
            video = self._video_url(match.group(1), url)
            if not video or video in seen or _skip(video):
                continue
            seen.add(video)
            window = (text or "")[max(0, match.start() - 500):match.end() + 400]
            alt = re.search(r'\salt="([^"]*)"', window, re.I)
            title_attr = re.search(r'\stitle="([^"]*)"', match.group(0), re.I)
            title = _clean((alt.group(1) if alt else "") or (title_attr.group(1) if title_attr else "")) or "Video"
            if _skip(title):
                continue
            thumb_match = re.search(r'(?:data-src|src)="([^"]+)"', window, re.I)
            thumb = urllib.parse.urljoin(url, html.unescape(thumb_match.group(1))) if thumb_match else self.icon
            kind = "video" if "/video/" in urllib.parse.urlparse(video).path.lower() else "hosted"
            rows.append((kind, title, video, thumb))
        if any(row[0] == "video" for row in rows):
            rows = [row for row in rows if row[0] == "video"]
        for _kind, title, video, thumb in rows:
            self.add_link(title, video, 4, thumb, self.fanart, info_labels={"title": title}, referer=self.base_url)
            shown += 1
        next_url = self._next_url(text, url)
        if next_url and not _skip(next_url):
            self.add_dir("Next Page", next_url, 2, self.icon, self.fanart)
        if shown == 0 and not next_url:
            self.notify_error("No {} results found".format(self.label))
        self.end_directory("videos")

    def search(self, query):
        cleaned = (query or "").strip()
        if not cleaned or _skip(cleaned):
            self.end_directory("videos")
            return
        self.process_content(self.search_url.format(urllib.parse.quote_plus(cleaned)))

    def process_content(self, url, page=1):
        if not url or url == "BOOTSTRAP":
            url = self.base_url
        if not self._same(url):
            self.end_directory("videos")
            return
        if self._page_of(url) <= 1 and "/video/" not in urllib.parse.urlparse(url).path:
            self.add_dir("Search", "", 5, self.icons.get("search", self.icon), self.fanart)
        text = self._get(url, referer=self.base_url)
        self._list(url, text)

    def play_video(self, url):
        if _skip(url) or not self._same(url):
            self.notify_error("Could not resolve stream URL")
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return
        stream = self._stream(self._get(url, referer=self.base_url), url)
        if not stream:
            self.notify_error("Could not resolve stream URL")
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return
        headers = self._headers(url, accept="*/*")
        play_url = "{}|{}".format(stream, urllib.parse.urlencode(headers))
        item = xbmcgui.ListItem(path=play_url)
        item.setProperty("IsPlayable", "true")
        item.setMimeType("video/mp4")
        item.setContentLookup(False)
        xbmcplugin.setResolvedUrl(self.addon_handle, True, item)
