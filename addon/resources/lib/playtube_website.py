# -*- coding: utf-8 -*-

import html
import os
import re
import urllib.parse

import requests
import xbmcgui
import xbmcplugin

from resources.lib.base_website import BaseWebsite
from resources.lib.playback_preferences import order_quality_variants, quality_from_value


class PlayTubeWebsite(BaseWebsite):
    """Reusable implementation for the small PlayTube-based sites."""

    label = ""
    sort_options = ["Latest", "Trending", "Top Rated"]
    sort_paths = {
        "Latest": "/videos/latest",
        "Trending": "/videos/trending",
        "Top Rated": "/videos/top",
    }
    skip_directory_titles = set()

    def __init__(self, name, label, base_url, addon_handle, addon=None):
        super().__init__(name, base_url, base_url + "search?keyword={}", addon_handle, addon)
        self.label = label
        self.session = requests.Session()
        self.ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/134.0.0.0 Safari/537.36"
        )
        self.icon = os.path.join(
            self.addon.getAddonInfo("path"), "resources", "logos", name + ".png"
        )
        self.icons["default"] = self.icon

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
            response = self.session.get(url, headers=self._headers(referer), timeout=20)
            if response.status_code == 200:
                return response.text
            self.logger.warning("[%s] HTTP %s for %s", self.name, response.status_code, url)
        except Exception as exc:
            self.logger.warning("[%s] Request failed for %s: %s", self.name, url, exc)
        return ""

    def _absolute(self, value):
        return urllib.parse.urljoin(self.base_url, html.unescape(value or "").strip())

    def _clean(self, value):
        value = re.sub(r"<[^>]+>", " ", value or "")
        return re.sub(r"\s+", " ", html.unescape(value)).strip()

    def _sort_key(self):
        try:
            index = int(self.addon.getSetting("{}_sort_by".format(self.name)) or "0")
        except (TypeError, ValueError):
            index = 0
        if not 0 <= index < len(self.sort_options):
            index = 0
        return self.sort_options[index]

    def get_start_url_and_label(self):
        key = self._sort_key()
        return self._absolute(self.sort_paths[key]), "{} [COLOR yellow]{}[/COLOR]".format(self.label, key)

    def get_page_url(self, url, page):
        if page <= 1:
            return url
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        query["page_id"] = [str(page)]
        return urllib.parse.urlunparse(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.params, urllib.parse.urlencode(query, doseq=True), parsed.fragment)
        )

    def _is_top_listing(self, url):
        path = urllib.parse.urlparse(url or "").path.rstrip("/")
        return path in tuple(path.rstrip("/") for path in self.sort_paths.values())

    def _video_items(self, page_html):
        items = []
        seen = set()
        blocks = re.split(
            r'(?=<div\b[^>]+class=["\'][^"\']*video-latest-list\s+video-wrapper[^"\']*["\'])',
            page_html or "",
            flags=re.I,
        )
        for block in blocks:
            href_match = re.search(r'<a\b[^>]+href=["\']([^"\']*/watch/[^"\']+)["\']', block, re.I)
            if not href_match:
                continue
            url = self._absolute(href_match.group(1))
            if url in seen:
                continue
            seen.add(url)

            img_match = re.search(r'<img\b[^>]*>', block, re.I)
            img_tag = img_match.group(0) if img_match else ""
            title_match = re.search(r'\s(?:alt|title)=["\']([^"\']+)', img_tag, re.I)
            if not title_match:
                title_match = re.search(r'<h4\b[^>]*title=["\']([^"\']+)', block, re.I)
            title = self._clean(title_match.group(1) if title_match else "")
            if not title:
                continue

            thumb_match = re.search(r'\s(?:data-src|data-original|src)=["\']([^"\']+)', img_tag, re.I)
            thumb = self._absolute(thumb_match.group(1)) if thumb_match else self.icon
            duration_match = re.search(r'class=["\'][^"\']*video-duration[^"\']*["\'][^>]*>([^<]+)', block, re.I)
            duration = self._clean(duration_match.group(1) if duration_match else "")
            seconds = self.convert_duration(duration)
            label = "{} [COLOR lime]({})[/COLOR]".format(title, duration) if duration else title
            info = {"title": title, "plot": title}
            if seconds:
                info["duration"] = seconds
            items.append({"label": label, "url": url, "thumb": thumb, "info": info})
        return items

    def process_content(self, url, page=1):
        if not url or url == "BOOTSTRAP":
            url, _ = self.get_start_url_and_label()
        if page == 1 and self._is_top_listing(url):
            self.add_dir("Search", "", 5, self.icons.get("search", self.icon))
            self.add_dir("Categories", self._absolute("/categories"), 8, self.icons.get("categories", self.icon))
            self.add_dir("Pornstars", self._absolute("/pornstars"), 9, self.icons.get("pornstars", self.icon))

        target = self.get_page_url(url, page)
        page_html = self._get(target)
        if not page_html:
            self.notify_error("Could not load {} content".format(self.label))
            self.end_directory("videos")
            return
        items = self._video_items(page_html)
        for item in items:
            self.add_link(item["label"], item["url"], 4, item["thumb"], self.fanart, info_labels=item["info"])
        if items and re.search(r'[?&]page_id={}\b'.format(page + 1), page_html):
            self.add_dir("Next Page", url, 2, self.icons.get("default", self.icon), page=page + 1)
        self.end_directory("videos")

    def _directory(self, url, marker, mode, icon):
        page = 1
        parsed = urllib.parse.urlparse(url)
        try:
            page = max(1, int(urllib.parse.parse_qs(parsed.query).get("page_id", [1])[0]))
        except (TypeError, ValueError):
            page = 1
        page_html = self._get(url)
        seen = set()
        for match in re.finditer(r'<a\b[^>]+href=["\']([^"\']+)["\'][^>]*>([\s\S]{0,1600}?)</a>', page_html, re.I):
            href, body = match.group(1), match.group(2)
            if marker not in href:
                continue
            target = self._absolute(href)
            if target in seen:
                continue
            seen.add(target)
            image = re.search(r'<img\b[^>]*>', body, re.I)
            image_tag = image.group(0) if image else ""
            title_match = re.search(r'\s(?:alt|title)=["\']([^"\']+)', image_tag, re.I)
            title = self._clean(title_match.group(1) if title_match else body)
            if not title or title.lower() in self.skip_directory_titles:
                continue
            thumb_match = re.search(r'\s(?:data-src|data-original|src)=["\']([^"\']+)', image_tag, re.I)
            art = self._absolute(thumb_match.group(1)) if thumb_match else icon
            self.add_dir(title, target, 2, art, self.fanart)
        if re.search(r'[?&]page_id={}\b'.format(page + 1), page_html):
            self.add_dir("Next Page", self.get_page_url(url, page + 1), mode, self.icons.get("default", self.icon))
        self.end_directory("videos")

    def process_categories(self, url):
        self._directory(url or self._absolute("/categories"), "/videos/category/", 8, self.icons.get("categories", self.icon))

    def process_pornstars(self, url):
        self._directory(url or self._absolute("/pornstars"), "/videos/pornstar/", 9, self.icons.get("pornstars", self.icon))

    def search(self, query):
        if query:
            self.process_content(self.search_url.format(urllib.parse.quote_plus(query.strip())))

    def _stream_variants(self, page_html):
        variants = []
        for source, label in re.findall(
            r'\{\s*["\']file["\']\s*:\s*["\']([^"\']+)["\']\s*,\s*["\']label["\']\s*:\s*["\']([^"\']+)',
            page_html or "",
            re.I,
        ):
            source = html.unescape(source).replace("\\/", "/")
            quality = 2160 if label.upper() == "4K" else 1440 if label.upper() == "2K" else quality_from_value(label)
            variants.append((quality, source))
        return order_quality_variants(variants, self.addon)

    def _probe(self, stream_url, referer):
        try:
            headers = self._headers(referer, "*/*")
            headers["Range"] = "bytes=0-0"
            response = self.session.get(stream_url, headers=headers, timeout=15, stream=True, allow_redirects=True)
            response.close()
            return response.status_code in (200, 206)
        except Exception:
            return False

    def resolve_recording_stream(self, url):
        page_html = self._get(url, referer=self.base_url)
        variants = self._stream_variants(page_html)
        if not variants:
            return None
        selected = next((stream for _, stream in variants if self._probe(stream, url)), variants[0][1])
        return {"url": selected, "headers": self._headers(url, "*/*"), "extension": "mp4"}

    def play_video(self, url):
        resolved = self.resolve_recording_stream(url)
        if not resolved:
            self.notify_error("Could not resolve {} stream".format(self.label))
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return
        play_url = resolved["url"] + "|" + urllib.parse.urlencode(resolved["headers"])
        item = xbmcgui.ListItem(path=play_url)
        item.setProperty("IsPlayable", "true")
        item.setMimeType("video/mp4")
        item.setContentLookup(False)
        xbmcplugin.setResolvedUrl(self.addon_handle, True, item)
