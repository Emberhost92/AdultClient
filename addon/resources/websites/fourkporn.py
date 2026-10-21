#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys

try:
    import xbmc
    _vendor = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lib", "vendor")
    if _vendor not in sys.path:
        sys.path.insert(0, _vendor)
    import cloudscraper
except Exception as exc:
    cloudscraper = None
    try:
        xbmc.log("[AdultHideout][4kPorn] cloudscraper import failed: {}".format(exc), xbmc.LOGERROR)
    except Exception:
        pass

from resources.lib.kvs_tube import KVSTubeWebsite
from resources.lib.resilient_http import fetch_text


class FourKPorn(KVSTubeWebsite):
    label = "4kPorn"
    sort_options = ["Latest", "Most Viewed", "Top Rated", "Longest"]
    sort_paths = {
        "Latest": "/latest-updates/",
        "Most Viewed": "/popular-videos/",
        "Top Rated": "/best-videos/",
        "Longest": "/latest-updates/?sort_by=duration",
    }
    categories_path = "/categories/"
    models_path = "/models/"
    video_path_markers = ("/videos/",)
    category_path_markers = ("/categories/", "/category/", "/models/")
    next_page_full_count = 24
    use_playback_proxy = True

    def _pick_thumb(self, img_tag):
        thumb = super()._pick_thumb(img_tag)
        if not thumb or not thumb.startswith("http"):
            return thumb
        try:
            from resources.lib.thumb_proxy import build_thumb_url
            return build_thumb_url(thumb, referer=self.base_url)
        except Exception:
            return thumb

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="fourkporn",
            base_url="https://4kporn.xxx/",
            search_url="https://4kporn.xxx/search/{}/",
            addon_handle=addon_handle,
            addon=addon,
        )
        self._reset_scraper()

    def _reset_scraper(self):
        if not cloudscraper:
            return False
        try:
            # Let cloudscraper select its bundled profile. Forcing a Windows
            # profile changes the TLS cipher set and fails in Kodi on Android.
            self.session = cloudscraper.create_scraper()
            self.session.headers.update(self._headers())
            # Establish Cloudflare cookies on the least restrictive endpoint.
            self.session.get(self.base_url, headers=self._headers(), timeout=20)
            return True
        except Exception as exc:
            self.logger.warning("4kPorn cloudscraper initialization failed: %s", exc)
            return False

    def _get(self, url, referer=None, max_retries=None):
        attempts = max_retries or 3
        last_error = ""
        for attempt in range(attempts):
            content = fetch_text(
                url,
                headers=self._headers(referer),
                scraper=self.session,
                # A 403 from Kodi's TLS client is expected before curl.exe
                # succeeds on Windows, so only log if every path fails.
                logger=None,
                timeout=20,
                use_windows_curl_fallback=True,
            )
            if content:
                return content
            last_error = "all request methods failed"
            if attempt + 1 < attempts:
                self._reset_scraper()
                xbmc.sleep(500 * (attempt + 1))
        self.logger.error("4kPorn failed to fetch %s: %s", url, last_error)
        return ""
