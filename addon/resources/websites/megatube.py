#!/usr/bin/env python
# -*- coding: utf-8 -*-

from resources.lib.kvs_tube import KVSTubeWebsite


class MegaTube(KVSTubeWebsite):
    name = "megatube"
    label = "MegaTube"
    cache_version = "2"
    sort_options = ["Latest", "Popular", "Top Rated", "Longest"]
    sort_paths = {
        "Latest": "/latest-updates/",
        "Popular": "/most-popular/",
        "Top Rated": "/top-rated/",
        "Longest": "/longest/",
    }
    categories_path = "/categories/"
    models_path = "/models/"
    category_path_markers = (".porn",)
    next_page_full_count = 24
    use_playback_proxy = True

    def __init__(self, addon_handle, addon=None):
        super().__init__("megatube", "https://www.megatube.xxx/", "https://www.megatube.xxx/search/{}/", addon_handle, addon)
