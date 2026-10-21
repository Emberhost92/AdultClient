#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import urllib.parse
import html
import xbmc
import xbmcgui
import xbmcplugin
import requests
from resources.lib.base_website import BaseWebsite
from resources.lib.proxy_utils import ProxyController, PlaybackGuard


class Freeonestube(BaseWebsite):
    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="freeonestube",
            base_url="https://freeonestube.com",
            search_url="https://freeonestube.com/?s={}",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.categories_url = f"{self.base_url}/categories/"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": self.base_url,
        })

    def make_request(self, url):
        try:
            response = self.session.get(url, timeout=20)
            response.raise_for_status()
            return response.text
        except Exception as e:
            self.logger.error(f"Request failed for {url}: {e}")
            self.notify_error("Failed to fetch URL")
            return None

    def search(self, query):
        if not query:
            return
        url = self.search_url.format(urllib.parse.quote(query))
        content = self.make_request(url)
        if not content:
            self.notify_error("Search failed")
            self.end_directory()
            return
        self._render_video_list(content)
        self._add_next_button(content, url)
        self.end_directory()

    def process_content(self, url):
        if not url or url == "BOOTSTRAP":
            url = self.base_url

        content = self.make_request(url)

        self.add_dir('[COLOR blue]Search[/COLOR]', '', 5, self.icons['search'])
        self.add_dir('[COLOR yellow]Categories[/COLOR]', self.categories_url, 8, self.icons['categories'])

        if content:
            self._render_video_list(content)
            self._add_next_button(content, url)

        self.end_directory()

    def process_categories(self, url):
        content = self.make_request(url)
        if not content:
            self.end_directory()
            return

        pattern = r'href="(https://freeonestube\.com/category/[a-z0-9-]+/)"[^>]*>\s*(?:<[^>]+>\s*)*([A-Z][A-Za-z0-9 &-]+)'
        seen = set()
        for cat_url, name in re.findall(pattern, content):
            if cat_url in seen:
                continue
            seen.add(cat_url)
            label = html.unescape(name.strip())
            self.add_dir(label, cat_url, 2, self.icons['categories'])

        self.end_directory(content_type='files')

    def _render_video_list(self, content):
        pattern = (
            r'<a class="thumb" href="(https://freeonestube\.com/video/[a-z0-9-]+/)">.*?'
            r'<img class="video-img[^>]*src="([^"]+)"[^>]*>.*?'
            r'<span class="duration">([\d:]+)</span>.*?'
            r'<a class="infos[^"]*" href="[^"]+" title="([^"]+)"'
        )
        seen = set()
        for video_url, thumb, duration, title in re.findall(pattern, content, re.DOTALL):
            if video_url in seen:
                continue
            seen.add(video_url)
            display_title = html.unescape(title.strip())
            thumb = html.unescape(thumb)
            label = "{} [COLOR lime]({})[/COLOR]".format(display_title, duration)
            info = {"title": display_title, "mediatype": "video"}
            seconds = self.convert_duration(duration)
            if seconds:
                info["duration"] = seconds
            self.add_link(label, video_url, 4, thumb, self.fanart, info_labels=info)

    def _add_next_button(self, content, current_url):
        parsed = urllib.parse.urlparse(current_url)
        # WordPress /page/N/ pagination, preserving any query string (search)
        page_match = re.search(r'/page/(\d+)/', parsed.path)
        if page_match:
            current_page = int(page_match.group(1))
            new_path = parsed.path[:page_match.start()] + "/page/{}/".format(current_page + 1)
        else:
            current_page = 1
            base_path = parsed.path.rstrip('/')
            new_path = (base_path + "/page/2/") if base_path else "/page/2/"
        next_url = urllib.parse.urlunparse(parsed._replace(path=new_path))
        if content.count('class="thumb"') >= 15:
            self.add_dir('[COLOR blue]Next Page >>[/COLOR]', next_url, 2, self.icons['default'])

    def play_video(self, url):
        content = self.make_request(url)
        if not content:
            self.notify_error("Failed to load video page")
            return

        match = re.search(r'itemprop="contentURL" content="([^"]+\.mp4[^"]*)"', content)
        if not match:
            match = re.search(r'(https://media\.freeones\.com/[^"\']+\.mp4)', content)
        if not match:
            self.notify_error("Could not find a playable video stream.")
            return

        stream_url = html.unescape(match.group(1))

        # Kodi's internal CCurlFile fails to read this CDN directly (cache stays
        # at 0); route playback through the local proxy so the same requests
        # session that works from Python fetches and relays the stream.
        controller = ProxyController(
            stream_url,
            upstream_headers={
                'User-Agent': self.session.headers['User-Agent'],
                'Referer': self.base_url,
            },
            session=self.session,
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
