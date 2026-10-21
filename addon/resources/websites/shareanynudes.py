#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re

from resources.lib.kvs_tube import KVSTubeWebsite


class Shareanynudes(KVSTubeWebsite):
    label = "ShareAnyNudes"
    sort_options = ["Latest", "Most Viewed", "Top Rated", "Longest"]
    sort_paths = {
        "Latest": "/latest-updates/",
        "Most Viewed": "/most-popular/",
        "Top Rated": "/top-rated/",
        "Longest": "/longest/",
    }
    categories_path = "/categories/"
    models_path = "/models/"
    video_path_markers = ("/video/",)
    next_page_full_count = 24
    use_playback_proxy = True

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="shareanynudes",
            base_url="https://shareanynudes.com/",
            search_url="https://shareanynudes.com/search/{}/",
            addon_handle=addon_handle,
            addon=addon,
        )

    def _extract_videos(self, html_content):
        videos = []
        seen = set()
        for match in re.finditer(
            r'<a\b[^>]*class="[^"]*\bmedia\b[^"]*"[^>]*href="([^"]+)"([^>]*)>',
            html_content or "",
            re.IGNORECASE,
        ):
            href = match.group(1)
            if "/video/" not in href:
                continue
            video_url = self._absolute(href.split("?")[0])
            if not video_url or video_url in seen:
                continue
            seen.add(video_url)
            title_match = re.search(r'\btitle="([^"]*)"', match.group(0), re.IGNORECASE)
            title = self._clean(title_match.group(1) if title_match else "") or "Video"
            window = (html_content or "")[match.start():match.start() + 1400]
            thumb = ""
            for attr in ("data-original", "data-src", "src"):
                img_match = re.search(
                    r'\b{}="([^"]+)"'.format(attr),
                    window,
                    re.IGNORECASE,
                )
                if img_match and not img_match.group(1).startswith("data:"):
                    thumb = self._absolute(img_match.group(1))
                    break
            videos.append({
                "label": title,
                "url": video_url,
                "thumb": thumb or self.icon,
                "info": {"title": title, "plot": title},
            })
        if videos:
            return videos
        return super()._extract_videos(html_content)
