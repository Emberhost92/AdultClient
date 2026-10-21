# -*- coding: utf-8 -*-

from resources.lib.booru_api import BooruApiWebsite


class Rule34paheal(BooruApiWebsite):
    name = "rule34paheal"
    label = "Rule34 Paheal"
    host = "https://rule34.paheal.net"
    style = "paheal"
    page_size = 40
