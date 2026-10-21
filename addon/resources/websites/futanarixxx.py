#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import urllib.parse

import requests
import xbmcgui
import xbmcplugin

from resources.lib.base_website import BaseWebsite


_SKIP = {
    "all-videos",
    "category",
    "tag",
    "author",
    "page",
    "amember",
    "feed",
    "comments",
    "wp-json",
    "xmlrpc",
    "wp-content",
    "wp-includes",
}


class FutanariXxx(BaseWebsite):
    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="futanarixxx",
            base_url="https://futanari.xxx/",
            search_url="https://futanari.xxx/?s={}",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.label = "Futanari XXX"
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
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _get(self, url, referer=None):
        try:
            response = self.session.get(url, headers=self._headers(referer), timeout=18)
            if response.status_code == 200 and response.text:
                return response.text
        except Exception as exc:
            self.logger.warning("Futanari request failed: %s", exc)
        return ""

    def _clean(self, value):
        import html
        return re.sub(r"\s+", " ", html.unescape(value or "")).strip()

    def _cards(self, content):
        cards = []
        seen = set()
        for match in re.finditer(
            r'<a\b[^>]+href="(https://futanari\.xxx/([a-z0-9-]{6,})/)"[^>]*>',
            content or "",
            re.IGNORECASE,
        ):
            href, slug = match.group(1), match.group(2).lower()
            if slug in _SKIP or slug.startswith(("category-", "tag-", "page-")):
                continue
            if href in seen:
                continue
            seen.add(href)
            window = (content or "")[match.start():match.start() + 900]
            title_match = re.search(r'\b(?:title|aria-label)="([^"]+)"', match.group(0) + window, re.IGNORECASE)
            thumb_match = re.search(r'<img\b[^>]+(?:data-src|src)="([^"]+)"', window, re.IGNORECASE)
            title = self._clean(title_match.group(1) if title_match else "") or slug.replace("-", " ").title()
            if title.lower() in ("watch now", "home", "videos"):
                title = slug.replace("-", " ").title()
            cards.append({
                "href": href,
                "title": title,
                "thumb": thumb_match.group(1) if thumb_match else self.icon,
            })
        return cards

    def process_content(self, url, page=1):
        if not url or url == "BOOTSTRAP":
            url = urllib.parse.urljoin(self.base_url, "/all-videos/")
        content = self._get(url)
        path = urllib.parse.urlparse(url).path.rstrip("/")
        if page == 1 and path in ("", "/all-videos"):
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
        next_match = re.search(
            r'href="(https://futanari\.xxx/all-videos/page/\d+/)"',
            content or "",
            re.IGNORECASE,
        )
        if next_match:
            self.add_dir("Next Page", next_match.group(1), 2, self.icons["default"])
        if not cards:
            self.notify_error("No Futanari videos found")
        self.end_directory("videos")

    def _playable(self, url, referer):
        try:
            response = self.session.get(
                url,
                headers={"User-Agent": self.ua, "Referer": referer, "Range": "bytes=0-0"},
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
        text = (page or "").replace("\\/", "/")
        mp4s = []
        for raw in re.findall(r"https?://[^\s\"'<>]+\.mp4", text, re.IGNORECASE):
            if raw not in mp4s:
                mp4s.append(raw)
        ordered = [item for item in mp4s if "teaser" not in item.lower()] + [
            item for item in mp4s if "teaser" in item.lower()
        ]
        for candidate in ordered[:4]:
            if self._playable(candidate, page_url):
                return candidate
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
