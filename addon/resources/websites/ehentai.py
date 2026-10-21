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
_GALLERY = re.compile(
    r'<a href="(https://e-hentai\.org/g/\d+/[0-9a-f]+/)"[^>]*>\s*<div class="glink">(.*?)</div>',
    re.I | re.S,
)
_PAGE = re.compile(r'href="(https://e-hentai\.org/s/[0-9a-f]+/\d+-\d+)"', re.I)
_MIN_PHOTO = 30000


def _clean(value):
    text = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _skip(value):
    text = (value or "").replace("_", " ")
    words = re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
    if any(word in _BLOCKED for word in words):
        return True
    return bool(_AGE.search(text))


class Ehentai(KVSTubeWebsite):
    label = "E-Hentai"
    sort_options = ["Latest"]
    sort_paths = {"Latest": "/"}
    categories_path = None
    models_path = None
    next_page_full_count = 0
    use_playback_proxy = False

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="ehentai",
            base_url="https://e-hentai.org/",
            search_url="https://e-hentai.org/?f_search={}",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.session = make_session()

    def _headers(self, referer=None, accept=None):
        headers = super()._headers(referer, accept)
        headers["User-Agent"] = UA
        for key, value in list(headers.items()):
            if not isinstance(value, str):
                continue
            try:
                value.encode("latin-1")
            except UnicodeEncodeError:
                headers[key] = urllib.parse.quote(value, safe=":/%?#[]@!$&'()*+,;=")
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
        self.logger.error("%s failed to fetch listing page: %s", self.label or self.name, last_error)
        return ""

    def _blocked_book(self, text):
        chunks = []
        for match in re.finditer(r'id="g[nj]"[^>]*>(.*?)</h1>', text or "", re.I | re.S):
            chunks.append(_clean(match.group(1)))
        for tag in re.findall(r'/tag/([^"\'?#]+)', text or "", re.I):
            chunks.append(urllib.parse.unquote(tag))
        return any(_skip(chunk) for chunk in chunks if chunk)

    def _thumb_before(self, text, start):
        window = text[max(0, start - 900):start]
        images = re.findall(r'src="(https?://[^"]+)"', window, re.I)
        return images[-1] if images else self.icon

    def _list_galleries(self, url, text):
        shown = 0
        seen = set()
        for match in _GALLERY.finditer(text or ""):
            gallery = match.group(1)
            if gallery in seen:
                continue
            seen.add(gallery)
            title = _clean(match.group(2)) or "Gallery"
            tail = text[match.end():match.end() + 1800]
            tags = [urllib.parse.unquote(tag) for tag in re.findall(r"/tag/([^\"'#]+)", tail, re.I)]
            nearby = _clean(re.sub(r"\s+", " ", text[max(0, match.start() - 400):match.start()]))
            if _skip(title) or _skip(gallery) or _skip(nearby) or any(_skip(tag) for tag in tags):
                continue
            self.add_dir(title, gallery, 2, self._thumb_before(text, match.start()), self.fanart)
            shown += 1
        next_url = ""
        next_match = re.search(r'id="unext" href="([^"]+)"', text or "", re.I)
        if next_match:
            next_url = urllib.parse.urljoin(url, html.unescape(next_match.group(1)))
        if next_url and next_url != url:
            self.add_dir("Next Page", next_url, 2, self.icon, self.fanart)
        if shown == 0 and not next_url:
            self.notify_error("No {} results found".format(self.label or self.name))
        self.end_directory("videos")

    def _list_pages(self, url, text):
        if self._blocked_book(text):
            self.end_directory("videos")
            return
        shown = 0
        seen = set()
        for match in _PAGE.finditer(text or ""):
            page = match.group(1)
            if page in seen:
                continue
            seen.add(page)
            number = page.rsplit("-", 1)[-1]
            thumb = self._thumb_before(text, match.start())
            self.add_link(
                "Page {}".format(number),
                page,
                4,
                thumb,
                self.fanart,
                info_labels={"title": "Page {}".format(number)},
                referer=url,
            )
            shown += 1
        current = 0
        parsed = urllib.parse.urlparse(url)
        try:
            current = int((urllib.parse.parse_qs(parsed.query).get("p") or ["0"])[0])
        except ValueError:
            current = 0
        next_url = ""
        next_page = None
        for href in re.findall(r'href="([^"]+)"', text or "", re.I):
            absolute = urllib.parse.urljoin(url, html.unescape(href))
            query = urllib.parse.parse_qs(urllib.parse.urlparse(absolute).query)
            if "p" not in query:
                continue
            try:
                number = int(query["p"][0])
            except ValueError:
                continue
            if number > current and (next_page is None or number < next_page):
                next_page = number
                next_url = absolute
        if next_url:
            self.add_dir("Next Page", next_url, 2, self.icon, self.fanart)
        if shown == 0 and not next_url:
            self.notify_error("No {} pages found".format(self.label or self.name))
        self.end_directory("videos")

    def search(self, query):
        cleaned = (query or "").strip()
        if not cleaned or _skip(cleaned):
            self.end_directory("videos")
            return
        super().search(cleaned)

    def process_content(self, url, page=1):
        if not url or url == "BOOTSTRAP":
            url, _label = self.get_start_url_and_label()
        parsed = urllib.parse.urlparse(url)
        if parsed.netloc and "e-hentai.org" not in parsed.netloc.lower():
            self.end_directory("videos")
            return
        text = self._get(url, referer=self.base_url)
        if "/g/" in (parsed.path or ""):
            self._list_pages(url, text)
            return
        if page <= 1 or urllib.parse.parse_qs(parsed.query).get("next") or urllib.parse.parse_qs(parsed.query).get("f_search"):
            self.add_dir("Search", "", 5, self.icons.get("search", self.icon), self.fanart)
        self._list_galleries(url, text)

    def _image_from_page(self, text):
        patterns = (
            r'<img[^>]+id="img"[^>]+src="([^"]+)"',
            r'<img[^>]+src="([^"]+)"[^>]+id="img"',
        )
        for pattern in patterns:
            match = re.search(pattern, text or "", re.I)
            if match:
                return html.unescape(match.group(1)).replace("\\/", "/")
        for match in re.findall(r'https?://[^"\s]+', (text or "").replace("\\/", "/"), re.I):
            if "hath.network" in match.lower() and re.search(r"\.(?:jpe?g|png|webp)(?:$|\?)", match, re.I):
                return match
        return ""

    def _photo_size(self, url, referer):
        try:
            response = self.session.get(
                url,
                headers=self._headers(referer, accept="image/*,*/*"),
                timeout=14,
                stream=True,
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
            response.close()
            return response.status_code, ctype, total
        except Exception:
            return 0, "", 0

    def play_video(self, url):
        image = url or ""
        referer = self.base_url
        if "/s/" in image:
            referer = image
            image = self._image_from_page(self._get(url, referer=self.base_url))
        if not re.search(r"\.(?:jpe?g|png|webp)(?:$|\?)", image.lower()):
            self.notify_error("Could not resolve stream URL")
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return
        status, ctype, total = self._photo_size(image, referer)
        if status not in (200, 206) or not ctype.startswith("image/") or (total and total < _MIN_PHOTO):
            self.notify_error("Could not resolve stream URL")
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return
        headers = self._headers(referer, accept="image/*,*/*")
        play_url = "{}|{}".format(image, urllib.parse.urlencode(headers))
        list_item = xbmcgui.ListItem(path=play_url)
        list_item.setProperty("IsPlayable", "true")
        if "webp" in ctype or ".webp" in image.lower():
            mime = "image/webp"
        elif "png" in ctype or ".png" in image.lower():
            mime = "image/png"
        else:
            mime = "image/jpeg"
        list_item.setMimeType(mime)
        list_item.setContentLookup(False)
        xbmcplugin.setResolvedUrl(self.addon_handle, True, list_item)
