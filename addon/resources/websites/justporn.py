#!/usr/bin/env python
# -*- coding: utf-8 -*-

from resources.lib.kvs_tube import KVSTubeWebsite


class JustPorn(KVSTubeWebsite):
    label = "JustPorn"
    sort_options = ["Latest", "Popular", "Top Rated"]
    sort_paths = {
        "Latest": "/latest-updates/",
        "Popular": "/most-popular/",
        "Top Rated": "/top-rated/",
    }
    categories_path = "/categories/"
    models_path = "/models/"
    next_page_full_count = 48
    use_playback_proxy = True

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="justporn",
            base_url="https://www.justporn.com/",
            search_url="https://www.justporn.com/search/{}/",
            addon_handle=addon_handle,
            addon=addon,
        )
