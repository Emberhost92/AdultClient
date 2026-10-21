#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import sys
import time
import urllib.parse

import requests
import xbmc
import xbmcgui
import xbmcplugin

from resources.lib.base_website import BaseWebsite
from resources.lib.decoders.tubepornclassic_decoder import custom_base64_decode
from resources.lib.proxy_utils import PlaybackGuard, ProxyController


class InPorn(BaseWebsite):
    label = "InPorn"
    min_duration = 600
    sort_options = ["Latest", "Most Viewed", "Top Rated", "Longest"]
    sort_values = ["latest-updates", "most-viewed", "top-rated", "longest"]

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="inporn",
            base_url="https://inporn.com/",
            search_url="https://inporn.com/search/?q={}",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.session = requests.Session()
        self.ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        )

    def _headers(self, referer=None):
        return {
            "User-Agent": self.ua,
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": referer or self.base_url,
        }

    def _json(self, url, referer=None):
        try:
            response = self.session.get(url, headers=self._headers(referer), timeout=25)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            self.logger.warning("InPorn request failed for %s: %s", url, exc)
            return {}

    def _sort_value(self):
        try:
            index = int(self.addon.getSetting("inporn_sort_by") or "0")
        except Exception:
            index = 0
        if not 0 <= index < len(self.sort_values):
            index = 0
        return self.sort_values[index]

    def get_start_url_and_label(self):
        return self.base_url + "videos/{}/".format(self._sort_value()), self.label

    def _video_api(self, page, section="", object_id="", search=""):
        sort = "relevance" if section == "search" else self._sort_value()
        if section == "search":
            params = "86400/str/{}/60/search.{}.{}.all...".format(sort, object_id, page)
            return self.base_url + "api/videos2.php?" + urllib.parse.urlencode(
                {"params": params, "s": search}
            )
        suffix = "{}.{}.{}.all...json".format(section, object_id, page)
        return self.base_url + "api/json/videos2/86400/str/{}/60/{}".format(sort, suffix)

    def _render_videos(self, payload, current_url):
        shown = 0
        for video in payload.get("videos") or []:
            duration = video.get("duration") or ""
            seconds = self.convert_duration(duration)
            if seconds < self.min_duration or str(video.get("is_private", "0")) == "1":
                continue
            video_id = str(video.get("video_id") or "")
            slug = video.get("dir") or "video"
            if not video_id:
                continue
            title = video.get("title") or "Untitled"
            thumb = video.get("scr") or self.icon
            video_url = self.base_url + "video/{}/{}/".format(video_id, slug)
            info = {
                "title": title,
                "plot": video.get("description") or title,
                "duration": seconds,
                "mediatype": "video",
            }
            label = "{} [COLOR lime]({})[/COLOR]".format(title, duration)
            self.add_link(
                label,
                video_url,
                4,
                thumb,
                self.fanart,
                info_labels=info,
                context_menu=[
                    (
                        "Sort by...",
                        "RunPlugin({}?mode=7&website=inporn&action=select_sort&original_url={})".format(
                            sys.argv[0], urllib.parse.quote_plus(current_url)
                        ),
                    )
                ],
            )
            shown += 1
        return shown

    def process_content(self, url, page=1):
        if not url or url == "BOOTSTRAP":
            url, _ = self.get_start_url_and_label()
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        search = query.get("q", [""])[0]
        parts = parsed.path.strip("/").split("/")
        category = parts[1] if len(parts) > 1 and parts[0] == "categories" else ""
        section = "search" if search else ("categories" if category else "")
        payload = self._json(
            self._video_api(
                page,
                section=section,
                object_id=category,
                search=search,
            ),
            referer=url,
        )
        if page == 1:
            self.add_dir("Search", "", 5, self.icons.get("search", self.icon))
            self.add_dir(
                "Categories",
                self.base_url + "categories/",
                8,
                self.icons.get("categories", self.icon),
            )
        shown = self._render_videos(payload, url)
        pages = int(payload.get("pages") or 1)
        if page < pages:
            self.add_dir(
                "Next Page",
                url,
                2,
                self.icons.get("default", self.icon),
                page=page + 1,
            )
        if not shown:
            self.notify_error("No full-length InPorn videos found on this page")
        self.end_directory("videos")

    def process_categories(self, url):
        payload = self._json(
            self.base_url + "api/json/categories/14400/str.all.en.json",
            referer=url or self.base_url,
        )
        for category in payload.get("categories") or []:
            name = (category.get("title") or "").strip()
            slug = category.get("dir") or ""
            if not name or not slug:
                continue
            thumb = self.icon
            top = category.get("toptn") or []
            if top:
                thumb = top[0].get("scr") or thumb
            self.add_dir(name, self.base_url + "categories/{}/".format(slug), 2, thumb)
        self.end_directory("files")

    def search(self, query):
        if query:
            self.process_content(self.search_url.format(urllib.parse.quote_plus(query.strip())))

    def _resolve(self, url):
        video_id = next(
            (part for part in urllib.parse.urlparse(url).path.split("/") if part.isdigit()),
            "",
        )
        if not video_id:
            return None
        endpoint = self.base_url + "api/videofile.php?" + urllib.parse.urlencode(
            {"video_id": video_id, "lifetime": 8640000, "ti": int(time.time())}
        )
        payload = self._json(endpoint, referer=url)
        if not isinstance(payload, list) or not payload:
            return None
        decoded = custom_base64_decode(payload[0].get("video_url") or "")
        if not decoded:
            return None
        return {
            "url": urllib.parse.urljoin(self.base_url, decoded),
            "headers": {"User-Agent": self.ua, "Referer": url},
            "extension": "mp4",
        }

    def resolve_recording_stream(self, url):
        return self._resolve(url)

    def play_video(self, url):
        resolved = self._resolve(url)
        if not resolved:
            self.notify_error("Could not resolve InPorn stream")
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return
        controller = ProxyController(
            resolved["url"],
            upstream_headers=resolved["headers"],
            session=self.session,
            use_urllib=True,
            probe_size=True,
            skip_resolve=True,
        )
        local_url = controller.start()
        guard = PlaybackGuard(xbmc.Player(), xbmc.Monitor(), local_url, controller)
        guard.start()
        item = xbmcgui.ListItem(path=local_url)
        item.setProperty("IsPlayable", "true")
        item.setMimeType("video/mp4")
        item.setContentLookup(False)
        xbmcplugin.setResolvedUrl(self.addon_handle, True, item)
        guard.join()
