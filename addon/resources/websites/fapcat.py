#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import urllib.parse

import xbmc

from resources.lib.kvs_tube import KVSTubeWebsite
from resources.lib.media_probe import make_session

_BLOCKED = ("teen", "teens", "underage", "preteen", "lolita", "jailbait", "child", "children")
_AGE = re.compile(r"\b(?:1[0-7]|[1-9])\s*(?:yo|y\.o\.?|years?\s*old)\b", re.IGNORECASE)
_VIDEO_BLOCK = "list_videos_common_videos_list"


def _skip(value):
    words = re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).split()
    if any(word in _BLOCKED for word in words):
        return True
    return bool(_AGE.search(value or ""))


class Fapcat(KVSTubeWebsite):
    label = "FapCat"
    sort_options = ["Latest", "Most Viewed", "Top Rated", "Longest"]
    sort_paths = {
        "Latest": "/latest-updates/",
        "Most Viewed": "/most-popular/",
        "Top Rated": "/top-rated/",
        "Longest": "/latest-updates/?sort_by=duration",
    }
    categories_path = "/categories/"
    models_path = "/models/"
    video_path_markers = ("/videos/",)
    use_playback_proxy = True

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="fapcat",
            base_url="https://fapcat.com/",
            search_url="https://fapcat.com/search/{}/",
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
                headers = self._headers(referer)
                if "function=get_block" in (url or ""):
                    headers["X-Requested-With"] = "XMLHttpRequest"
                response = self.session.get(url, headers=headers, timeout=15)
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

    def _video_ids(self, html_content):
        return set(re.findall(r"/videos/\d+/", html_content or "", re.IGNORECASE))

    def _pager(self, html_content):
        html_content = html_content or ""
        marker = 'id="{}{}"'.format(_VIDEO_BLOCK, "_pagination")
        pos = html_content.find(marker)
        if pos < 0:
            pos = html_content.lower().find(marker.lower())
        chunk = html_content[pos:pos + 20000] if pos >= 0 else ""
        for stop in ('id="list_models', 'class="section section-stars'):
            end = chunk.find(stop)
            if end > 0:
                chunk = chunk[:end]
                break
        sort_by = ""
        values = []
        for params in re.findall(r'data-parameters=["\']([^"\']+)["\']', chunk, re.IGNORECASE):
            sort_match = re.search(r"sort_by:([A-Za-z0-9_]+)", params)
            from_match = re.search(r"from1:(\d+)", params)
            if sort_match and not sort_by:
                sort_by = sort_match.group(1)
            if not from_match:
                continue
            number = int(from_match.group(1))
            if number not in values:
                values.append(number)
        return sort_by or "post_date", values

    def _ajax_listing(self, current_url, sort_by, number):
        parsed = urllib.parse.urlparse(current_url or self.base_url)
        query = {
            "mode": "async",
            "function": "get_block",
            "block_id": _VIDEO_BLOCK,
            "sort_by": sort_by or "post_date",
            "from1": str(number),
        }
        return urllib.parse.urlunparse((
            parsed.scheme or "https",
            parsed.netloc or urllib.parse.urlparse(self.base_url).netloc,
            parsed.path or "/",
            "",
            urllib.parse.urlencode(query),
            "",
        ))

    def _next_listing_url(self, current_url, html_content):
        sort_by, values = self._pager(html_content)
        if not values:
            return ""
        current_ids = self._video_ids(html_content)
        raw = urllib.parse.parse_qs(urllib.parse.urlparse(current_url or "").query).get("from1", [""])[0]
        current_from = int(raw) if str(raw).isdigit() else 0
        tried = 0
        for number in values:
            if number <= current_from:
                continue
            tried += 1
            if tried > 2:
                break
            candidate = self._ajax_listing(current_url, sort_by, number)
            nxt = self._get(candidate, referer=current_url)
            nxt_ids = self._video_ids(nxt)
            if nxt_ids and not nxt_ids <= current_ids:
                return candidate
        return ""

    def get_page_url(self, base_url, page_num):
        # The next page is already a full ajax URL. Do not append /2/.
        return base_url

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
                item["label"], item["url"], 4, item["thumb"], self.fanart,
                context_menu=context_menu, info_labels=item["info"],
            )
        next_url = self._next_listing_url(target_url, html_content)
        if next_url:
            self.add_dir(
                "Next Page", next_url, 2, self.icons.get("default", self.icon),
                context_menu=context_menu, page=1,
            )
        self.end_directory("videos")
