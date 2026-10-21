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


class Camvideos(BaseWebsite):
    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="camvideos",
            base_url="https://camvideos.me/",
            search_url="https://camvideos.me/search?query={}",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.label = "CamVideos"
        self.host = "camvideos.me"
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

    def _href(self, tag):
        match = re.search(r'href="([^"]+)"', tag or "", re.IGNORECASE)
        return html.unescape(match.group(1)) if match else ""

    def _cards(self, content, base):
        cards = []
        seen = set()
        chunks = re.findall(
            r'<div\b[^>]*class="[^"]*\bpost-container\b[^"]*"[\s\S]*?(?=<div\b[^>]*class="[^"]*\bpost-container\b|$)',
            content or "",
            re.IGNORECASE,
        )
        for chunk in chunks:
            anchor = re.search(
                r'<a\b[^>]*class="[^"]*\bpost-(?:name|content)\b[^"]*"[^>]*>',
                chunk,
                re.IGNORECASE,
            )
            if anchor and "href=" not in anchor.group(0).lower():
                anchor = re.search(
                    r'<a\b[^>]*href="[^"]+"[^>]*class="[^"]*\bpost-(?:name|content)\b[^"]*"',
                    chunk,
                    re.IGNORECASE,
                )
            href = self._href(anchor.group(0) if anchor else "")
            if not href:
                continue
            full = self._abs(href, base).split("#")[0].split("?")[0]
            if not self._same(full):
                continue
            parts = [part for part in urllib.parse.urlparse(full).path.split("/") if part]
            if len(parts) < 2 or _blocked("/".join(parts)):
                continue
            if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) < 4:
                continue
            if not full.endswith("/"):
                full += "/"
            if full in seen:
                continue
            seen.add(full)
            img = re.search(
                r'<img\b[^>]*\b(?:data-src|data-original|src)="([^"]+)"',
                chunk,
                re.IGNORECASE,
            )
            thumb = self._abs(img.group(1), base) if img else self.icon
            title = parts[-1].replace("-", " ").replace("_", " ").title() or "Recording"
            cards.append({"href": full, "title": title, "thumb": thumb})
        return cards

    def resolve_stream(self, page_url):
        page = self._get(page_url)
        for raw in re.findall(r'<source\b[^>]*\bsrc="([^"]+)"', page or "", re.IGNORECASE):
            media = self._abs(html.unescape(raw), page_url)
            if _blocked(media):
                continue
            if probe(media, referer=page_url, session=self.session):
                return media
        return ""

    def process_content(self, url, page=1):
        if not url or url == "BOOTSTRAP":
            url = self.base_url
        parsed = urllib.parse.urlparse(url)
        if page > 1 and "page=" not in (parsed.query or ""):
            query = urllib.parse.parse_qs(parsed.query)
            query["page"] = [str(page)]
            url = urllib.parse.urlunparse((
                parsed.scheme, parsed.netloc, parsed.path, parsed.params,
                urllib.parse.urlencode(query, doseq=True), parsed.fragment,
            ))
        content = self._get(url)
        path = urllib.parse.urlparse(url).path
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        if page == 1 and path in ("", "/") and "page" not in query and "q" not in query:
            self.add_dir("Search", "", 5, self.icons["search"])
        base = url
        cards = self._cards(content, base)
        for card in cards:
            self.add_link(
                card["title"], card["href"], 4, card["thumb"], self.fanart,
                info_labels={"title": card["title"], "plot": card["title"]},
            )
        nxt = re.search(r'href="([^"]*[?&]page=\d+[^"]*)"', content or "", re.IGNORECASE)
        if nxt:
            self.add_dir("Next Page", self._abs(html.unescape(nxt.group(1)), url), 2, self.icons["default"])
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
