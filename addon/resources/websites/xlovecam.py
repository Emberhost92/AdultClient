#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
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


class Xlovecam(KVSTubeWebsite):
    label = "XloveCam"
    sort_options = []
    sort_paths = {}
    use_playback_proxy = False

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="xlovecam",
            base_url="https://www.xlovecam.com/",
            search_url="https://www.xlovecam.com/",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.session = make_session()

    def _headers(self, referer=None, accept=None):
        headers = super()._headers(referer, accept or "text/html,*/*")
        headers["Origin"] = "https://www.xlovecam.com"
        for key, value in list(headers.items()):
            if not isinstance(value, str):
                continue
            try:
                value.encode("latin-1")
            except UnicodeEncodeError:
                headers[key] = urllib.parse.quote(value, safe=":/%?#[]@!$&'()*+,;=")
        return headers

    def _get(self, url, referer=None):
        last_error = ""
        for attempt in range(1, 3):
            try:
                response = self.session.get(url, headers=self._headers(referer), timeout=20)
                if response.status_code == 200 and response.text:
                    return response.text
                last_error = "HTTP {}".format(response.status_code)
            except Exception as exc:
                last_error = exc.__class__.__name__
                self.session = make_session()
            if attempt < 2:
                xbmc.sleep(400)
        self.logger.error("%s failed to fetch listing page: %s", self.label, last_error)
        return ""

    def _rooms(self):
        raw = (self._get(self.base_url, self.base_url) or "").replace("\\/", "/")
        decoder = json.JSONDecoder()
        rooms = []
        seen = set()
        for match in re.finditer(r'\{\s*"id"\s*:', raw):
            try:
                obj, _end = decoder.raw_decode(raw, match.start())
            except ValueError:
                continue
            if not isinstance(obj, dict):
                continue
            stream = str(obj.get("hlsPlaylist") or obj.get("hlsPlaylistSafe") or "").strip()
            name = str(obj.get("nickname") or "").strip()
            if not name or ".m3u8" not in stream.lower():
                continue
            key = name.lower()
            if key in seen:
                continue
            try:
                if obj.get("age") is not None and int(obj.get("age")) < 18:
                    continue
            except (TypeError, ValueError):
                pass
            show = str(obj.get("showType") or "")
            if _skip(" ".join((name, show, stream))):
                continue
            seen.add(key)
            thumb = str(obj.get("liveImg") or obj.get("profileImg") or "")
            if thumb.startswith("//"):
                thumb = "https:" + thumb
            if not thumb.startswith("http"):
                thumb = ""
            rooms.append((name, stream, thumb))
        return rooms

    def process_content(self, url, page=1):
        try:
            page_num = int(page or 1)
        except (TypeError, ValueError):
            page_num = 1
        if page_num > 1 or _skip(url):
            self.end_directory("videos")
            return
        if not url or url == "BOOTSTRAP":
            url = self.base_url
        self.add_dir("Search", "", 5, self.icons.get("search", self.icon))
        rooms = self._rooms()
        if not rooms:
            self.notify_error("Could not load {} listing".format(self.label))
            self.end_directory("videos")
            return
        for label, stream, thumb in rooms:
            self.add_link(
                label,
                stream,
                4,
                thumb or self.icon,
                self.fanart,
                info_labels={"title": label},
                referer=self.base_url,
            )
        self.end_directory("videos")

    def search(self, query):
        cleaned = (query or "").strip()
        if not cleaned or _skip(cleaned):
            self.end_directory("videos")
            return
        needle = cleaned.lower()
        for label, stream, thumb in self._rooms():
            if needle not in label.lower():
                continue
            self.add_link(
                label,
                stream,
                4,
                thumb or self.icon,
                self.fanart,
                info_labels={"title": label},
                referer=self.base_url,
            )
        self.end_directory("videos")

    def play_video(self, url):
        if ".m3u8" not in (url or "").lower() or _skip(url):
            self.notify_error("Could not resolve stream URL")
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return
        headers = self._headers(self.base_url, accept="*/*")
        list_item = xbmcgui.ListItem(path="{}|{}".format(url, urllib.parse.urlencode(headers)))
        list_item.setProperty("IsPlayable", "true")
        list_item.setMimeType("application/vnd.apple.mpegurl")
        list_item.setContentLookup(False)
        try:
            if xbmc.getCondVisibility("System.HasAddon(inputstream.adaptive)"):
                list_item.setProperty("inputstream", "inputstream.adaptive")
                list_item.setProperty("inputstream.adaptive.manifest_type", "hls")
        except Exception:
            pass
        xbmcplugin.setResolvedUrl(self.addon_handle, True, list_item)
