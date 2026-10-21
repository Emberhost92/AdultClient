#!/usr/bin/env python
# -*- coding: utf-8 -*-

import html
import re
import urllib.parse

import requests

from resources.lib.base_website import BaseWebsite
from resources.lib.resilient_http import fetch_text


class Nudostar(BaseWebsite):
    def __init__(self, addon_handle, addon=None):
        super().__init__(
            "nudostar",
            "https://nudostar.tv/",
            "https://nudostar.tv/models/{}/",
            addon_handle,
            addon,
        )
        self.label = "NudoStar"

    def _headers(self):
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
            "Referer": self.base_url,
            "Accept": "text/html",
        }

    def _get(self, url):
        try:
            response = requests.get(url, headers=self._headers(), timeout=20)
            if response.status_code == 200 and response.text:
                return response.text
        except Exception:
            pass
        return fetch_text(url, headers=self._headers(), logger=self.logger, timeout=20) or ""

    def _region(self, content):
        match = re.search(
            r'id="list_videos_common_videos_list_items"([\s\S]*?)(?:<div class="pagination"|id="list_videos_related_videos")',
            content or "",
            re.IGNORECASE,
        )
        if match and 'class="item"' in match.group(1):
            return match.group(1)
        return content or ""

    def _full_image(self, thumb):
        return (thumb or "").replace("_320px.", ".")

    def _cards(self, content):
        cards = []
        seen = set()
        for href, block in re.findall(
            r'<div class="item">\s*<a href="(https://nudostar\.tv/models/[^"]+)"[^>]*>([\s\S]{0,700}?)</a>',
            self._region(content),
            re.IGNORECASE,
        ):
            href = html.unescape(href).split("?")[0]
            if href in seen or re.search(r"/next-\d+/?$", href):
                continue
            seen.add(href)
            image = re.search(r'<img[^>]+src="([^"]+)"', block, re.IGNORECASE)
            title = re.search(r'<strong class="title">([^<]+)</strong>', block, re.IGNORECASE)
            alt = re.search(r'\balt="([^"]*)"', block, re.IGNORECASE)
            label = html.unescape(title.group(1) if title else (alt.group(1) if alt else "")).strip()
            cards.append({
                "href": href,
                "thumb": html.unescape(image.group(1)) if image else "",
                "label": re.sub(r"\s+", " ", label),
            })
        return cards

    def _photo(self, content):
        match = re.search(
            r'class="block-video"[\s\S]{0,800}?<img src="(https://nudostar\.tv/contents/[^"]+\.jpg)"',
            content or "",
            re.IGNORECASE,
        )
        return html.unescape(match.group(1)) if match else ""

    def search(self, query):
        slug = re.sub(r"[^a-z0-9]+", "-", (query or "").strip().lower()).strip("-")
        if not slug:
            return
        self.process_content("{}models/{}/".format(self.base_url, urllib.parse.quote(slug)))

    def process_content(self, url, page=1):
        if not url or url == "BOOTSTRAP":
            url = self.base_url
        content = self._get(url)
        path = urllib.parse.urlparse(url).path.rstrip("/")
        if page == 1 and path in ("", "/models"):
            self.add_dir("Search", "", 5, self.icons["search"])
            if path == "":
                self.add_dir("Models", self.base_url + "models/", 2, self.icons["pornstars"])
        count = 0
        for card in self._cards(content):
            parts = [part for part in urllib.parse.urlparse(card["href"]).path.split("/") if part]
            thumb = card["thumb"] or self.icon
            if len(parts) >= 3 and parts[-1].isdigit():
                label = card["label"] or "Photo {}".format(parts[-1])
                image = self._full_image(thumb)
                self.add_link(
                    label,
                    image or card["href"],
                    4,
                    thumb,
                    self.fanart,
                    info_labels={"title": label, "plot": label},
                )
            else:
                label = card["label"] or "Model"
                self.add_dir(label, card["href"], 2, thumb)
            count += 1
        if not count:
            image = self._photo(content)
            if image:
                self.add_link("Photo", image, 4, image, self.fanart, info_labels={"title": "Photo"})
                count = 1
        current = url.split("?")[0].rstrip("/")
        for href in re.findall(r'href="(https://nudostar\.tv/models/[^"]+/next-\d+/)"', content or "", re.IGNORECASE):
            if href.rstrip("/") != current:
                self.add_dir("Next Page", href, 2, self.icon)
                break
        if not count:
            self.notify_error("No NudoStar items found")
        self.end_directory("videos")
