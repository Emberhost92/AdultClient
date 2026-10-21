# -*- coding: utf-8 -*-

import base64
import html
import os
import urllib.parse
import urllib.request

import xbmc
import xbmcgui
import xbmcplugin

from resources.lib.base_website import BaseWebsite
from resources.lib.proxy_utils import PlaybackGuard, ProxyController


class Abxxx(BaseWebsite):
    sort_options = ("Latest", "Most Popular", "Top Rated")
    sort_values = ("latest-updates", "most-popular", "top-rated")
    _CYRILLIC = {
        0x0410: "A", 0x0412: "B", 0x0415: "E", 0x041C: "M",
        0x0421: "C", 0x041D: "H", 0x041A: "K", 0x0420: "P",
        0x0422: "T", 0x041E: "O", 0x0425: "X",
    }

    def __init__(self, addon_handle, addon=None):
        super().__init__("abxxx", "https://abxxx.com/", "abxxx://search?q={}", addon_handle, addon)
        self.ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36"
        self.icon = os.path.join(self.addon.getAddonInfo("path"), "resources", "logos", "abxxx.png")
        self.icons["default"] = self.icon

    def _headers(self, referer=None):
        return {
            "User-Agent": self.ua,
            "Referer": referer or self.base_url,
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "identity",
            "X-Requested-With": "XMLHttpRequest",
        }

    def _json(self, url, referer=None):
        request = urllib.request.Request(url, headers=self._headers(referer))
        with urllib.request.urlopen(request, timeout=20) as response:
            return __import__("json").loads(response.read().decode("utf-8", "replace"))

    def _listing_url(self, sort="latest-updates", page=1, query=""):
        return "abxxx://listing?" + urllib.parse.urlencode({"sort": sort, "page": page, "q": query})

    def _parse_listing(self, url):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url or "").query)
        return (
            query.get("sort", ["latest-updates"])[0],
            max(1, int(query.get("page", ["1"])[0] or "1")),
            query.get("q", [""])[0].strip(),
        )

    def get_start_url_and_label(self):
        try:
            index = int(self.addon.getSetting("abxxx_sort_by") or "0")
        except Exception:
            index = 0
        index = index if 0 <= index < len(self.sort_options) else 0
        return self._listing_url(self.sort_values[index]), "ABXXX [COLOR yellow]{}[/COLOR]".format(self.sort_options[index])

    def _fetch_listing(self, sort, page, query):
        if query:
            params = "0/str/relevance/60/search..{}.all...".format(page)
            url = self.base_url + "api/videos2.php?" + urllib.parse.urlencode({"params": params, "s": query})
            referer = self.base_url + "search/?s=" + urllib.parse.quote_plus(query)
        else:
            url = self.base_url + "api/json/videos2/0/str/{}/60/..{}.all...jsond".format(sort, page)
            referer = self.base_url + "videos/{}/{}/".format(sort, page)
        return self._json(url, referer)

    def process_content(self, url, page=1):
        if not url or url == "BOOTSTRAP":
            url, _ = self.get_start_url_and_label()
        sort, current_page, query = self._parse_listing(url)
        if page > 1:
            current_page = page
        self.add_dir("Search", "", 5, self.icons.get("search", self.icon))
        try:
            data = self._fetch_listing(sort, current_page, query)
        except Exception as exc:
            self.logger.warning("ABXXX listing failed: %s", exc)
            return self.end_directory("videos")
        videos = data.get("videos") or []
        for video in videos:
            video_id = str(video.get("video_id") or "")
            slug = str(video.get("dir") or "")
            if not video_id or not slug:
                continue
            title = html.unescape(str(video.get("title") or slug.replace("-", " ")).strip())
            duration = str(video.get("duration") or "").strip()
            label = "{} [COLOR lime]({})[/COLOR]".format(title, duration) if duration else title
            video_url = self.base_url + "video/{}/{}/".format(video_id, slug)
            info = {"title": title, "plot": title}
            duration_seconds = self.convert_duration(duration)
            if duration_seconds:
                info["duration"] = duration_seconds
            self.add_link(label, video_url, 4, video.get("scr") or self.icon, self.fanart, info_labels=info)
        if current_page < int(data.get("pages") or 0):
            self.add_dir("Next Page", self._listing_url(sort, current_page + 1, query), 2, self.icon)
        self.end_directory("videos")

    def search(self, query):
        if query:
            self.process_content(self._listing_url("relevance", 1, query.strip()))

    def _decode(self, value):
        normalized = "".join(self._CYRILLIC.get(ord(char), char) for char in value or "")
        normalized = normalized.replace(",", "+").replace("~", "=")
        normalized += "=" * ((4 - len(normalized) % 4) % 4)
        path = base64.b64decode(normalized).decode("utf-8", "replace").replace("/>", "/?")
        return urllib.parse.urljoin(self.base_url, path)

    def resolve_recording_stream(self, url):
        video_id = urllib.parse.urlparse(url).path.strip("/").split("/")[1]
        sources = self._json(self.base_url + "api/videofile.php?video_id=" + video_id, url)
        usable = [source for source in sources if source.get("video_url") and source.get("format") != "_tr.mp4"]
        if not usable:
            return None
        best = max(usable, key=lambda source: ("_fhd" in str(source.get("format")), source.get("is_default", 0)))
        return {"url": self._decode(best["video_url"]), "headers": self._headers(url), "extension": "mp4"}

    def play_video(self, url):
        try:
            resolved = self.resolve_recording_stream(url)
            if not resolved:
                raise ValueError("no stream")
            controller = ProxyController(resolved["url"], upstream_headers=resolved["headers"], use_urllib=True, probe_size=True)
            local_url = controller.start()
            item = xbmcgui.ListItem(path=local_url)
            item.setProperty("IsPlayable", "true")
            item.setMimeType("video/mp4")
            item.setContentLookup(False)
            xbmcplugin.setResolvedUrl(self.addon_handle, True, item)
            PlaybackGuard(xbmc.Player(), xbmc.Monitor(), local_url, controller).start()
        except Exception as exc:
            self.logger.warning("ABXXX playback failed: %s", exc)
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
