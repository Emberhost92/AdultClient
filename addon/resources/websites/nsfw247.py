#!/usr/bin/env python
# -*- coding: utf-8 -*-

import html
import re
import urllib.parse

import requests

from resources.lib.base_website import BaseWebsite

_RESERVED = {
    "category", "tag", "page", "author", "wp-content", "wp-json", "wp-includes",
    "feed", "comments", "xmlrpc.php", "search", "login", "signup", "register",
    "about", "contact", "privacy", "dmca", "terms", "forum", "cdn-cgi",
    "cart", "account", "home", "start", "homepage",
}
_BLOCKED = ("teen", "teens", "underage", "preteen", "lolita", "jailbait", "child", "children")


def _blocked(value):
    words = re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).split()
    return any(word in _BLOCKED for word in words)


class Nsfw247(BaseWebsite):
    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="nsfw247",
            base_url="https://nsfw247.to/",
            search_url="https://nsfw247.to/?s={}",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.label = "NSFW247"
        self.host = "nsfw247.to"
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
            response = self.session.get(url, headers=self._headers(url), timeout=18)
            if response.status_code == 200 and response.text:
                return response.text
        except Exception as exc:
            self.logger.warning("%s request failed: %s", self.label, exc)
        return ""

    def _same(self, url):
        host = urllib.parse.urlparse(url).netloc.lower()
        return host == self.host or host.endswith("." + self.host)

    def _abs(self, href):
        if href.startswith("//"):
            return "https:" + href
        return urllib.parse.urljoin(self.base_url, href)

    def _posts(self, content):
        cards = []
        seen = set()
        for match in re.finditer(r'href="([^"]+)"', content or "", re.IGNORECASE):
            href = html.unescape(match.group(1)).split("#")[0]
            if href.startswith("javascript") or href.startswith("mailto:"):
                continue
            full = self._abs(href).split("?")[0]
            if not self._same(full):
                continue
            parts = [part for part in urllib.parse.urlparse(full).path.split("/") if part]
            if len(parts) != 1 or parts[0].lower() in _RESERVED or len(parts[0]) < 6:
                continue
            if _blocked(parts[0]):
                continue
            if not full.endswith("/"):
                full += "/"
            if full in seen:
                continue
            seen.add(full)
            window = (content or "")[match.end():match.end() + 800]
            img = re.search(
                r'(?:data-src|data-lazy-src|src)="([^"]+\.(?:jpe?g|png|webp)[^"]*)"',
                window,
                re.IGNORECASE,
            )
            thumb = self._abs(html.unescape(img.group(1))) if img else self.icon
            cards.append({
                "href": full,
                "title": parts[0].replace("-", " ").replace("_", " ").title(),
                "thumb": thumb,
            })
        return cards

    def _images(self, content):
        found = []
        seen = set()
        blobs = re.findall(
            r'(?:src|data-src|data-lazy-src|srcset)="([^"]+)"',
            content or "",
            re.IGNORECASE,
        )
        for blob in blobs:
            for part in html.unescape(blob).split(","):
                raw = part.strip().split(" ")[0]
                if not re.search(r"\.(?:jpe?g|png|webp)(?:$|\?)", raw, re.IGNORECASE):
                    continue
                src = self._abs(raw)
                low = src.lower()
                if not src.startswith("http") or any(bit in low for bit in ("logo", "icon", "favicon", "sprite", "emoji")):
                    continue
                if _blocked(src) or src in seen:
                    continue
                seen.add(src)
                found.append(src)
        return found

    def _listing(self, url):
        parts = [part for part in urllib.parse.urlparse(url).path.split("/") if part]
        if not parts:
            return True
        return parts[0].lower() in ("page", "category", "tag", "search") or parts[0].lower().startswith("homepage")

    def process_content(self, url, page=1):
        if not url or url == "BOOTSTRAP":
            url = self.base_url
        content = self._get(url)
        count = 0
        if self._listing(url):
            if page == 1 and urllib.parse.urlparse(url).path.strip("/") in ("",):
                self.add_dir("Search", "", 5, self.icons["search"])
            for card in self._posts(content):
                self.add_dir(card["title"], card["href"], 2, card["thumb"])
                count += 1
            nxt = re.search(r'href="(https?://[^"]+/page/\d+/)"', content or "", re.IGNORECASE)
            if nxt and self._same(nxt.group(1)):
                self.add_dir("Next Page", nxt.group(1), 2, self.icons["default"])
        else:
            for index, image in enumerate(self._images(content), 1):
                label = "Photo {}".format(index)
                self.add_link(label, image, 4, image, self.fanart, info_labels={"title": label, "plot": label})
                count += 1
        if not count:
            self.notify_error("No {} items found".format(self.label))
        self.end_directory("videos")

    def play_video(self, url):
        import xbmcgui
        import xbmcplugin
        item = xbmcgui.ListItem(path=url)
        item.setProperty("IsPlayable", "true")
        xbmcplugin.setResolvedUrl(self.addon_handle, True, item)
