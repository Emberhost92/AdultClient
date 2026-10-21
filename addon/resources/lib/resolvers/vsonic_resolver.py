# -*- coding: utf-8 -*-
import re

from resources.lib.resolvers.resolver_utils import http_get


def resolve(embed_url, referer, headers):
    request_headers = dict(headers or {})
    request_headers["Referer"] = referer or embed_url
    request_headers["Accept-Encoding"] = "identity"
    page = http_get(embed_url, headers=request_headers)
    match = re.search(r"const\s+_0x1\s*=\s*['\"]([0-9a-fA-F|]+)", page or "")
    if not match:
        return "", request_headers
    try:
        decoded = bytes.fromhex(match.group(1).replace("|", "")).decode("utf-8")[::-1]
    except (ValueError, UnicodeDecodeError):
        return "", request_headers
    if not decoded.startswith(("http://", "https://")):
        return "", request_headers
    request_headers["Referer"] = embed_url
    request_headers["Origin"] = "https://vsonic.click"
    return decoded, request_headers
