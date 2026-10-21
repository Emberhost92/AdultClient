# -*- coding: utf-8 -*-
import html
import os
import re
import urllib.parse

from resources.lib.kvs_tube import KVSTubeWebsite


class PornMike(KVSTubeWebsite):
    label = "PornMike"
    sort_options = ["Newest", "Most Viewed", "Top Rated"]
    sort_paths = {
        "Newest": "/newest-porn-videos/",
        "Most Viewed": "/most-viewed-porn-videos/",
        "Top Rated": "/top-rated-porn-videos/",
    }
    categories_path = "/categories/"
    models_path = "/pornstars/"
    category_path_markers = ("/category/", "/pornstar/")
    video_path_markers = ("/videos/",)
    use_playback_proxy = True

    def __init__(self, addon_handle, addon=None):
        super().__init__("pornmike", "https://pornmike.com/", "https://pornmike.com/search/?q={}", addon_handle, addon)
        self.icon = os.path.join(self.addon.getAddonInfo("path"), "resources", "logos", "pornmike.png")
        self.icons["default"] = self.icon

    def _extract_videos(self, content):
        videos, seen = [], set()
        for block in re.findall(r'<figure\b[^>]*class=["\'][^"\']*grid-item[^"\']*["\'][^>]*>([\s\S]*?)</figure>', content or "", re.I):
            link = re.search(r'href=["\'](/videos/[^"\']+)["\']', block, re.I)
            image = re.search(r'<img\b[^>]*src=["\']([^"\']+)["\'][^>]*alt=["\']([^"\']+)', block, re.I)
            if not link or not image:
                continue
            url = urllib.parse.urljoin(self.base_url, link.group(1))
            if url in seen:
                continue
            seen.add(url)
            title = html.unescape(image.group(2)).strip()
            duration_match = re.search(r'class=["\']time["\'][^>]*>\s*([^<]+)', block, re.I)
            duration = duration_match.group(1).strip() if duration_match else ""
            info = {"title": title, "plot": title}
            seconds = self.convert_duration(duration)
            if seconds:
                info["duration"] = seconds
            label = "{} [COLOR lime]({})[/COLOR]".format(title, duration) if duration else title
            videos.append({
                "label": label,
                "url": url,
                "thumb": urllib.parse.urljoin(self.base_url, image.group(1)),
                "info": info,
            })
        return videos

    def _is_top_listing(self, url):
        parsed = urllib.parse.urlparse(url or self.base_url)
        return parsed.path.rstrip("/") in (
            "", "/newest-porn-videos", "/most-viewed-porn-videos", "/top-rated-porn-videos"
        ) and "q" not in urllib.parse.parse_qs(parsed.query)

    def get_page_url(self, base_url, page_num):
        if page_num <= 1:
            return base_url
        parsed = urllib.parse.urlparse(base_url)
        query = urllib.parse.parse_qs(parsed.query)
        query["p"] = [str(page_num)]
        return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', urllib.parse.urlencode(query, doseq=True), ''))
