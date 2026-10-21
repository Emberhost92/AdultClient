#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re

from resources.lib.leak_extract import LeakWebsite, _absolute, _keep_image, images


class Amateurdoporn(LeakWebsite):
    site_name = "amateurdoporn"
    site_base = "https://amateurdoporn.com/"
    site_host = "amateurdoporn.com"
    site_label = "Amateur do Porn"

    def _photos(self, content, base):
        found = list(images(content, base))
        seen = set(found)
        for href in re.findall(r'href="([^"]+)"', content or "", re.IGNORECASE):
            url = _absolute(base, href).split("?")[0]
            path = url.lower()
            if "/uploads/" not in path:
                continue
            if not re.search(r"\.(?:jpe?g|png|webp)$", path, re.IGNORECASE):
                continue
            if url in seen or not _keep_image(url):
                continue
            seen.add(url)
            found.append(url)
        for match in re.finditer(r"https?:\\?/\\?/[^\"'\s>]+\.(?:jpe?g|png|webp)", content or "", re.IGNORECASE):
            url = _absolute(base, match.group(0).replace("\\/", "/")).split("?")[0]
            if "/uploads/" not in url.lower():
                continue
            if url in seen or not _keep_image(url):
                continue
            seen.add(url)
            found.append(url)
        return found

    def _videos(self, content, base):
        found = []
        seen = set()
        for match in re.finditer(r"<video\b([^>]*)>([\s\S]*?)</video>", content or "", re.IGNORECASE):
            attrs, inner = match.group(1), match.group(2)
            poster_match = re.search(r'\bposter="([^"]+)"', attrs, re.IGNORECASE)
            poster = _absolute(base, poster_match.group(1)) if poster_match else ""
            if not _keep_image(poster):
                poster = ""
            for src in re.findall(r'\bsrc="([^"]+)"', inner, re.IGNORECASE):
                url = _absolute(base, src).split("#")[0]
                path = url.lower().split("?")[0]
                if not url.startswith("http"):
                    continue
                if not (path.endswith(".m3u8") or path.endswith(".mp4")):
                    continue
                if not _keep_image(url) or url in seen:
                    continue
                seen.add(url)
                found.append((url, poster))
        return found

    def process_content(self, url, page=1):
        target = self.base_url if not url or url == "BOOTSTRAP" else url
        if self._listing(target):
            return super().process_content(url, page)
        content = self._get(target)
        base = self.last_url or target
        photos = self._photos(content, base)
        count = 0
        for index, image in enumerate(photos, 1):
            label = "Photo {}".format(index)
            self.add_link(
                label, image, 4, image, self.fanart,
                info_labels={"title": label, "plot": label},
                referer=target,
            )
            count += 1
        thumb = photos[0] if photos else self.icon
        for index, (stream, poster) in enumerate(self._videos(content, base), 1):
            label = "Video {}".format(index)
            self.add_link(
                label, stream, 4, poster or thumb, self.fanart,
                info_labels={"title": label, "plot": label},
                referer=target,
            )
            count += 1
        if not count:
            self.notify_error("No {} items found".format(self.label))
        self.end_directory("videos")
