# -*- coding: utf-8 -*-
from resources.websites.hdzog import Hdzog


class Bdsmx(Hdzog):
    """BDSMX uses the same public video JSON as HDZog."""

    def __init__(self, addon_handle):
        super().__init__(addon_handle)
        self.name = "bdsmx"
        self.base_url = "https://bdsmx.tube/"
        self.search_url = "https://bdsmx.tube/search/{}"
        self.label = "BDSMX"
