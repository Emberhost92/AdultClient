#!/usr/bin/env python
# -*- coding: utf-8 -*-

import html
import re

from resources.lib.kvs_tube import KVSTubeWebsite


class PornRabbit(KVSTubeWebsite):
    label = "PornRabbit"
    # The current Latest feed is filled with dead live-cam widgets. Keep it
    # selectable, but open the healthy public archive by default.
    sort_options = ["Popular", "Top Rated", "Longest", "Latest"]
    sort_paths = {
        "Latest": "/latest-updates/",
        "Popular": "/most-popular/",
        "Top Rated": "/top-rated/",
        "Longest": "/longest/",
    }
    categories_path = "/categories/"
    models_path = "/models/"
    next_page_full_count = 24
    use_playback_proxy = True

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            "pornrabbit",
            "https://www.pornrabbit.com/",
            "https://www.pornrabbit.com/search/{}/",
            addon_handle,
            addon,
        )

    def _is_top_listing(self, url):
        path = (url or "").split("?", 1)[0].rstrip("/")
        return any(path.endswith(value.rstrip("/")) for value in self.sort_paths.values())

    def _extract_stream_url(self, html_content, referer=None):
        # Current PornRabbit pages expose the public video in schema.org JSON,
        # rather than in the normal KVS flashvars object.
        content_url = re.search(r'"contentUrl"\s*:\s*"([^"\\]+(?:\\.[^"\\]*)*)"', html_content or "", re.I)
        if content_url:
            stream = html.unescape(content_url.group(1)).replace("\\/", "/")
            if "/get_file/" in stream and ".mp4" in stream:
                return self._absolute(stream)
        return super()._extract_stream_url(html_content, referer)

    def _extract_videos(self, html_content):
        # The current MyFreeCams archive cards only contain dead embeds.  They
        # have no public media URL, so do not surface them as playable videos.
        return [item for item in super()._extract_videos(html_content)
                if "myfreecams" not in item.get("label", "").lower()]
