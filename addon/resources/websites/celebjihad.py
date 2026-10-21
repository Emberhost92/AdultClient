#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import urllib.parse

import xbmc
import xbmcgui
import xbmcplugin

from resources.lib.kvs_tube import KVSTubeWebsite
from resources.lib.media_probe import make_session

_BLOCKED = ("teen", "teens", "underage", "preteen", "lolita", "jailbait", "child", "children")
_AGE = re.compile(r"\b(?:1[0-7]|[1-9])\s*(?:yo|y\.o\.?|years?\s*old)\b", re.IGNORECASE)
_LISTING = {"category", "tag", "author", "page", "feed", "hub"}
_SKIP_IMG = ("icon", "logo", "emoji", "avatar", "sprite", "gravatar", "placeholder", "thumb")
_PREVIEW = ("trailer", "preview", "teaser", "sample")


def _skip(value):
    text = (value or "").replace("_", " ")
    words = re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
    if any(word in _BLOCKED for word in words):
        return True
    return bool(_AGE.search(text))


class Celebjihad(KVSTubeWebsite):
    label = "Celeb Jihad"
    sort_options = ["Latest"]
    sort_paths = {"Latest": "/"}
    categories_path = None
    models_path = None
    use_playback_proxy = False

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="celebjihad",
            base_url="https://celebjihad.com/",
            search_url="https://celebjihad.com/?s={}",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.session = make_session()

    def _headers(self, referer=None, accept=None):
        headers = super()._headers(referer, accept)
        for key, value in list(headers.items()):
            if not isinstance(value, str):
                continue
            try:
                value.encode("latin-1")
            except UnicodeEncodeError:
                headers[key] = urllib.parse.quote(value, safe=":/%?#[]@!$&'()*+,;=")
        return headers

    def _get(self, url, referer=None, max_retries=None):
        if max_retries is None:
            max_retries = self.request_retries
        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                response = self.session.get(url, headers=self._headers(referer), timeout=20)
                if response.status_code == 200 and response.text:
                    return response.text
                last_error = "HTTP {}".format(response.status_code)
            except Exception as exc:
                last_error = exc
                self.session = make_session()
            if attempt < max_retries:
                xbmc.sleep(650 * attempt)
        self.logger.error("%s failed to fetch listing page: %s", self.label or self.name, last_error)
        return ""

    def _is_listing_url(self, url):
        parsed = urllib.parse.urlparse(url or self.base_url)
        if urllib.parse.parse_qs(parsed.query).get("s"):
            return True
        parts = [part.lower() for part in (parsed.path or "/").split("/") if part]
        return not parts or parts[0] in _LISTING

    def _region(self, html_content):
        match = re.search(
            r'class=["\'][^"\']*(?:entry-content|post-content|article-content)[^"\']*["\'][^>]*>([\s\S]{0,250000})',
            html_content or "",
            re.IGNORECASE,
        )
        return match.group(1) if match else ""

    def _keep_photo(self, image):
        lowered = (image or "").lower()
        if not lowered.startswith("http") or _skip(image):
            return False
        if any(token in lowered for token in _SKIP_IMG):
            return False
        if not re.search(r"\.(?:jpe?g|png|webp)(?:$|\?)", lowered):
            return False
        if re.search(r"-\d+x\d+\.(?:jpe?g|png|webp)(?:$|\?)", lowered):
            return False
        return True

    def _articles(self, html_content):
        posts = []
        seen = set()
        for chunk in re.findall(r"<article\b[\s\S]*?</article>", html_content or "", re.IGNORECASE):
            post_url = ""
            for href in re.findall(r'href=["\']([^"\']+)["\']', chunk, re.IGNORECASE):
                candidate = self._absolute(href)
                parts = [part.lower() for part in urllib.parse.urlparse(candidate).path.split("/") if part]
                host = urllib.parse.urlparse(candidate).netloc.lower()
                if "celebjihad.com" not in host or not parts or parts[0] in _LISTING:
                    continue
                if _skip(candidate):
                    continue
                post_url = candidate
                break
            if not post_url or post_url in seen:
                continue
            title_match = re.search(r"<h\d\b[^>]*>([\s\S]{0,300}?)</h\d>", chunk, re.IGNORECASE)
            if not title_match:
                title_match = re.search(r'\b(?:aria-label|title)=["\']([^"\']+)["\']', chunk, re.IGNORECASE)
            title = self._clean(title_match.group(1) if title_match else "")
            if not title or _skip(title):
                continue
            seen.add(post_url)
            posts.append({
                "label": title,
                "url": post_url,
                "thumb": self.icon,
                "info": {"title": title, "plot": title},
            })
        return posts

    def _clips(self, html_content):
        region = self._region(html_content)
        clips = []
        for href in re.findall(r'https?://[^"\'\s>]+\.mp4(?:\?[^"\'\s>]*)?', region, re.IGNORECASE):
            clip = self._absolute(href.replace("&amp;", "&"))
            lowered = clip.lower()
            if not clip.startswith("http") or clip in clips or _skip(clip):
                continue
            if any(token in lowered for token in _PREVIEW):
                continue
            clips.append(clip)
        return clips

    def _photos(self, html_content):
        region = self._region(html_content)
        photos = []
        for href in re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\']', region, re.IGNORECASE):
            photo = self._absolute(href.replace("&amp;", "&"))
            if self._keep_photo(photo) and photo not in photos:
                photos.append(photo)
        if len(photos) < 3:
            for src in re.findall(r'(?:data-lazy-src|data-src|data-original|src)=["\']([^"\']+)["\']', region, re.IGNORECASE):
                photo = self._absolute(src.replace("&amp;", "&"))
                if self._keep_photo(photo) and photo not in photos:
                    photos.append(photo)
        return photos

    def process_content(self, url, page=1):
        if not url or url == "BOOTSTRAP":
            url, _ = self.get_start_url_and_label()
        context_menu = self._context_menu(url)
        if not self._is_listing_url(url):
            html_content = self._get(url, referer=self.base_url)
            clips = self._clips(html_content)
            photos = self._photos(html_content)
            if not clips and not photos:
                self.notify_error("No {} media found".format(self.label or self.name))
                self.end_directory("videos")
                return
            for index, clip in enumerate(clips, 1):
                label = "Video" if len(clips) == 1 else "Video {}".format(index)
                self.add_link(label, clip, 4, self.icon, self.fanart, info_labels={"title": label, "plot": label}, referer=url)
            for index, photo in enumerate(photos, 1):
                label = "Photo {}".format(index)
                self.add_link(label, photo, 4, photo, self.fanart, info_labels={"title": label, "plot": label}, referer=url)
            self.end_directory("videos")
            return
        if page <= 1 and not urllib.parse.parse_qs(urllib.parse.urlparse(url or "").query).get("s"):
            self.add_dir("Search", "", 5, self.icons.get("search", self.icon), context_menu=context_menu)
        html_content = self._get(url, referer=self.base_url)
        posts = self._articles(html_content)
        if not posts:
            self.notify_error("No {} posts found".format(self.label or self.name))
            self.end_directory("videos")
            return
        for item in posts:
            self.add_dir(item["label"], item["url"], 2, item["thumb"], self.fanart, info_labels=item["info"])
        self.end_directory("videos")

    def add_dir(self, name, url, mode, icon=None, fanart=None, context_menu=None, name_param=None, info_labels=None, **kwargs):
        if _skip(name) or _skip(url):
            return
        super().add_dir(name, url, mode, icon, fanart, context_menu, name_param, info_labels, **kwargs)

    def search(self, query):
        if _skip(query):
            self.end_directory("videos")
            return
        self.process_content(self.search_url.format(urllib.parse.quote_plus(query.strip())))

    def play_video(self, url):
        lowered = (url or "").lower()
        is_image = bool(re.search(r"\.(?:jpe?g|png|webp)(?:$|\?)", lowered))
        is_video = ".mp4" in lowered and not any(token in lowered for token in _PREVIEW)
        if not is_image and not is_video:
            self.notify_error("Could not resolve stream URL")
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return
        headers = self._headers(self.base_url, accept="*/*")
        list_item = xbmcgui.ListItem(path="{}|{}".format(url, urllib.parse.urlencode(headers)))
        list_item.setProperty("IsPlayable", "true")
        if is_video:
            mime = "video/mp4"
        elif ".webp" in lowered:
            mime = "image/webp"
        elif ".png" in lowered:
            mime = "image/png"
        else:
            mime = "image/jpeg"
        list_item.setMimeType(mime)
        list_item.setContentLookup(False)
        xbmcplugin.setResolvedUrl(self.addon_handle, True, list_item)
