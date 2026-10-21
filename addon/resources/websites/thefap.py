#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re

from resources.lib.kvs_tube import KVSTubeWebsite


class Thefap(KVSTubeWebsite):
    label = "TheFap"
    sort_options = ["Latest"]
    sort_paths = {"Latest": "/videos/"}
    categories_path = ""
    models_path = None
    video_path_markers = ("/i",)
    next_page_full_count = 24
    use_playback_proxy = True

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="thefap",
            base_url="https://thefap.net/",
            search_url="https://thefap.net/search/{}/",
            addon_handle=addon_handle,
            addon=addon,
        )

    def get_page_url(self, base_url, page_num):
        if page_num <= 1:
            return self._absolute("/videos/")
        return self._absolute("/ajax/videos/page-{}".format(page_num))

    def _extract_videos(self, html_content):
        videos = []
        seen = set()
        blocks = re.findall(
            r'<div class="bg-yellow-400\b[\s\S]{0,4000}?<div>\s*[^<]{1,80}\s*</div>',
            html_content or "",
            re.IGNORECASE,
        )
        for block in blocks:
            href_match = re.search(r'<a href="(/[^"]+/i\d+)">', block, re.IGNORECASE)
            if not href_match:
                continue
            video_url = self._absolute(href_match.group(1))
            if not video_url or video_url in seen:
                continue
            seen.add(video_url)
            img_match = re.search(r'<img src="(https?://[^"]+)"', block, re.IGNORECASE)
            thumb = img_match.group(1) if img_match and "icon-play" not in img_match.group(1) else ""
            names = re.findall(r"<div>\s*([^<]{1,80}?)\s*</div>", block, re.IGNORECASE)
            title = self._clean(names[-1] if names else "")
            if not title:
                continue
            videos.append({
                "label": title,
                "url": video_url,
                "thumb": thumb or self.icon,
                "info": {"title": title, "plot": title},
            })
        return videos
