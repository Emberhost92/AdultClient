#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Shared listing and image extraction for lazy-loaded leak blogs."""

import html
import re
import urllib.parse

import requests
import xbmcgui
import xbmcplugin

from resources.lib.base_website import BaseWebsite

_RESERVED = {
    "category", "tag", "page", "author", "wp-content", "wp-json", "wp-includes",
    "feed", "comments", "xmlrpc.php", "search", "login", "signup", "register",
    "about", "contact", "privacy", "dmca", "terms", "forum", "cdn-cgi",
    "cart", "account", "home", "start", "homepage", "submit", "upload",
    "disclaimer", "sitemap", "wp-admin", "2257", "faq", "help", "support",
}
_BLOCKED = ("teen", "teens", "underage", "preteen", "lolita", "jailbait", "child", "children")
_SKIP_URL = ("logo", "icon", "favicon", "sprite", "emoji", "avatar", "placeholder", "blank.gif", "1x1", "spinner")
_LAZY_ATTRS = ("data-lazy-src", "data-src", "data-original", "data-bg", "data-lazy", "data-lazy-srcset", "data-srcset", "srcset", "src")


def _blocked(value):
    words = re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).split()
    return any(word in _BLOCKED for word in words)


def _absolute(base_url, href):
    href = html.unescape(href or "").strip()
    if href.startswith("//"):
        return "https:" + href
    return urllib.parse.urljoin(base_url, href)


def _same(url, host):
    netloc = urllib.parse.urlparse(url).netloc.lower()
    return netloc == host or netloc.endswith("." + host)


def _image_candidates(blob):
    for part in html.unescape(blob or "").split(","):
        raw = part.strip().split(" ")[0]
        if re.search(r"\.(?:jpe?g|png|webp)(?:$|\?)", raw, re.IGNORECASE):
            yield raw


def _srcset_best(blob):
    best_url = ""
    best_width = -1
    for part in html.unescape(blob or "").split(","):
        bits = part.strip().split()
        if not bits:
            continue
        raw = bits[0]
        if not re.search(r"\.(?:jpe?g|png|webp)(?:$|\?)", raw, re.IGNORECASE):
            continue
        width = 0
        if len(bits) > 1 and bits[1].endswith("w"):
            try:
                width = int(bits[1][:-1])
            except ValueError:
                width = 0
        if width >= best_width:
            best_width = width
            best_url = raw
    return best_url


def _tag_image(tag):
    for attr in ("data-lazy-src", "data-src", "data-original", "data-bg", "data-lazy"):
        match = re.search(r'\b{}="([^"]+)"'.format(attr), tag, re.IGNORECASE)
        if match:
            for raw in _image_candidates(match.group(1)):
                return raw
    for attr in ("data-lazy-srcset", "data-srcset", "srcset"):
        match = re.search(r'\b{}="([^"]+)"'.format(attr), tag, re.IGNORECASE)
        if match:
            best = _srcset_best(match.group(1))
            if best:
                return best
    match = re.search(r'\bsrc="([^"]+)"', tag, re.IGNORECASE)
    if match:
        for raw in _image_candidates(match.group(1)):
            return raw
    return ""


def _keep_image(url):
    if not url.startswith("http") or url.startswith("data:") or _blocked(url):
        return False
    low = url.lower()
    return not any(bit in low for bit in _SKIP_URL)


def images(content, base_url):
    found = []
    seen = set()
    for tag in re.findall(r"<img\b[^>]*>", content or "", re.IGNORECASE):
        raw = _tag_image(tag)
        if not raw:
            continue
        src = _absolute(base_url, raw)
        if not _keep_image(src) or src in seen:
            continue
        seen.add(src)
        found.append(src)
    if found:
        return found
    for attr in _LAZY_ATTRS:
        for blob in re.findall(r'\b{}="([^"]+)"'.format(attr), content or "", re.IGNORECASE):
            for raw in _image_candidates(blob):
                src = _absolute(base_url, raw)
                if not _keep_image(src) or src in seen:
                    continue
                seen.add(src)
                found.append(src)
    return found


def _thumb_from(block, base_url):
    for tag in re.findall(r"<img\b[^>]*>", block or "", re.IGNORECASE):
        raw = _tag_image(tag)
        if not raw:
            continue
        candidate = _absolute(base_url, raw)
        if _keep_image(candidate):
            return candidate
    return ""


