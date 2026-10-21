# -*- coding: utf-8 -*-

import urllib.parse
import re

from resources.lib.kvs_tube import KVSTubeWebsite


class MoreHardPorn(KVSTubeWebsite):
    label = "MoreHardPorn"
    sort_options = ["Latest", "Most Viewed", "Top Rated"]
    sort_paths = {
        "Latest": "/latest-updates/",
        "Most Viewed": "/most-popular/",
        "Top Rated": "/top-rated/",
    }
    categories_path = "/categories/"
    models_path = "/models/"
    directory_path_prefixes = ("/categories/",)
    next_page_full_count = 30
    use_playback_proxy = True

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="morehardporn",
            base_url="https://morehardporn.com/",
            search_url="https://morehardporn.com/search/{}/",
            addon_handle=addon_handle,
            addon=addon,
        )

    def _is_top_listing(self, url):
        path = urllib.parse.urlparse(url or self.base_url).path.rstrip("/")
        return path in ("", "/latest-updates", "/most-popular", "/top-rated")

    def _extract_videos(self, html_content):
        videos = []
        seen = set()
        blocks = re.split(
            r'(?=<div\b[^>]+class=["\']thumb\s+thumb_rel\s+item\b[^"\']*["\'])',
            html_content or "",
            flags=re.I,
        )
        for block in blocks:
            href = re.search(r'<a\b[^>]+href=["\']([^"\']*/video/[^"\']+)["\']', block, re.I)
            image = re.search(r'<img\b[^>]*>', block, re.I)
            if not href or not image:
                continue
            url = self._absolute(href.group(1))
            if not url or url in seen:
                continue
            seen.add(url)
            image_tag = image.group(0)
            title_match = re.search(r'\s(?:alt|title)=["\']([^"\']+)', image_tag, re.I)
            title = self._clean(title_match.group(1) if title_match else "")
            if not title:
                continue
            thumb = ""
            for attribute in ("data-original", "data-webp", "data-src", "src"):
                thumb_match = re.search(r'\s{}=["\']([^"\']+)'.format(attribute), image_tag, re.I)
                if thumb_match:
                    thumb = self._absolute(thumb_match.group(1))
                    break
            thumb = thumb or self.icon
            duration_match = re.search(r'class=["\'][^"\']*\btime\b[^"\']*["\'][^>]*>([^<]+)', block, re.I)
            duration = self._clean(duration_match.group(1) if duration_match else "")
            seconds = self.convert_duration(duration)
            label = "{} [COLOR lime]({})[/COLOR]".format(title, duration) if duration else title
            info = {"title": title, "plot": title}
            if seconds:
                info["duration"] = seconds
            videos.append({"label": label, "url": url, "thumb": thumb, "info": info})
        return videos
