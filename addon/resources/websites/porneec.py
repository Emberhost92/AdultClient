# -*- coding: utf-8 -*-
import html
import os
import re
import urllib.parse

from resources.lib.kvs_tube import KVSTubeWebsite


class Porneec(KVSTubeWebsite):
    label = "Porneec"
    sort_options = ["Newest", "Best", "Most Viewed", "Longest"]
    sort_paths = {
        "Newest": "/?filter=latest",
        "Best": "/?filter=popular",
        "Most Viewed": "/?filter=most-viewed",
        "Longest": "/?filter=longest",
    }
    categories_path = "/categories/"
    models_path = "/actors/"
    category_path_markers = ("/c/", "/actors/")
    use_playback_proxy = True

    def __init__(self, addon_handle, addon=None):
        super().__init__("porneec", "https://porneec.com/", "https://porneec.com/?s={}", addon_handle, addon)
        self.icon = os.path.join(self.addon.getAddonInfo("path"), "resources", "logos", "porneec.png")
        self.icons["default"] = self.icon

    def _is_top_listing(self, url):
        parsed = urllib.parse.urlparse(url or self.base_url)
        return parsed.path.rstrip("/") == "" and "s" not in urllib.parse.parse_qs(parsed.query)

    def _extract_videos(self, content):
        videos, seen = [], set()
        for block in re.findall(r'<article\b[^>]*class=["\'][^"\']*thumb-block[^"\']*["\'][^>]*>([\s\S]*?)</article>', content or "", re.I):
            link = re.search(r'<a\b[^>]*href=["\'](https?://porneec\.com/[^"\']+)["\'][^>]*title=["\']([^"\']+)', block, re.I)
            image = re.search(r'<img\b[^>]*(?:data-src|data-original)=["\']([^"\']+)', block, re.I)
            if not link or not image or link.group(1) in seen:
                continue
            seen.add(link.group(1))
            title = html.unescape(link.group(2)).strip()
            duration_match = re.search(r'class=["\']duration["\'][^>]*>\s*([^<]+)', block, re.I)
            duration = duration_match.group(1).strip() if duration_match else ""
            info = {"title": title, "plot": title}
            seconds = self.convert_duration(duration)
            if seconds:
                info["duration"] = seconds
            label = "{} [COLOR lime]({})[/COLOR]".format(title, duration) if duration else title
            videos.append({"label": label, "url": link.group(1), "thumb": html.unescape(image.group(1)), "info": info})
        return videos

    def get_page_url(self, base_url, page_num):
        if page_num <= 1:
            return base_url
        parsed = urllib.parse.urlparse(base_url)
        path = re.sub(r'/page/\d+/?$', '/', parsed.path)
        if not path.endswith('/'):
            path += '/'
        path += 'page/{}/'.format(page_num)
        return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, path, '', parsed.query, ''))

    def _extract_stream_url(self, content, referer=None):
        streams = re.findall(r'https?://[^"\'\s<>]+\.mp4(?:\?[^"\'\s<>]*)?', content or "", re.I)
        if streams:
            return html.unescape(streams[0])
        return super()._extract_stream_url(content, referer)
