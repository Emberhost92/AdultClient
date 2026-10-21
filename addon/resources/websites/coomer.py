# -*- coding: utf-8 -*-

from resources.lib.kemono_api import KemonoApiWebsite


class Coomer(KemonoApiWebsite):
    name = "coomer"
    label = "Coomer"
    host = "https://coomer.st"
    api_base = "https://coomer.st/api/v1"
    api_mirrors = (
        "https://coomer.cr/api/v1",
        "https://kemono.cr/api/v1",
    )
    default_service = "onlyfans"
    cache_version = "2"
    # test_media2 and a direct range check found no host that returns video bytes.
    media_mirrors = ()