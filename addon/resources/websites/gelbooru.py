# -*- coding: utf-8 -*-

from resources.lib.booru_api import BooruApiWebsite


class Gelbooru(BooruApiWebsite):
    name = "gelbooru"
    label = "Gelbooru"
    host = "https://gelbooru.com"
    style = "gelbooru-html"
    home_tags = "all"
    page_size = 42
