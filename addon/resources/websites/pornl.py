# -*- coding: utf-8 -*-
from resources.websites.hdzog import Hdzog


class Pornl(Hdzog):
    """PornL uses the same public video JSON as HDZog."""

    def __init__(self, addon_handle):
        super().__init__(addon_handle)
        self.name = "pornl"
        self.base_url = "https://pornl.com/"
        self.search_url = "https://pornl.com/search/{}"
        self.label = "PornL"
