# -*- coding: utf-8 -*-
from resources.websites.hdzog import Hdzog


class Mrgay(Hdzog):
    """Mr Gay uses the same public video JSON as HDZog."""

    def __init__(self, addon_handle):
        super().__init__(addon_handle)
        self.name = "mrgay"
        self.base_url = "https://mrgay.com/"
        self.search_url = "https://mrgay.com/search/{}"
        self.label = "Mr Gay"
