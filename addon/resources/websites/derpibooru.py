# -*- coding: utf-8 -*-

from resources.lib.booru_api import BooruApiWebsite


class Derpibooru(BooruApiWebsite):
    name = "derpibooru"
    label = "Derpibooru"
    host = "https://derpibooru.org"
    style = "derpi"
    home_tags = "*"
    page_size = 40
