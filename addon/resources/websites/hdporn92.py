# -*- coding: utf-8 -*-
import html
import re
import urllib.parse

from resources.lib.resolvers import resolver
from resources.lib.wordpress_api_tube import WordPressApiTube


class HDPorn92(WordPressApiTube):
    def __init__(self, addon_handle, addon=None):
        super().__init__("hdporn92", "HDPorn92", "https://hdporn92.com/", addon_handle, addon)

    def _html_listing_url(self, url, page):
        parsed = urllib.parse.urlparse(url or self.base_url)
        query = urllib.parse.parse_qs(parsed.query)
        source = (query.get("ah_source") or [""])[0]
        target = source or url or self.base_url
        target_parsed = urllib.parse.urlparse(target)
        target_query = urllib.parse.parse_qs(target_parsed.query)
        for internal_key in ("ah_category", "ah_tag", "ah_source"):
            target_query.pop(internal_key, None)
        path = re.sub(r"/page/\d+/?$", "/", target_parsed.path or "/")
        if page > 1:
            path = path.rstrip("/") + "/page/{}/".format(page)
        return urllib.parse.urlunparse(target_parsed._replace(
            path=path,
            query=urllib.parse.urlencode(target_query, doseq=True),
        ))

    def _listing_thumbnails(self, url, page):
        page_html = self._get(self._html_listing_url(url, page), referer=self.base_url)
        thumbnails = {}
        for block in re.findall(
            r'<article\b[^>]+class=["\'][^"\']*loop-video[^"\']*["\'][^>]*>([\s\S]*?)</article>',
            page_html or "", re.IGNORECASE,
        ):
            link = re.search(r'<a\b[^>]+href=["\']([^"\']+)', block, re.IGNORECASE)
            image = re.search(r'<img\b[^>]+class=["\'][^"\']*video-main-thumb[^"\']*["\'][^>]+src=["\']([^"\']+)', block, re.IGNORECASE)
            if link and image:
                thumb = self._absolute(image.group(1))
                thumb += "|" + urllib.parse.urlencode({
                    "User-Agent": self.ua,
                    "Referer": self.base_url,
                })
                thumbnails[self._absolute(link.group(1)).rstrip("/")] = thumb
        return thumbnails

    def _video_items(self, posts):
        items = super()._video_items(posts)
        thumbnails = getattr(self, "_current_thumbnails", {})
        for item in items:
            item["thumb"] = thumbnails.get(item["url"].rstrip("/"), item["thumb"])
        return items

    def process_content(self, url, page=1):
        self._current_thumbnails = self._listing_thumbnails(url, page)
        super().process_content(url, page=page)

    def resolve_recording_stream(self, url):
        page_html = self._get(url, referer=self.base_url)
        match = re.search(
            r'<iframe\b[^>]+src=["\'](https?://(?:www\.)?morencius\.com/(?:embed|e)/[^"\']+)',
            page_html or "", re.IGNORECASE,
        )
        if not match:
            return None
        embed_url = html.unescape(match.group(1)).strip()
        stream_url, headers = resolver.resolve(embed_url, referer=url, headers={"User-Agent": self.ua})
        if not stream_url:
            return None
        return {"url": stream_url, "headers": headers or {}, "extension": "m3u8"}
