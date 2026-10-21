# -*- coding: utf-8 -*-
from resources.websites.hdzog import Hdzog


class Manysex(Hdzog):
    """ManySex uses the same public video JSON as HDZog."""

    def __init__(self, addon_handle):
        super().__init__(addon_handle)
        self.name = "manysex"
        self.base_url = "https://manysex.com/"
        self.search_url = "https://manysex.com/search/{}"
        self.label = "ManySex"