def _one_permalink(block, base_url, host):
    direct = None
    fallback = None
    for match in re.finditer(r'href="([^"]+)"', block or "", re.IGNORECASE):
        href = html.unescape(match.group(1)).split("#")[0]
        if href.startswith("javascript") or href.startswith("mailto:"):
            continue
        full = _absolute(base_url, href).split("?")[0]
        if not _same(full, host):
            continue
        parts = [part for part in urllib.parse.urlparse(full).path.split("/") if part]
        if not parts or parts[0].lower() in _RESERVED or _blocked("/".join(parts)):
            continue
        if not full.endswith("/"):
            full += "/"
        if len(parts) == 1 and len(parts[0]) >= 6:
            direct = (full, parts)
            break
        if len(parts[-1]) >= 6 and (fallback is None or len(parts) > len(fallback[1])):
            fallback = (full, parts)
    return direct or fallback


def _permalinks(content, base_url, host):
    blocks = re.findall(r"<article\b[\s\S]*?</article>", content or "", re.IGNORECASE)
    cards = []
    seen = set()
    if blocks:
        scopes = [(block, True) for block in blocks]
    else:
        scopes = [(content or "", False)]
    for block, from_article in scopes:
        if from_article:
            picked = _one_permalink(block, base_url, host)
            picks = [picked] if picked else []
        else:
            picks = []
            for match in re.finditer(r'href="([^"]+)"', block, re.IGNORECASE):
                href = html.unescape(match.group(1)).split("#")[0]
                full = _absolute(base_url, href).split("?")[0]
                if not _same(full, host):
                    continue
                parts = [part for part in urllib.parse.urlparse(full).path.split("/") if part]
                if len(parts) != 1 or parts[0].lower() in _RESERVED or len(parts[0]) < 6 or _blocked(parts[0]):
                    continue
                if not full.endswith("/"):
                    full += "/"
                picks.append((full, parts))
        for picked in picks:
            if not picked:
                continue
            full, parts = picked
            if full in seen:
                continue
            seen.add(full)
            title = parts[-1].replace("-", " ").replace("_", " ").title() or "Post"
            cards.append({
                "href": full,
                "title": title,
                "thumb": _thumb_from(block, base_url),
            })
    return cards


class LeakWebsite(BaseWebsite):
    site_name = ""
    site_base = ""
    site_host = ""
    site_label = ""

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name=self.site_name,
            base_url=self.site_base,
            search_url=self.site_base + "?s={}",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.label = self.site_label
        self.host = self.site_host
        self.last_url = self.site_base
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
                self.last_url = response.url or url
                final = urllib.parse.urlparse(response.url).netloc.lower()
                if final.startswith("www."):
                    final = final[4:]
                stem = (self.host or "").split(".")[0]
                if stem and final.startswith(stem) and final != self.host:
                    self.host = final
                return response.text
        except Exception as exc:
            self.logger.warning("%s request failed: %s", self.label, exc)
        return ""

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
            path = urllib.parse.urlparse(url).path.strip("/")
            if page == 1 and path in ("",):
                self.add_dir("Search", "", 5, self.icons["search"])
            for card in _permalinks(content, self.last_url or self.base_url, self.host):
                self.add_dir(card["title"], card["href"], 2, card["thumb"] or self.icon)
                count += 1
            nxt = re.search(r'href="(https?://[^"]+/page/\d+/)"', content or "", re.IGNORECASE)
            if nxt and _same(nxt.group(1), self.host):
                self.add_dir("Next Page", nxt.group(1), 2, self.icons["default"])
        else:
            for index, image in enumerate(images(content, self.last_url or url), 1):
                label = "Photo {}".format(index)
                self.add_link(
                    label, image, 4, image, self.fanart,
                    info_labels={"title": label, "plot": label},
                    referer=url,
                )
                count += 1
        if not count:
            self.notify_error("No {} items found".format(self.label))
        self.end_directory("videos")

    def play_video(self, url):
        item = xbmcgui.ListItem(path=url)
        item.setProperty("IsPlayable", "true")
        xbmcplugin.setResolvedUrl(self.addon_handle, True, item)
