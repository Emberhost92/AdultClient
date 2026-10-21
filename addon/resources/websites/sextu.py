# -*- coding: utf-8 -*-
import html
import json
import re
import urllib.parse

import requests
import xbmc
import xbmcgui
import xbmcplugin

from resources.lib.base_website import BaseWebsite
from resources.lib.proxy_utils import PlaybackGuard, ProxyController
from resources.lib.resilient_http import fetch_text

# The site obfuscates its stream URLs with a "base164" scheme: standard base64
# whose alphabet swaps five ASCII letters (A B C E M) for their Cyrillic
# homoglyphs (А В С Е М). Decode with the site's own alphabet, then unquote.
_B164_ALPHABET = ("АВСDЕFGHIJKLМNOPQRSTUVWXYZ"
                  "abcdefghijklmnopqrstuvwxyz0123456789.,~")
_B164_STRIP = re.compile("[^" + _B164_ALPHABET + "]")


def _base164_decode(data):
    data = _B164_STRIP.sub("", data)
    out = []
    n = 0
    idx = _B164_ALPHABET.index
    while n < len(data):
        o = idx(data[n]); p = idx(data[n + 1])
        q = idx(data[n + 2]); r = idx(data[n + 3])
        n += 4
        out.append(chr(o << 2 | p >> 4))
        if q != 64:
            out.append(chr((p & 15) << 4 | q >> 2))
        if r != 64:
            out.append(chr((q & 3) << 6 | r))
    return urllib.parse.unquote("".join(out))


class Sextu(BaseWebsite):
    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="sextu",
            base_url="https://fullvideosporn.com/",
            search_url="https://fullvideosporn.com/en/videos.php?p=1&q={}",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.label = "Sextu"
        self.ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.ua, "Referer": self.base_url})
        self.sort_options = ["Latest", "Most Viewed", "Top Rated", "Popular Today"]
        self.sort_paths = {
            "Latest": "/en/videos.php?p=1&s=l",
            "Most Viewed": "/en/videos.php?p=1&s=pm",
            "Top Rated": "/en/videos.php?p=1&s=bm",
            "Popular Today": "/en/videos.php?p=1&s=pd",
        }
        self.categories_url = f"{self.base_url}en/categories.php"

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
            self.logger.warning("Sextu HTTP %s for %s", response.status_code, url)
        except Exception as exc:
            self.logger.warning("Sextu request failed for %s: %s", url, exc)
            self.session = requests.Session()
        return fetch_text(url, headers=self._headers(referer), logger=self.logger,
                          timeout=25, use_windows_curl_fallback=True) or ""

    def _page_url(self, url, page):
        if page <= 1:
            return url
        parsed = urllib.parse.urlparse(url)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        query["p"] = str(page)
        return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))

    def process_content(self, url, page=1, **kwargs):
        if not url or url == "BOOTSTRAP":
            url, _ = self.get_start_url_and_label()

        if page == 1:
            self.add_dir('[COLOR blue]Search[/COLOR]', '', 5, self.icons['search'])
            self.add_dir('[COLOR yellow]Categories[/COLOR]', self.categories_url, 8, self.icons['categories'])

        content = self.make_request(self._page_url(url, page))
        if not content:
            self.notify_error("Could not load Sextu")
            return self.end_directory()

        count = self._render_video_list(content)
        if count:
            self.add_dir('[COLOR blue]Next Page >>[/COLOR]', url, 2, self.icons['default'], page=page + 1)

        self.end_directory()

    def _render_video_list(self, content):
        pattern = (
            r'<a href="(/en/video/\d+/[^"]+)" title="([^"]*)">'
            r'[\s\S]*?<img[^>]*?(?:data-original|data-src|src)="([^"]+\.(?:webp|jpg))"'
            r'[\s\S]*?<span class="duration">\s*([\d:]+)\s*</span>'
        )
        seen = set()
        count = 0
        for path, title, thumb, duration in re.findall(pattern, content):
            if path in seen:
                continue
            seen.add(path)
            video_url = urllib.parse.urljoin(self.base_url, path)
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
        content = self.make_request(url or self.categories_url)
        if not content:
            return self.end_directory(content_type='files')

        self.add_dir('[COLOR blue]Search[/COLOR]', '', 5, self.icons['search'])
        pattern = r'<a class="item" href="(/en/videos\.php\?[^"]*q=[^"]+)" title="([^"]+)"'
        seen = set()
        for cat_path, name in re.findall(pattern, content):
            cat_url = urllib.parse.urljoin(self.base_url, html.unescape(cat_path))
            if cat_url in seen:
                continue
            seen.add(cat_url)
            label = html.unescape(name.strip())
            if label:
                self.add_dir(label, cat_url, 2, self.icons['categories'])

        self.end_directory(content_type='files')

    def search(self, query):
        if query:
            self.process_content(self.search_url.format(urllib.parse.quote_plus(query.strip())))

    def _resolve_stream(self, url):
        vid_match = re.search(r'/video/(\d+)', url)
        if not vid_match:
            return None
        video_id = vid_match.group(1)

        embed = self.make_request(
            urllib.parse.urljoin(self.base_url, "embed.php?id={}".format(video_id)),
            referer=url,
        )
        if not embed:
            return None

        blob_match = re.search(r"'(W3si[A-Za-z0-9+/=~.,АВСЕМ]+)'", embed)
        if not blob_match:
            self.logger.warning("Sextu: no media blob for %s", video_id)
            return None
        try:
            files = json.loads(_base164_decode(blob_match.group(1)))
        except Exception as exc:
            self.logger.warning("Sextu: media blob decode failed: %s", exc)
            return None

        # Prefer the highest available quality (_vhq > _hq > _lq).
        quality_rank = {"_vhq": 3, "_hq": 2, "_lq": 1}
        best_url, best_rank = None, -1
        for entry in files:
            enc = entry.get("video_url")
            if not enc:
                continue
            stream_path = _base164_decode(enc)
            fmt = entry.get("format", "")
            rank = quality_rank.get(fmt.replace(".mp4", ""), 0)
            if rank > best_rank:
                best_rank = rank
                best_url = urllib.parse.urljoin(self.base_url, stream_path)
        return best_url

    def play_video(self, url):
        stream_url = self._resolve_stream(url)
        if not stream_url:
            self.notify_error("Could not resolve Sextu stream")
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return

        # The decoded get_file URL 302-redirects to a signed znvcdn.com host;
        # route it through the local proxy so the add-on's own session resolves
        # and serves it (the token is bound to this session).
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
