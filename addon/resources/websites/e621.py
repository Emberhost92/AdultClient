# -*- coding: utf-8 -*-

from resources.lib.booru_api import BooruApiWebsite


class E621(BooruApiWebsite):
    name = "e621"
    label = "e621"
    host = "https://e621.net"
    style = "posts"
    page_size = 40
    user_agent = "AdultHideout/1.0 (local)"
