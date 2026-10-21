#!/usr/bin/env python
# -*- coding: utf-8 -*-

from resources.lib.kvs_tube import KVSTubeWebsite


class FapNFuck(KVSTubeWebsite):
    label = "FapNFuck"
    sort_options = ["Latest", "Most Viewed", "Top Rated"]
    sort_paths = {
        "Latest": "/latest-updates/",
        "Most Viewed": "/most-popular/",
        "Top Rated": "/top-rated/",
    }
    categories_path = "/categories/"
    models_path = "/models/"
    next_page_full_count = 30
    use_playback_proxy = True
    skip_category_titles = {
        "ar", "cs", "de", "en", "es", "fr", "hi", "id", "it", "ja", "ko", "nl",
        "pl", "pt", "ru", "sv", "th", "tr", "vi", "zh", "next", "previous", "last",
    }

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="fapnfuck",
            base_url="https://fapnfuck.com/",
            search_url="https://fapnfuck.com/search/{}/",
            addon_handle=addon_handle,
            addon=addon,
        )
