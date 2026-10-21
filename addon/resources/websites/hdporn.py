# -*- coding: utf-8 -*-
import html
import re
import urllib.parse

import xbmcgui
import xbmcplugin

from resources.lib.base_website import BaseWebsite
from resources.lib.resilient_http import fetch_text
from resources.lib.stream_validation import is_stream_host_resolvable


class Hdporn(BaseWebsite):
    """HDPorn listings from the public card markup and the single source tag."""

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="hdporn",
            base_url="https://hdporn.net",
            search_url="",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36"
        )
        self._card = re.compile(
            r'href="(/video/\d+)"[^>]*title="([^"]*)"[^>]*>\s*'
            r'<img[^>]+src="([^"]+)"'
            r'[\s\S]{0,1600}?class="time[^"]*"[^>]*>\s*TIME:\s*(\d{1,2}:\d{2}(?::\d{2})?)',
            re.IGNORECASE,
        )

    def get_start_url_and_label(self):
        return self.base_url + "/", "HDPorn"

    def make_request(self, url):
        return fetch_text(
            url=url,
            headers={
                "User-Agent": self.ua,
                "Referer": self.base_url + "/",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            logger=self.logger,
            timeout=12,
        )

    def search(self, query):
        self.notify_info("HDPorn hat keine Suche.")
        self.end_directory()

    def process_content(self, url):
        page_url = url if url and url not in ("BOOTSTRAP",) else self.base_url + "/"
        page = self.make_request(page_url)
        if not page:
            self.notify_error("Seite nicht geladen")
            self.end_directory()
            return

        seen = set()
        count = 0
        for path, title, thumb, clock in self._card.findall(page):
            if path in seen:
                continue
            seen.add(path)
            name = html.unescape(title).strip() or "Video"
            video_url = urllib.parse.urljoin(self.base_url + "/", path)
            thumb_url = urllib.parse.urljoin(page_url, html.unescape(thumb).replace("&amp;", "&"))
            seconds = self.convert_duration(clock)
            info = {"duration": seconds} if seconds else None
            self.add_link(
                name,
                video_url,
                4,
                thumb_url,
                self.fanart,
                info_labels=info,
                referer=self.base_url + "/",
            )
            count += 1

        next_url = self._next_url(page_url, page)
        if count and next_url:
            self.add_dir("Next Page", next_url, 2, self.icons.get("default", self.icon), self.fanart)
        elif not count:
            self.notify_error("Keine Videos gefunden")
        self.end_directory()

    def _next_url(self, page_url, page):
        current = 1
        match = re.search(r"page(\d+)\.html", urllib.parse.urlparse(page_url).path, re.IGNORECASE)
        if match:
            current = int(match.group(1))
        numbers = set()
        for href in re.findall(r'href="([^"]+)"', page, re.IGNORECASE):
            found = re.search(r"page(\d+)\.html", href, re.IGNORECASE)
            if found:
                numbers.add(int(found.group(1)))
        nxt = current + 1
        if nxt not in numbers:
            return ""
        return urllib.parse.urljoin(self.base_url + "/", "page%d.html" % nxt)

    def play_video(self, url):
        page = self.make_request(url)
        source = ""
        if page:
            match = re.search(r'<source\b[^>]*\bsrc=["\']([^"\']+)["\']', page, re.IGNORECASE)
            if match:
                source = html.unescape(match.group(1).replace("&amp;", "&").strip())
        if source and not source.startswith("http"):
            source = urllib.parse.urljoin(url, source)
        path = urllib.parse.urlparse(source).path.lower() if source else ""
        if not source.startswith("https://") or not path.endswith(".mp4"):
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return
        if not is_stream_host_resolvable(source, self.logger):
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return
        headers = {
            "User-Agent": self.ua,
            "Referer": url,
            "Origin": self.base_url,
            "Accept": "*/*",
        }
        item = xbmcgui.ListItem(path=source + "|" + urllib.parse.urlencode(headers))
        item.setProperty("IsPlayable", "true")
        item.setMimeType("video/mp4")
        item.setContentLookup(False)
        xbmcplugin.setResolvedUrl(self.addon_handle, True, item)
