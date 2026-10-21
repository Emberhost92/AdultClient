# -*- coding: utf-8 -*-
import hashlib
import json
import os
import re
import urllib.parse

import requests
import xbmc
import xbmcvfs

from resources.lib.resolvers import resolver_utils
from resources.lib.thumb_proxy import build_loadvid_url


def _field(page, name):
    match = re.search(r"\b{}\s*:\s*'([^']*)'".format(re.escape(name)), page or "", re.I)
    return match.group(1) if match else ""


def resolve(url, referer=None, headers=None):
    session = requests.Session()
    request_headers = dict(headers or {})
    request_headers.update({
        "User-Agent": request_headers.get("User-Agent") or resolver_utils.get_ua(),
        "Referer": referer or url,
        "Accept-Encoding": "identity",
    })
    try:
        response = session.get(url, headers=request_headers, timeout=20)
        response.raise_for_status()
        csrf = re.search(r'name=["\']csrf-token["\']\s+content=["\']([^"\']+)', response.text, re.I)
        video_hash = _field(response.text, "videoHash")
        video_token = _field(response.text, "videoToken")
        if not csrf or not video_hash or not video_token:
            return None, {}

        parsed = urllib.parse.urlparse(url)
        origin = "{}://{}".format(parsed.scheme, parsed.netloc)
        api_headers = {
            "User-Agent": request_headers["User-Agent"],
            "Referer": url,
            "Origin": origin,
            "Content-Type": "application/json",
            "X-CSRF-TOKEN": csrf.group(1),
            "Accept": "application/vnd.apple.mpegurl,*/*",
            "Accept-Encoding": "identity",
        }
        playlist = session.post(
            origin + "/videos/resolve-token",
            headers=api_headers,
            data=json.dumps({"token": video_token, "hash": video_hash}),
            timeout=20,
        )
        playlist.raise_for_status()
        if "#EXTM3U" not in playlist.text[:1024]:
            return None, {}

        temp_dir = xbmcvfs.translatePath("special://temp")
        filename = "adulthideout_loadvid_{}.m3u8".format(
            hashlib.sha1(video_hash.encode("utf-8")).hexdigest()[:16]
        )
        path = os.path.join(temp_dir, filename)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(playlist.text)
        local_url = build_loadvid_url(filename)
        if not local_url:
            xbmc.log("[AdultHideout][loadvid] Persistent proxy is unavailable", xbmc.LOGERROR)
            return None, {}
        xbmc.log("[AdultHideout][loadvid] HLS playlist resolved", xbmc.LOGINFO)
        return local_url, {}
    except Exception as exc:
        xbmc.log("[AdultHideout][loadvid] Resolve failed: {}".format(exc), xbmc.LOGERROR)
        return None, {}
