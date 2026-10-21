# -*- coding: utf-8 -*-
"""Shared engine for booru post listings.

One JSON or HTML post list, one full file per post.
No login, no downloader, no browser automation.
"""

import html
import re
import urllib.parse

import xbmc
import xbmcgui
import xbmcplugin

from resources.lib.base_website import BaseWebsite
from resources.lib.media_probe import UA, make_session

SEARCH_MARKER = "AH_BOORU|"
_BLOCKED = ("teen", "teens", "underage", "preteen", "lolita", "jailbait", "child", "children")
_AGE = re.compile(r"\b(?:1[0-7]|[1-9])\s*(?:yo|y\.o\.?|years?\s*old)\b", re.IGNORECASE)
_SMALL = ("thumbnail", "/thumb", "preview", "/samples/", "/sample/")
_VIDEO = (".mp4", ".webm", ".m4v", ".mov")


def _skip(value):
    text = (value or "").lower().replace("_", " ")
    words = re.sub(r"[^a-z0-9]+", " ", text).split()
    if any(word in _BLOCKED for word in words):
        return True
    return bool(_AGE.search(text))


def _mime(url):
    path = urllib.parse.urlparse(url or "").path.lower()
    if path.endswith(".png"):
        return "image/png"
    if path.endswith(".webp"):
        return "image/webp"
    if path.endswith(".gif"):
        return "image/gif"
    if path.endswith(".webm"):
        return "video/webm"
    if path.endswith(_VIDEO):
        return "video/mp4"
    return "image/jpeg"


