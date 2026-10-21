#!/usr/bin/env python
# -*- coding: utf-8 -*-
from resources.lib.kvs_tube import KVSTubeWebsite


class Xozilla(KVSTubeWebsite):
    label = "Xozilla"
    sort_options = ["Latest", "Most Viewed", "Top Rated", "Longest"]
    sort_paths = {
        "Latest": "/latest-updates/",
        "Most Viewed": "/most-popular/",
        "Top Rated": "/top-rated/",
        "Longest": "/longest/",
    }
    categories_path = "/categories/"
    models_path = "/models/"
    use_playback_proxy = True

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            "xozilla",
            "https://www.xozilla.com/",
            "https://www.xozilla.com/search/{}/",
            addon_handle,
            addon,
        )
