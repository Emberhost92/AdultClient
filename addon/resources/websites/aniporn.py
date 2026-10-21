# -*- coding: utf-8 -*-
from resources.websites.hdzog import Hdzog


class Aniporn(Hdzog):
    """AniPorn uses the same public video JSON as HDZog."""

    def __init__(self, addon_handle):
        super().__init__(addon_handle)
        self.name = "aniporn"
        self.base_url = "https://aniporn.com/"
        self.search_url = "https://aniporn.com/search/{}"
        self.label = "AniPorn"
