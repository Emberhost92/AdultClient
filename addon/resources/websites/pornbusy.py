# -*- coding: utf-8 -*-
import re
import html
import urllib.parse

from resources.lib.resolvers import resolver
from resources.lib.wordpress_api_tube import WordPressApiTube


class PornBusy(WordPressApiTube):
    def __init__(self, addon_handle, addon=None):
        super().__init__("pornbusy", "PornBusy", "https://pornbusy.com/", addon_handle, addon)

    def _thumbnail(self, post):
        thumbnail = super()._thumbnail(post)
        if thumbnail and thumbnail != self.icon and "|" not in thumbnail:
            thumbnail += "|" + urllib.parse.urlencode({
                "User-Agent": self.ua,
                "Referer": self.base_url,
            })
        return thumbnail

    def resolve_recording_stream(self, url):
        page = self._get(url, referer=self.base_url)
        embeds = []
        for value in re.findall(r'<iframe\b[^>]+src=["\']([^"\']+)', page or "", re.I):
            embed = html.unescape(value).strip()
            if embed.startswith("//"):
                embed = "https:" + embed
            else:
                embed = urllib.parse.urljoin(url, embed)
            if resolver.resolver_entry_for_url(embed) and embed not in embeds:
                embeds.append(embed)

        for embed in resolver.sort_urls_by_resolver_preference(embeds, self.addon):
            if not resolver.is_resolver_enabled(embed, self.addon):
                continue
            stream, headers = resolver.resolve(embed, referer=url, headers=self._headers(url))
            if stream:
                return {"url": stream, "headers": headers or {}, "extension": "m3u8"}
        return None
