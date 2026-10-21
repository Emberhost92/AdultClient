#!/usr/bin/env python
# -*- coding: utf-8 -*-

from resources.lib.kvs_tube import KVSTubeWebsite


class CherryGasp(KVSTubeWebsite):
    label = "CherryGasp"
    sort_options = ["Latest", "Most Viewed", "Top Rated"]
    sort_paths = {
        "Latest": "/videos/",
        "Most Viewed": "/most-popular/",
        "Top Rated": "/top-rated/",
    }
    categories_path = "/categories/"
    models_path = "/models/"
    next_page_full_count = 30
    use_playback_proxy = True
    skip_category_path_prefixes = ("/albums/",)

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="cherrygasp",
            base_url="https://cherrygasp.com/",
            search_url="https://cherrygasp.com/search/{}/",
            addon_handle=addon_handle,
            addon=addon,
        )

    def _extract_videos(self, html_content):
        # The header's /videos/ directory link uses the same markup as cards.
        # It is navigation, not a playable scene.
        return [
            item for item in super()._extract_videos(html_content)
            if item.get("url", "").rstrip("/") != self.base_url.rstrip("/") + "/videos"
        ]
