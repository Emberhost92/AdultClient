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
_BOOK = re.compile(r'<a href="(/g/\d+/)" class="cover"[^>]*>(.*?)</a>', re.I | re.S)
_READER = re.compile(r'href="(/g/\d+/\d+/)"', re.I)
_IMAGE = re.compile(r'https?://i\d*\.nhentai\.net/[^"\s\\]+\.(?:jpe?g|png|webp)', re.I)
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


def _page_number(url):
    numbers = re.findall(r"(\d+)", urllib.parse.urlparse(url or "").path)
    if not numbers:
        return 0
    try:
        return int(numbers[-1])
    except ValueError:
        return 0


class Nhentai(KVSTubeWebsite):
    label = "nhentai"
    sort_options = ["Latest"]
    sort_paths = {"Latest": "/"}
    categories_path = None
    models_path = None
    next_page_full_count = 0
    use_playback_proxy = False

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="nhentai",
            base_url="https://nhentai.net/",
            search_url="https://nhentai.net/search/?q={}",
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
        for match in re.finditer(r"<h[12][^>]*>(.*?)</h[12]>", text or "", re.I | re.S):
            chunks.append(_clean(match.group(1)))
        for tag in re.findall(r'href="/(?:tag|artist|parody|character|group|category)/([^"?#]+)"', text or "", re.I):
            chunks.append(urllib.parse.unquote(tag))
        return any(_skip(chunk) for chunk in chunks if chunk)

    def _next_page(self, url, text):
        parsed = urllib.parse.urlparse(url)
        try:
            current = int((urllib.parse.parse_qs(parsed.query).get("page") or ["1"])[0])
        except ValueError:
            current = 1
        wanted = str(current + 1)
        for href in re.findall(r'href="([^"]+)"', text or "", re.I):
            absolute = urllib.parse.urljoin(url, html.unescape(href))
            query = urllib.parse.parse_qs(urllib.parse.urlparse(absolute).query)
            if (query.get("page") or [""])[0] == wanted:
                return absolute
        return ""

    def _list_books(self, url, text):
        shown = 0
        seen = set()
        for match in _BOOK.finditer(text or ""):
            path = match.group(1)
            if path in seen:
                continue
            seen.add(path)
            inner = match.group(2)
            title_match = re.search(r'class="caption"[^>]*>(.*?)</div>', inner, re.I | re.S)
            if not title_match:
                title_match = re.search(
                    r'class="caption"[^>]*>(.*?)</div>',
                    text[match.end():match.end() + 500],
                    re.I | re.S,
                )
            title = _clean(title_match.group(1)) if title_match else "Gallery"
            if _skip(title) or _skip(path):
                continue
            thumb_match = re.search(r'(?:data-src|src)="([^"]+)"', inner, re.I)
            thumb = html.unescape(thumb_match.group(1)) if thumb_match else self.icon
            self.add_dir(title, urllib.parse.urljoin(self.base_url, path), 2, thumb, self.fanart)
            shown += 1
        next_url = self._next_page(url, text)
        if next_url and next_url != url:
            self.add_dir("Next Page", next_url, 2, self.icon, self.fanart)
        if shown == 0 and not next_url:
            self.notify_error("No {} results found".format(self.label or self.name))
        self.end_directory("videos")

    def _list_pages(self, url, text):
        if self._blocked_book(text):
            self.end_directory("videos")
            return
        thumbs = {}
        for thumb in re.findall(r'https?://t\d*\.nhentai\.net/[^"\s\\]+', (text or "").replace("\\/", "/"), re.I):
            number = _page_number(thumb)
            if number and number not in thumbs:
                thumbs[number] = thumb
        readers = []
        seen = set()
        for match in _READER.finditer(text or ""):
            path = match.group(1)
            if path in seen or path.rstrip("/") == urllib.parse.urlparse(url).path.rstrip("/"):
                continue
            seen.add(path)
            readers.append(urllib.parse.urljoin(self.base_url, path))
        readers.sort(key=_page_number)
        shown = 0
        if readers:
            for page in readers:
                number = _page_number(page)
                self.add_link(
                    "Page {}".format(number or shown + 1),
                    page,
                    4,
                    thumbs.get(number) or self.icon,
                    self.fanart,
                    info_labels={"title": "Page {}".format(number or shown + 1)},
                    referer=url,
                )
                shown += 1
        else:
            images = []
            for image in _IMAGE.findall((text or "").replace("\\/", "/")):
                if image not in images and "thumb" not in image.lower():
                    images.append(image)
            images.sort(key=_page_number)
            for image in images:
                number = _page_number(image)
                self.add_link(
                    "Page {}".format(number or shown + 1),
                    image,
                    4,
                    thumbs.get(number) or self.icon,
                    self.fanart,
                    info_labels={"title": "Page {}".format(number or shown + 1)},
                    referer=url,
                )
                shown += 1
        if shown == 0:
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
        if parsed.netloc and "nhentai.net" not in parsed.netloc.lower():
            self.end_directory("videos")
            return
        path = parsed.path or "/"
        text = self._get(url, referer=self.base_url)
        if re.search(r"/g/\d+/?$", path):
            self._list_pages(url, text)
            return
        self.add_dir("Search", "", 5, self.icons.get("search", self.icon), self.fanart)
        self._list_books(url, text)

    def _image_from_page(self, text):
        images = []
        for image in _IMAGE.findall((text or "").replace("\\/", "/")):
            if "thumb" not in image.lower() and image not in images:
                images.append(image)
        if not images:
            return ""
        images.sort(key=_page_number)
        return images[0]

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
        if re.search(r"/g/\d+/\d+/?$", image):
            referer = image
            image = self._image_from_page(self._get(url, referer=self.base_url))
        if not re.search(r"\.(?:jpe?g|png|webp)(?:$|\?)", (image or "").lower()):
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
