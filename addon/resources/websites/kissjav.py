#!/usr/bin/env python
# -*- coding: utf-8 -*-

import base64
import html
import re
import urllib.parse

import xbmc

from resources.lib.kvs_tube import KVSTubeWebsite
from resources.lib.media_probe import make_session

_BLOCKED = ("teen", "teens", "underage", "preteen", "lolita", "jailbait", "child", "children")
_AGE = re.compile(r"\b(?:1[0-7]|[1-9])\s*(?:yo|y\.o\.?|years?\s*old)\b", re.IGNORECASE)
_PREVIEW = ("trailer", "preview", "teaser", "sample")


def _skip(value):
    text = (value or "").replace("_", " ")
    words = re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
    if any(word in _BLOCKED for word in words):
        return True
    return bool(_AGE.search(text))


def _b64(value):
    try:
        pad = value + "=" * ((4 - len(value) % 4) % 4)
        return base64.b64decode(pad).decode("utf-8", "ignore")
    except Exception:
        return ""


class Kissjav(KVSTubeWebsite):
    label = "KissJAV"
    sort_options = ["Latest", "Most Viewed"]
    sort_paths = {
        "Latest": "/latest-updates/",
        "Most Viewed": "/most-popular/",
    }
    categories_path = "/categories/"
    models_path = None
    video_path_markers = ("/video/",)
    category_path_markers = ("/categories/", "/tags/")
    directory_path_prefixes = ("/categories/", "/tags/")
    next_page_full_count = 24
    use_playback_proxy = False

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="kissjav",
            base_url="https://kissjav.li/",
            search_url="https://kissjav.li/search/{}/",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.session = make_session()

    def _headers(self, referer=None, accept=None):
        headers = super()._headers(referer, accept)
        for key, value in list(headers.items()):
            if not isinstance(value, str):
                continue
            try:
                value.encode("latin-1")
            except UnicodeEncodeError:
                headers[key] = urllib.parse.quote(value, safe=":/%?#[]@!$&'()*+,;=")
        return headers

    def _get(self, url, referer=None, max_retries=None):
        if max_retries is None:
            max_retries = self.request_retries
        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                response = self.session.get(url, headers=self._headers(referer), timeout=20)
                if response.status_code == 200 and response.text:
                    return response.text
                last_error = "HTTP {}".format(response.status_code)
            except Exception as exc:
                last_error = exc
                self.session = make_session()
            if attempt < max_retries:
                xbmc.sleep(650 * attempt)
        self.logger.error("%s failed to fetch listing page: %s", self.label or self.name, last_error)
        return ""

    def _normalize_stream(self, value, license_code=None):
        raw = html.unescape(value or "").replace("\\/", "/").strip()
        if raw and not raw.startswith(("http://", "https://", "function/", "/")):
            decoded = _b64(raw)
            if decoded.startswith(("http://", "https://", "function/", "/")):
                raw = decoded
        return super()._normalize_stream(raw, license_code)

    def _is_stream_candidate(self, value):
        if not super()._is_stream_candidate(value):
            return False
        low = (value or "").lower()
        return not any(token in low for token in _PREVIEW)

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
        super().add_dir(name, url, mode, icon, fanart, context_menu, name_param, info_labels, **kwargs)

    def search(self, query):
        if _skip(query):
            self.end_directory("videos")
            return
        super().search(query)
