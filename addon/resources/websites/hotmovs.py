# -*- coding: utf-8 -*-
from resources.websites.hdzog import Hdzog


class Hotmovs(Hdzog):
    """HotMovs uses the same public video JSON as HDZog."""

    def __init__(self, addon_handle):
        super().__init__(addon_handle)
        self.name = "hotmovs"
        self.base_url = "https://hotmovs.com/"
        self.search_url = "https://hotmovs.com/search/{}"
        self.label = "HotMovs"
