# -*- coding: utf-8 -*-
from resources.websites.hdzog import Hdzog


class Tube01(Hdzog):
    """01Tube uses the same public video JSON as HDZog."""

    def __init__(self, addon_handle):
        super().__init__(addon_handle)
        self.name = "tube01"
        self.base_url = "https://01tube.com/"
        self.search_url = "https://01tube.com/search/{}"
        self.label = "01Tube"
