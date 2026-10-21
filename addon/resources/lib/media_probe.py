# -*- coding: utf-8 -*-
"""Robuste Medien-Probe: folgt Redirects, nutzt Referer, Range-GET,
cloudscraper-Fallback fuer Cloudflare-Seiten."""
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def make_session():
    """cloudscraper wenn vorhanden, sonst requests."""
    try:
        from resources.lib.vendor import cloudscraper
        return cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False})
    except Exception:
        return requests.Session()


def probe(url, referer="", session=None, timeout=12):
    """True wenn mindestens ein Byte kommt. Folgt Redirects, sendet Referer."""
    if not url:
        return False
    headers = {"User-Agent": UA, "Accept": "*/*", "Range": "bytes=0-2047"}
    if referer:
        headers["Referer"] = referer
    sess = session or make_session()
    try:
        response = sess.get(url, headers=headers, timeout=timeout, stream=True)
        if response.status_code not in (200, 206):
            response.close()
            return False
        chunk = next(response.iter_content(2048), b"")
        response.close()
        return len(chunk) > 0
    except Exception:
        return False


def resolve_final_url(url, referer="", session=None, timeout=12):
    """End-URL nach allen Weiterleitungen — fuer Sites, die umgezogen sind."""
    headers = {"User-Agent": UA, "Accept": "text/html,*/*"}
    if referer:
        headers["Referer"] = referer
    sess = session or make_session()
    try:
        response = sess.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        final = response.url
        response.close()
        return final
    except Exception:
        return url
