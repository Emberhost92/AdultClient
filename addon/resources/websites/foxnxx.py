# -*- coding: utf-8 -*-
import html
import re
import urllib.parse

import requests
import xbmcgui
import xbmcplugin

from resources.lib.base_website import BaseWebsite
from resources.lib.resolvers import resolver


class FoxNXX(BaseWebsite):
    label = "FOXNXX"

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            "foxnxx",
            "http://foxnxx.com/",
            "http://foxnxx.com/search/{}.html",
            addon_handle,
            addon,
        )
        self.session = requests.Session()
        self.ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36"
        )

    def _headers(self, referer=None, accept=None):
        return {
            "User-Agent": self.ua,
            "Referer": referer or self.base_url,
            "Accept": accept or "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "identity",
        }

    def _get(self, url, referer=None):
        try:
            response = self.session.get(url, headers=self._headers(referer), timeout=25)
            if response.status_code == 200:
                return response.text
            self.logger.warning("[foxnxx] HTTP %s for %s", response.status_code, url)
        except Exception as exc:
            self.logger.warning("[foxnxx] Request failed for %s: %s", url, exc)
        return ""

    def _absolute(self, value, base=None):
        value = html.unescape(value or "").strip()
        absolute = urllib.parse.urljoin(base or self.base_url, value)
        if urllib.parse.urlparse(absolute).hostname == "foxnxx.com":
            absolute = "http://" + absolute.split("://", 1)[-1]
        return absolute

    @staticmethod
    def _clean(value):
        value = re.sub(r"<[^>]+>", " ", value or "")
        return re.sub(r"\s+", " ", html.unescape(value)).strip()

    def get_page_url(self, base_url, page_num):
        if page_num <= 1 or "/search/" in (base_url or ""):
            return base_url
        return self._absolute("/page/{:02d}.html".format(page_num))

    def _items(self, page_html):
        items = []
        seen = set()
        pattern = r'<a\b[^>]+href=["\']([^"\']*/xxx/[^"\']+)["\'][^>]*>([\s\S]*?)</a>'
        for href, body in re.findall(pattern, page_html or "", re.IGNORECASE):
            url = self._absolute(href)
            if url in seen:
                continue
            title_match = re.search(r'class=["\']titlethumb["\'][^>]*>([\s\S]*?)</div>', body, re.IGNORECASE)
            image_tag = re.search(r'<img\b[^>]*>', body, re.IGNORECASE)
            image_match = None
            if image_tag:
                image_match = re.search(r'\bdata-src=["\']([^"\']+)', image_tag.group(0), re.IGNORECASE)
                if not image_match:
                    image_match = re.search(r'\bsrc=["\']([^"\']+)', image_tag.group(0), re.IGNORECASE)
            duration_match = re.search(r'class=["\']timer["\'][^>]*>([^<]+)', body, re.IGNORECASE)
            title = self._clean(title_match.group(1) if title_match else "")
            if not title or not image_match:
                continue
            seen.add(url)
            duration = self._clean(duration_match.group(1) if duration_match else "")
            seconds = self.convert_duration(duration)
            info = {"title": title, "plot": title}
            if seconds:
                info["duration"] = seconds
            label = "{} [COLOR lime]({})[/COLOR]".format(title, duration) if duration else title
            thumb = self._absolute(image_match.group(1))
            thumb += "|" + urllib.parse.urlencode({
                "User-Agent": self.ua,
                "Referer": self.base_url,
            })
            items.append((label, url, thumb, info))
        return items

    def process_content(self, url, page=1):
        url = self.base_url if not url or url == "BOOTSTRAP" else url
        target = self.get_page_url(url, page)
        page_html = self._get(target)
        self.add_dir("Search", "", 5, self.icons.get("search", self.icon))
        if not page_html:
            self.notify_error("Could not load FOXNXX")
            return self.end_directory("videos")
        items = self._items(page_html)
        for label, video_url, thumb, info in items:
            self.add_link(label, video_url, 4, thumb, self.fanart, info_labels=info)
        if items and "/search/" not in target:
            next_path = "/page/{:02d}.html".format(page + 1)
            if re.search(r'href=["\'][^"\']*{}["\']'.format(re.escape(next_path)), page_html, re.IGNORECASE):
                self.add_dir("Next Page", url, 2, self.icons.get("default", self.icon), page=page + 1)
        self.end_directory("videos")

    def search(self, query):
        if query:
            slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")
            if slug:
                self.process_content(self.search_url.format(urllib.parse.quote(slug)))

    def resolve_recording_stream(self, url):
        page_html = self._get(url, referer=self.base_url)
        match = re.search(r'<iframe\b[^>]+src=["\']([^"\']*myxstudio\.top/[^"\']+)', page_html, re.IGNORECASE)
        if not match:
            return None
        embed_url = self._absolute(match.group(1), url)
        stream_url, headers = resolver.resolve(embed_url, referer=url, headers=self._headers(url))
        if not stream_url:
            return None
        return {"url": stream_url, "headers": headers or {}, "extension": "mp4"}

    def play_video(self, url):
        resolved = self.resolve_recording_stream(url)
        if not resolved:
            self.notify_error("Could not resolve FOXNXX stream")
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return
        play_url = resolved["url"]
        if resolved["headers"]:
            play_url += "|" + urllib.parse.urlencode(resolved["headers"])
        item = xbmcgui.ListItem(path=play_url)
        item.setProperty("IsPlayable", "true")
        item.setMimeType("video/mp4")
        item.setContentLookup(False)
        xbmcplugin.setResolvedUrl(self.addon_handle, True, item)
