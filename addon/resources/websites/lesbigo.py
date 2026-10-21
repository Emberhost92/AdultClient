# -*- coding: utf-8 -*-
from resources.websites.hdzog import Hdzog


class Lesbigo(Hdzog):
    """Lesbigo uses the same public video JSON as HDZog."""

    def __init__(self, addon_handle):
        super().__init__(addon_handle)
        self.name = "lesbigo"
        self.base_url = "https://lesbigo.com/"
        self.search_url = "https://lesbigo.com/search/{}"
        self.label = "Lesbigo"
