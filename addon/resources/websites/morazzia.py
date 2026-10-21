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
_GO = re.compile(r'href="(/go/\d+[^"]*)"', re.I)
_POST = re.compile(r'<a\b[^>]*\bitem-post\b[^>]*>', re.I)


def _skip(value):
    text = (value or "").replace("_", " ")
    words = re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
    if any(word in _BLOCKED for word in words):
        return True
    return bool(_AGE.search(text))


def _clean(value):
    text = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


class Morazzia(KVSTubeWebsite):
    label = "Morazzia"
    sort_options = ["Latest"]
    sort_paths = {"Latest": "/"}
    categories_path = None
    models_path = None
    next_page_full_count = 0
    use_playback_proxy = False

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="morazzia",
            base_url="https://www.morazzia.com/",
            search_url="https://www.morazzia.com/search/{}",
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

    def _listing_host(self, url):
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        return host.endswith("morazzia.com")

    def _gallery(self, url):
        path = urllib.parse.urlparse(url or "").path.lower()
        return "/go/" in path or "babesandgirls.com" in (urllib.parse.urlparse(url).hostname or "")

    def _full_image(self, url):
        parts = urllib.parse.urlsplit(url)
        path = parts.path.replace("/tn/", "/")
        path = re.sub(r"/tn_(\d+)(\.[a-z0-9]+)$", r"/\1\2", path, flags=re.I)
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))

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

    def _list_sets(self, url, text):
        shown = 0
        seen = set()
        for match in _POST.finditer(text or ""):
            href_match = re.search(r'href="([^"]+)"', match.group(0), re.I)
            if not href_match:
                continue
            target = urllib.parse.urljoin(url, html.unescape(href_match.group(1)))
            parsed = urllib.parse.urlparse(target)
            host = (parsed.hostname or "").lower()
            path = (parsed.path or "").lower()
            if not host.endswith("morazzia.com") or target in seen or _skip(target):
                continue
            if "/go/" in path or path.startswith("/search") or any(
                part in path for part in ("/categor", "/model", "/page", "/tag", "/blog")
            ):
                continue
            seen.add(target)
            window = (text or "")[match.start():match.end() + 500]
            alt = re.search(r'\salt="([^"]*)"', window, re.I)
            title = _clean(alt.group(1) if alt else "") or "Set"
            if _skip(title):
                continue
            thumb_match = re.search(r'(?:data-src|src)="([^"]+)"', window, re.I)
            thumb = urllib.parse.urljoin(url, html.unescape(thumb_match.group(1))) if thumb_match else self.icon
            shown += 1
            self.add_dir(title, target, 2, thumb, self.fanart)
        if shown == 0:
            self.notify_error("No {} results found".format(self.label))
        self.end_directory("videos")

    def _list_galleries(self, url, text):
        shown = 0
        seen = set()
        for match in _GO.finditer(text or ""):
            gallery = urllib.parse.urljoin(url, html.unescape(match.group(1)))
            if gallery in seen or _skip(gallery):
                continue
            seen.add(gallery)
            window = (text or "")[max(0, match.start() - 700):match.end() + 200]
            alt = re.search(r'\salt="([^"]*)"', window, re.I)
            title = _clean(alt.group(1) if alt else "") or "Gallery"
            if _skip(title):
                continue
            thumb_match = re.search(r'(?:data-src|src)="([^"]+)"', window, re.I)
            thumb = urllib.parse.urljoin(url, html.unescape(thumb_match.group(1))) if thumb_match else self.icon
            self.add_dir(title, gallery, 2, thumb, self.fanart)
            shown += 1
        if shown == 0:
            self.notify_error("No {} results found".format(self.label))
        self.end_directory("videos")

    def _list_images(self, url, text):
        if _skip(url):
            self.end_directory("videos")
            return
        shown = 0
        seen = set()
        raw = (text or "").replace("\\/", "/")
        sources = re.findall(r'(?:src|href)="([^"]+\.(?:jpe?g|png|webp)[^"]*)"', raw, re.I)
        for source in sources:
            image = urllib.parse.urljoin(url, html.unescape(source))
            low = image.lower()
            if any(part in low for part in ("logo", "icon", "sprite", "avatar", "emoji", "blank")):
                continue
            image = self._full_image(image)
            if image in seen or _skip(image):
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
            url = self.base_url
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
        if host and not (host.endswith("morazzia.com") or host.endswith("babesandgirls.com")):
            self.end_directory("videos")
            return
        text = self._get(url, referer=self.base_url)
        if self._gallery(url) or "babesandgirls.com" in (urllib.parse.urlparse(getattr(self, "_last", "") or "").hostname or ""):
            self._list_images(url, text)
            return
        if "/go/" in (parsed.path or "") or (text and "entry__cover" in text and "babesandgirls" in text):
            self._list_images(url, text)
            return
        if (parsed.path or "").lower().startswith("/search"):
            self._list_sets(url, text)
            return
        if (parsed.path or "/") in ("", "/"):
            self.add_dir("Search", "", 5, self.icons.get("search", self.icon), self.fanart)
        self._list_galleries(url, text)

    def play_video(self, url):
        image = html.unescape(url or "").replace("\\/", "/")
        if not re.search(r"\.(?:jpe?g|png|webp)(?:$|\?)", image.lower()) or _skip(image):
            self.notify_error("Could not resolve stream URL")
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return
        referer = "https://www.babesandgirls.com/"
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
