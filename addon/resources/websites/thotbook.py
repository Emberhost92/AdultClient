#!/usr/bin/env python
# -*- coding: utf-8 -*-

from resources.lib.leak_extract import LeakWebsite


class Thotbook(LeakWebsite):
    site_name = "thotbook"
    site_base = "https://thotbook.tv/"
    site_host = "thotbook.tv"
    site_label = "ThotBook"
