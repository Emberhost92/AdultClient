# -*- coding: utf-8 -*-
import os

from resources.lib.kvs_tube import KVSTubeWebsite


class One43Porn(KVSTubeWebsite):
    label = "143Porn"
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
    category_path_markers = ("/categories/",)
    use_playback_proxy = True

    def __init__(self, addon_handle, addon=None):
        super().__init__("one43porn", "https://143porn.com/", "https://143porn.com/search/{}/", addon_handle, addon)
        self.icon = os.path.join(self.addon.getAddonInfo("path"), "resources", "logos", "one43porn.png")
        self.icons["default"] = self.icon
