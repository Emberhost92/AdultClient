# -*- coding: utf-8 -*-

import re
import urllib.parse

import xbmcgui
import xbmcplugin

from resources.lib.booru_api import BooruApiWebsite

_MIN_PHOTO = 30000


class Xbooru(BooruApiWebsite):
    name = "xbooru"
    label = "Xbooru"
    host = "https://xbooru.com"
    style = "gelbooru-html"
    home_tags = ""
    page_size = 42

    def _photo_size(self, url):
        try:
            response = self.session.get(
                url,
                headers=dict(self._headers(accept="image/*,*/*"), **{"Range": "bytes=0-1"}),
                timeout=14,
                stream=True,
                allow_redirects=True,
            )
            total = 0
            match = re.search(r"/(\d+)", response.headers.get("Content-Range") or "")
            if match:
                total = int(match.group(1))
            elif response.status_code == 200:
                try:
                    total = int(response.headers.get("Content-Length") or 0)
                except ValueError:
                    total = 0
            ctype = (response.headers.get("Content-Type") or "").split(";")[0].lower()
            status = response.status_code
            response.close()
            return status, ctype, total
        except Exception:
            return 0, "", 0

    def play_video(self, url):
        if self.style == "gelbooru-html" and "s=view" in (url or ""):
            url = self._resolve_view(url)
        status, ctype, total = self._photo_size(url) if url else (0, "", 0)
        image = ctype.startswith("image/")
        video = ctype.startswith("video/") or ctype == "application/octet-stream"
        big_enough = (image and (not total or total >= _MIN_PHOTO)) or (video and (not total or total >= 8000000))
        if status not in (200, 206) or not big_enough:
            self.notify_error("Could not resolve image")
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return
        headers = self._headers(accept="*/*")
        play_url = "{}|{}".format(url, urllib.parse.urlencode(headers))
        item = xbmcgui.ListItem(path=play_url)
        item.setProperty("IsPlayable", "true")
        item.setMimeType(ctype if image or ctype.startswith("video/") else "image/jpeg")
        item.setContentLookup(False)
        xbmcplugin.setResolvedUrl(self.addon_handle, True, item)
