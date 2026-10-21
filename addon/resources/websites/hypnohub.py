# -*- coding: utf-8 -*-

from resources.lib.booru_api import BooruApiWebsite


class Hypnohub(BooruApiWebsite):
    name = "hypnohub"
    label = "HypnoHub"
    host = "https://hypnohub.net"
    style = "gelbooru-json"
    page_size = 40
