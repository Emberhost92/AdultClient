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
_LISTING = {"category", "tag", "author", "page", "feed", "gallery", "search"}
_SKIP_IMG = ("icon", "logo", "emoji", "avatar", "sprite", "gravatar", "placeholder", "thumb")


def _skip(value):
    text = (value or "").replace("_", " ")
    words = re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
    if any(word in _BLOCKED for word in words):
        return True
    return bool(_AGE.search(text))


class Thefappeningblog(KVSTubeWebsite):
    label = "The Fappening Blog"
    sort_options = ["Latest"]
    sort_paths = {"Latest": "/"}
    categories_path = "/"
    models_path = None
    use_playback_proxy = False

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name="thefappeningblog",
            base_url="https://thefappeningblog.com/",
            search_url="https://thefappeningblog.com/search/?q={}",
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

    def get_page_url(self, base_url, page_num):
        parsed = urllib.parse.urlparse(base_url or self.base_url)
        path = parsed.path or "/"
        if not path.endswith("/"):
            path += "/"
        path = re.sub(r"/page/\d+/$", "/", path, flags=re.IGNORECASE)
        if page_num and page_num > 1:
            path = path.rstrip("/") + "/page/{}/".format(page_num)
        scheme = parsed.scheme or "https"
        netloc = parsed.netloc or urllib.parse.urlparse(self.base_url).netloc
        return urllib.parse.urlunparse((scheme, netloc, path, "", parsed.query, ""))

    def _is_listing_url(self, url):
        parsed = urllib.parse.urlparse(url or self.base_url)
        if urllib.parse.parse_qs(parsed.query).get("s"):
            return True
        parts = [part.lower() for part in (parsed.path or "/").split("/") if part]
        if not parts or "page" in parts or parts[0] in _LISTING:
            return True
        return False

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
                if "thefappeningblog.com" not in host or not parts or parts[0] in _LISTING:
                    continue
                if parts[0] in ("wp-content", "wp-json", "cdn-cgi") or _skip(candidate):
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
            thumb = ""
            for src in re.findall(r'(?:data-lazy-src|data-src|src)=["\']([^"\']+)["\']', chunk, re.IGNORECASE):
                image = self._absolute(src.replace("&amp;", "&"))
                if self._keep_photo(image) or (image.startswith("http") and re.search(r"\.(?:jpe?g|png|webp)", image, re.I)):
                    thumb = image
                    break
            posts.append({
                "label": title,
                "url": post_url,
                "thumb": thumb or self.icon,
                "info": {"title": title, "plot": title},
            })
        return posts

    def _photos(self, html_content):
        match = re.search(
            r'class=["\'][^"\']*(?:entry-content|post-content|article-content)[^"\']*["\'][^>]*>([\s\S]{0,250000})',
            html_content or "",
            re.IGNORECASE,
        )
        region = match.group(1) if match else ""
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

    def _has_next(self, html_content, url, page):
        next_path = urllib.parse.urlparse(self.get_page_url(url, (page or 1) + 1)).path
        if next_path and next_path in (html_content or ""):
            return True
        return bool(re.search(r'rel=["\']next["\']', html_content or "", re.IGNORECASE))

    def process_content(self, url, page=1):
        if not url or url == "BOOTSTRAP":
            url, _ = self.get_start_url_and_label()
        context_menu = self._context_menu(url)
        target = self.get_page_url(url, page)
        if not self._is_listing_url(target):
            html_content = self._get(target, referer=self.base_url)
            photos = self._photos(html_content)
            if not photos:
                self.notify_error("No {} photos found".format(self.label or self.name))
                self.end_directory("videos")
                return
            for index, photo in enumerate(photos, 1):
                self.add_link(
                    "Photo {}".format(index),
                    photo,
                    4,
                    photo,
                    self.fanart,
                    info_labels={"title": "Photo {}".format(index), "plot": "Photo {}".format(index)},
                    referer=target,
                )
            self.end_directory("videos")
            return
        if self._is_top_listing(url) and page <= 1:
            self.add_dir("Categories", self.base_url, 8, self.icons.get("categories", self.icon), context_menu=context_menu)
        html_content = self._get(target, referer=self.base_url)
        if not html_content:
            self.notify_error("Could not load {} listing".format(self.label or self.name))
            self.end_directory("videos")
            return
        posts = self._articles(html_content)
        if not posts:
            self.notify_error("No {} posts found".format(self.label or self.name))
            self.end_directory("videos")
            return
        for item in posts:
            self.add_dir(item["label"], item["url"], 2, item["thumb"], self.fanart, info_labels=item["info"])
        if self._has_next(html_content, url, page):
            self.add_dir("Next Page", url, 2, self.icons.get("default", self.icon), context_menu=context_menu, page=page + 1)
        self.end_directory("videos")

    def process_categories(self, url):
        html_content = self._get(self.base_url)
        seen = set()
        for match in re.finditer(r'<a\b[^>]+href=["\']([^"\']+)["\'][^>]*>([\s\S]{0,200}?)</a>', html_content or "", re.IGNORECASE):
            target = self._absolute(match.group(1))
            parts = [part.lower() for part in urllib.parse.urlparse(target).path.split("/") if part]
            if len(parts) < 2 or parts[0] != "category":
                continue
            title = self._clean(match.group(2))
            if not title or title.isdigit() or _skip(title) or _skip(target) or target in seen:
                continue
            if title.lower() in ("next", "previous", "prev"):
                continue
            seen.add(target)
            self.add_dir(title, target, 2, self.icons.get("categories", self.icon), self.fanart)
        if not seen:
            self.notify_error("No {} categories found".format(self.label or self.name))
        self.end_directory("videos")

    def add_dir(self, name, url, mode, icon=None, fanart=None, context_menu=None, name_param=None, info_labels=None, **kwargs):
        if _skip(name) or _skip(url):
            return
        super().add_dir(name, url, mode, icon, fanart, context_menu, name_param, info_labels, **kwargs)

    def search(self, query):
        self.end_directory("videos")

    def play_video(self, url):
        if not re.search(r"\.(?:jpe?g|png|webp)(?:$|\?)", (url or "").lower()):
            self.notify_error("Could not resolve stream URL")
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return
        headers = self._headers(self.base_url, accept="image/*,*/*")
        play_url = "{}|{}".format(url, urllib.parse.urlencode(headers))
        list_item = xbmcgui.ListItem(path=play_url)
        list_item.setProperty("IsPlayable", "true")
        lowered = url.lower()
        if ".webp" in lowered:
            mime = "image/webp"
        elif ".png" in lowered:
            mime = "image/png"
        else:
            mime = "image/jpeg"
        list_item.setMimeType(mime)
        list_item.setContentLookup(False)
        xbmcplugin.setResolvedUrl(self.addon_handle, True, list_item)
