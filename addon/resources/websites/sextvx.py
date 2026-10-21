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


class SexTVx(BaseWebsite):
    label = "SexTVx"
    sort_options = ["Latest", "Most Viewed", "HD"]
    sort_paths = ["/recent/", "/popular/", "/hd_porn/"]

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="sextvx",
            base_url="https://www.sextvx.com/",
            search_url="https://www.sextvx.com/results?search_query={}",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.session = requests.Session()
        self.ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36"
        )

    def _headers(self, referer=None):
        return {
            "User-Agent": self.ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "identity",
            "Referer": referer or self.base_url,
        }

    def _get(self, url, referer=None):
        try:
            response = self.session.get(
                url,
                headers=self._headers(referer),
                timeout=25,
                allow_redirects=True,
            )
            if response.status_code == 200:
                return response.text
            self.logger.warning("SexTVx HTTP %s for %s", response.status_code, url)
        except Exception as exc:
            self.logger.warning("SexTVx request failed for %s: %s", url, exc)
        return ""

    def _sort_index(self):
        try:
            index = int(self.addon.getSetting("sextvx_sort_by") or "0")
        except Exception:
            index = 0
        return index if 0 <= index < len(self.sort_paths) else 0

    def get_start_url_and_label(self):
        return urllib.parse.urljoin(self.base_url, self.sort_paths[self._sort_index()]), self.label

    def _page_url(self, url, page):
        if page <= 1:
            return url
        parsed = urllib.parse.urlparse(url)
        path = re.sub(r"/\d+/?$", "/", parsed.path or "/")
        if path == "/":
            path = "/{}/".format(page)
        else:
            path = path.rstrip("/") + "/{}/".format(page)
        return urllib.parse.urlunparse(
            (parsed.scheme, parsed.netloc, path, parsed.params, parsed.query, "")
        )

    def _extract_videos(self, content):
        videos = []
        seen = set()
        for block in re.findall(
            r'<div class="video rotate"[^>]*>(.*?)</div>\s*</div>',
            content or "",
            re.IGNORECASE | re.DOTALL,
        ):
            link = re.search(
                r'<a href="((?:https://www\.sextvx\.com)?/video/[^"]+)"',
                block,
                re.IGNORECASE,
            )
            image = re.search(
                r'<img[^>]+(?:data-src|src)="([^"]+)"[^>]+alt="([^"]*)"',
                block,
                re.IGNORECASE,
            )
            duration = re.search(
                r'<span class="duration"[^>]*>.*?</span>\s*(?:(\d+)\s*h\s*)?(\d+)\s*min',
                block,
                re.IGNORECASE | re.DOTALL,
            )
            quality = re.search(r'<span class="hd-res">\s*([^<]+)', block, re.IGNORECASE)
            title_match = re.search(r'<h3><a[^>]+title="([^"]+)"', block, re.IGNORECASE)
            if not link or not image:
                continue
            video_url = urllib.parse.urljoin(self.base_url, html.unescape(link.group(1)))
            if video_url in seen:
                continue
            seen.add(video_url)
            title = html.unescape(
                (title_match.group(1) if title_match else image.group(2)).strip()
            )
            thumb = html.unescape(image.group(1))
            duration_text = ""
            seconds = 0
            if duration:
                hours = int(duration.group(1) or "0")
                minutes = int(duration.group(2))
                seconds = hours * 3600 + minutes * 60
                duration_text = "{}:{:02d}:00".format(hours, minutes) if hours else "{} min".format(minutes)
            display = title
            if duration_text:
                display += " [COLOR lime]({})[/COLOR]".format(duration_text)
            if quality:
                display += " [COLOR cyan][{}][/COLOR]".format(quality.group(1).strip())
            info = {"title": title, "plot": title, "mediatype": "video"}
            if seconds:
                info["duration"] = seconds
            videos.append((display, video_url, thumb, info))
        return videos

    def process_content(self, url, page=1):
        if not url or url == "BOOTSTRAP":
            url, _ = self.get_start_url_and_label()
        if page == 1:
            self.add_dir("Search", "", 5, self.icons.get("search", self.icon))
            self.add_dir(
                "Categories",
                urllib.parse.urljoin(self.base_url, "/categories/"),
                8,
                self.icons.get("categories", self.icon),
            )
            self.add_dir(
                "Pornstars",
                urllib.parse.urljoin(self.base_url, "/pornstars/"),
                9,
                self.icons.get("pornstars", self.icon),
            )
        target = self._page_url(url, page)
        content = self._get(target)
        videos = self._extract_videos(content)
        for label, video_url, thumb, info in videos:
            self.add_link(label, video_url, 4, thumb, self.fanart, info_labels=info)
        if videos and re.search(
            r'href=["\']{}["\']'.format(re.escape(self._page_url(url, page + 1))),
            content,
            re.IGNORECASE,
        ):
            self.add_dir(
                "Next Page",
                url,
                2,
                self.icons.get("default", self.icon),
                page=page + 1,
            )
        self.end_directory("videos")

    def process_categories(self, url):
        content = self._get(url or urllib.parse.urljoin(self.base_url, "/categories/"))
        seen = set()
        for href, name in re.findall(
            r'<a href="(/category/[^"]+/)"[^>]*>([^<]+)</a>',
            content,
            re.IGNORECASE,
        ):
            name = html.unescape(name).strip()
            if not name or href in seen or name.lower() in ("gays", "gay"):
                continue
            seen.add(href)
            self.add_dir(
                name,
                urllib.parse.urljoin(self.base_url, href),
                2,
                self.icons.get("categories", self.icon),
            )
        self.end_directory("files")

    def process_pornstars(self, url):
        content = self._get(url or urllib.parse.urljoin(self.base_url, "/pornstars/"))
        seen = set()
        for block in re.findall(
            r'<div class="video rotate pstar"[^>]*>(.*?)</div>\s*</div>',
            content,
            re.IGNORECASE | re.DOTALL,
        ):
            href_match = re.search(r'<a href="(/pornstar/[^"]+)"', block, re.IGNORECASE)
            image_match = re.search(r'<img[^>]+src="([^"]+)"', block, re.IGNORECASE)
            name_match = re.search(
                r'<h3>\s*<a[^>]*>([^<]+)</a>',
                block,
                re.IGNORECASE | re.DOTALL,
            )
            if not href_match or not image_match or not name_match:
                continue
            href = href_match.group(1)
            image = image_match.group(1)
            name = name_match.group(1)
            if href in seen:
                continue
            seen.add(href)
            self.add_dir(
                html.unescape(name).strip(),
                urllib.parse.urljoin(self.base_url, href),
                2,
                html.unescape(image),
            )
        self.end_directory("files")

    def search(self, query):
        if query:
            self.process_content(self.search_url.format(urllib.parse.quote_plus(query.strip())))

    def _resolve(self, url):
        content = self._get(url, self.base_url)
        sources = []
        for stream, quality in re.findall(
            r'<source[^>]+src=[\'"]([^\'"]+)[\'"][^>]+title=[\'"](\d+)p[\'"]',
            content,
            re.IGNORECASE,
        ):
            sources.append((int(quality), html.unescape(stream)))
        if not sources:
            return None
        _, stream_url = max(sources, key=lambda item: item[0])
        return {
            "url": stream_url,
            "headers": {"User-Agent": self.ua, "Referer": url},
            "extension": "mp4",
        }

    def resolve_recording_stream(self, url):
        return self._resolve(url)

    def play_video(self, url):
        resolved = self._resolve(url)
        if not resolved:
            self.notify_error("Could not resolve SexTVx stream")
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return
        controller = ProxyController(
            resolved["url"],
            upstream_headers=resolved["headers"],
            session=self.session,
            use_urllib=True,
            probe_size=True,
            skip_resolve=True,
        )
        local_url = controller.start()
        guard = PlaybackGuard(xbmc.Player(), xbmc.Monitor(), local_url, controller)
        guard.start()
        item = xbmcgui.ListItem(path=local_url)
        item.setProperty("IsPlayable", "true")
        item.setMimeType("video/mp4")
        item.setContentLookup(False)
        xbmcplugin.setResolvedUrl(self.addon_handle, True, item)
        guard.join()
