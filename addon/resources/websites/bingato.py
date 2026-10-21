#!/usr/bin/env python
# -*- coding: utf-8 -*-

import html
import re
import urllib.parse

import requests
import xbmc
import xbmcgui
import xbmcplugin

from resources.lib.base_website import BaseWebsite
from resources.lib.proxy_utils import PlaybackGuard, ProxyController


class Bingato(BaseWebsite):
    label = "Bingato"

    def __init__(self, addon_handle, addon=None):
        super().__init__("bingato", "https://bingato.com/", "https://bingato.com/search?q={}", addon_handle, addon)
        self.session = requests.Session()
        self.ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"

    def _get(self, url):
        try:
            response = self.session.get(url, headers={"User-Agent": self.ua, "Referer": self.base_url}, timeout=20)
            response.raise_for_status()
            return response.text
        except Exception as exc:
            self.logger.warning("Bingato request failed for %s: %s", url, exc)
            return ""

    def _page_url(self, url, page):
        if page <= 1:
            return url
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        query["page"] = [str(page)]
        return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urllib.parse.urlencode(query, doseq=True), parsed.fragment))

    @staticmethod
    def _clean(value):
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(value or ""))).strip()

    def process_content(self, url, page=1):
        top = not url or url == "BOOTSTRAP" or url.rstrip("/") == self.base_url.rstrip("/")
        url = self.base_url if top else url
        if top:
            self.add_dir("Search", "", 5, self.icons.get("search", self.icon))
            self.add_dir("Categories", self.base_url + "categories", 8, self.icons.get("categories", self.icon))
            self.add_dir("Models", self.base_url + "babes", 8, self.icons.get("pornstars", self.icon))
        content = self._get(self._page_url(url, page))
        seen = set()
        for block in re.split(r'(?=<div\b[^>]+class=["\'][^"\']*\bitem\b[^"\']*["\'])', content, flags=re.I):
            link = re.search(r'<a\b[^>]+href=["\']([^"\']*/item/[^"\']+)', block, re.I)
            title = re.search(r'<a\b[^>]+title=["\']([^"\']+)', block, re.I)
            image = re.search(r'<img\b[^>]+(?:data-original|src)=["\']([^"\']+)', block, re.I)
            duration = re.search(r'(?:duration|time)[^>]*>([^<]+)', block, re.I)
            if not link or not title:
                continue
            target = urllib.parse.urljoin(self.base_url, link.group(1))
            if target in seen:
                continue
            seen.add(target)
            name = self._clean(title.group(1)); length = self._clean(duration.group(1)) if duration else ""
            info = {"title": name, "plot": name}
            if length: info["duration"] = self.convert_duration(length)
            self.add_link("{} [COLOR lime]({})[/COLOR]".format(name, length) if length else name, target, 4, image.group(1) if image else self.icon, self.fanart, info_labels=info)
        if seen and re.search(r'href=["\'](?:/|https://bingato\.com/)?\?page={}'.format(page + 1), content, re.I):
            self.add_dir("Next Page", url, 2, self.icon, page=page + 1)
        self.end_directory("videos")

    def process_categories(self, url):
        content = self._get(url)
        seen = set()
        for href, title in re.findall(r'<a\b[^>]+href=["\']([^"\']+)["\'][^>]*>([\s\S]{0,400}?)</a>', content, re.I):
            target = urllib.parse.urljoin(self.base_url, href)
            if not any(part in urllib.parse.urlparse(target).path for part in ("/category/", "/categories/", "/babes/", "/c/")):
                continue
            name = self._clean(title)
            if not name or target in seen:
                continue
            seen.add(target)
            self.add_dir(name, target, 2, self.icons.get("categories", self.icon))
        self.end_directory("videos")

    def play_video(self, url):
        content = self._get(url)
        source = re.search(r'<source\b[^>]+src=["\']([^"\']+)', content, re.I)
        if not source:
            return self.notify_error("Could not resolve Bingato stream")
        stream = html.unescape(source.group(1))
        proxy = ProxyController(stream, upstream_headers={"User-Agent": self.ua, "Referer": url}, use_urllib=True, probe_size=True)
        local_url = proxy.start(); guard = PlaybackGuard(xbmc.Player(), xbmc.Monitor(), local_url, proxy); guard.start()
        item = xbmcgui.ListItem(path=local_url); item.setProperty("IsPlayable", "true"); item.setMimeType("video/mp4"); item.setContentLookup(False)
        xbmcplugin.setResolvedUrl(self.addon_handle, True, item); guard.join()
