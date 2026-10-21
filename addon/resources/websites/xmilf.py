# -*- coding: utf-8 -*-
from resources.websites.hdzog import Hdzog


class Xmilf(Hdzog):
    """XMilf uses the same public video JSON as HDZog."""

    def __init__(self, addon_handle):
        super().__init__(addon_handle)
        self.name = "xmilf"
        self.base_url = "https://xmilf.com/"
        self.search_url = "https://xmilf.com/search/{}"
        self.label = "XMilf"
