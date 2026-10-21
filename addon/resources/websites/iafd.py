#!/usr/bin/env python
# -*- coding: utf-8 -*-

import html
import re
import urllib.parse

import xbmc
import xbmcgui
import xbmcplugin

from resources.lib.base_website import BaseWebsite
from resources.lib.media_probe import UA, make_session

_BLOCKED = ("teen", "teens", "underage", "preteen", "lolita", "jailbait", "child", "children")
_AGE = re.compile(r"\b(?:1[0-7]|[1-9])\s*(?:yo|y\.o\.?|years?\s*old)\b", re.IGNORECASE)
_SKIP_IMG = (
    "thumb", "preview", "teaser", "sample", "poster", "icon", "logo", "sprite",
    "avatar", "placeholder", "pixel", "emoji", "favicon", "spinner", "blank",
)
_MIN_PHOTO = 8000


def _skip(value):
    text = (value or "").replace("_", " ")
    words = re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
    if any(word in _BLOCKED for word in words):
        return True
    return bool(_AGE.search(text))


class Iafd(BaseWebsite):
    label = "IAFD"

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="iafd",
            base_url="https://www.iafd.com/",
            search_url="https://www.iafd.com/ramesearch.asp?searchtype=comprehensive&searchstring={}",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.session = make_session()

    def _headers(self, referer=None, accept=None):
        headers = {
            "User-Agent": UA,
            "Accept": accept or "text/html,application/xhtml+xml,*/*",
            "Referer": referer or self.base_url,
        }
        for key, value in list(headers.items()):
            if not isinstance(value, str):
                continue
            try:
                value.encode("latin-1")
            except UnicodeEncodeError:
                headers[key] = urllib.parse.quote(value, safe=":/%?#[]@!$&'()*+,;=")
        return headers

    def _get(self, url, referer=None):
        last_error = ""
        for attempt in range(1, 3):
            try:
                response = self.session.get(url, headers=self._headers(referer), timeout=20)
                if response.status_code == 200 and response.text:
                    return response.url or url, response.text
                last_error = "HTTP {}".format(response.status_code)
            except Exception as exc:
                last_error = exc.__class__.__name__
                self.session = make_session()
            if attempt < 2:
                xbmc.sleep(400)
        self.logger.error("%s failed to fetch listing page: %s", self.label or self.name, last_error)
        return url, ""

    def _kind(self, url):
        parsed = urllib.parse.urlparse(urllib.parse.urljoin(self.base_url, url or self.base_url))
        parts = [part.lower() for part in parsed.path.split("/") if part]
        if "ramesearch.asp" in parts:
            return "search", parsed
        if "person.rme" in parts:
            return "person", parsed
        if "title.rme" in parts:
            return "title", parsed
        if not parts:
            return "home", parsed
        return "other", parsed

    def _label(self, body, slug):
        plain = re.sub(r"<[^>]+>", " ", body or "")
        plain = html.unescape(plain)
        plain = re.sub(r"\s+", " ", plain).strip()
        if len(plain) >= 2:
            return plain
        slug = urllib.parse.unquote(slug or "")
        slug = re.sub(r"\.(?:html?|php|asp)$", "", slug, flags=re.IGNORECASE)
        slug = slug.split("=")[-1].replace("-", " ").replace("_", " ").replace(".", " ")
        return re.sub(r"\s+", " ", slug).strip()

    def _entries(self, page_url, text, marker):
        items = []
        seen = set()
        for match in re.finditer(r"<a\b([^>]*)>([\s\S]*?)</a>", text or "", re.IGNORECASE):
            href_match = re.search(r'href=["\']([^"\']+)["\']', match.group(1), re.IGNORECASE)
            if not href_match:
                continue
            absolute = urllib.parse.urljoin(page_url, html.unescape(href_match.group(1)).split("#")[0])
            parsed = urllib.parse.urlparse(absolute)
            if not parsed.netloc.lower().endswith("iafd.com"):
                continue
            parts = [part for part in parsed.path.split("/") if part]
            if marker not in [part.lower() for part in parts] or len(parts) < 2:
                continue
            key = urllib.parse.urlunparse(parsed._replace(query="", fragment=""))
            if key in seen:
                continue
            label = self._label(match.group(2), parts[-1])
            if not label or _skip(label) or _skip(parsed.path):
                continue
            seen.add(key)
            items.append((label, key))
        return items

    def _image_urls(self, text):
        raw = html.unescape(text or "").replace("\\/", "/")
        found = []
        seen = set()
        for url in re.findall(r'https?://[^"\'\s<>]+\.(?:jpe?g|png|webp)', raw, re.IGNORECASE):
            url = url.rstrip(").,;'\"")
            parsed = urllib.parse.urlparse(url)
            if not parsed.netloc.lower().endswith("iafd.com"):
                continue
            if any(token in url.lower() for token in _SKIP_IMG) or _skip(parsed.path):
                continue
            base = parsed.path.rsplit("/", 1)[-1].lower()
            if not base or base in seen:
                continue
            seen.add(base)
            found.append(url)
        return found

    def _image_size(self, url, referer):
        try:
            response = self.session.get(
                url,
                headers=dict(self._headers(referer, "image/*,*/*"), **{"Range": "bytes=0-1"}),
                timeout=12,
                stream=True,
            )
            status = response.status_code
            ctype = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            final_host = urllib.parse.urlparse(response.url).netloc.lower()
            size = 0
            match = re.search(r"/(\d+)", response.headers.get("Content-Range") or "")
            if match:
                size = int(match.group(1))
            elif status == 200:
                try:
                    size = int(response.headers.get("Content-Length") or 0)
                except ValueError:
                    size = 0
            response.close()
            if not final_host.endswith("iafd.com"):
                return 0, "", 0
            return status, ctype, size
        except Exception:
            return 0, "", 0

    def _photos(self, text, referer, limit=3):
        best = {}
        for url in self._image_urls(text)[:20]:
            status, ctype, size = self._image_size(url, referer)
            if status not in (200, 206) or not ctype.startswith("image/") or size < _MIN_PHOTO:
                continue
            base = urllib.parse.urlparse(url).path.rsplit("/", 1)[-1].lower()
            current = best.get(base)
            if current is None or size > current[0]:
                best[base] = (size, url)
        ranked = sorted(best.values(), key=lambda item: item[0], reverse=True)
        return [url for _size, url in ranked[:limit]]

    def process_content(self, url, page=1):
        try:
            page_num = int(page or 1)
        except (TypeError, ValueError):
            page_num = 1
        if page_num > 1:
            self.end_directory("videos")
            return
        if not url or url == "BOOTSTRAP":
            url = self.base_url
        if _skip(url):
            self.end_directory("videos")
            return
        kind, parsed = self._kind(url)
        if kind == "search":
            query = urllib.parse.parse_qs(parsed.query).get("searchstring", [""])[0]
            if _skip(query):
                self.end_directory("videos")
                return
        final, text = self._get(url if kind != "home" else self.base_url, referer=self.base_url)
        if not text:
            self.notify_error("Could not load {} listing".format(self.label or self.name))
            self.end_directory("videos")
            return
        if kind in ("home", "search"):
            if kind == "home":
                self.add_dir("Search", "", 5, self.icons.get("search", self.icon))
            people = self._entries(final, text, "person.rme")
            if kind == "home" and not people:
                self.notify_error("Could not load {} listing".format(self.label or self.name))
                self.end_directory("videos")
                return
            for label, link in people:
                self.add_dir(label, link, 2, self.icons.get("pornstars", self.icon), self.fanart)
            self.end_directory("videos")
            return
        if kind == "person":
            for index, photo in enumerate(self._photos(text, final, limit=3), 1):
                self.add_link(
                    "Photo {}".format(index),
                    photo,
                    4,
                    photo,
                    self.fanart,
                    info_labels={"title": "Photo {}".format(index)},
                    referer=final or self.base_url,
                )
            for label, link in self._entries(final, text, "title.rme"):
                self.add_dir(label, link, 2, self.icons.get("default", self.icon), self.fanart)
            self.end_directory("videos")
            return
        for index, photo in enumerate(self._photos(text, final, limit=1), 1):
            self.add_link(
                "Photo {}".format(index),
                photo,
                4,
                photo,
                self.fanart,
                info_labels={"title": "Photo {}".format(index)},
                referer=final or self.base_url,
            )
        self.end_directory("videos")

    def search(self, query):
        if not query or _skip(query):
            self.end_directory("videos")
            return
        super().search(query)

    def play_video(self, url):
        if not re.search(r"\.(?:jpe?g|png|webp)(?:$|\?)", (url or "").lower()) or _skip(url):
            self.notify_error("Could not resolve stream URL")
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return
        headers = self._headers(self.base_url, accept="image/*,*/*")
        play_url = "{}|{}".format(url, urllib.parse.urlencode(headers))
        list_item = xbmcgui.ListItem(path=play_url)
        list_item.setProperty("IsPlayable", "true")
        lowered = url.lower()
        if ".webp" in lowered:
            mime = "image/webp"
        elif ".png" in lowered:
            mime = "image/png"
        else:
            mime = "image/jpeg"
        list_item.setMimeType(mime)
        list_item.setContentLookup(False)
        xbmcplugin.setResolvedUrl(self.addon_handle, True, list_item)
