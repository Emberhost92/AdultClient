#!/usr/bin/env python
# -*- coding: utf-8 -*-

from resources.lib.kvs_tube import KVSTubeWebsite


class PornVe(KVSTubeWebsite):
    label = "PornVe"
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

    def _pick_thumb(self, img_tag):
        thumb = super()._pick_thumb(img_tag)
        if not thumb or not thumb.startswith("http"):
            return thumb
        try:
            from resources.lib.thumb_proxy import build_thumb_url
            return build_thumb_url(thumb, referer="https://pornve.com/")
        except Exception:
            return thumb

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="pornve",
            base_url="https://pornve.com/",
            search_url="https://pornve.com/search/{}/",
            addon_handle=addon_handle,
            addon=addon,
        )
