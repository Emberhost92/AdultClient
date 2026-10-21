# -*- coding: utf-8 -*-

from resources.lib.booru_api import BooruApiWebsite


class Rule34(BooruApiWebsite):
    name = "rule34"
    label = "Rule34"
    host = "https://rule34.xxx"
    style = "gelbooru-html"
    home_tags = ""
    page_size = 42
