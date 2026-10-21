#!/usr/bin/env python
# -*- coding: utf-8 -*-

from resources.lib.days_network import DaysNetworkWebsite


class Porn4Days(DaysNetworkWebsite):
    label = "Porn4Days"
    categories_path = "/paysitelist"
    category_markers = ("/search/",)
    direct_mp4 = False
    proxy_mp4 = True

    def __init__(self, addon_handle, addon=None):
        super().__init__("porn4days", "https://porn4days.pw/", addon_handle, addon)
