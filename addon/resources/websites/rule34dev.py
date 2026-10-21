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
_MIN_BYTES = 8000000
_POST = re.compile(r'href="(/(?:r34|gel)/\d+/[^"#?]*)"', re.I)
_MEDIA = re.compile(r"https?://[^\"'\s>]+\.(?:mp4|png|jpe?g|webp)(?:\?[^\"'\s>]*)?", re.I)


def _skip(value):
    text = (value or "").replace("_", " ")
    words = re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
    if any(word in _BLOCKED for word in words):
        return True
    return bool(_AGE.search(text))


def _clean(value):
    text = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


class Rule34dev(KVSTubeWebsite):
    label = "Rule34.dev"
    sort_options = ["Latest"]
    sort_paths = {"Latest": "/"}
    categories_path = None
    models_path = None
    next_page_full_count = 0
    use_playback_proxy = False

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="rule34dev",
            base_url="https://rule34.dev/",
            search_url="https://rule34.dev/?q={}",
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
        return host.endswith("rule34.dev")

    def _is_post(self, url):
        return bool(re.search(r"/(?:r34|gel)/\d+", urllib.parse.urlparse(url or "").path or "", re.I))

    def _junk(self, url):
        low = (url or "").lower()
        return any(part in low for part in ("logo", "icon", "sprite", "avatar", "emoji", "thumb", "preview", "/small/"))

    def _measure(self, url, referer):
        headers = self._headers(referer, accept="*/*")
        headers["Range"] = "bytes=0-1"
        try:
            response = self.session.get(url, headers=headers, timeout=14, stream=True, allow_redirects=True)
        except Exception:
            return 0, "", 0
        try:
            status = response.status_code
            ctype = (response.headers.get("Content-Type") or "").split(";")[0].lower()
            total = 0
            match = re.search(r"/(\d+)", response.headers.get("Content-Range") or "")
            if match:
                total = int(match.group(1))
            elif status == 200:
                try:
                    total = int(response.headers.get("Content-Length") or 0)
                except ValueError:
                    total = 0
            return status, ctype, total
        finally:
            response.close()

    def _list_posts(self, url, text):
        shown = 0
        seen = set()
        for match in _POST.finditer(text or ""):
            post = urllib.parse.urljoin(url, html.unescape(match.group(1)))
            if post in seen or _skip(post) or not self._same(post):
                continue
            seen.add(post)
            window = (text or "")[max(0, match.start() - 400):match.end() + 500]
            if _skip(window):
                continue
            alt = re.search(r'\salt="([^"]*)"', window, re.I)
            title = _clean(alt.group(1) if alt else "") or "Post"
            if _skip(title):
                continue
            thumb_match = re.search(r'(?:data-src|src)="(https?://[^"]+)"', window, re.I)
            thumb = html.unescape(thumb_match.group(1)) if thumb_match else self.icon
            self.add_dir(title, post, 2, thumb, self.fanart)
            shown += 1
        if shown == 0:
            self.notify_error("No {} results found".format(self.label))
        self.end_directory("videos")

    def _list_media(self, url, text):
        if _skip(url):
            self.end_directory("videos")
            return
        shown = 0
        seen = set()
        raw = (text or "").replace("\\/", "/")
        for match in _MEDIA.finditer(raw):
            media = html.unescape(match.group(0))
            if media in seen or self._junk(media) or _skip(media):
                continue
            seen.add(media)
            if len(seen) > 12:
                break
            status, ctype, total = self._measure(media, url)
            image = ctype.startswith("image/")
            video = ctype.startswith("video/") or (ctype == "application/octet-stream" and ".mp4" in media.lower())
            if status not in (200, 206):
                continue
            if image and total and total < _MIN_PHOTO:
                continue
            if video and total and total < _MIN_BYTES:
                continue
            if not image and not video:
                continue
            shown += 1
            label = "Video {}".format(shown) if video else "Image {}".format(shown)
            self.add_link(label, media, 4, media, self.fanart, info_labels={"title": label}, referer=url)
        if shown == 0:
            self.notify_error("No {} media found".format(self.label))
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
        text = self._get(url, referer=self.base_url)
        if self._is_post(url):
            self._list_media(url, text)
            return
        parsed = urllib.parse.urlparse(url)
        if (parsed.path or "/") in ("", "/") and not parsed.query:
            self.add_dir("Search", "", 5, self.icons.get("search", self.icon), self.fanart)
        self._list_posts(url, text)

    def play_video(self, url):
        media = html.unescape(url or "").replace("\\/", "/")
        if _skip(media) or self._junk(media):
            self.notify_error("Could not resolve stream URL")
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return
        status, ctype, total = self._measure(media, self.base_url)
        image = ctype.startswith("image/")
        video = ctype.startswith("video/") or ctype == "application/octet-stream"
        ok_image = image and status in (200, 206) and (not total or total >= _MIN_PHOTO)
        ok_video = video and status in (200, 206) and (not total or total >= _MIN_BYTES)
        if not ok_image and not ok_video:
            self.notify_error("Could not resolve stream URL")
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return
        headers = self._headers(self.base_url, accept="*/*")
        play_url = "{}|{}".format(media, urllib.parse.urlencode(headers))
        item = xbmcgui.ListItem(path=play_url)
        item.setProperty("IsPlayable", "true")
        if video:
            mime = "video/mp4"
        elif "png" in ctype or ".png" in media.lower():
            mime = "image/png"
        elif "webp" in ctype or ".webp" in media.lower():
            mime = "image/webp"
        else:
            mime = "image/jpeg"
        item.setMimeType(mime)
        item.setContentLookup(False)
        xbmcplugin.setResolvedUrl(self.addon_handle, True, item)
