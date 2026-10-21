#!/usr/bin/env python
# -*- coding: utf-8 -*-

import html
import re
import urllib.parse

import requests
import xbmcgui
import xbmcplugin

from resources.lib.base_website import BaseWebsite


class Erothots(BaseWebsite):
    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="erothots",
            base_url="https://erothots.co/",
            search_url="https://erothots.co/search/?q={}",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.label = "EroThots"
        self.session = requests.Session()
        self.ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )

    def _headers(self, referer=None):
        return {
            "User-Agent": self.ua,
            "Referer": referer or self.base_url,
            "Accept": "text/html,video/mp4,*/*",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _get(self, url, referer=None):
        try:
            response = self.session.get(url, headers=self._headers(referer), timeout=18)
            if response.status_code == 200 and response.text:
                return response.text
        except Exception as exc:
            self.logger.warning("EroThots request failed: %s", exc)
        return ""

    def _clean(self, value):
        return re.sub(r"\s+", " ", html.unescape(value or "")).strip()

    def _cards(self, content):
        cards = []
        seen = set()
        for match in re.finditer(
            r'<a class="video video-media" href="(https://erothots\.co/video/[^"]+)"[^>]*>([\s\S]{0,1500}?)</a>',
            content or "",
            re.IGNORECASE,
        ):
            href = match.group(1).split("?")[0]
            if href in seen:
                continue
            seen.add(href)
            block = match.group(2)
            alt = re.search(r'\balt="([^"]*)"', block, re.IGNORECASE)
            thumb = re.search(r'\bdata-src="(https?://[^"]+)"', block, re.IGNORECASE)
            title = self._clean(alt.group(1) if alt else "") or "Video"
            cards.append({
                "href": href,
                "title": title,
                "thumb": html.unescape(thumb.group(1)) if thumb else self.icon,
            })
        return cards

    def process_content(self, url, page=1):
        if not url or url == "BOOTSTRAP":
            url = urllib.parse.urljoin(self.base_url, "/videos")
        content = self._get(url)
        path = urllib.parse.urlparse(url).path.rstrip("/")
        if page == 1 and path in ("", "/videos", "/videos/hot"):
            self.add_dir("Search", "", 5, self.icons["search"])
            self.add_dir("Models", urllib.parse.urljoin(self.base_url, "/models"), 2, self.icons["pornstars"])
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
            for model in re.findall(r'href="(https://erothots\.co/models?/[^"]+)"', content or "", re.IGNORECASE):
                slug = model.rstrip("/").split("/")[-1]
                if slug and slug not in ("models", "model"):
                    self.add_dir(slug.replace("-", " ").title(), model.split("?")[0], 2, self.icon)
                    cards.append(model)
        if not cards:
            self.notify_error("No EroThots videos found")
        self.end_directory("videos")

    def _playable(self, url, referer):
        try:
            headers = self._headers(referer)
            headers["Range"] = "bytes=0-1"
            response = self.session.get(
                url,
                headers=headers,
                timeout=14,
                stream=True,
                allow_redirects=True,
            )
            ctype = (response.headers.get("Content-Type") or "").lower()
            code = response.status_code
            response.close()
            return code in (200, 206) and ("video" in ctype or "octet-stream" in ctype)
        except Exception:
            return False

    def resolve_stream(self, page_url):
        page = self._get(page_url)
        sources = re.findall(r'<source[^>]+src="([^"]+)"', page or "", re.IGNORECASE)
        if not sources:
            sources = re.findall(r'https?://[^"\']+\.mp4[^"\']*', page or "", re.IGNORECASE)
        for source in sources:
            source = html.unescape(source)
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
        item.setMimeType("video/mp4")
        item.setContentLookup(False)
        xbmcplugin.setResolvedUrl(self.addon_handle, True, item)
