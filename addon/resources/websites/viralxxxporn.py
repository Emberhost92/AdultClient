#!/usr/bin/env python
# -*- coding: utf-8 -*-
from resources.lib.kvs_tube import KVSTubeWebsite

class ViralXXXPorn(KVSTubeWebsite):
    label = "ViralXXXPorn"
    sort_options = ["Latest", "Popular", "Top Rated", "Longest"]
    sort_paths = {"Latest":"/latest-updates/", "Popular":"/most-popular/", "Top Rated":"/top-rated/", "Longest":"/longest/"}
    categories_path = "/categories/"
    models_path = "/models/"
    skip_category_titles = {"deutsch", "français", "francais"}
    # The site exposes these language folders but currently serves no videos
    # for them, so hide dead-end directories from Kodi.
    skip_category_titles = set(skip_category_titles) | {
        "espa" + chr(0x00f1) + "ol",
        "italiano",
        "portugu" + chr(0x00ea) + "s",
        chr(0x4e2d) + chr(0x6587),
    }
    # These are header language-selector routes, not content categories.
    skip_category_path_prefixes = ("/de/", "/fr/", "/es/", "/it/", "/pt/", "/zh/", "/ja/", "/ru/", "/tr/")
    next_page_full_count = 24
    use_playback_proxy = True
    def __init__(self, addon_handle, addon=None):
        super().__init__("viralxxxporn", "https://viralxxxporn.com/", "https://viralxxxporn.com/search/{}/", addon_handle, addon)

    def _pick_thumb(self, img_tag):
        thumb = super()._pick_thumb(img_tag)
        if thumb.startswith("https://imgcdn.viralxxxporn.com/"):
            # The 800x450 endpoint sends WebP bytes with a JPEG header. Kodi on
            # Windows cannot decode that mismatch; 320x180 is a genuine JPEG.
            return thumb.replace("/800x450/", "/320x180/")
        return thumb
