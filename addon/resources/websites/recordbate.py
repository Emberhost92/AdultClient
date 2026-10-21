#!/usr/bin/env python
# -*- coding: utf-8 -*-

import html
import re
import urllib.parse

import requests
import xbmcgui
import xbmcplugin

from resources.lib.base_website import BaseWebsite

_BLOCKED = ("teen", "teens", "underage", "preteen", "lolita", "jailbait", "child", "children")
_SKIP = {
    "categories", "category", "tags", "tag", "search", "channels", "pornstars",
    "models", "stars", "page", "popular", "top-rated", "most-viewed", "newest",
}


def _blocked(value):
    words = re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).split()
    return any(word in _BLOCKED for word in words)


class Recordbate(BaseWebsite):
    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="recordbate",
            base_url="https://recordbate.com/",
            search_url="https://recordbate.com/search?q={}",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.label = "RecordBate"
        self.host = "recordbate.com"
        self.session = requests.Session()
        self.ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )

    def _headers(self, referer=None):
        return {
            "User-Agent": self.ua,
            "Referer": referer or self.base_url,
            "Accept": "text/html",
        }

    def _get(self, url):
        try:
            response = self.session.get(url, headers=self._headers(url), timeout=16)
            if response.status_code == 200 and response.text:
                return response.text
        except Exception as exc:
            self.logger.warning("%s request failed: %s", self.label, exc)
        return ""

    def _abs(self, href):
        if href.startswith("//"):
            return "https:" + href
        return urllib.parse.urljoin(self.base_url, href)

    def _same(self, url):
        host = urllib.parse.urlparse(url).netloc.lower()
        return host == self.host or host.endswith("." + self.host)

    def _cards(self, content):
        cards = []
        seen = set()
        for match in re.finditer(r'href="([^"]+)"', content or "", re.IGNORECASE):
            href = self._abs(html.unescape(match.group(1))).split("#")[0].split("?")[0]
            if not self._same(href):
                continue
            parts = [part for part in urllib.parse.urlparse(href).path.split("/") if part]
            if len(parts) < 2 or parts[0].lower() not in ("video", "videos"):
                continue
            if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) < 4:
                continue
            slug = parts[-1]
            if slug.lower() in _SKIP or _blocked(slug):
                continue
            if href in seen:
                continue
            seen.add(href)
            title = re.sub(r"\.(?:html|php)$", "", slug, flags=re.IGNORECASE)
            title = re.sub(r"-\d+$", "", title).replace("-", " ").replace("_", " ").title() or "Video"
            window = (content or "")[match.start():match.start() + 900]
            img = re.search(r'(?:data-original|data-src|src)="([^"]+\.(?:jpe?g|png|webp)[^"]*)"', window, re.IGNORECASE)
            thumb = self._abs(html.unescape(img.group(1))) if img else self.icon
            cards.append({"href": href, "title": title, "thumb": thumb})
        return cards

    def _playable(self, url, referer):
        try:
            response = self.session.get(
                url,
                headers={"User-Agent": self.ua, "Referer": referer, "Range": "bytes=0-1"},
                timeout=14,
                stream=True,
                allow_redirects=True,
            )
            ctype = (response.headers.get("Content-Type") or "").lower()
            ok = response.status_code in (200, 206) and (
                "video" in ctype or "mpegurl" in ctype or "octet-stream" in ctype
            )
            response.close()
            return ok
        except Exception:
            return False

    def resolve_stream(self, page_url):
        page = self._get(page_url)
        sources = re.findall(r"https?://[^\"'\s>]+\.(?:mp4|m3u8)(?:\?[^\"'\s>]*)?", page or "", re.IGNORECASE)
        for source in sources:
            source = source.replace("\\/", "/").replace("&amp;", "&")
            if _blocked(source):
                continue
            if self._playable(source, page_url):
                return source
        return ""

    def process_content(self, url, page=1):
        if not url or url == "BOOTSTRAP":
            url = self.base_url
        content = self._get(url)
        path = urllib.parse.urlparse(url).path
        if page == 1 and path in ("", "/"):
            self.add_dir("Search", "", 5, self.icons["search"])
        cards = self._cards(content)
        for card in cards:
            self.add_link(
                card["title"], card["href"], 4, card["thumb"], self.fanart,
                info_labels={"title": card["title"], "plot": card["title"]},
            )
        if not cards:
            self.notify_error("No {} videos found".format(self.label))
        self.end_directory("videos")

    def play_video(self, url):
        stream = self.resolve_stream(url)
        if not stream:
            self.notify_error("Could not resolve stream URL")
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return
        headers = urllib.parse.urlencode(self._headers(url))
        mime = "application/vnd.apple.mpegurl" if ".m3u8" in stream.lower() else "video/mp4"
        item = xbmcgui.ListItem(path="{}|{}".format(stream, headers))
        item.setProperty("IsPlayable", "true")
        item.setMimeType(mime)
        item.setContentLookup(False)
        xbmcplugin.setResolvedUrl(self.addon_handle, True, item)
