# -*- coding: utf-8 -*-
from resources.websites.hdzog import Hdzog


class Ooxxx(Hdzog):
    """OoXXX uses the same public video JSON as HDZog."""

    def __init__(self, addon_handle):
        super().__init__(addon_handle)
        self.name = "ooxxx"
        self.base_url = "https://ooxxx.com/"
        self.search_url = "https://ooxxx.com/search/{}"
        self.label = "OoXXX"
