# -*- coding: utf-8 -*-
from resources.websites.hdzog import Hdzog


class Tporn(Hdzog):
    """TPorn uses the same public video JSON. tporn.tube redirects here."""

    def __init__(self, addon_handle):
        super().__init__(addon_handle)
        self.name = "tporn"
        self.base_url = "https://tporn.xxx/"
        self.search_url = "https://tporn.xxx/search/{}"
        self.label = "TPorn"
