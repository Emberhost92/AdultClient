#!/usr/bin/env python
# -*- coding: utf-8 -*-

import html
import re
import urllib.parse

import xbmc
import xbmcgui
import xbmcplugin

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


class Hdsex(KVSTubeWebsite):
    label = "HDSex"
    sort_options = ["Latest"]
    sort_paths = {"Latest": "/"}
    categories_path = "/categories/"
    models_path = None
    video_path_markers = ("/video/",)
    category_path_markers = ("/categories/", "/tags/")
    directory_path_prefixes = ("/categories/", "/tags/")
    next_page_full_count = 0
    use_playback_proxy = False

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="hdsex",
            base_url="https://hdsex.org/",
            search_url="https://hdsex.org/search/{}/",
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

    def _is_video_href(self, href):
        path = urllib.parse.urlparse(href or "").path
        return path.startswith("/video/") and not path.startswith("/videos/")

    def _extract_next_page(self, html_content, current_url, page):
        return None

    def _playlist_seconds(self, stream_url, referer):
        headers = self._headers(referer, accept="*/*")
        try:
            response = self.session.get(stream_url, headers=headers, timeout=15, allow_redirects=True)
        except Exception:
            return 0
        try:
            if response.status_code not in (200, 206):
                return 0
            duration = 0.0
            for line in response.text[:20000].splitlines():
                if line.startswith("#EXTINF:"):
                    try:
                        duration += float(line.split(":", 1)[1].split(",")[0])
                    except ValueError:
                        pass
            return duration
        finally:
            response.close()

    def _extract_stream_url(self, html_content, referer=None):
        text = html.unescape(html_content or "").replace("\\/", "/")
        seen = set()
        probed = 0
        for value in re.findall(r"https?://[^\"'\s>]+\.m3u8[^\"'\s>]*", text, re.IGNORECASE):
            stream_url = self._normalize_stream(value)
            if not stream_url or stream_url in seen:
                continue
            seen.add(stream_url)
            if any(token in stream_url.lower() for token in _PREVIEW):
                continue
            probed += 1
            if self._playlist_seconds(stream_url, referer) >= 90:
                return stream_url
            if probed >= 4:
                break
        return None

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

    def play_video(self, url):
        resolved = self.resolve_recording_stream(url)
        if not resolved:
            self.notify_error("Could not resolve stream URL")
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return
        play_url = resolved["url"]
        headers = resolved.get("headers") or {}
        if headers:
            play_url = "{}|{}".format(play_url, urllib.parse.urlencode(headers))
        list_item = xbmcgui.ListItem(path=play_url)
        list_item.setProperty("IsPlayable", "true")
        list_item.setMimeType("application/vnd.apple.mpegurl")
        list_item.setContentLookup(False)
        xbmcplugin.setResolvedUrl(self.addon_handle, True, list_item)
