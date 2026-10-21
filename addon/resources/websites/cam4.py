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
_DIRECTORY = "https://www.cam4.com/directoryCams?directoryJson=true&page={}"


def _skip(value):
    text = (value or "").replace("_", " ")
    words = re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
    if any(word in _BLOCKED for word in words):
        return True
    return bool(_AGE.search(text))


def _tags(value):
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value or "")


class Cam4(KVSTubeWebsite):
    label = "CAM4"
    sort_options = []
    sort_paths = {}
    use_playback_proxy = False

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="cam4",
            base_url="https://www.cam4.com/",
            search_url="https://www.cam4.com/directoryCams?directoryJson=true&page=1",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.session = make_session()

    def _headers(self, referer=None, accept=None):
        headers = super()._headers(referer, accept or "*/*")
        headers["Origin"] = "https://www.cam4.com"
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

    def _rooms(self, page):
        text = self._get(_DIRECTORY.format(max(1, int(page or 1))), self.base_url)
        try:
            data = json.loads(text) if text else []
        except ValueError:
            data = []
        if isinstance(data, dict):
            for value in data.values():
                if isinstance(value, list):
                    data = value
                    break
        if not isinstance(data, list):
            data = []
        rooms = []
        for row in data:
            if not isinstance(row, dict):
                continue
            if str(row.get("showType") or "").upper() != "NORMAL":
                continue
            try:
                if row.get("age") is not None and int(row.get("age")) < 18:
                    continue
            except (TypeError, ValueError):
                pass
            stream = str(row.get("hlsPreviewUrl") or "").replace("\\/", "/").strip()
            name = str(row.get("username") or "").strip()
            blob = " ".join((name, _tags(row.get("showTags")), str(row.get("statusMessage") or ""), stream))
            if not name or ".m3u8" not in stream.lower() or _skip(blob):
                continue
            thumb = str(row.get("snapshotImageLink") or row.get("profileImageLink") or "")
            if thumb.startswith("//"):
                thumb = "https:" + thumb
            if not thumb.startswith("http"):
                thumb = ""
            viewers = row.get("viewers")
            label = name
            if isinstance(viewers, int) and viewers >= 0:
                label = "{} ({})".format(name, viewers)
            rooms.append((label, stream, thumb))
        return rooms, len(data) >= 40

    def process_content(self, url, page=1):
        try:
            page_num = int(page or 1)
        except (TypeError, ValueError):
            page_num = 1
        if not url or url == "BOOTSTRAP":
            url = self.base_url
        if _skip(url):
            self.end_directory("videos")
            return
        if page_num <= 1:
            self.add_dir("Search", "", 5, self.icons.get("search", self.icon))
        rooms, full = self._rooms(page_num)
        if page_num <= 1 and not rooms:
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
        if full:
            self.add_dir(
                "Next Page",
                self.base_url,
                2,
                self.icons.get("default", self.icon),
                page=page_num + 1,
            )
        self.end_directory("videos")

    def search(self, query):
        cleaned = (query or "").strip()
        if not cleaned or _skip(cleaned):
            self.end_directory("videos")
            return
        needle = cleaned.lower()
        for label, stream, thumb in self._rooms(1)[0]:
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
