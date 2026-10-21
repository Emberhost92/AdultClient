# -*- coding: utf-8 -*-

from resources.lib.booru_api import BooruApiWebsite


class Yandere(BooruApiWebsite):
    name = "yandere"
    label = "yande.re"
    host = "https://yande.re"
    style = "moebooru"
    page_size = 40
