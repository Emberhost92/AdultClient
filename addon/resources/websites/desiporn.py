# -*- coding: utf-8 -*-
from resources.websites.hdzog import Hdzog


class Desiporn(Hdzog):
    """Desi Porn uses the same public video JSON as HDZog."""

    def __init__(self, addon_handle):
        super().__init__(addon_handle)
        self.name = "desiporn"
        self.base_url = "https://desi-porn.tube/"
        self.search_url = "https://desi-porn.tube/search/{}"
        self.label = "Desi Porn"
