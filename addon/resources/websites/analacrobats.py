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


def _blocked(value):
    words = re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).split()
    return any(word in _BLOCKED for word in words)


class Analacrobats(BaseWebsite):
    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="analacrobats",
            base_url="https://www.analacrobats.com/",
            search_url="https://www.analacrobats.com/searchgate.php?q={}",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.label = "Anal Acrobats"
        self.host = "analacrobats.com"
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

    def _cards(self, content):
        cards = []
        seen = set()
        for match in re.finditer(r'href="([^"]*/video/[^"]+\.html)"', content or "", re.IGNORECASE):
            href = self._abs(html.unescape(match.group(1))).split("?")[0]
            if href in seen or _blocked(href):
                continue
            seen.add(href)
            slug = urllib.parse.urlparse(href).path.rsplit("/", 1)[-1]
            slug = re.sub(r"\.html$", "", slug, flags=re.IGNORECASE)
            slug = re.sub(r"-\d+$", "", slug)
            title = slug.replace("-", " ").title() or "Video"
            window = (content or "")[match.start():match.start() + 900]
            img = re.search(r'(?:data-src|src)="([^"]+\.(?:jpe?g|png|webp)[^"]*)"', window, re.IGNORECASE)
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
            ok = response.status_code in (200, 206) and ("video" in ctype or "octet-stream" in ctype)
            response.close()
            return ok
        except Exception:
            return False

    def resolve_stream(self, page_url):
        page = self._get(page_url)
        for source in re.findall(r"https?://[^\"'\s>]+\.mp4(?:\?[^\"'\s>]*)?", page or "", re.IGNORECASE):
            source = source.replace("\\/", "/").replace("&amp;", "&")
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
                card["title"],
                card["href"],
                4,
                card["thumb"],
                self.fanart,
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
        item = xbmcgui.ListItem(path="{}|{}".format(stream, headers))
        item.setProperty("IsPlayable", "true")
        item.setMimeType("video/mp4")
        item.setContentLookup(False)
        xbmcplugin.setResolvedUrl(self.addon_handle, True, item)
