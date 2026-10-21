#!/usr/bin/env python
# -*- coding: utf-8 -*-

import html
import re
import sys
import urllib.parse

import requests
import xbmcgui
import xbmcplugin

from resources.lib.base_website import BaseWebsite
from resources.lib.resilient_http import fetch_text


class NetFapX(BaseWebsite):
    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="netfapx",
            base_url="https://netfapx.com/",
            search_url="https://netfapx.com/?s={}",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.label = "NetFapX"
        self.session = requests.Session()
        self.sort_options = ["Latest"]
        self.ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )

    def _headers(self, referer=None, accept="text/html,application/xhtml+xml,*/*;q=0.8"):
        return {
            "User-Agent": self.ua,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "identity",
            "Referer": referer or self.base_url,
        }

    def _get(self, url, referer=None):
        try:
            response = self.session.get(url, headers=self._headers(referer), timeout=20)
            if response.status_code == 200:
                return response.text
        except Exception as exc:
            self.logger.warning("NetFapX request failed for %s: %s", url, exc)
            self.session = requests.Session()
        return fetch_text(url, headers=self._headers(referer), logger=self.logger, timeout=20) or ""

    def _absolute(self, value):
        absolute = urllib.parse.urljoin(self.base_url, html.unescape(value or "").strip())
        parsed = urllib.parse.urlsplit(absolute)
        return urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, urllib.parse.quote(urllib.parse.unquote(parsed.path), safe="/%"), parsed.query, parsed.fragment)
        )

    @staticmethod
    def _clean(value):
        return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value or ""))).strip()

    def get_start_url_and_label(self):
        return self.base_url, self.label

    def get_page_url(self, base_url, page_num):
        if page_num <= 1:
            return base_url
        parsed = urllib.parse.urlparse(base_url)
        if parsed.query:
            query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            query["paged"] = [str(page_num)]
            return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", urllib.parse.urlencode(query, doseq=True), ""))
        return urllib.parse.urljoin(base_url.rstrip("/") + "/", "page/{}/".format(page_num))

    def _extract_videos(self, content):
        videos = []
        seen = set()
        for block in re.findall(r'<article\b[^>]*class=["\'][^"\']*\bpinbox\b[^"\']*["\'][^>]*>([\s\S]*?)</article>', content or "", re.I):
            link = re.search(r'<h3\b[^>]*class=["\'][^"\']*\btitle-2\b[^"\']*["\'][^>]*>\s*<a\b[^>]*href=["\']([^"\']+)["\'][^>]*title=["\']([^"\']+)', block, re.I)
            if not link:
                continue
            video_url = self._absolute(link.group(1))
            if video_url in seen:
                continue
            seen.add(video_url)
            title = self._clean(link.group(2))
            image = re.search(r'<img\b[^>]*(?:data-src|src)=["\']([^"\']+)["\'][^>]*>', block, re.I)
            thumb = self._absolute(image.group(1)) if image else self.icon
            duration_match = re.search(r'title=["\']Duration["\'][^>]*>\s*([^<]+)', block, re.I)
            duration = self._clean(duration_match.group(1)) if duration_match else ""
            info = {"title": title, "plot": title}
            seconds = self.convert_duration(duration)
            if seconds:
                info["duration"] = seconds
            label = "{} [COLOR lime]({})[/COLOR]".format(title, duration) if duration else title
            videos.append((label, video_url, thumb, info))
        return videos

    def process_content(self, url, page=1):
        if not url or url == "BOOTSTRAP":
            url = self.base_url
        target = self.get_page_url(url, page)
        content = self._get(target)
        if page == 1:
            self.add_dir("Search", "", 5, self.icons.get("search", self.icon))
        videos = self._extract_videos(content)
        for label, video_url, thumb, info in videos:
            self.add_link(label, video_url, 4, thumb, self.fanart, info_labels=info)
        if videos and (re.search(r'rel=["\']next["\']', content, re.I) or re.search(r'class=["\']next["\']', content, re.I)):
            self.add_dir("Next Page", url, 2, self.icons.get("default", self.icon), page=page + 1)
        if not videos:
            self.notify_error("No NetFapX videos found")
        self.end_directory("videos")

    def search(self, query):
        if query:
            self.process_content(self.search_url.format(urllib.parse.quote_plus(query.strip())))

    def resolve_recording_stream(self, url):
        content = self._get(url, self.base_url)
        post_id = re.search(r'ajax_object\s*=\s*\{[^}]*["\']post_id["\']\s*:\s*["\']?(\d+)', content, re.I)
        if not post_id:
            post_id = re.search(r'\bpost-(\d+)\b', content, re.I)
        if not post_id:
            return None
        endpoint = urllib.parse.urljoin(self.base_url, "wp-admin/admin-ajax.php")
        try:
            response = self.session.post(
                endpoint,
                data={"action": "get_download_url", "idpost": post_id.group(1)},
                headers=self._headers(url, "*/*"),
                timeout=20,
            )
            stream = response.text.strip().strip('"') if response.status_code == 200 else ""
        except Exception as exc:
            self.logger.warning("NetFapX stream request failed: %s", exc)
            return None
        stream = stream.replace("\\/", "/").replace("\\u0026", "&")
        if not stream.startswith("http") or ".mp4" not in stream:
            return None
        return {"url": stream, "headers": self._headers(url, "*/*"), "extension": "mp4"}

    def play_video(self, url):
        resolved = self.resolve_recording_stream(url)
        if not resolved:
            self.notify_error("Could not resolve NetFapX stream")
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return
        play_url = resolved["url"]
        headers = resolved.get("headers") or {}
        if headers:
            play_url = "{}|{}".format(play_url, urllib.parse.urlencode(headers))
        item = xbmcgui.ListItem(path=play_url)
        item.setProperty("IsPlayable", "true")
        item.setMimeType("video/mp4")
        item.setContentLookup(False)
        xbmcplugin.setResolvedUrl(self.addon_handle, True, item)
