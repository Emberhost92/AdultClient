#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import urllib.parse

import xbmc

from resources.lib.kvs_tube import KVSTubeWebsite
from resources.lib.media_probe import make_session

_BLOCKED = ("teen", "teens", "underage", "preteen", "lolita", "jailbait", "child", "children")
_AGE = re.compile(r"\b(?:1[0-7]|[1-9])\s*(?:yo|y\.o\.?|years?\s*old)\b", re.IGNORECASE)
_PREVIEW = ("trailer", "preview", "teaser", "sample")
_LANG = {"de", "es", "fr", "it", "ja", "pt", "ru", "tr", "zh", "en"}


def _skip(value):
    words = re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).split()
    if any(word in _BLOCKED for word in words):
        return True
    return bool(_AGE.search(value or ""))


class Perverttube(KVSTubeWebsite):
    label = "PervertTube"
    sort_options = ["Latest", "Most Viewed", "Top Rated"]
    sort_paths = {
        "Latest": "/latest-updates/",
        "Most Viewed": "/most-popular/",
        "Top Rated": "/top-rated/",
    }
    categories_path = "/categories/"
    models_path = "/models/"
    video_path_markers = ("/video/",)
    directory_path_prefixes = ("/categories/", "/tags/")
    next_page_full_count = 30
    use_playback_proxy = True

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="perverttube",
            base_url="https://perverttube.com/",
            search_url="https://perverttube.com/search/{}/",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.session = make_session()

    def _get(self, url, referer=None, max_retries=None):
        if max_retries is None:
            max_retries = self.request_retries
        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                response = self.session.get(url, headers=self._headers(referer), timeout=15)
                if response.status_code == 200 and response.text:
                    return self._prepare_html(url, response.text)
                last_error = "HTTP {}".format(response.status_code)
            except Exception as exc:
                last_error = exc
                self.session = make_session()
            if attempt < max_retries:
                xbmc.sleep(650 * attempt)
        self.logger.error("%s failed to fetch listing page: %s", self.label or self.name, last_error)
        return ""

    def _prepare_html(self, url, text):
        path = urllib.parse.urlparse(url or "").path or ""
        if not re.fullmatch(r"/models(?:/\d+)?/?", path):
            return text
        return re.sub(
            r'(<a\b[^>]*class=["\'][^"\']*\bitem\b[^"\']*["\'][^>]*>)',
            r'\1<img alt="">',
            text,
            flags=re.IGNORECASE,
        )

    def _extract_videos(self, html_content):
        videos = []
        for item in super()._extract_videos(html_content):
            if _skip(item.get("url", "")) or _skip(item.get("info", {}).get("title", "")):
                continue
            videos.append(item)
        return videos

    def add_dir(self, name, url, mode, icon=None, fanart=None, context_menu=None, name_param=None, info_labels=None, **kwargs):
        if _skip(name) or _skip(url):
            return
        parts = [part for part in urllib.parse.urlparse(url or "").path.split("/") if part]
        if parts and parts[0] in _LANG:
            return
        super().add_dir(name, url, mode, icon, fanart, context_menu, name_param, info_labels, **kwargs)

    def search(self, query):
        if _skip(query):
            self.end_directory("videos")
            return
        super().search(query)

    def _is_stream_candidate(self, value):
        if not super()._is_stream_candidate(value):
            return False
        low = (value or "").lower()
        return not any(token in low for token in _PREVIEW)

    def _extract_next_page(self, html_content, current_url, page):
        path = urllib.parse.urlparse(current_url or "").path
        if "/search/" in path:
            self.next_page_full_count = 0
            return None
        self.next_page_full_count = 30
        return super()._extract_next_page(html_content, current_url, page)
