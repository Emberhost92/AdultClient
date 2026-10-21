#!/usr/bin/env python
# -*- coding: utf-8 -*-

from resources.lib.kvs_tube import KVSTubeWebsite


class W1mp(KVSTubeWebsite):
    """W1mp uses its own KVS get_file CDN with tokenized direct MP4 streams."""

    label = "W1mp"
    sort_options = ["Latest", "Most Viewed", "Top Rated", "Longest"]
    sort_paths = {
        "Latest": "/latest-updates/",
        "Most Viewed": "/most-popular/",
        "Top Rated": "/top-rated/",
        "Longest": "/longest/",
    }
    categories_path = "/categories/"
    models_path = "/models/"
    # The category page begins with translated copies of itself; keep the
    # English catalogue rather than opening empty language directories.
    directory_path_prefixes = ("/categories/",)
    next_page_full_count = 24
    use_playback_proxy = True

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="w1mp",
            base_url="https://w1mp.com/",
            search_url="https://w1mp.com/search/{}/",
            addon_handle=addon_handle,
            addon=addon,
        )
