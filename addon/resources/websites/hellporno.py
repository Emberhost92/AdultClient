#!/usr/bin/env python
# -*- coding: utf-8 -*-

import html
import re
import urllib.parse

import xbmc

from resources.lib.kvs_tube import KVSTubeWebsite
from resources.lib.media_probe import make_session

_BLOCKED = ("teen", "teens", "underage", "preteen", "lolita", "jailbait", "child", "children")
_AGE = re.compile(r"\b(?:1[0-7]|[1-9])\s*(?:yo|y\.o\.?|years?\s*old)\b", re.IGNORECASE)
_PREVIEW = ("trailer", "preview", "teaser", "sample")
_MIN_BYTES = 8000000


def _skip(value):
    text = (value or "").replace("_", " ")
    words = re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
    if any(word in _BLOCKED for word in words):
        return True
    return bool(_AGE.search(text))


class Hellporno(KVSTubeWebsite):
    label = "HellPorno"
    sort_options = ["Latest"]
    sort_paths = {"Latest": "/"}
    categories_path = None
    models_path = None
    video_path_markers = ("/videos/",)
    next_page_full_count = 0
    use_playback_proxy = False

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="hellporno",
            base_url="https://hellporno.com/",
            search_url="https://hellporno.com/search/?q={}",
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

    def _extract_next_page(self, html_content, current_url, page):
        return None

    def _measured_size(self, stream_url, referer):
        low = (stream_url or "").lower()
        if not stream_url or any(token in low for token in _PREVIEW):
            return 0
        playlist = ".m3u8" in low
        headers = self._headers(referer, accept="*/*")
        if not playlist:
            headers["Range"] = "bytes=0-1"
        try:
            response = self.session.get(stream_url, headers=headers, timeout=15, allow_redirects=True, stream=True)
        except Exception:
            return 0
        try:
            status = response.status_code
            ctype = (response.headers.get("Content-Type") or "").lower()
            if status not in (200, 206):
                return 0
            if playlist or "mpegurl" in ctype or "#EXTM3U" in (response.headers.get("Content-Type") or ""):
                body = response.raw.read(20000) or b""
                duration = 0.0
                for line in body.decode("utf-8", "ignore").splitlines():
                    if line.startswith("#EXTINF:"):
                        try:
                            duration += float(line.split(":", 1)[1].split(",")[0])
                        except ValueError:
                            pass
                return _MIN_BYTES if duration >= 90 else 0
            if "video" not in ctype and "octet-stream" not in ctype:
                return 0
            match = re.search(r"/(\d+)", response.headers.get("Content-Range") or "")
            if match:
                return int(match.group(1))
            length = response.headers.get("Content-Length") or ""
            return int(length) if length.isdigit() else 0
        finally:
            response.close()

    def _extract_stream_url(self, html_content, referer=None):
        text = html.unescape(html_content or "").replace("\\/", "/")
        license_match = re.search(r"license_code\s*:\s*['\"]([^'\"]+)['\"]", text, re.IGNORECASE)
        license_code = license_match.group(1).strip() if license_match else ""
        ordered = []
        ordered.extend(re.findall(r"https?://[^\"'\s>]+\.m3u8[^\"'\s>]*", text, re.IGNORECASE))
        ordered.extend(re.findall(r"['\"]([^'\"]*get_file/[^'\"]+)['\"]", text, re.IGNORECASE))
        ordered.extend(re.findall(r"(?:video_url|video_alt_url\d*)\s*:\s*['\"]([^'\"]+)['\"]", text, re.IGNORECASE))
        ordered.extend(re.findall(r"https?://[^\"'\s>]+\.mp4[^\"'\s>]*", text, re.IGNORECASE))
        seen = set()
        probed = 0
        for value in ordered:
            stream_url = self._normalize_stream(value, license_code)
            if not stream_url or stream_url in seen:
                continue
            seen.add(stream_url)
            if any(token in stream_url.lower() for token in _PREVIEW):
                continue
            probed += 1
            if self._measured_size(stream_url, referer) >= _MIN_BYTES:
                return stream_url
            if probed >= 6:
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
