# -*- coding: utf-8 -*-
from resources.websites.hdzog import Hdzog


class Tikporn(Hdzog):
    """TikPorn uses the same public video JSON as HDZog."""

    def __init__(self, addon_handle):
        super().__init__(addon_handle)
        self.name = "tikporn"
        self.base_url = "https://tikporn.tube/"
        self.search_url = "https://tikporn.tube/search/{}"
        self.label = "TikPorn"
