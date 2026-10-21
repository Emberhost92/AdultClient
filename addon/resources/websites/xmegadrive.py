#!/usr/bin/env python
# -*- coding: utf-8 -*-

from resources.lib.kvs_tube import KVSTubeWebsite


class XMegaDrive(KVSTubeWebsite):
    label = "XMegaDrive"
    sort_options = ["Latest", "Popular"]
    sort_paths = {"Latest": "/latest-updates/", "Popular": "/most-popular/"}
    categories_path = "/categories/"
    next_page_full_count = 24
    use_playback_proxy = True

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            "xmegadrive",
            "https://www.xmegadrive.com/",
            "https://www.xmegadrive.com/search/{}/",
            addon_handle,
            addon,
        )
