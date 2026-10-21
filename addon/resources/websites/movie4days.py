#!/usr/bin/env python
# -*- coding: utf-8 -*-

from resources.lib.days_network import DaysNetworkWebsite


class Movie4Days(DaysNetworkWebsite):
    label = "Movie4Days"

    def __init__(self, addon_handle, addon=None):
        super().__init__("movie4days", "https://movie4days.com/", addon_handle, addon)
