#!/usr/bin/env python
# -*- coding: utf-8 -*-

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


class Hotscope(BaseWebsite):
    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="hotscope",
            base_url="https://hotscope.tv/",
            search_url="https://hotscope.tv/search?q={}",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.label = "HotScope"
        self.session = requests.Session()
        self.ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )

    def _headers(self, referer=None):
        return {
            "User-Agent": self.ua,
            "Referer": referer or self.base_url,
            "Accept": "text/html,application/vnd.apple.mpegurl,*/*",
        }

    def _get(self, url, referer=None):
        try:
            response = self.session.get(url, headers=self._headers(referer), timeout=18)
            if response.status_code == 200 and response.text:
                return response.text
        except Exception as exc:
            self.logger.warning("HotScope request failed: %s", exc)
        return ""

    def _cards(self, content):
        cards = []
        seen = set()
        for match in re.finditer(r'<a\b[^>]+href="(/video/[^"]+)"[^>]*>', content or "", re.IGNORECASE):
            href = match.group(1).split("?")[0]
            if href in seen or _blocked(href):
                continue
            seen.add(href)
            window = (content or "")[match.start():match.start() + 900]
            img = re.search(r'<img\b[^>]*\bsrc="([^"]+)"', window, re.IGNORECASE)
            alt = re.search(r'\balt="([^"]*)"', window, re.IGNORECASE)
            title = ""
            if alt:
                title = re.sub(r"\s+", " ", alt.group(1)).strip()
            if not title or _blocked(title):
                title = "Clip"
            thumb = img.group(1) if img and img.group(1).startswith("http") else self.icon
            cards.append({
                "href": urllib.parse.urljoin(self.base_url, href),
                "title": title,
                "thumb": thumb,
            })
        return cards

    def process_content(self, url, page=1):
        if not url or url == "BOOTSTRAP":
            url = self.base_url
        content = self._get(url)
        if page == 1 and urllib.parse.urlparse(url).path in ("", "/"):
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
            self.notify_error("No HotScope videos found")
        self.end_directory("videos")

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
                "mpegurl" in ctype or "video" in ctype or "octet-stream" in ctype
            )
            response.close()
            return ok
        except Exception:
            return False

    def resolve_stream(self, page_url):
        page = self._get(page_url)
        for source in re.findall(r'https?://[^"\']+\.m3u8[^"\']*', page or "", re.IGNORECASE):
            source = source.replace("\\u002F", "/").replace("\\/", "/")
            if self._playable(source, page_url):
                return source
        return ""

    def play_video(self, url):
        stream = self.resolve_stream(url)
        if not stream:
            self.notify_error("Could not resolve stream URL")
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return
        headers = self._headers(url)
        play_url = "{}|{}".format(stream, urllib.parse.urlencode(headers))
        item = xbmcgui.ListItem(path=play_url)
        item.setProperty("IsPlayable", "true")
        item.setMimeType("application/vnd.apple.mpegurl")
        item.setContentLookup(False)
        xbmcplugin.setResolvedUrl(self.addon_handle, True, item)
