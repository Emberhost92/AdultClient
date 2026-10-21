# -*- coding: utf-8 -*-
import json
import urllib.parse

import requests
import xbmc

from resources.lib.resolvers import resolver_utils
from resources.lib.vendor.byse_crypto import cbc_decrypt, pkcs7_unpad


_KEY = b"kiemtienmua911ca"
_IV = b"1234567890oiuytr"


def _decrypt(response):
    encrypted = bytes.fromhex(response.content.decode("ascii").strip())
    plain = pkcs7_unpad(cbc_decrypt(_KEY, _IV, encrypted))
    return json.loads(plain.decode("utf-8"))


def resolve(url, referer=None, headers=None):
    video_id = urllib.parse.urlparse(url).fragment
    if not video_id:
        video_id = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("id", [""])[0]
    if not video_id:
        return None, {}

    player_url = "https://av.seeks.cloud/#{}".format(video_id)
    request_headers = dict(headers or {})
    request_headers.update({
        "User-Agent": request_headers.get("User-Agent") or resolver_utils.get_ua(),
        "Referer": player_url,
        "Accept": "application/octet-stream,*/*;q=0.8",
        "Accept-Encoding": "identity",
    })
    try:
        response = requests.get(
            "https://av.seeks.cloud/api/v1/video?id=" + urllib.parse.quote(video_id),
            headers=request_headers,
            timeout=20,
        )
        response.raise_for_status()
        data = _decrypt(response)
        stream = data.get("cfNative") or data.get("source") or data.get("hlsVideoTiktok")
        if stream and stream.startswith("/"):
            stream = urllib.parse.urljoin("https://av.seeks.cloud/", stream)
        if not stream:
            return None, {}
        xbmc.log("[AdultHideout][avseeks] HLS stream resolved", xbmc.LOGINFO)
        return stream, {
            "User-Agent": request_headers["User-Agent"],
            "Referer": player_url,
        }
    except Exception as exc:
        xbmc.log("[AdultHideout][avseeks] Resolve failed: {}".format(exc), xbmc.LOGERROR)
        return None, {}
