#!/usr/bin/env python
# -*- coding: utf-8 -*-

import html
import re
import urllib.parse

import requests

from resources.lib.base_website import BaseWebsite


class NudostarCom(BaseWebsite):
    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="nudostarcom",
            base_url="https://nudostar.com/",
            search_url="https://nudostar.com/?s={}",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.label = "NudoStar.com"
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
            response = self.session.get(url, headers=self._headers(), timeout=18)
            if response.status_code == 200 and response.text:
                return response.text
        except Exception as exc:
            self.logger.warning("NudoStar.com request failed: %s", exc)
        return ""

    def _clean(self, value):
        return re.sub(r"\s+", " ", html.unescape(value or "")).strip()

    def _models(self, content):
        cards = []
        seen = set()
        for href in re.findall(r'href="(https://nudostar\.com/model/[^"#?]+/)"', content or "", re.IGNORECASE):
            if href in seen:
                continue
            seen.add(href)
            slug = [part for part in urllib.parse.urlparse(href).path.split("/") if part][-1]
            cards.append({"href": href, "title": slug.replace("-", " ").title(), "thumb": self.icon})
        return cards

    def _images(self, content):
        found = []
        seen = set()
        for src in re.findall(
            r'(?:src|data-src)="(https://nudostar\.com/content/[^"]+\.(?:jpe?g|png|webp))"',
            content or "",
            re.IGNORECASE,
        ):
            src = html.unescape(src)
            if src in seen:
                continue
            low = src.lower()
            if any(bit in low for bit in ("logo", "icon", "sprite", "emoji", "favicon")):
                continue
            seen.add(src)
            found.append(src)
        return found

    def process_content(self, url, page=1):
        if not url or url == "BOOTSTRAP":
            url = self.base_url
        content = self._get(url)
        path = urllib.parse.urlparse(url).path.rstrip("/")
        if page == 1 and path in ("",):
            self.add_dir("Search", "", 5, self.icons["search"])
        count = 0
        if "/model/" not in path:
            for card in self._models(content):
                self.add_dir(card["title"], card["href"], 2, card["thumb"])
                count += 1
        images = self._images(content) if "/model/" in path or not count else []
        for index, image in enumerate(images, 1):
            label = "Photo {}".format(index)
            self.add_link(label, image, 4, image, self.fanart, info_labels={"title": label, "plot": label})
            count += 1
        next_match = re.search(r'href="(https://nudostar\.com/page/\d+/)"', content or "", re.IGNORECASE)
        if next_match and "/model/" not in path:
            self.add_dir("Next Page", next_match.group(1), 2, self.icons["default"])
        if not count:
            self.notify_error("No NudoStar.com items found")
        self.end_directory("videos")

    def play_video(self, url):
        import xbmcgui
        import xbmcplugin
        item = xbmcgui.ListItem(path=url)
        item.setProperty("IsPlayable", "true")
        xbmcplugin.setResolvedUrl(self.addon_handle, True, item)
