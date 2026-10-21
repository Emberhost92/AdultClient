# -*- coding: utf-8 -*-
import html
import re
import urllib.parse

import requests
import xbmc
import xbmcgui
import xbmcplugin

from resources.lib.base_website import BaseWebsite
from resources.lib.proxy_utils import PlaybackGuard, ProxyController
from resources.lib.resilient_http import fetch_text

# 2-letter dirs on the site are language editions, not real categories.
_LANG_CODES = {
    "ar", "bg", "cz", "de", "es", "fr", "it", "ja", "pt", "ru", "pl", "nl",
    "tr", "ro", "hu", "en", "ko", "zh", "vi", "th", "id", "uk", "el", "he",
    "fa", "hi", "gr", "hr", "my", "sv",
}
_NON_CATEGORY = {"index", "2257", "xfsearch", "uploads", "templates", "tags", "page"}


class Youperv(BaseWebsite):
    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="youperv",
            base_url="https://youperv.com/",
            search_url="https://youperv.com/index.php?do=search&subaction=search&story={}",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.label = "YouPerv"
        self.ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.ua, "Referer": self.base_url})

    def _headers(self, referer=None, accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"):
        return {
            "User-Agent": self.ua,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": referer or self.base_url,
        }

    def make_request(self, url, referer=None):
        try:
            response = self.session.get(url, headers=self._headers(referer), timeout=25, allow_redirects=True)
            if response.status_code == 200:
                return response.text
            self.logger.warning("Youperv HTTP %s for %s", response.status_code, url)
        except Exception as exc:
            self.logger.warning("Youperv request failed for %s: %s", url, exc)
            self.session = requests.Session()
        return fetch_text(url, headers=self._headers(referer), logger=self.logger,
                          timeout=25, use_windows_curl_fallback=True) or ""

    def _page_url(self, url, page):
        if page <= 1 or "index.php" in url:
            return url
        base = url if url.endswith("/") else url + "/"
        base = re.sub(r"page/\d+/$", "", base)
        return "{}page/{}/".format(base, page)

    def process_content(self, url, page=1, **kwargs):
        if not url or url == "BOOTSTRAP":
            url, _ = self.get_start_url_and_label()

        if page == 1:
            self.add_dir('[COLOR blue]Search[/COLOR]', '', 5, self.icons['search'])
            self.add_dir('[COLOR yellow]Categories[/COLOR]', self.base_url, 8, self.icons['categories'])

        content = self.make_request(self._page_url(url, page))
        if not content:
            self.notify_error("Could not load YouPerv")
            return self.end_directory()

        count = self._render_video_list(content)
        if count and "index.php" not in url:
            self.add_dir('[COLOR blue]Next Page >>[/COLOR]', url, 2, self.icons['default'], page=page + 1)

        self.end_directory()

    def _render_video_list(self, content):
        pattern = (
            r'<div class="item">\s*<a href="(https://youperv\.com/[^"]+\.html)" class="item-link">'
            r'[\s\S]*?<img[^>]*class="xfieldimage poster"[^>]*src="([^"]+)"[^>]*alt="([^"]*)"'
            r'[\s\S]*?<span class="tim">\s*([\d:]+)'
        )
        seen = set()
        count = 0
        for video_url, thumb, title, duration in re.findall(pattern, content):
            if video_url in seen:
                continue
            seen.add(video_url)
            thumb_url = urllib.parse.urljoin(self.base_url, html.unescape(thumb))
            display_title = html.unescape(title.strip()) or "Untitled"
            label = "{} [COLOR lime]({})[/COLOR]".format(display_title, duration)
            info = {"title": display_title, "mediatype": "video"}
            seconds = self.convert_duration(duration)
            if seconds:
                info["duration"] = seconds
            self.add_link(label, video_url, 4, thumb_url, self.fanart, info_labels=info)
            count += 1
        return count

    def process_categories(self, url):
        content = self.make_request(url or self.base_url)
        if not content:
            return self.end_directory(content_type='files')

        self.add_dir('[COLOR blue]Search[/COLOR]', '', 5, self.icons['search'])
        slugs = set(re.findall(r'href="https://youperv\.com/([a-z0-9-]+)/\d+-[^"]+\.html"', content))
        slugs |= set(re.findall(r'href="https://youperv\.com/([a-z0-9-]+)/"', content))
        cats = sorted(s for s in slugs if len(s) > 2 and s not in _LANG_CODES and s not in _NON_CATEGORY)
        for slug in cats:
            name = slug.replace("-", " ").title()
            self.add_dir(name, "{}{}/".format(self.base_url, slug), 2, self.icons['categories'])

        self.end_directory(content_type='files')

    def search(self, query):
        if query:
            self.process_content(self.search_url.format(urllib.parse.quote_plus(query.strip())))

    def _resolve_stream(self, url):
        content = self.make_request(url, referer=self.base_url)
        if not content:
            return None
        match = re.search(r'<source[^>]+src="([^"]+\.mp4)"', content)
        if not match:
            return None
        stream = html.unescape(match.group(1)).strip()
        return urllib.parse.quote(stream, safe=":/?&=%")

    def play_video(self, url):
        stream_url = self._resolve_stream(url)
        if not stream_url:
            self.notify_error("Could not resolve YouPerv stream")
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return

        # Direct, non-signed .mp4 on the site's CDN that 403s without the site
        # Referer, so serve it through the local proxy which carries the header.
        controller = ProxyController(
            stream_url,
            upstream_headers={
                'User-Agent': self.ua,
                'Referer': self.base_url,
            },
            cookies=self.session.cookies.get_dict() if self.session else None,
            session=self.session,
            use_urllib=True,
            probe_size=True,
            skip_resolve=True,
        )
        local_url = controller.start()

        guard = PlaybackGuard(xbmc.Player(), xbmc.Monitor(), local_url, controller)
        guard.start()

        li = xbmcgui.ListItem(path=local_url)
        li.setProperty('IsPlayable', 'true')
        li.setMimeType('video/mp4')
        li.setContentLookup(False)
        xbmcplugin.setResolvedUrl(self.addon_handle, True, li)
        guard.join()
