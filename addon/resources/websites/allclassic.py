#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re

from resources.lib.kvs_tube import KVSTubeWebsite


class AllClassic(KVSTubeWebsite):
    label = "AllClassic"
    sort_options = ["Latest", "Popular"]
    sort_paths = {"Latest": "/", "Popular": "/most-popular/"}
    categories_path = "/categories/"
    models_path = "/models/"
    next_page_full_count = 36
    use_playback_proxy = True

    def __init__(self, addon_handle, addon=None):
        super().__init__("allclassic", "https://allclassic.porn/", "https://allclassic.porn/search/{}/", addon_handle, addon)

    def get_page_url(self, base_url, page_num):
        if page_num <= 1:
            return base_url
        if "/search/" in base_url:
            return super().get_page_url(base_url, page_num)
        return self.base_url + "page/{}/".format(page_num)

    def _extract_videos(self, html_content):
        videos = []
        seen = set()
        for block in re.split(r'(?=<a\b[^>]+class=["\'][^"\']*\bth\b[^"\']*\bitem\b)', html_content or "", flags=re.I):
            href = re.search(r'<a\b[^>]+href=["\']([^"\']+/videos/[^"\']+)', block, re.I)
            image = re.search(r'<img\b[^>]+src=["\']([^"\']+)', block, re.I)
            title = re.search(r'<img\b[^>]+alt=["\']([^"\']+)', block, re.I)
            duration = re.search(r'th-duration[^>]*>[\s\S]*?</i>\s*([^<]+)', block, re.I)
            if not href or not title:
                continue
            url = self._absolute(href.group(1))
            if url in seen:
                continue
            seen.add(url)
            name = self._clean(title.group(1))
            length = self._clean(duration.group(1)) if duration else ""
            video_id = re.search(r"/videos/(\d+)/", url)
            if video_id:
                number = int(video_id.group(1))
                folder = (number // 1000) * 1000
                thumb = "{0}contents/videos_screenshots/{1}/{2}/320x240/1.jpg".format(self.base_url, folder, number)
            else:
                thumb = self._absolute(image.group(1)) if image else self.icon
            info = {"title": name, "plot": name}
            if length:
                info["duration"] = self.convert_duration(length)
            label = "{} [COLOR lime]({})[/COLOR]".format(name, length) if length else name
            videos.append({"label": label, "url": url, "thumb": thumb, "info": info})
        return videos