class BooruApiWebsite(BaseWebsite):
    name = ""
    label = ""
    host = ""
    style = ""
    home_tags = ""
    page_size = 40
    user_agent = ""

    def __init__(self, addon_handle, addon=None):
        super().__init__(
            name=self.name,
            base_url=self.host.rstrip("/") + "/",
            search_url=SEARCH_MARKER + "{}",
            addon_handle=addon_handle,
            addon=addon,
        )
        self.session = make_session()
        self._raw_count = 0

    def _ua(self):
        return self.user_agent or UA

    def _headers(self, referer=None, accept="*/*"):
        return {
            "User-Agent": self._ua(),
            "Referer": referer or self.base_url,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _absolute(self, value, base=None):
        value = html.unescape(value or "").replace("\\/", "/").strip()
        if value.startswith("//"):
            value = "https:" + value
        if not value:
            return ""
        return urllib.parse.urljoin(base or self.base_url, value)

    def _get(self, url, accept="*/*"):
        last_error = None
        for attempt in range(1, 3):
            try:
                response = self.session.get(url, headers=self._headers(accept=accept), timeout=20)
                if response.status_code == 200 and response.content:
                    return response
                last_error = "HTTP {}".format(response.status_code)
            except Exception as exc:
                last_error = exc
                self.session = make_session()
            if attempt < 2:
                xbmc.sleep(400)
        self.logger.warning("%s request failed: %s", self.label or self.name, last_error)
        return None

    def _text(self, url):
        response = self._get(url, accept="text/html,application/xhtml+xml,*/*")
        return response.text if response is not None else ""

    def _json(self, url):
        response = self._get(url, accept="application/json,text/plain,*/*")
        if response is None:
            return None
        try:
            return response.json()
        except Exception:
            return None

    def get_start_url_and_label(self):
        return self.base_url, self.label or self.name

    def search(self, query):
        if not query or _skip(query):
            self.end_directory("videos")
            return
        super().search(query)

    def _tags_of(self, url):
        if (url or "").startswith(SEARCH_MARKER):
            return urllib.parse.unquote_plus(url.split("|", 1)[1])
        return self.home_tags

    def _is_home(self, url):
        if not url or url.startswith(SEARCH_MARKER):
            return False
        parsed = urllib.parse.urlparse(url)
        return (parsed.netloc.lower() in ("", urllib.parse.urlparse(self.base_url).netloc.lower())
                and parsed.path in ("", "/"))

    def _small(self, url):
        low = (url or "").lower()
        return any(token in low for token in _SMALL)

    def _tag_text(self, value):
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            names = []
            for item in value:
                if isinstance(item, str):
                    names.append(item)
                elif isinstance(item, dict):
                    names.append(str(item.get("name") or item.get("tag") or ""))
            return " ".join(names)
        if isinstance(value, dict):
            names = []
            for item in value.values():
                if isinstance(item, list):
                    names.extend(str(part) for part in item)
            return " ".join(names)
        return ""

    def _keep(self, tags, file_url):
        if not file_url or self._small(file_url):
            return False
        if _skip(self._tag_text(tags)) or _skip(urllib.parse.urlparse(file_url).path):
            return False
        return True

    def _label(self, tags, post_id):
        text = re.sub(r"\s+", " ", self._tag_text(tags)).strip()
        if not text:
            return "Post {}".format(post_id or "")
        return text[:90]

    def _append(self, posts, post_id, file_url, thumb, tags):
        file_url = self._absolute(file_url)
        if not self._keep(tags, file_url):
            return
        thumb_url = self._absolute(thumb) if thumb else ""
        if not thumb_url.startswith("http"):
            thumb_url = self.icon
        posts.append({
            "id": str(post_id or ""),
            "file": file_url,
            "page": "",
            "thumb": thumb_url,
            "tags": tags,
        })

    def _html_posts(self, tags, page):
        params = {"page": "post", "s": "list", "pid": str(max(0, page - 1) * self.page_size)}
        if tags:
            params["tags"] = tags
        url = self.base_url + "index.php?" + urllib.parse.urlencode(params)
        text = self._text(url)
        posts = []
        seen = set()
        for match in re.finditer(r"<a\b([^>]*)href=[\"']([^\"']+)[\"']([^>]*)>([\s\S]{0,1800}?)</a>", text, re.IGNORECASE):
            href = self._absolute(html.unescape(match.group(2)), url)
            query = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            if "view" not in (query.get("s") or []):
                continue
            post_id = (query.get("id") or [""])[0]
            if not post_id or post_id in seen:
                continue
            seen.add(post_id)
            body = match.group(4)
            img = re.search(r"<img\b[^>]*>", body, re.IGNORECASE)
            thumb = ""
            alt = ""
            if img:
                tag = img.group(0)
                for attr in ("data-original", "data-src", "src"):
                    found = re.search(r'\s{}=["\']([^"\']+)["\']'.format(attr), tag, re.IGNORECASE)
                    if found:
                        thumb = self._absolute(found.group(1), url)
                        break
                alt_match = re.search(r'\salt=["\']([^"\']*)["\']', tag, re.IGNORECASE)
                alt = alt_match.group(1) if alt_match else ""
            if _skip(alt) or _skip(href):
                continue
            posts.append({
                "id": post_id,
                "file": "",
                "page": href,
                "thumb": thumb or self.icon,
                "tags": alt,
            })
        self._raw_count = len(seen)
        return posts

    def _from_maps(self, rows):
        posts = []
        self._raw_count = len(rows or [])
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            file_url = ""
            for key in ("file_url", "large_file_url", "view_url"):
                value = row.get(key)
                if isinstance(value, str) and value and not self._small(value):
                    file_url = value
                    break
            file_obj = row.get("file")
            if not file_url and isinstance(file_obj, dict):
                file_url = file_obj.get("url") or ""
            representations = row.get("representations")
            if not file_url and isinstance(representations, dict):
                file_url = representations.get("full") or representations.get("large") or ""
            thumb = ""
            for key in ("preview_url", "preview_file_url", "sample_url"):
                value = row.get(key)
                if isinstance(value, str) and value:
                    thumb = value
                    break
            preview = row.get("preview")
            if not thumb and isinstance(preview, dict):
                thumb = preview.get("url") or ""
            if not thumb and isinstance(representations, dict):
                thumb = representations.get("thumb") or representations.get("small") or ""
            tags = row.get("tags")
            if tags is None:
                tags = row.get("tag_string") or row.get("tag_list") or ""
            self._append(posts, row.get("id"), file_url, thumb, tags)
        return posts

    def _json_rows(self, payload):
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("post", "posts", "images"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        return []

    def _paheal_posts(self, tags, page):
        params = {"limit": str(self.page_size), "pid": str(max(0, page - 1))}
        if tags:
            params["tags"] = tags
        url = self.base_url + "api/danbooru/find_posts?" + urllib.parse.urlencode(params)
        text = self._text(url)
        posts = []
        rows = re.findall(r"<post\b([^>]*)/?>", text or "", re.IGNORECASE)
        self._raw_count = len(rows)
        for raw in rows:
            attrs = dict(re.findall(r"([A-Za-z0-9_:-]+)='([^']*)'", raw))
            if "file_url" not in attrs:
                attrs = dict(re.findall(r'([A-Za-z0-9_:-]+)="([^"]*)"', raw))
            self._append(
                posts,
                attrs.get("id"),
                html.unescape(attrs.get("file_url") or ""),
                html.unescape(attrs.get("preview_url") or ""),
                html.unescape(attrs.get("tags") or ""),
            )
        return posts

    def _posts(self, tags, page):
        if self.style == "gelbooru-html":
            return self._html_posts(tags, page)
        if self.style == "paheal":
            return self._paheal_posts(tags, page)
        params = {}
        if self.style == "gelbooru-json":
            params = {
                "page": "dapi",
                "s": "post",
                "q": "index",
                "json": "1",
                "limit": str(self.page_size),
                "pid": str(max(0, page - 1)),
            }
            if tags:
                params["tags"] = tags
            url = self.base_url + "index.php?" + urllib.parse.urlencode(params)
        elif self.style == "derpi":
            params = {"per_page": str(self.page_size), "page": str(page), "q": tags or "*"}
            url = self.base_url + "api/v1/json/search/images?" + urllib.parse.urlencode(params)
        elif self.style == "moebooru":
            params = {"limit": str(self.page_size), "page": str(page)}
            if tags:
                params["tags"] = tags
            url = self.base_url + "post.json?" + urllib.parse.urlencode(params)
        else:
            params = {"limit": str(self.page_size), "page": str(page)}
            if tags:
                params["tags"] = tags
            url = self.base_url + "posts.json?" + urllib.parse.urlencode(params)
        payload = self._json(url)
        return self._from_maps(self._json_rows(payload))

    def _file_ok(self, url):
        path = urllib.parse.urlparse(url or "").path.lower()
        if not url or self._small(url):
            return False
        return path.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".webm", ".mp4", ".m4v"))

    def _same_site(self, url):
        host = (urllib.parse.urlparse(url or "").hostname or "").lower()
        site = (urllib.parse.urlparse(self.host).hostname or "").lower()
        return bool(host) and (host == site or host.endswith("." + site) or site.endswith("." + host))

    def _resolve_view(self, page_url):
        text = self._text(page_url)
        candidates = []
        patterns = (
            r'<img\b[^>]*\bid=["\']image["\'][^>]*>',
            r'<img\b[^>]*\ssrc=["\'][^"\']+["\'][^>]*\bid=["\']image["\'][^>]*>',
            r'<video\b[^>]*>',
            r'<source\b[^>]*>',
        )
        for pattern in patterns:
            for tag in re.findall(pattern, text, re.IGNORECASE):
                found = re.search(r'\ssrc=["\']([^"\']+)["\']', tag, re.IGNORECASE)
                if found:
                    candidates.append(self._absolute(found.group(1), page_url))
        for href, label in re.findall(r'href=["\']([^"\']+)["\'][^>]*>\s*([^<]{0,32})', text, re.IGNORECASE):
            if label.strip().lower().startswith("original"):
                candidates.append(self._absolute(href, page_url))
        same = [url for url in candidates if self._file_ok(url) and self._same_site(url)]
        other = [url for url in candidates if self._file_ok(url) and url not in same]
        if same:
            return same[0]
        return other[0] if other else ""

    def process_content(self, url, page=1):
        try:
            page = max(1, int(page or 1))
        except (TypeError, ValueError):
            page = 1
        if self._is_home(url) and page == 1:
            self.add_dir("Search", "", 5, self.icons.get("search", self.icon))
        posts = self._posts(self._tags_of(url), page)
        if not posts:
            self.notify_error("No {} results".format(self.label or self.name))
            self.end_directory("videos")
            return
        for post in posts:
            target = post["page"] or post["file"]
            self.add_link(
                self._label(post["tags"], post["id"]),
                target,
                4,
                post["thumb"] or self.icon,
                self.fanart,
                info_labels={"title": self._label(post["tags"], post["id"]), "mediatype": "image"},
            )
        if url and self._raw_count >= max(15, int(self.page_size * 0.7)):
            self.add_dir("Next Page", url, 2, self.icons.get("default", self.icon), page=page + 1)
        self.end_directory("videos")

    def _mime_for(self, url):
        path = urllib.parse.urlparse(url or "").path.lower()
        if path.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".webm", ".mp4", ".m4v")):
            return _mime(url)
        try:
            response = self.session.get(
                url,
                headers=dict(self._headers(accept="*/*"), **{"Range": "bytes=0-0"}),
                timeout=12,
                stream=True,
                allow_redirects=True,
            )
            ctype = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            response.close()
            if ctype.startswith("image/") or ctype.startswith("video/"):
                return ctype
        except Exception:
            pass
        return _mime(url)

    def play_video(self, url):
        if self.style == "gelbooru-html" and "s=view" in (url or ""):
            url = self._resolve_view(url)
        if not url or not url.startswith("http"):
            self.notify_error("Could not resolve image")
            xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem())
            return
        headers = self._headers(accept="*/*")
        play_url = "{}|{}".format(url, urllib.parse.urlencode(headers))
        item = xbmcgui.ListItem(path=play_url)
        item.setProperty("IsPlayable", "true")
        item.setMimeType(self._mime_for(url))
        item.setContentLookup(False)
        xbmcplugin.setResolvedUrl(self.addon_handle, True, item)
