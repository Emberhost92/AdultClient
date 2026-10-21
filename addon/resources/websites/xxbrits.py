# -*- coding: utf-8 -*-
import html
import re
import urllib.parse

import requests
import xbmc
import xbmcgui
import xbmcplugin

from resources.lib.base_website import BaseWebsite
from resources.lib.decoders.kvs_decoder import kvs_decode_url
from resources.lib.proxy_utils import PlaybackGuard, ProxyController
from resources.lib.resilient_http import fetch_text


class XXBrits(BaseWebsite):
    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="xxbrits",
            base_url="https://www.xxbrits.com/",
            search_url="https://www.xxbrits.com/search/{}/",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.label = "XXBrits"
        self.ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.ua, "Referer": self.base_url})
        self.sort_options = ["Latest", "Most Viewed", "Top Rated"]
        self.sort_paths = {
            "Latest": "/latest/",
            "Most Viewed": "/most-popular/",
            "Top Rated": "/top-rated/",
        }
        self.categories_url = f"{self.base_url}ct/"

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
            self.logger.warning("XXBrits HTTP %s for %s", response.status_code, url)
        except Exception as exc:
            self.logger.warning("XXBrits request failed for %s: %s", url, exc)
            self.session = requests.Session()
        return fetch_text(url, headers=self._headers(referer), logger=self.logger,
                          timeout=25, use_windows_curl_fallback=True) or ""

    def _page_url(self, url, page):
        if page <= 1:
            return url
        parsed = urllib.parse.urlparse(url)
        path = parsed.path
        if not path.endswith("/"):
            path += "/"
        path = re.sub(r"/\d+/$", "/", path) + "{}/".format(page)
        return urllib.parse.urlunparse(parsed._replace(path=path))

    def process_content(self, url, page=1, **kwargs):
        if not url or url == "BOOTSTRAP":
            url, _ = self.get_start_url_and_label()

        if page == 1:
            self.add_dir('[COLOR blue]Search[/COLOR]', '', 5, self.icons['search'])
            self.add_dir('[COLOR yellow]Categories[/COLOR]', self.categories_url, 8, self.icons['categories'])

        content = self.make_request(self._page_url(url, page))
        if not content:
            self.notify_error("Could not load XXBrits")
            return self.end_directory()

        count = self._render_video_list(content)
        if count:
            self.add_dir('[COLOR blue]Next Page >>[/COLOR]', url, 2, self.icons['default'], page=page + 1)

        self.end_directory()

    def _render_video_list(self, content):
        pattern = (
            r'<a class="card-image" href="(https://www\.xxbrits\.com/videos/\d+/[^"]+/)" title="([^"]*)"[^>]*>'
            r'[\s\S]*?<img[^>]*?(?:data-original|src)="([^"]+\.jpg)"'
            r'[\s\S]*?<span>\s*(\d{1,2}:\d{2}(?::\d{2})?)\s*</span>'
        )
        seen = set()
        count = 0
        for video_url, title, thumb, duration in re.findall(pattern, content):
            if video_url in seen:
                continue
            seen.add(video_url)
            display_title = html.unescape(title.strip()) or "Untitled"
            thumb = html.unescape(thumb)
            label = "{} [COLOR lime]({})[/COLOR]".format(display_title, duration)
            info = {"title": display_title, "mediatype": "video"}
            seconds = self.convert_duration(duration)
            if seconds:
                info["duration"] = seconds
            self.add_link(label, video_url, 4, thumb, self.fanart, info_labels=info)
            count += 1
        return count

    def process_categories(self, url):
        content = self.make_request(url or self.categories_url)
        if not content:
            return self.end_directory(content_type='files')

        self.add_dir('[COLOR blue]Search[/COLOR]', '', 5, self.icons['search'])
        pattern = r'<a href="(https://www\.xxbrits\.com/ct/[^"/]+/)">\s*<span>([^<]+)</span>'
        seen = set()
        for cat_url, name in re.findall(pattern, content):
            if cat_url in seen:
                continue
            seen.add(cat_url)
            label = html.unescape(name.strip())
            if label:
                self.add_dir(label, cat_url, 2, self.icons['categories'])

        self.end_directory(content_type='files')

    def search(self, query):
        if query:
            # the site rewrites /search/<q>/ to a hashed URL via 301; the session
            # follows the redirect automatically.
            self.process_content(self.search_url.format(urllib.parse.quote_plus(query.strip())))

    def _resolve_stream(self, url):
        content = self.make_request(url, referer=self.base_url)
        if not content:
            return None
        license_match = re.search(r"license_code:\s*'([^']*)'", content)
        license_code = html.unescape(license_match.group(1)).strip() if license_match else ""

        best_url, best_res = None, -1
        for key, value in re.findall(r"(video_url|video_alt_url\d*):\s*'([^']+)'", content):
            stream = html.unescape(value).replace("\\/", "/").strip()
            if stream.startswith("function/0/") and license_code:
                try:
                    stream = kvs_decode_url(stream, license_code)
                except Exception as exc:
                    self.logger.warning("XXBrits KVS decode failed: %s", exc)
                    continue
            if ".mp4" not in stream.lower():
                continue
            label_match = re.search(re.escape(key) + r"_text:\s*'(\d+)p'", content)
            res = int(label_match.group(1)) if label_match else 0
            if res > best_res:
                best_res, best_url = res, urllib.parse.urljoin(self.base_url, stream)
        return best_url

    def play_video(self, url):
        stream_url = self._resolve_stream(url)
        if not stream_url:
            self.notify_error("Could not resolve XXBrits stream")
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return

        # the tokenised get_file URL 302-redirects to a signed CDN host; route it
        # through the local proxy so the add-on's own session resolves and serves.
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
