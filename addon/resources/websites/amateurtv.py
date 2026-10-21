#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import urllib.parse

import requests
import xbmcgui
import xbmcplugin

from resources.lib.base_website import BaseWebsite


class AmateurTv(BaseWebsite):
    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="amateurtv",
            base_url="https://www.amateur.tv/",
            search_url="https://www.amateur.tv/search/{}",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.label = "Amateur.tv"
        self.session = requests.Session()
        self.ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )

    def _headers(self, referer=None):
        return {
            "User-Agent": self.ua,
            "Referer": referer or self.base_url,
            "Accept": "text/html",
        }

    def _get(self, url):
        try:
            response = self.session.get(url, headers=self._headers(), timeout=18)
            if response.status_code == 200 and response.text:
                return response.text
        except Exception as exc:
            self.logger.warning("Amateur.tv request failed: %s", exc)
        return ""

    def _plain(self, content):
        text = content or ""
        if '\\"' in text:
            text = text.replace('\\"', '"').replace("\\/", "/")
        return text

    def _clips(self, content):
        text = self._plain(content)
        clips = []
        seen = set()
        for match in re.finditer(r'"video":"(https://clips\.amateur\.tv/[^"]+\.mp4)"', text):
            url = match.group(1)
            if url in seen:
                continue
            seen.add(url)
            window = text[max(0, match.start() - 900):match.end() + 500]
            age_match = re.search(r'"ages":\["(\d+)"\]', window)
            if age_match and int(age_match.group(1)) < 18:
                continue
            tags = re.findall(r'"tags":\[(.*?)\]', window)
            tag_text = tags[0].lower() if tags else ""
            if age_match is None and re.search(r'"teens?"', tag_text):
                continue
            thumb_match = re.search(r'"videoCapture":"(https://clips\.amateur\.tv/[^"]+)"', window)
            name_match = re.search(
                r'"(?:username|nickname|name|displayName|model)":"([^"]{1,48})"',
                window,
            )
            title = name_match.group(1) if name_match else "Live clip"
            clips.append({
                "url": url,
                "thumb": thumb_match.group(1) if thumb_match else self.icon,
                "title": title,
            })
        return clips

    def process_content(self, url, page=1):
        if not url or url == "BOOTSTRAP":
            url = self.base_url
        content = self._get(url)
        clips = self._clips(content)
        for clip in clips:
            self.add_link(
                clip["title"],
                clip["url"],
                4,
                clip["thumb"],
                self.fanart,
                info_labels={"title": clip["title"], "plot": clip["title"]},
            )
        if not clips:
            self.notify_error("No Amateur.tv clips found")
        self.end_directory("videos")

    def search(self, query):
        if query:
            self.process_content(self.base_url)

    def play_video(self, url):
        headers = self._headers(self.base_url)
        play_url = "{}|{}".format(url, urllib.parse.urlencode(headers))
        item = xbmcgui.ListItem(path=play_url)
        item.setProperty("IsPlayable", "true")
        item.setMimeType("video/mp4")
        item.setContentLookup(False)
        xbmcplugin.setResolvedUrl(self.addon_handle, True, item)
