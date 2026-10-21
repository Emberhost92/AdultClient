#!/usr/bin/env python
# -*- coding: utf-8 -*-

from resources.lib.days_network import DaysNetworkWebsite


class Tube321(DaysNetworkWebsite):
    label = "321Tube"

    def __init__(self, addon_handle, addon=None):
        super().__init__("321tube", "https://321tube.com/", addon_handle, addon)
