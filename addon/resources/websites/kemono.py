# -*- coding: utf-8 -*-

from resources.lib.kemono_api import KemonoApiWebsite


class Kemono(KemonoApiWebsite):
    name = "kemono"
    label = "Kemono"
    host = "https://kemono.cr"
    api_base = "https://kemono.cr/api/v1"
    api_mirrors = (
        "https://kemono.su/api/v1",
    )
    default_service = "patreon"
    cache_version = "2"
    # test_media2 and a direct range check found no host that returns video bytes.
    media_mirrors = ()