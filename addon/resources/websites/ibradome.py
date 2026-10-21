#!/usr/bin/env python
# -*- coding: utf-8 -*-

import html
import re
import urllib.parse

import requests

from resources.lib.base_website import BaseWebsite


class Ibradome(BaseWebsite):
    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="ibradome",
            base_url="https://ibradome.com/",
            search_url="https://ibradome.com/search?q={}",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.label = "Ibradome"
        self.session = requests.Session()
        self.ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )

    def _headers(self):
        return {"User-Agent": self.ua, "Referer": self.base_url, "Accept": "text/html"}

    def _get(self, url):
        try:
            response = self.session.get(url, headers=self._headers(), timeout=18)
            if response.status_code == 200 and response.text:
                return response.text
        except Exception as exc:
            self.logger.warning("Ibradome request failed: %s", exc)
        return ""

    def _clean(self, value):
        return re.sub(r"\s+", " ", html.unescape(value or "")).strip()

    def _creators(self, content):
        cards = []
        seen = set()
        for href, title in re.findall(
            r'<a\b[^>]*href="(https://ibradome\.com/creator/[^"]+)"[^>]*title="([^"]*)"',
            content or "",
            re.IGNORECASE,
        ):
            href = href.split("?")[0]
            if href in seen:
                continue
            seen.add(href)
            label = self._clean(title) or href.rstrip("/").split("/")[-1].replace("-", " ").title()
            cards.append({"href": href, "title": label})
        return cards

    def _images(self, content):
        found = []
        seen = set()
        for src in re.findall(
            r'(?:src|data-src)="([^"]+\.(?:jpe?g|png|webp)[^"]*)"',
            content or "",
            re.IGNORECASE,
        ):
            src = html.unescape(src.split()[0])
            if src.startswith("//"):
                src = "https:" + src
            elif src.startswith("/"):
                src = urllib.parse.urljoin(self.base_url, src)
            low = src.lower()
            if not src.startswith("http") or any(bit in low for bit in ("logo", "icon", "favicon", "sprite")):
                continue
            if src in seen:
                continue
            seen.add(src)
            found.append(src)
        return found

    def process_content(self, url, page=1):
        if not url or url == "BOOTSTRAP":
            url = self.base_url
        content = self._get(url)
        path = urllib.parse.urlparse(url).path
        count = 0
        if "/creator/" not in path:
            if page == 1:
                self.add_dir("Search", "", 5, self.icons["search"])
            for card in self._creators(content):
                self.add_dir(card["title"], card["href"], 2, self.icon)
                count += 1
        else:
            for index, image in enumerate(self._images(content), 1):
                label = "Photo {}".format(index)
                self.add_link(label, image, 4, image, self.fanart, info_labels={"title": label, "plot": label})
                count += 1
        if not count:
            self.notify_error("No Ibradome items found")
        self.end_directory("videos")

    def play_video(self, url):
        import xbmcgui
        import xbmcplugin
        item = xbmcgui.ListItem(path=url)
        item.setProperty("IsPlayable", "true")
        xbmcplugin.setResolvedUrl(self.addon_handle, True, item)
