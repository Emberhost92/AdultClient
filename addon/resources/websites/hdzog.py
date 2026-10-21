#!/usr/bin/env python

import json
import logging
import re
import sys
import urllib.parse
from urllib import request

import xbmc
import xbmcgui
import xbmcplugin

from resources.lib.base_website import BaseWebsite
from resources.lib.decoders.txxx_decoder import TxxxDecoder


class Hdzog(BaseWebsite):
    def __init__(self, addon_handle):
        super().__init__("hdzog", "https://hdzog.com/", "https://hdzog.com/search/{}", addon_handle)

        self.label = "HDZog"
        self.logger.setLevel(logging.WARNING)

        self.sort_options = [
            "Most Popular",
            "Latest Updates",
            "Top Rated",
            "Most Viewed",
            "Longest",
        ]
        self.sort_paths = {
            "Most Popular": "most-popular",
            "Latest Updates": "latest-updates",
            "Top Rated": "top-rated",
            "Most Viewed": "most-viewed",
            "Longest": "longest",
        }
        self.headers = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "X-Requested-With": "XMLHttpRequest",
        }
        self.api_filter = "str"
        self.txxx_decoder = TxxxDecoder()

    def get_start_url_and_label(self):
        setting_id = f"{self.name}_sort_by"
        try:
            sort_idx = int(self.addon.getSetting(setting_id))
        except Exception:
            sort_idx = 0
        if not 0 <= sort_idx < len(self.sort_options):
            sort_idx = 0

        sort_key = self.sort_options[sort_idx]
        sort_path = self.sort_paths.get(sort_key, "most-popular")
        return urllib.parse.urljoin(self.base_url, sort_path), f"{self.label} [COLOR yellow]{sort_key}[/COLOR]"

    def _get_context_menu(self, current_url):
        return [
            (
                "Sort by...",
                "RunPlugin({}?mode=7&website={}&action=select_sort&original_url={})".format(
                    sys.argv[0], self.name, urllib.parse.quote_plus(current_url)
                ),
            )
        ]

    def _get_json(self, url, headers=None):
        try:
            req = request.Request(url, headers=headers or self.headers)
            with request.urlopen(req, timeout=20) as response:
                if response.getcode() == 200:
                    return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            self.logger.error("HDZog JSON request failed for %s: %s", url, exc)
        return None

    def select_sort(self, original_url=None):
        setting_id = f"{self.name}_sort_by"
        try:
            current_idx = int(self.addon.getSetting(setting_id))
        except Exception:
            current_idx = 0
        if not 0 <= current_idx < len(self.sort_options):
            current_idx = 0

        selected_idx = xbmcgui.Dialog().select("Sort by...", self.sort_options, preselect=current_idx)
        if selected_idx == -1 or selected_idx == current_idx:
            return

        self.addon.setSetting(setting_id, str(selected_idx))
        new_start_url, _ = self.get_start_url_and_label()
        xbmc.executebuiltin(
            "Container.Update({}?mode=2&website={}&url={},replace)".format(
                sys.argv[0], self.name, urllib.parse.quote_plus(new_start_url)
            )
        )

    def _add_static_dirs(self, current_url):
        context_menu = self._get_context_menu(current_url)
        self.add_dir(
            "[COLOR blue]Search %s[/COLOR]" % self.label,
            "",
            5,
            icon=self.icons["search"],
            context_menu=context_menu,
            name_param=self.name,
        )
        self.add_dir(
            "[COLOR blue]Categories[/COLOR]",
            urllib.parse.urljoin(self.base_url, "categories/"),
            8,
            icon=self.icons["categories"],
            context_menu=context_menu,
        )

    def _absolute_url(self, raw):
        text = str(raw or "").strip()
        if not text or text.lower() in ("none", "null"):
            return ""
        if text.startswith("//"):
            return "https:" + text
        if text.startswith("/"):
            return urllib.parse.urljoin(self.base_url, text)
        if text.startswith("http://") or text.startswith("https://"):
            return text
        if "/" in text and " " not in text:
            return "https://" + text.lstrip("/")
        return ""

    def _image_url(self, raw):
        url = self._absolute_url(raw)
        lower = url.lower().split("?", 1)[0]
        if not url or ".mp4" in lower or ".webm" in lower or ".m3u8" in lower:
            return ""
        return url

    def _clip_url(self, video):
        if not isinstance(video, dict):
            return ""
        for key in ("pv", "preview_url"):
            url = self._absolute_url(video.get(key))
            lower = url.lower().split("?", 1)[0]
            if ".mp4" in lower or ".webm" in lower:
                return url
        return ""

    def _frame_list(self, video):
        frames = []
        if not isinstance(video, dict):
            return frames
        for key in ("thumbs", "screenshots", "preview_images"):
            raw = video.get(key)
            if not isinstance(raw, list):
                continue
            for item in raw:
                if isinstance(item, dict):
                    item = item.get("src") or item.get("url") or item.get("scr") or ""
                url = self._image_url(item)
                if url and url not in frames:
                    frames.append(url)
                if len(frames) >= 16:
                    return frames
        return frames

    def _category_icon(self, category):
        if isinstance(category, dict):
            for key in ("scr", "screenshot", "thumb", "thumbnail", "img"):
                picture = self._image_url(category.get(key))
                if picture:
                    return picture
        return self.icons["categories"]

    def _quality_choice(self, fmt, stream_url):
        token = str(fmt or "").lower()
        name = str(stream_url or "").split("|", 1)[0].lower().rsplit("/", 1)[-1]
        if "_tr" in token or "trailer" in token or "_tr." in name:
            return None
        height = 0
        size = re.search(r"(\d{3,4})x(\d{3,4})", token)
        if size:
            height = int(size.group(2))
        if "_hq" in token or "_hd" in token:
            height = max(height, 720)
        elif "_sq" in token or "_sd" in token:
            height = max(height, 480)
        elif "_lq" in token:
            height = max(height, 360)
        if height >= 1080:
            label = "1080p"
        elif height >= 720:
            label = "720p"
        elif height >= 480:
            label = "480p"
        elif height >= 360:
            label = "360p"
        elif height > 1:
            label = "%dp" % height
        else:
            height = 1
            label = "Standard"
        return height, label

    def _play_target(self, url):
        text = urllib.parse.unquote(str(url or "").strip())
        if text.startswith("{"):
            try:
                data = json.loads(text)
            except Exception:
                return None
            video_id = str(data.get("video_id") or "").strip()
            video_dir = str(data.get("dir") or "").strip().strip("/")
            if not (video_id and video_dir):
                return None
            base = str(data.get("base_url") or self.base_url).strip()
            if not base.endswith("/"):
                base += "/"
            return {
                "video_id": video_id,
                "title": data.get("title") or self.label,
                "thumbnail": data.get("thumbnail") or self.icon,
                "base_url": base,
                "page": "%svideos/%s/%s/" % (base, video_id, video_dir),
            }
        parsed = urllib.parse.urlparse(text)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return None
        match = re.search(r"/videos/(\d+)/([^/?#]+)", parsed.path or "")
        if not match:
            return None
        base = "%s://%s/" % (parsed.scheme, parsed.netloc)
        video_dir = match.group(2).strip("/")
        return {
            "video_id": match.group(1),
            "title": self.label,
            "thumbnail": self.icon,
            "base_url": base,
            "page": "%svideos/%s/%s/" % (base, match.group(1), video_dir),
        }

    def process_content(self, url):
        parsed_url = urllib.parse.urlparse(url)
        path = parsed_url.path.strip("/")

        is_category = path.startswith("categories/")
        is_search = path.startswith("search/")
        is_main_page = not is_category and not is_search

        if is_main_page:
            self._add_static_dirs(url)

        path_parts = [part for part in path.split("/") if part]
        page = "1"
        if path_parts and path_parts[-1].isdigit():
            page = path_parts.pop()

        sort_order = "most-popular"
        if is_main_page and path_parts:
            sort_order = path_parts[0]
        elif not is_main_page:
            try:
                sort_idx = int(self.addon.getSetting(f"{self.name}_sort_by"))
            except Exception:
                sort_idx = 0
            if 0 <= sort_idx < len(self.sort_options):
                sort_order = self.sort_paths.get(self.sort_options[sort_idx], "most-popular")

        path_for_paging = "/".join(path_parts) if not is_main_page else sort_order
        filter_string = f"..{page}.all..day"
        timeframe = "14400"

        if is_category and len(path_parts) > 1:
            filter_string = "categories.{}.{}.all..day".format(path_parts[1], page)
        elif is_search:
            timeframe = "259200"
            query_part = path_parts[1] if len(path_parts) > 1 else ""
            api_url = (
                f"{self.base_url}api/videos2.php?params="
                f"{timeframe}/{self.api_filter}/relevance/60/search..{page}.all..&s="
                f"{urllib.parse.quote_plus(query_part)}"
            )

        if "api_url" not in locals():
            api_url = (
                f"{self.base_url}api/json/videos2/{timeframe}/{self.api_filter}/"
                f"{sort_order}/60/{filter_string}.json"
            )

        data = self._get_json(api_url)
        if not data or "videos" not in data:
            return self.end_directory()

        context_menu = self._get_context_menu(url)

        for video in data.get("videos", []):
            if not isinstance(video, dict):
                continue
            title = video.get("title") or "Unknown Title"
            video_dir = str(video.get("dir") or "").strip().strip("/")
            video_id = str(video.get("video_id") or "").strip()
            if not (video_id and video_dir):
                continue

            duration_str = "00:00"
            seconds = 0
            try:
                parts = str(video.get("duration") or "0:0").split(":")
                if len(parts) == 2:
                    seconds = int(parts[0]) * 60 + int(parts[1])
                    duration_str = f"{int(parts[0]):02}:{int(parts[1]):02}"
                elif len(parts) == 3:
                    seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                    duration_str = f"{int(parts[0]):02}:{int(parts[1]):02}:{int(parts[2]):02}"
            except Exception:
                seconds = 0

            thumbnail = self._image_url(video.get("scr")) or self.icon
            page_url = urllib.parse.urljoin(self.base_url, "videos/%s/%s/" % (video_id, video_dir))
            models_raw = video.get("models") or ""
            if isinstance(models_raw, list):
                cast = [str(part).strip() for part in models_raw if str(part).strip()]
            elif isinstance(models_raw, str):
                cast = [part.strip() for part in models_raw.split(",") if part.strip()]
            else:
                cast = []
            plot = str(video.get("description") or "").strip()
            if plot.lower() == str(title).strip().lower():
                plot = ""
            info_labels = {"title": title, "studio": str(video.get("content_source_name") or self.label).strip() or self.label}
            if seconds > 0:
                info_labels["duration"] = seconds
            if cast:
                info_labels["cast"] = cast
            if plot:
                info_labels["plot"] = plot
            posted = str(video.get("post_date") or "").strip().split(" ")[0]
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", posted):
                info_labels["premiered"] = posted
            try:
                rating = float(video.get("rating") or 0)
            except (TypeError, ValueError):
                rating = 0
            if rating > 0:
                info_labels["rating"] = rating
            frames = self._frame_list(video)
            username = str(video.get("username") or "").strip()
            label = f"{title} [COLOR lime]({duration_str})[/COLOR]"
            self.add_link(
                name=label,
                url=page_url,
                mode=4,
                icon=thumbnail,
                fanart=self.fanart,
                context_menu=context_menu,
                info_labels=info_labels,
                uploader_name=username or None,
                preview=frames if len(frames) > 1 else None,
                clip=self._clip_url(video) or None,
                referer=self.base_url,
            )

        current_page = int(page)
        total_pages = int(data.get("pages", 1))
        if current_page < total_pages:
            next_path_parts = list(path_parts)
            next_path_parts.append(str(current_page + 1))
            next_path = "/".join(next_path_parts)
            if not next_path:
                next_path = f"{sort_order}/{current_page + 1}"
            next_page_url = urllib.parse.urljoin(self.base_url, f"{next_path}/")
            self.add_dir(
                name="[COLOR cyan]>> Next Page[/COLOR]",
                url=next_page_url,
                mode=2,
                icon=self.icons["default"],
                context_menu=context_menu,
            )

        self.end_directory()

    def process_categories(self, url):
        data = self._get_json(f"{self.base_url}api/json/categories/14400/{self.api_filter}.all.en.json")
        if not data or "categories" not in data:
            return self.end_directory()

        context_menu = self._get_context_menu(url)
        for category in sorted(data.get("categories", []), key=lambda item: item.get("title", "")):
            title = category.get("title")
            cat_dir = category.get("dir")
            if not (title and cat_dir):
                continue
            self.add_dir(
                name=title,
                url=f"{self.base_url}categories/{cat_dir}/",
                mode=2,
                icon=self._category_icon(category),
                context_menu=context_menu,
            )

        self.end_directory()

    def play_video(self, url):
        target = self._play_target(url)
        if not target:
            self.notify_error("Invalid video data.")
            return

        req_headers = dict(self.headers)
        req_headers["Referer"] = target["page"]
        stream_info = self._get_json(
            "%sapi/videofile.php?video_id=%s&lifetime=8640000" % (target["base_url"], target["video_id"]),
            headers=req_headers,
        )
        choices = []
        seen = set()
        if isinstance(stream_info, list):
            for row in stream_info:
                if not isinstance(row, dict) or not row.get("video_url"):
                    continue
                if self._quality_choice(row.get("format"), "") is None:
                    continue
                decoded = self.txxx_decoder.decode_stream_url(
                    row.get("video_url"), target["base_url"], target["page"], self.logger
                )
                ranked = self._quality_choice(row.get("format"), decoded or "")
                if not decoded or ranked is None:
                    continue
                bare = decoded.split("|", 1)[0]
                if not bare.startswith("http") or bare in seen:
                    continue
                seen.add(bare)
                choices.append((ranked[0], ranked[1], decoded))
        if not choices:
            self.notify_error("No playable streams found.")
            return

        choices.sort(key=lambda item: item[0])
        sources = [{"label": label, "path": path} for _height, label, path in choices]
        stream_url = sources[-1]["path"]
        list_item = xbmcgui.ListItem(target["title"], path=stream_url)
        list_item.setArt({"thumb": target["thumbnail"], "icon": "DefaultVideo.png"})
        list_item.setProperty("IsPlayable", "true")
        list_item.setProperty("web_sources", json.dumps(sources))
        bare_url = stream_url.split("|", 1)[0]
        if ".m3u8" in bare_url:
            list_item.setMimeType("application/vnd.apple.mpegurl")
            list_item.setProperty("inputstream", "inputstream.adaptive")
            list_item.setProperty("inputstream.adaptive.manifest_type", "hls")
        elif ".mp4" in bare_url:
            list_item.setMimeType("video/mp4")
        xbmcplugin.setResolvedUrl(self.addon_handle, True, listitem=list_item)

    def search(self, query):
        if query:
            super().search(query)
