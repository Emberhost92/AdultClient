# -*- coding: utf-8 -*-

from resources.lib.booru_api import BooruApiWebsite


class Danbooru(BooruApiWebsite):
    name = "danbooru"
    label = "Danbooru"
    host = "https://danbooru.donmai.us"
    style = "posts"
    page_size = 20
    user_agent = "AdultHideout/1.0 (local)"
