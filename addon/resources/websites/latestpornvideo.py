# -*- coding: utf-8 -*-
import re
import urllib.parse

from resources.lib.resolvers import resolver
from resources.lib.wordpress_api_tube import WordPressApiTube


class LatestPornVideo(WordPressApiTube):
    name = "latestpornvideo"
    cache_version = "2"
    def __init__(self, addon_handle, addon=None):
        super().__init__(
            "latestpornvideo",
            "Latest Porn Video",
            "https://latestpornvideo.com/",
            addon_handle,
            addon,
        )

    def _thumbnail(self, post):
        thumbnail = super()._thumbnail(post)
        if not thumbnail or thumbnail == self.icon:
            return thumbnail
        return thumbnail + "|" + urllib.parse.urlencode({
            "User-Agent": self.ua,
            "Referer": self.base_url,
        })

    def resolve_recording_stream(self, url):
        page_html = self._get(url, referer=self.base_url)
        match = re.search(
            r'<iframe\b[^>]+src=["\'](https?://(?:www\.)?(?:luluvdo|lulustream|lulu)[^"\']+)',
            page_html or "",
            re.IGNORECASE,
        )
        if not match:
            return None
        stream_url, headers = resolver.resolve(match.group(1), referer=url, headers=self._headers(url))
        if not stream_url:
            return None
        extension = "m3u8" if ".m3u8" in stream_url.lower() else "mp4"
        return {"url": stream_url, "headers": headers or {}, "extension": extension}
