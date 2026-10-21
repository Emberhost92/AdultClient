#!/usr/bin/env python
# -*- coding: utf-8 -*-

import html
import re
import urllib.parse

import requests

from resources.lib.base_website import BaseWebsite

_BLOCKED = ("teen", "teens", "underage", "preteen", "lolita", "jailbait", "child", "children")
_SKIP_SLUG = ("rules", "reglement", "faq", "announcement", "regel")
_SKIP_URL = (
    "avatar", "smilie", "emoji", "logo", "icon", "favicon", "sprite",
    "reaction", "badge", "/styles/", "/data/assets/",
)
_SKIP_HOST = ("jsdelivr.net", "gstatic.com", "googleapis.com", "xenforo.com")


def _blocked(value):
    words = re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).split()
    return any(word in _BLOCKED for word in words)


class Socialmediagirls(BaseWebsite):
    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="socialmediagirls",
            base_url="https://forums.socialmediagirls.com/",
            search_url="https://forums.socialmediagirls.com/search/search?keywords={}",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.label = "Social Media Girls"
        self.host = "socialmediagirls.com"
        self.feed_url = "https://forums.socialmediagirls.com/whats-new/posts/"
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
            response = self.session.get(url, headers=self._headers(url), timeout=20)
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

    def _threads(self, content):
        cards = []
        seen = set()
        for match in re.finditer(r'href="([^"]+)"', content or "", re.IGNORECASE):
            raw = html.unescape(match.group(1))
            if "/threads/" not in raw:
                continue
            full = self._abs(raw).split("#")[0].split("?")[0]
            if not self._same(full):
                continue
            path = urllib.parse.urlparse(full).path
            found = re.search(r"/threads/([^/]+)", path, re.IGNORECASE)
            if not found:
                continue
            leaf = found.group(1).lower()
            if any(bit in leaf for bit in _SKIP_SLUG) or _blocked(leaf):
                continue
            thread = urllib.parse.urljoin(self.base_url, "threads/{}/".format(found.group(1)))
            if thread in seen:
                continue
            seen.add(thread)
            title = re.sub(r"\.\d+$", "", found.group(1)).replace("-", " ").replace("_", " ").title() or "Thread"
            cards.append({"href": thread, "title": title, "thumb": self.icon})
        return cards

    def _images(self, content):
        found = []
        seen = set()
        blobs = re.findall(
            r'(?:src|data-src|data-url|href)="([^"]+)"',
            content or "",
            re.IGNORECASE,
        )
        blobs.extend(re.findall(r"https?://[^\"\s>]+\.(?:jpe?g|png|webp)(?:\?[^\"\s>]*)?", content or "", re.IGNORECASE))
        for blob in blobs:
            for part in html.unescape(blob).split(","):
                raw = part.strip().split(" ")[0]
                if not re.search(r"\.(?:jpe?g|png|webp)(?:$|\?)", raw, re.IGNORECASE):
                    continue
                src = self._abs(raw)
                low = src.lower()
                host = urllib.parse.urlparse(src).netloc.lower()
                if not src.startswith("http") or src in seen or _blocked(src):
                    continue
                if any(bit in low for bit in _SKIP_URL):
                    continue
                if any(host == bit or host.endswith("." + bit) for bit in _SKIP_HOST):
                    continue
                seen.add(src)
                found.append(src)
        return found

    def _is_thread(self, url):
        return "/threads/" in urllib.parse.urlparse(url).path

    def process_content(self, url, page=1):
        if not url or url == "BOOTSTRAP":
            url = self.feed_url
        content = self._get(url)
        cards = [] if self._is_thread(url) else self._threads(content)
        if not self._is_thread(url) and not cards and url.rstrip("/") != self.base_url.rstrip("/"):
            url = self.base_url
            content = self._get(url)
            cards = self._threads(content)
        count = 0
        if self._is_thread(url):
            for index, image in enumerate(self._images(content), 1):
                label = "Photo {}".format(index)
                self.add_link(
                    label, image, 4, image, self.fanart,
                    info_labels={"title": label, "plot": label},
                    referer=url,
                )
                count += 1
        else:
            if page == 1 and urllib.parse.urlparse(url).path.strip("/") in ("", "whats-new", "whats-new/posts"):
                self.add_dir("Search", "", 5, self.icons["search"])
            for card in cards:
                self.add_dir(card["title"], card["href"], 2, card["thumb"])
                count += 1
            nxt = re.search(
                r'href="([^"]+)"[^>]*class="[^"]*pageNav-jump--next',
                content or "",
                re.IGNORECASE,
            )
            if not nxt:
                nxt = re.search(
                    r'class="[^"]*pageNav-jump--next[^"]*"[^>]*href="([^"]+)"',
                    content or "",
                    re.IGNORECASE,
                )
            if nxt:
                nxt_url = self._abs(html.unescape(nxt.group(1)))
                if self._same(nxt_url):
                    self.add_dir("Next Page", nxt_url, 2, self.icons["default"])
        if not count:
            self.notify_error("No {} items found".format(self.label))
        self.end_directory("videos")

    def play_video(self, url):
        import xbmcgui
        import xbmcplugin
        item = xbmcgui.ListItem(path=url)
        item.setProperty("IsPlayable", "true")
        xbmcplugin.setResolvedUrl(self.addon_handle, True, item)
