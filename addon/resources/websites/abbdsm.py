# -*- coding: utf-8 -*-
from resources.websites.hdzog import Hdzog


class Abbdsm(Hdzog):
    """AbBDSM uses the same public video JSON as HDZog."""

    def __init__(self, addon_handle):
        super().__init__(addon_handle)
        self.name = "abbdsm"
        self.base_url = "https://abbdsm.com/"
        self.search_url = "https://abbdsm.com/search/{}"
        self.label = "AbBDSM"
