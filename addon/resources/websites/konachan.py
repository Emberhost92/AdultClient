# -*- coding: utf-8 -*-

from resources.lib.booru_api import BooruApiWebsite


class Konachan(BooruApiWebsite):
    name = "konachan"
    label = "Konachan"
    host = "https://konachan.com"
    style = "moebooru"
    page_size = 40
