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
_MIN_PHOTO = 30000
_ALBUM = re.compile(
    r'href="(?:https?://(?:www\.)?luscious\.net)?(/albums/[^"#?]+)"',
    re.I,
)
_IMAGE = re.compile(r"https?://ah-img\.luscious\.net[^\"'\s>]+\.(?:jpe?g|png|webp)", re.I)


def _skip(value):
    text = (value or "").replace("_", " ")
    words = re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
    if any(word in _BLOCKED for word in words):
        return True
    return bool(_AGE.search(text))


def _clean(value):
    text = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


class Luscious(KVSTubeWebsite):
    label = "Luscious"
    sort_options = ["Latest"]
    sort_paths = {"Latest": "/albums/list/"}
    categories_path = None
    models_path = None
    next_page_full_count = 0
    use_playback_proxy = False

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="luscious",
            base_url="https://www.luscious.net/",
            search_url="https://www.luscious.net/albums/search/?q={}",
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
        return host.endswith("luscious.net")

    def _is_album(self, url):
        path = urllib.parse.urlparse(url or "").path.lower().rstrip("/")
        if path in ("/albums", "/albums/list", "/albums/search"):
            return False
        return path.startswith("/albums/")

    def _page_of(self, url):
        parsed = urllib.parse.urlparse(url or "")
        query = urllib.parse.parse_qs(parsed.query)
        if query.get("page"):
            try:
                return int(query["page"][0])
            except ValueError:
                return 0
        path = (parsed.path or "/").rstrip("/")
        if path in ("", "/albums/list", "/albums/search"):
            return 1
        return 0

    def _photo_size(self, url, referer):
        try:
            headers = self._headers(referer, accept="image/*,*/*")
            headers["Range"] = "bytes=0-1"
            response = self.session.get(
                url,
                headers=headers,
                timeout=14,
                stream=True,
                allow_redirects=True,
            )
            total = 0
            match = re.search(r"/(\d+)", response.headers.get("Content-Range") or "")
            if match:
                total = int(match.group(1))
            elif response.status_code == 200:
                try:
                    total = int(response.headers.get("Content-Length") or 0)
                except ValueError:
                    total = 0
            ctype = (response.headers.get("Content-Type") or "").split(";")[0].lower()
            status = response.status_code
            response.close()
            return status, ctype, total
        except Exception:
            return 0, "", 0

    def _list_albums(self, url, text):
        shown = 0
        seen = set()
        for match in _ALBUM.finditer(text or ""):
            album = urllib.parse.urljoin(url, html.unescape(match.group(1)))
            path = urllib.parse.urlparse(album).path.lower().rstrip("/")
            if path in ("/albums", "/albums/list", "/albums/search") or album in seen or _skip(album):
                continue
            seen.add(album)
            window = (text or "")[max(0, match.start() - 600):match.end() + 300]
            alt = re.search(r'\salt="([^"]*)"', window, re.I)
            title = _clean(alt.group(1) if alt else "") or "Album"
            if _skip(title):
                continue
            thumb_match = re.search(r'(?:data-src|src)="(https?://[^"]+)"', window, re.I)
            thumb = html.unescape(thumb_match.group(1)) if thumb_match else self.icon
            self.add_dir(title, album, 2, thumb, self.fanart)
            shown += 1
        current_page = self._page_of(url) or 1
        found = []
        for href in re.findall(r'href="([^"]+)"', text or "", re.I):
            full = urllib.parse.urljoin(url, html.unescape(href))
            if not self._same(full):
                continue
            if urllib.parse.urlparse(full).path.rstrip("/").lower() != urllib.parse.urlparse(url).path.rstrip("/").lower():
                continue
            number = self._page_of(full)
            if number > current_page:
                found.append((number, full))
        next_url = ""
        if found:
            found.sort()
            next_url = found[0][1]
        if next_url and not _skip(next_url):
            self.add_dir("Next Page", next_url, 2, self.icon, self.fanart)
        if shown == 0 and not next_url:
            self.notify_error("No {} results found".format(self.label))
        self.end_directory("videos")

    def _list_images(self, url, text):
        if _skip(url):
            self.end_directory("videos")
            return
        shown = 0
        seen = set()
        raw = (text or "").replace("\\/", "/")
        for match in _IMAGE.finditer(raw):
            image = html.unescape(match.group(0))
            low = image.lower()
            if image in seen or _skip(image):
                continue
            if any(part in low for part in ("logo", "icon", "sprite", "avatar", "emoji", "thumb", "/small/")):
                continue
            seen.add(image)
            shown += 1
            self.add_link(
                "Image {}".format(shown),
                image,
                4,
                image,
                self.fanart,
                info_labels={"title": "Image {}".format(shown)},
                referer=url,
            )
        if shown == 0:
            self.notify_error("No {} images found".format(self.label))
        self.end_directory("videos")

    def search(self, query):
        cleaned = (query or "").strip()
        if not cleaned or _skip(cleaned):
            self.end_directory("videos")
            return
        self.process_content(self.search_url.format(urllib.parse.quote_plus(cleaned)))

    def process_content(self, url, page=1):
        if not url or url == "BOOTSTRAP":
            url = urllib.parse.urljoin(self.base_url, "/albums/list/")
        if not self._same(url):
            self.end_directory("videos")
            return
        parsed = urllib.parse.urlparse(url)
        if (parsed.path or "/") in ("", "/"):
            url = urllib.parse.urljoin(self.base_url, "/albums/list/")
            parsed = urllib.parse.urlparse(url)
        text = self._get(url, referer=self.base_url)
        if self._is_album(url):
            self._list_images(url, text)
            return
        path = (parsed.path or "/").lower().rstrip("/")
        if path in ("/albums/list", "") and not parsed.query:
            self.add_dir("Search", "", 5, self.icons.get("search", self.icon), self.fanart)
        self._list_albums(url, text)

    def play_video(self, url):
        image = html.unescape(url or "").replace("\\/", "/")
        if not re.search(r"\.(?:jpe?g|png|webp)(?:$|\?)", image.lower()) or _skip(image):
            self.notify_error("Could not resolve stream URL")
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return
        referer = self.base_url
        status, ctype, total = self._photo_size(image, referer)
        if status not in (200, 206) or not ctype.startswith("image/") or (total and total < _MIN_PHOTO):
            self.notify_error("Could not resolve stream URL")
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return
        headers = self._headers(referer, accept="image/*,*/*")
        play_url = "{}|{}".format(image, urllib.parse.urlencode(headers))
        item = xbmcgui.ListItem(path=play_url)
        item.setProperty("IsPlayable", "true")
        if "webp" in ctype or ".webp" in image.lower():
            mime = "image/webp"
        elif "png" in ctype or ".png" in image.lower():
            mime = "image/png"
        else:
            mime = "image/jpeg"
        item.setMimeType(mime)
        item.setContentLookup(False)
        xbmcplugin.setResolvedUrl(self.addon_handle, True, item)
