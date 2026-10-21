#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import urllib.parse

import xbmc
import xbmcgui
import xbmcplugin

from resources.lib.kvs_tube import KVSTubeWebsite
from resources.lib.media_probe import make_session

_BLOCKED = ("teen", "teens", "underage", "preteen", "lolita", "jailbait", "child", "children")
_AGE = re.compile(r"\b(?:1[0-7]|[1-9])\s*(?:yo|y\.o\.?|years?\s*old)\b", re.IGNORECASE)


def _skip(value):
    text = (value or "").replace("_", " ")
    words = re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
    if any(word in _BLOCKED for word in words):
        return True
    return bool(_AGE.search(text))


class Wikifeet(KVSTubeWebsite):
    label = "WikiFeet"
    sort_options = ["Search"]
    sort_paths = {"Search": "/"}
    categories_path = None
    models_path = None
    next_page_full_count = 0
    use_playback_proxy = False

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="wikifeet",
            base_url="https://wikifeet.com/",
            search_url="https://wikifeet.com/api/suggest",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.session = make_session()

    def _headers(self, referer=None, accept=None):
        headers = super()._headers(referer, accept)
        headers["Origin"] = "https://wikifeet.com"
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

    def _profile_url(self, slug):
        return urllib.parse.urljoin(self.base_url, urllib.parse.quote(slug, safe=""))

    def _photo_url(self, slug, pid):
        return "https://pics.wikifeet.com/{}-Feet-{}.jpg".format(urllib.parse.quote(slug, safe=""), pid)

    def _results(self, query):
        try:
            response = self.session.post(
                self.search_url,
                headers=self._headers(self.base_url, accept="*/*"),
                files={"query": (None, query)},
                timeout=20,
            )
            data = response.json()
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        for item in data:
            if isinstance(item, list) and item and item[0] == "tdata" and isinstance(item[1], dict):
                rows = item[1].get("searchresults") or []
                return rows if isinstance(rows, list) else []
        return []

    def process_content(self, url, page=1):
        if not url or url == "BOOTSTRAP":
            url, _ = self.get_start_url_and_label()
        parsed = urllib.parse.urlparse(url)
        slug = urllib.parse.unquote(parsed.path.strip("/").split("/")[0] if parsed.path.strip("/") else "")
        if not slug or _skip(slug):
            if page <= 1 and self._is_top_listing(url):
                self.add_dir("Search", "", 5, self.icons.get("search", self.icon), context_menu=self._context_menu(url))
            self.end_directory("videos")
            return
        html_content = self._get(self._profile_url(slug), referer=self.base_url)
        pids = []
        seen = set()
        for pid in re.findall(r'"pid"\s*:\s*(\d+)', html_content or ""):
            if pid in seen:
                continue
            seen.add(pid)
            pids.append(pid)
        if not pids:
            self.notify_error("No {} photos found".format(self.label or self.name))
            self.end_directory("videos")
            return
        referer = self._profile_url(slug)
        for index, pid in enumerate(pids, 1):
            photo = self._photo_url(slug, pid)
            thumb = "https://thumbs.wikifeet.com/{}.jpg".format(pid)
            self.add_link(
                "Photo {}".format(index),
                photo,
                4,
                thumb,
                self.fanart,
                info_labels={"title": "Photo {}".format(index), "plot": "Photo {}".format(index)},
                referer=referer,
            )
        self.end_directory("videos")

    def search(self, query):
        cleaned = (query or "").strip()
        if _skip(cleaned) or len(cleaned) < 2:
            self.end_directory("videos")
            return
        shown = 0
        for row in self._results(cleaned):
            if not isinstance(row, dict):
                continue
            name = (row.get("name") or "").strip()
            slug = (row.get("fetchname") or "").strip()
            if not name or not slug or _skip(name) or _skip(slug):
                continue
            count = row.get("pcount")
            label = name
            if isinstance(count, int) and count > 0:
                label = "{} ({})".format(name, count)
            self.add_dir(label, self._profile_url(slug), 2, self.icon, self.fanart)
            shown += 1
        if not shown:
            self.notify_error("No {} results found".format(self.label or self.name))
        self.end_directory("videos")

    def play_video(self, url):
        if not re.search(r"\.(?:jpe?g|png|webp)(?:$|\?)", (url or "").lower()):
            self.notify_error("Could not resolve stream URL")
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return
        headers = self._headers(self.base_url, accept="image/*,*/*")
        play_url = "{}|{}".format(url, urllib.parse.urlencode(headers))
        list_item = xbmcgui.ListItem(path=play_url)
        list_item.setProperty("IsPlayable", "true")
        lowered = url.lower()
        if ".webp" in lowered:
            mime = "image/webp"
        elif ".png" in lowered:
            mime = "image/png"
        else:
            mime = "image/jpeg"
        list_item.setMimeType(mime)
        list_item.setContentLookup(False)
        xbmcplugin.setResolvedUrl(self.addon_handle, True, list_item)
