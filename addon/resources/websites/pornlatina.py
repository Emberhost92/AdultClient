# -*- coding: utf-8 -*-
from resources.websites.hdzog import Hdzog


class Pornlatina(Hdzog):
    """Porn Latina uses the same public video JSON as HDZog."""

    def __init__(self, addon_handle):
        super().__init__(addon_handle)
        self.name = "pornlatina"
        self.base_url = "https://porn-latina.com/"
        self.search_url = "https://porn-latina.com/search/{}"
        self.label = "Porn Latina"
