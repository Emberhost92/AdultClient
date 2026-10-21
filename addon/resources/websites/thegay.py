# -*- coding: utf-8 -*-
from resources.websites.hdzog import Hdzog


class Thegay(Hdzog):
    """TheGay uses the same public video JSON as HDZog."""

    def __init__(self, addon_handle):
        super().__init__(addon_handle)
        self.name = "thegay"
        self.base_url = "https://thegay.com/"
        self.search_url = "https://thegay.com/search/{}"
        self.label = "TheGay"
