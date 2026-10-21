# -*- coding: utf-8 -*-

import base64
import json
import re
import sys
import urllib.parse

try:
    import cloudscraper
except ImportError:
    vendor = __file__.rsplit("resources", 1)[0] + "resources/lib/vendor"
    if vendor not in sys.path:
        sys.path.insert(0, vendor)
    import cloudscraper


_KEY = "G7#kP!2qZxV9mRwL"


def _decode_config(token):
    encoded = token.split("~", 1)[-1]
    encoded += "=" * (-len(encoded) % 4)
    raw = base64.b64decode(encoded)
    decoded = bytes(value ^ ord(_KEY[index % len(_KEY)]) for index, value in enumerate(raw))
    return json.loads(decoded.decode("utf-8"))


def resolve(embed_url, referer, headers):
    request_headers = dict(headers or {})
    request_headers.setdefault(
        "User-Agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    )
    request_headers["Referer"] = referer or embed_url
    request_headers["Accept-Encoding"] = "identity"

    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )
    response = scraper.get(embed_url, headers=request_headers, timeout=20)
    if response.status_code != 200:
        return "", request_headers

    match = re.search(r"\b_cfg\s*=\s*_dp\(\s*['\"]([^'\"]+)", response.text)
    if not match:
        return "", request_headers
    try:
        stream = _decode_config(match.group(1)).get("videoUrl", "")
    except Exception:
        return "", request_headers
    if not stream.startswith("http"):
        return "", request_headers

    parsed = urllib.parse.urlparse(embed_url)
    stream_headers = {
        "User-Agent": request_headers["User-Agent"],
        "Referer": embed_url,
        "Origin": "{}://{}".format(parsed.scheme, parsed.netloc),
        "Accept-Encoding": "identity",
    }
    return stream, stream_headers
