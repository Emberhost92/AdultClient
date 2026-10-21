# -*- coding: utf-8 -*-
from resources.websites.hdzog import Hdzog


class Blackporn(Hdzog):
    """Black Porn uses the same public video JSON as HDZog."""

    def __init__(self, addon_handle):
        super().__init__(addon_handle)
        self.name = "blackporn"
        self.base_url = "https://blackporn.tube/"
        self.search_url = "https://blackporn.tube/search/{}"
        self.label = "Black Porn"
