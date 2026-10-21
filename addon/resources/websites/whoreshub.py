#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os

from resources.lib.kvs_tube import KVSTubeWebsite


class WhoresHub(KVSTubeWebsite):
    label = "WhoresHub"
    sort_options = ["Latest", "Most Viewed", "Top Rated"]
    sort_paths = {
        "Latest": "/latest-updates/",
        "Most Viewed": "/most-popular/",
        "Top Rated": "/top-rated/",
    }
    search_path = "/search/{}/"
    categories_path = "/categories/"
    models_path = "/models/"
    video_path_markers = ("/videos/",)
    category_path_markers = ("/categories/", "/tags/")
    next_page_full_count = 30
    use_playback_proxy = True

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="whoreshub",
            base_url="https://www.whoreshub.com/",
            search_url="https://www.whoreshub.com/search/{}/",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.icon = os.path.join(self.addon.getAddonInfo("path"), "resources", "logos", "whoreshub.png")
        self.icons["default"] = self.icon
