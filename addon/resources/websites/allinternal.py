#!/usr/bin/env python
# -*- coding: utf-8 -*-

import html
import re
import urllib.parse

import xbmcgui
import xbmcplugin

from resources.lib.base_website import BaseWebsite
from resources.lib.media_probe import make_session, probe

_BLOCKED = ("teen", "teens", "underage", "preteen", "lolita", "jailbait", "child", "children")
_AGE = re.compile(r"\b(?:1[0-7]|[1-9])\s*(?:yo|y\.o\.?|years?\s*old)\b", re.IGNORECASE)


def _blocked(value):
    words = re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).split()
    if any(word in _BLOCKED for word in words):
        return True
    return bool(_AGE.search(value or ""))


class Allinternal(BaseWebsite):
    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="allinternal",
            base_url="https://www.allinternal.com/",
            search_url="https://www.allinternal.com/search?q={}",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.label = "AllInternal"
        self.host = "allinternal.com"
        self.session = make_session()
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
            response = self.session.get(url, headers=self._headers(url), timeout=25)
            if response.status_code == 200 and response.text:
                return response.text
        except Exception as exc:
            self.logger.warning("%s request failed: %s", self.label, exc)
        return ""

    def _abs(self, href, base=None):
        href = html.unescape(href or "").strip()
        if href.startswith("//"):
            return "https:" + href
        return urllib.parse.urljoin(base or self.base_url, href)

    def _same(self, url):
        host = urllib.parse.urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host == self.host or host.endswith("." + self.host)

    def _cards(self, content, base):
        cards = []
        seen = set()
        for match in re.finditer(r'href="([^"]+)"', content or "", re.IGNORECASE):
            full = self._abs(html.unescape(match.group(1)), base).split("#")[0].split("?")[0]
            if not self._same(full):
                continue
            parts = [part for part in urllib.parse.urlparse(full).path.split("/") if part]
            if len(parts) < 2 or parts[0].lower() != "movies" or _blocked("/".join(parts)):
                continue
            if parts[1].isdigit() and len(parts[1]) < 4:
                continue
            if not full.endswith("/"):
                full += "/"
            if full in seen:
                continue
            seen.add(full)
            window = (content or "")[max(0, match.start() - 900):match.start()]
            images = re.findall(
                r'(?:data-src|src)="([^"]+\.(?:jpe?g|png|webp)[^"]*)"',
                window,
                re.IGNORECASE,
            )
            thumb = self._abs(html.unescape(images[-1]), base) if images else self.icon
            title = parts[-1].replace("-", " ").replace("_", " ").title() or "Movie"
            cards.append({"href": full, "title": title, "thumb": thumb})
        return cards

    def resolve_stream(self, page_url):
        page = (self._get(page_url) or "").replace("\\u002F", "/").replace("\\/", "/")
        for raw in re.findall(r"https?://[^\"'\s<>\\]+\.mp4", page, re.IGNORECASE):
            if _blocked(raw):
                continue
            if probe(raw, referer=page_url, session=self.session):
                return raw
        return ""

    def process_content(self, url, page=1):
        if not url or url == "BOOTSTRAP":
            url = self.base_url
        content = self._get(url)
        cards = self._cards(content, url)
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
        item = xbmcgui.ListItem(path="{}|{}".format(stream, headers))
        item.setProperty("IsPlayable", "true")
        item.setMimeType("video/mp4")
        item.setContentLookup(False)
        xbmcplugin.setResolvedUrl(self.addon_handle, True, item)
