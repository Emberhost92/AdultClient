# -*- coding: utf-8 -*-
from resources.websites.hdzog import Hdzog


class Gettranny(Hdzog):
    """GetTranny uses the same public video JSON as HDZog."""

    def __init__(self, addon_handle):
        super().__init__(addon_handle)
        self.name = "gettranny"
        self.base_url = "https://gettranny.com/"
        self.search_url = "https://gettranny.com/search/{}"
        self.label = "GetTranny"
