#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import urllib.parse

import xbmc

from resources.lib.kvs_tube import KVSTubeWebsite
from resources.lib.media_probe import make_session

_BLOCKED = ("teen", "teens", "underage", "preteen", "lolita", "jailbait", "child", "children")
_AGE = re.compile(r"\b(?:1[0-7]|[1-9])\s*(?:yo|y\.o\.?|years?\s*old)\b", re.IGNORECASE)
_PREVIEW = ("trailer", "preview", "teaser", "sample", "thumb", "poster")
_DURATION = re.compile(r"(\d+)\s*h(?:\s*(\d+)\s*min)?|(\d+)\s*min", re.IGNORECASE)


def _skip(value):
    words = re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).split()
    if any(word in _BLOCKED for word in words):
        return True
    return bool(_AGE.search(value or ""))


def _seconds(text):
    match = _DURATION.search(text or "")
    if not match:
        return 0
    if match.group(1):
        return int(match.group(1)) * 3600 + int(match.group(2) or 0) * 60
    return int(match.group(3) or 0) * 60


class Pissvids(KVSTubeWebsite):
    label = "PissVids"
    sort_options = ["Latest", "Best"]
    sort_paths = {
        "Latest": "/new-videos/",
        "Best": "/best-videos/",
    }
    categories_path = "/genres/"
    models_path = "/models/"
    category_path_markers = ("/genre/",)
    video_path_markers = ("/watch/",)
    use_playback_proxy = True

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="pissvids",
            base_url="https://pissvids.com/",
            search_url="https://pissvids.com/search/{}/",
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
                    return response.text
                last_error = "HTTP {}".format(response.status_code)
            except Exception as exc:
                last_error = exc
                self.session = make_session()
            if attempt < max_retries:
                xbmc.sleep(650 * attempt)
        self.logger.error("%s failed to fetch listing page: %s", self.label or self.name, last_error)
        return ""

    def get_page_url(self, base_url, page_num):
        parsed = urllib.parse.urlparse(base_url or self.base_url)
        path = parsed.path or "/"
        if path in ("", "/"):
            path = "/new-videos/"
        if not path.endswith("/"):
            path += "/"
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        query.pop("page", None)
        if page_num and page_num > 1:
            query["page"] = [str(page_num)]
        scheme = parsed.scheme or urllib.parse.urlparse(self.base_url).scheme or "https"
        netloc = parsed.netloc or urllib.parse.urlparse(self.base_url).netloc
        return urllib.parse.urlunparse((
            scheme,
            netloc,
            path,
            "",
            urllib.parse.urlencode(query, doseq=True),
            "",
        ))

    def _extract_videos(self, html_content):
        videos = []
        seen = set()
        blocks = re.split(
            r'(?=<div\b[^>]+class=["\'][^"\']*\bcard-scene\b)',
            html_content or "",
            flags=re.IGNORECASE,
        )
        for block in blocks:
            href_match = re.search(r'href=["\']([^"\']*/watch/\d+/[^"\']*)["\']', block, re.IGNORECASE)
            if not href_match:
                continue
            video_url = self._absolute(href_match.group(1))
            if not video_url or video_url in seen or _skip(video_url):
                continue
            title_match = re.search(
                r'card-scene__text[\s\S]{0,500}?<(?:a|span|h\d)\b[^>]*>([\s\S]{0,240}?)</',
                block,
                re.IGNORECASE,
            )
            if not title_match:
                title_match = re.search(r'\stitle=["\']([^"\']+)["\']', block, re.IGNORECASE)
            title = self._clean(title_match.group(1) if title_match else "")
            if not title or _skip(title):
                continue
            seen.add(video_url)
            thumb_match = re.search(r'\bdata-src=["\']([^"\']+)["\']', block, re.IGNORECASE)
            thumb = self._absolute(thumb_match.group(1)) if thumb_match else ""
            if thumb.startswith("data:"):
                thumb = ""
            duration_match = re.search(r'label--time[^>]*>([^<]+)', block, re.IGNORECASE)
            duration = self._clean(duration_match.group(1) if duration_match else "")
            seconds = _seconds(duration)
            clip_match = re.search(r'\bdata-preview=["\']([^"\']+)["\']', block, re.IGNORECASE)
            clip = self._absolute(clip_match.group(1)) if clip_match else ""
            if clip.startswith("data:") or _skip(clip):
                clip = ""
            label = "{} [COLOR lime]({})[/COLOR]".format(title, duration) if duration else title
            info = {"title": title, "plot": title}
            if seconds:
                info["duration"] = seconds
            videos.append({
                "label": label,
                "url": video_url,
                "thumb": thumb or self.icon,
                "info": info,
                "clip": clip,
            })
        return videos

    def _extract_next_page(self, html_content, current_url, page):
        path = urllib.parse.urlparse(current_url or "").path.lower()
        if "/search/" in path or "/model/" in path:
            return None
        return self.get_page_url(current_url, (page or 1) + 1)

    def process_content(self, url, page=1):
        if not url or url == "BOOTSTRAP":
            url, _ = self.get_start_url_and_label()
        context_menu = self._context_menu(url)
        if self._is_top_listing(url):
            self.add_dir("Search", "", 5, self.icons.get("search", self.icon), context_menu=context_menu)
            if self.categories_path:
                self.add_dir("Categories", self._absolute(self.categories_path), 8, self.icons.get("categories", self.icon), context_menu=context_menu)
            if self.models_path:
                self.add_dir("Models", self._absolute(self.models_path), 8, self.icons.get("pornstars", self.icon), context_menu=context_menu)
        target_url = self.get_page_url(url, page)
        html_content = self._get(target_url)
        if not html_content:
            self.notify_error("Could not load {} listing".format(self.label or self.name))
            self.end_directory("videos")
            return
        videos = self._extract_videos(html_content)
        if not videos:
            self.notify_error("No {} videos found".format(self.label or self.name))
            return self.end_directory("videos")
        for item in videos:
            self.add_link(
                item["label"],
                item["url"],
                4,
                item["thumb"],
                self.fanart,
                context_menu=context_menu,
                info_labels=item["info"],
                clip=item.get("clip") or None,
            )
        if self._extract_next_page(html_content, target_url, page):
            self.add_dir("Next Page", url, 2, self.icons.get("default", self.icon), context_menu=context_menu, page=page + 1)
        self.end_directory("videos")

    def process_categories(self, url):
        saved = self.models_path
        path = urllib.parse.urlparse(url or "").path
        if path.rstrip("/") == "/models" or path.startswith("/models/"):
            self.models_path = "/model"
        try:
            return super().process_categories(url)
        finally:
            self.models_path = saved

    def add_dir(self, name, url, mode, icon=None, fanart=None, context_menu=None, name_param=None, info_labels=None, **kwargs):
        if _skip(name) or _skip(url):
            return
        super().add_dir(name, url, mode, icon, fanart, context_menu, name_param, info_labels, **kwargs)

    def _stream_candidates(self, html_content):
        found = []
        for tag in re.findall(r"<source\b([^>]*)>", html_content or "", re.IGNORECASE):
            src_match = re.search(r'\bsrc=["\']([^"\']+)["\']', tag, re.IGNORECASE)
            if not src_match:
                continue
            stream_url = self._normalize_stream(src_match.group(1))
            lowered = stream_url.lower()
            if not stream_url.startswith("http") or _skip(stream_url):
                continue
            if any(token in lowered for token in _PREVIEW) or "video-preview" in lowered:
                continue
            if ".mp4" not in lowered:
                continue
            size_match = re.search(r'\bsize=["\'](\d+)["\']', tag, re.IGNORECASE)
            size = int(size_match.group(1)) if size_match else 0
            found.append((size, stream_url))
        found.sort(key=lambda item: item[0], reverse=True)
        return found

    def _probe_ok(self, stream_url, referer):
        try:
            headers = self._headers(referer, accept="*/*")
            headers["Range"] = "bytes=0-1"
            response = self.session.get(stream_url, headers=headers, timeout=15, stream=True, allow_redirects=True)
            ctype = (response.headers.get("Content-Type") or "").lower()
            ok = response.status_code in (200, 206) and ("video" in ctype or "mpegurl" in ctype or "octet-stream" in ctype)
            response.close()
            return ok
        except Exception:
            return False

    def _extract_stream_url(self, html_content, referer=None):
        candidates = self._stream_candidates(html_content)
        for _size, stream_url in candidates:
            if self._probe_ok(stream_url, referer or self.base_url):
                return stream_url
        if candidates:
            return candidates[0][1]
        return None
