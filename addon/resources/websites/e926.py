# -*- coding: utf-8 -*-

from resources.lib.booru_api import BooruApiWebsite


class E926(BooruApiWebsite):
    name = "e926"
    label = "e926"
    host = "https://e926.net"
    style = "posts"
    page_size = 40
    user_agent = "AdultHideout/1.0 (local)"
