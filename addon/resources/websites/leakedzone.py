#!/usr/bin/env python
# -*- coding: utf-8 -*-

import base64
import re
import urllib.parse

from resources.lib.kvs_tube import KVSTubeWebsite


class Leakedzone(KVSTubeWebsite):
    label = "LeakedZone"
    sort_options = ["Latest"]
    sort_paths = {"Latest": "/videos"}
    categories_path = ""
    models_path = None
    video_path_markers = ("/video/",)
    next_page_full_count = 24
    use_playback_proxy = True

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="leakedzone",
            base_url="https://leakedzone.com/",
            search_url="https://leakedzone.com/search?search={}",
            addon_handle=addon_handle,
            addon=addon,
        )

    def _is_top_listing(self, url):
        path = urllib.parse.urlparse(url or self.base_url).path.rstrip("/")
        return path in ("", "/videos")

    def get_page_url(self, base_url, page_num):
        parsed = urllib.parse.urlparse(base_url or self._absolute("/videos"))
        query = urllib.parse.parse_qs(parsed.query)
        if page_num <= 1:
            query.pop("page", None)
        else:
            query["page"] = [str(page_num)]
        return urllib.parse.urlunparse((
            parsed.scheme or "https",
            parsed.netloc or "leakedzone.com",
            parsed.path or "/videos",
            "",
            urllib.parse.urlencode(query, doseq=True),
            "",
        ))

    def _extract_videos(self, html_content):
        videos = []
        seen = set()
        blocks = re.findall(
            r'<a href="https://leakedzone.com/[^"]+/video/\d+" class="block">[\s\S]{0,2500}?</a>',
            html_content or "",
            re.IGNORECASE,
        )
        for block in blocks:
            href_match = re.search(r'href="(https://leakedzone.com/[^"]+/video/\d+)"', block, re.IGNORECASE)
            if not href_match:
                continue
            video_url = href_match.group(1)
            if video_url in seen:
                continue
            seen.add(video_url)
            title_match = re.search(r'line-clamp-2">([^<]+)', block, re.IGNORECASE)
            if not title_match:
                title_match = re.search(r'\salt="([^"]+)"', block, re.IGNORECASE)
            title = self._clean(title_match.group(1) if title_match else "")
            if not title:
                continue
            img_match = re.search(r'<img\b[^>]*\bsrc="(https?://[^"]+)"', block, re.IGNORECASE)
            duration_match = re.search(r">(\d{1,2}:\d{2}(?::\d{2})?)<", block)
            duration = duration_match.group(1) if duration_match else ""
            seconds = self.convert_duration(duration)
            info = {"title": title, "plot": title}
            if seconds:
                info["duration"] = seconds
            label = "{} [COLOR lime]({})[/COLOR]".format(title, duration) if duration else title
            videos.append({
                "label": label,
                "url": video_url,
                "thumb": img_match.group(1) if img_match else self.icon,
                "info": info,
            })
        return videos

    def _decode_media(self, value):
        raw = (value or "")[16:-16][::-1]
        try:
            return base64.b64decode(raw).decode("utf-8")
        except Exception:
            return ""

    def _extract_stream_url(self, html_content, referer=None):
        for blob in re.findall(r"\bf\(\s*['\"]([A-Za-z0-9+/=]{40,})['\"]\s*\)", html_content or ""):
            stream_url = self._decode_media(blob)
            if stream_url.startswith("http") and ".m3u8" in stream_url.split("?", 1)[0]:
                return stream_url
        return None
