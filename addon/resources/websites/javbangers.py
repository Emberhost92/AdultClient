#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re

from resources.lib.kvs_tube import KVSTubeWebsite

_BLOCKED = ("teen", "teens", "underage", "preteen", "lolita", "jailbait", "child", "children")


def _blocked(value):
    words = re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).split()
    return any(word in _BLOCKED for word in words)


class Javbangers(KVSTubeWebsite):
    label = "JAV Bangers"
    sort_options = ["Latest", "Most Viewed", "Top Rated", "Longest"]
    sort_paths = {
        "Latest": "/",
        "Most Viewed": "/most-popular/",
        "Top Rated": "/top-rated/",
        "Longest": "/longest/",
    }
    categories_path = "/categories/"
    models_path = "/models/"
    video_path_markers = ("/video/",)
    next_page_full_count = 24
    use_playback_proxy = True

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="javbangers",
            base_url="https://www.javbangers.com/",
            search_url="https://www.javbangers.com/search/{}/",
            addon_handle=addon_handle,
            addon=addon,
        )

    def _extract_videos(self, html_content):
        videos = []
        for item in super()._extract_videos(html_content):
            if _blocked(item.get("url", "")):
                continue
            videos.append(item)
        return videos
