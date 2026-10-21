# -*- coding: utf-8 -*-
import os
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from resources.lib.kvs_tube import KVSTubeWebsite
from resources.lib.resolvers import resolver


class MyGoodPorn(KVSTubeWebsite):
    label = "MyGoodPorn"
    sort_options = ["Latest", "Most Viewed", "Top Rated"]
    sort_paths = {
        "Latest": "/latest-updates/",
        "Most Viewed": "/most-popular/",
        "Top Rated": "/top-rated/",
    }
    categories_path = "/categories/"
    models_path = "/models/"
    video_path_markers = ("/video/",)
    category_path_markers = ("/categories/",)
    use_playback_proxy = True
    _tube_embed_hosts = ("eporner.", "xhamster.", "xvideos.")

    def __init__(self, addon_handle, addon=None):
        super().__init__("mygoodporn", "https://mygoodporn.tv/", "https://mygoodporn.tv/search/{}/", addon_handle, addon)
        self.icon = os.path.join(self.addon.getAddonInfo("path"), "resources", "logos", "mygoodporn.png")
        self.icons["default"] = self.icon

    def _pick_thumb(self, img_tag):
        # data-webp ends in .jpg but contains WebP, which Kodi on Windows may
        # identify as JPEG and then fail to decode. The src attribute is a real JPEG.
        source = re.search(r'\ssrc=["\']([^"\']+)["\']', img_tag or "", re.I)
        thumb = self._absolute(source.group(1)) if source else super()._pick_thumb(img_tag)
        if thumb and thumb.startswith("http") and "|" not in thumb:
            thumb += "|" + urllib.parse.urlencode({
                "User-Agent": self.ua,
                "Referer": self.base_url,
            })
        return thumb

    def _is_usable_video(self, item):
        """Hide deleted host files and embeds that merely mirror other tubes."""
        try:
            page = self._get(item["url"], self.base_url)
            embeds = re.findall(r'<iframe\b[^>]+src=["\'](https?://[^"\']+)', page or "", re.I)
            if not embeds:
                return True
            for embed in embeds:
                host = urllib.parse.urlparse(embed).netloc.lower()
                if any(marker in host for marker in self._tube_embed_hosts):
                    continue
                if "streamtape." in host:
                    response = self.session.get(
                        embed,
                        headers=self._headers(item["url"]),
                        timeout=10,
                        allow_redirects=True,
                    )
                    body = response.text.lower()
                    if response.status_code != 200 or 'fileid:"nofile"' in body or "errorsite" in body:
                        continue
                return True
        except Exception as exc:
            self.logger.debug("MyGoodPorn preflight failed for %s: %s", item.get("url"), exc)
            return True
        return False

    def _extract_videos(self, html_content):
        videos = super()._extract_videos(html_content)
        if not videos:
            return videos
        with ThreadPoolExecutor(max_workers=min(8, len(videos))) as executor:
            usable = list(executor.map(self._is_usable_video, videos))
        return [item for item, keep in zip(videos, usable) if keep]

    def resolve_recording_stream(self, url):
        content = self._get(url, self.base_url)
        embeds = re.findall(r'<iframe\b[^>]+src=["\'](https?://[^"\']+)', content or "", re.I)
        for embed in embeds:
            stream, headers = resolver.resolve(embed, referer=url, headers=self._headers(url))
            if stream:
                return {
                    "url": stream,
                    "headers": headers or {},
                    "extension": "m3u8" if ".m3u8" in stream.lower() else "mp4",
                }
        return None
