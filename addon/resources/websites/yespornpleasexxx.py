# -*- coding: utf-8 -*-
import base64
import html
import re
import urllib.parse

from resources.lib.wordpress_api_tube import WordPressApiTube


class YesPornPleaseXXX(WordPressApiTube):
    def __init__(self, addon_handle, addon=None):
        super().__init__(
            "yespornpleasexxx", "YesPornPleaseXXX",
            "https://yespornpleasexxx.com/", addon_handle, addon,
        )
        self.show_pornstars = True

    def _thumbnail(self, post):
        thumbnail = super()._thumbnail(post)
        if not thumbnail or thumbnail == self.icon:
            return thumbnail
        try:
            from resources.lib.thumb_proxy import build_thumb_url
            return build_thumb_url(thumbnail, referer=self.base_url)
        except Exception:
            return thumbnail

    def resolve_recording_stream(self, url):
        page_html = self._get(url, referer=self.base_url)
        match = re.search(r'player-x\.php\?q=([^"\'&]+)', page_html or "", re.IGNORECASE)
        if not match:
            return None
        try:
            encoded = html.unescape(match.group(1))
            decoded = base64.b64decode(encoded + "===").decode("utf-8", "replace")
            player_tag = urllib.parse.unquote(decoded)
        except Exception as exc:
            self.logger.warning("[yespornpleasexxx] Player payload decode failed: %s", exc)
            return None
        stream = re.search(r'(?:src|href)=["\'](https?://[^"\']+\.mp4[^"\']*)', player_tag, re.IGNORECASE)
        if not stream:
            return None
        return {
            "url": html.unescape(stream.group(1)).strip(),
            "headers": self._headers(url, accept="*/*"),
            "extension": "mp4",
        }
