#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Adult Client by emberhost: local browser using the installed Kodi provider addon."""

import base64
from contextlib import closing
import concurrent.futures as futures
import datetime
import hashlib
import html
import http.cookiejar
import importlib
import json
import mimetypes
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import media_library
from download_library import DownloadLibrary
import site_previews
import settings_design
import tube_consumption
import star_store
import star_runtime
import star_finder
import star_discovery
import live_cam_providers
import live_cam_models
import live_cam_library_sync
import live_cam_biography

ROOT = os.path.dirname(os.path.abspath(__file__))
SHIM = os.path.join(ROOT, "shim")
ADDON = os.environ.get(
    "AH_ADDON",
    os.path.join(os.environ.get("APPDATA", ""), "Kodi", "addons", "plugin.video.adulthideout"),
)
PROFILE = os.environ.get("AH_PROFILE", os.path.join(ROOT, "profile"))
PORT = int(os.environ.get("AH_PORT", "8765"))
MEDIA_PORT = int(os.environ.get("AH_MEDIA_PORT", str(PORT + 1)))
MULTI_PORTS = [MEDIA_PORT + 1 + index for index in range(20)]
PLUGIN = "plugin://plugin.video.adulthideout/"

os.environ["AH_ADDON"] = ADDON
os.environ["AH_PROFILE"] = PROFILE
os.makedirs(PROFILE, exist_ok=True)

sys.path.insert(0, ADDON)
sys.path.insert(0, SHIM)

import xbmc
import xbmcgui
import xbmcplugin

_lock = threading.Lock()
_user_busy = threading.Event()
_image_slots = threading.BoundedSemaphore(6)
_stream_slots = threading.BoundedSemaphore(48)
_ui_touch = 0.0
_job_slot = threading.BoundedSemaphore(16)
_JOB_QUIET = 0.2
_UI_QUIET_PATHS = frozenset({
    "/api/health",
    "/api/log",
    "/api/star-sync",
    "/api/star-lang-batch",
    "/api/star-finder/jobs",
    "/api/restart",
})
_extra_saved_mono = 0.0
_extra_dirty = False
_extra_trim_mono = 0.0
_babe_counts = {"at": 0.0, "about": 0, "photos": 0}


def note_ui(path=""):
    """Echte Bedienung. Die Status-Abfrage der Model-Läufe zählt nicht, sonst stehen die Läufe nie still."""
    global _ui_touch
    if path in _UI_QUIET_PATHS:
        return
    _ui_touch = time.monotonic()


def _ui_hot():
    return time.monotonic() - _ui_touch < _JOB_QUIET


def job_wait():
    """Kurz Luft lassen, wenn gerade eine Seite lädt. Bis zu sechs Läufe holen gleichzeitig."""
    _star_runtime_hub().wait()
    if _ui_hot():
        time.sleep(0.05)
    if not _job_slot.acquire(timeout=3):
        time.sleep(0.05)
        _job_slot.acquire()
    _star_runtime_hub().wait()


def job_done():
    try:
        _job_slot.release()
    except ValueError:
        pass


_job_cursors = None
_job_cursors_lock = threading.Lock()
_job_cursors_saved = 0.0


def _job_cursor_path():
    return os.path.join(PROFILE, "job_cursors.json")


def _job_cursors_load():
    global _job_cursors
    if _job_cursors is not None:
        return _job_cursors
    data = {}
    try:
        with open(_job_cursor_path(), encoding="utf-8") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, ValueError):
        data = {}
    _job_cursors = data
    return data


def _job_cursor_get(name):
    with _job_cursors_lock:
        row = _job_cursors_load().get(name)
        return dict(row) if isinstance(row, dict) else {}


def _job_cursor_put(name, row, force=False):
    global _job_cursors_saved
    # Persist completed profile results before advertising a later resume point.
    if _star_store is not None:
        with _star_extra_lock:
            _star_store.flush(records_only=name in ("library", "more", "lang"))
    with _job_cursors_lock:
        data = _job_cursors_load()
        data[name] = row
        now = time.monotonic()
        if not force and _job_cursors_saved and now - _job_cursors_saved < 2:
            return
        path = _job_cursor_path()
        temp = path + ".tmp"
        try:
            with open(temp, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
            os.replace(temp, path)
            _job_cursors_saved = now
        except OSError:
            return
DEBUG_LOG = os.path.join(PROFILE, "debug.log")
_debug_lock = threading.Lock()


def debug_log(src, kind, msg, detail=None):
    row = {
        "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "src": str(src or "")[:40],
        "kind": str(kind or "")[:40],
        "msg": str(msg or "")[:400],
    }
    if detail not in (None, "", {}, []):
        if not isinstance(detail, (dict, list, str, int, float, bool)):
            detail = str(detail)[:400]
        row["detail"] = detail
    line = json.dumps(row, ensure_ascii=False) + "\n"
    try:
        with _debug_lock:
            if os.path.isfile(DEBUG_LOG) and os.path.getsize(DEBUG_LOG) > 1_500_000:
                with open(DEBUG_LOG, "rb") as handle:
                    handle.seek(-600_000, os.SEEK_END)
                    kept = handle.read()
                cut = kept.find(b"\n")
                with open(DEBUG_LOG, "wb") as handle:
                    handle.write(kept[cut + 1:] if cut >= 0 else kept)
            with open(DEBUG_LOG, "a", encoding="utf-8") as handle:
                handle.write(line)
    except OSError:
        pass
_addon_main = None
_VIDEO_URL = re.compile(r"\.(?:mp4|m4v|webm|m3u8|ts|m4s|mov|mkv)(?:$|[/?#])", re.I)


def addon_main():
    global _addon_main
    if _addon_main is None:
        sys.argv = [PLUGIN, "1", ""]
        import default as addon_default
        original_loader = addon_default.load_single_website
        addon_default.load_single_website = lambda name: media_library.adapt_provider(original_loader(name))
        _addon_main = addon_default
    return _addon_main


CONTENT_FILTERS = [
    ("general", "Allgemein"),
    ("trans", "Trans"),
    ("hentai", "Hentai"),
    ("jav", "JAV"),
    ("rule34", "Rule 34"),
    ("fetish", "Fetish"),
    ("live", "Live"),
    ("creator", "Creator"),
]
TYPE_FILTERS = [
    ("tube", "Tube"),
    ("archive", "Archiv"),
    ("live", "Live"),
    ("resolver", "Resolver"),
]
SORTS = [
    ("0", "A–Z"),
    ("1", "Z–A"),
    ("2", "Neueste"),
    ("3", "Kategorie"),
]


def split_kodi_url(url):
    """Kodi hängt Header als url|Name=Wert&Name=Wert an."""
    if not url or "|" not in url:
        return url or "", {}
    base, _, extra = url.partition("|")
    headers = {}
    for part in extra.split("&"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        headers[urllib.parse.unquote_plus(key).strip()] = urllib.parse.unquote_plus(value).strip()
    return base, headers


def rewrite_playlist(text, playlist_url, forward_headers):
    def wrap(target):
        absolute = urllib.parse.urljoin(playlist_url, target.strip())
        if not absolute.startswith(("https://", "http://")):
            return absolute
        query = {"url": absolute}
        query.update(forward_headers)
        return "/api/stream?" + urllib.parse.urlencode(query)

    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            def repl(match):
                return match.group(1) + wrap(match.group(2)) + match.group(3)
            lines.append(re.sub(r'(URI=")([^"]+)(")', repl, line))
        else:
            lines.append(wrap(stripped))
    return "\n".join(lines) + "\n"


_MOUFLON_KEYS_URL = "https://raw.githubusercontent.com/kesamom/stripchat_mouflon/refs/heads/main/stripchat_mouflon_keys.json"
_mouflon_state = {"at": 0.0, "keys": {}}
_mouflon_lock = threading.Lock()


def _mouflon_parse_keys(body):
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except (ValueError, AttributeError):
        return {}
    if not isinstance(data, dict):
        return {}
    clean = {}
    for key, value in data.items():
        if len(clean) >= 40:
            break
        key = str(key or "")
        value = str(value or "")
        if re.fullmatch(r"[A-Za-z0-9]{8,64}", key) and re.fullmatch(r"[A-Za-z0-9]{8,64}", value):
            clean[key] = value
    return clean


def _mouflon_keys(force=False):
    """Public pkey to pdkey map. Cached in memory only. Never logged or written."""
    now = time.time()
    with _mouflon_lock:
        cached = dict(_mouflon_state["keys"])
        fresh = bool(cached) and now - _mouflon_state["at"] < 1800
    if fresh and not force:
        return cached
    status, body = _cam_open(
        _MOUFLON_KEYS_URL,
        {"User-Agent": _CAM_UA, "Accept": "application/json"},
        6,
        100_000,
    )
    parsed = _mouflon_parse_keys(body) if status == 200 else {}
    with _mouflon_lock:
        if parsed:
            _mouflon_state["keys"] = parsed
            _mouflon_state["at"] = time.time()
            return dict(parsed)
        return dict(_mouflon_state["keys"])


def _mouflon_pkey(text, playlist_url, keys):
    query = urllib.parse.parse_qs(urllib.parse.urlparse(playlist_url or "").query)
    wanted = (query.get("pkey") or [""])[0]
    found = []
    for line in text.splitlines():
        parts = line.strip().split(":")
        if len(parts) >= 4 and parts[0] == "#EXT-X-MOUFLON" and parts[1] == "PSCH":
            if re.fullmatch(r"v\d+", parts[2]) and re.fullmatch(r"[A-Za-z0-9]{8,64}", parts[3]):
                found.append((parts[2], parts[3]))
    if wanted and re.fullmatch(r"[A-Za-z0-9]{8,64}", wanted) and wanted in keys:
        for version, key in found:
            if key == wanted:
                return version, key
        return "v2", wanted
    for version, key in found:
        if key in keys:
            return version, key
    return "", ""


def _mouflon_plain(fragment, pdkey):
    if not fragment or not pdkey or len(fragment) > 160 or len(pdkey) > 64:
        return ""
    reversed_s = fragment[::-1]
    pad = "=" * ((4 - len(reversed_s) % 4) % 4)
    raw = None
    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            raw = decoder(reversed_s + pad)
            break
        except Exception:
            raw = None
    if not raw or len(raw) > 200:
        return ""
    digest = hashlib.sha256(pdkey.encode("utf-8")).digest()
    out = bytes(byte ^ digest[index % len(digest)] for index, byte in enumerate(raw))
    try:
        text = out.decode("utf-8")
    except UnicodeDecodeError:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9._~-]{2,80}", text):
        return ""
    return text


def _mouflon_unwrap_url(url, pdkey):
    parsed = urllib.parse.urlparse(url or "")
    if parsed.scheme != "https" or "doppiocdn" not in parsed.netloc.lower() or ".." in parsed.path:
        return ""
    pieces = url.split("_")
    if len(pieces) < 3:
        return ""
    token = pieces[-2]
    if not token or token.isdigit() or not re.fullmatch(r"[A-Za-z0-9+/=_-]{6,160}", token):
        return ""
    plain = _mouflon_plain(token, pdkey)
    if not plain:
        return ""
    marker = "_" + token + "_"
    if marker not in url:
        return ""
    return url.replace(marker, "_" + plain + "_", 1)


def _live_playlist(text, playlist_url):
    """Stripchat's unsigned media playlist is a short advert and is not forwarded.
    A public pkey from that master selects the live window. Wrapped segment names
    are turned into ordinary media URLs before the player sees the playlist."""
    host = urllib.parse.urlparse(playlist_url or "").netloc.lower()
    if "doppiocdn" not in host or "EXT-X-MOUFLON" not in text:
        return text
    if "EXT-X-MOUFLON-ADVERT" in text:
        return None
    keys = _mouflon_keys()
    psch, pkey = _mouflon_pkey(text, playlist_url, keys)
    if not pkey or pkey not in keys:
        keys = _mouflon_keys(True)
        psch, pkey = _mouflon_pkey(text, playlist_url, keys)
    pdkey = keys.get(pkey, "") if pkey else ""
    lines = []
    skip = False
    held = None
    decoded_next = ""

    def flush_held():
        nonlocal held
        if held is not None:
            lines.append(held)
            held = None

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#EXT-X-STREAM-INF") and "blur" in stripped.lower():
            flush_held()
            skip = True
            continue
        if skip:
            if stripped and not stripped.startswith("#"):
                skip = False
            continue
        if stripped.startswith("#EXT-X-MOUFLON:URI:") and pdkey:
            unwrapped = _mouflon_unwrap_url(stripped.split("URI:", 1)[1].strip(), pdkey)
            if held is not None:
                lines.append(unwrapped or held)
                held = None
            elif unwrapped:
                decoded_next = unwrapped
            continue
        if stripped.startswith("#EXT-X-MOUFLON"):
            continue
        media_name = stripped.split("?", 1)[0].lower()
        if stripped and not stripped.startswith("#") and media_name.endswith(".m3u8"):
            flush_held()
            if "blur" in stripped.lower():
                continue
            if pkey and "pkey=" not in stripped:
                sep = "&" if "?" in stripped else "?"
                stripped = stripped + sep + "psch=" + urllib.parse.quote(psch or "v2") + "&pkey=" + urllib.parse.quote(pkey)
            lines.append(stripped)
            continue
        if stripped and not stripped.startswith("#"):
            if decoded_next:
                lines.append(decoded_next)
                decoded_next = ""
            else:
                flush_held()
                held = stripped
            continue
        flush_held()
        lines.append(line)
    flush_held()
    if decoded_next:
        lines.append(decoded_next)
    return "\n".join(lines) + "\n"


def read_prefs():
    import xbmcaddon
    addon = xbmcaddon.Addon()
    def load_list(key, allowed):
        try:
            values = json.loads(addon.getSetting(key) or "[]")
        except (TypeError, ValueError):
            values = []
        allowed_keys = {item[0] for item in allowed}
        return [value for value in values if value in allowed_keys]
    return {
        "sort": addon.getSetting("main_menu_website_sort") or "0",
        "content": load_list("main_menu_website_content_filter", CONTENT_FILTERS),
        "types": load_list("main_menu_website_type_filter", TYPE_FILTERS),
        "sorts": [{"id": key, "label": label} for key, label in SORTS],
        "contentOptions": [{"id": key, "label": label} for key, label in CONTENT_FILTERS],
        "typeOptions": [{"id": key, "label": label} for key, label in TYPE_FILTERS],
    }


def write_prefs(data):
    import xbmcaddon
    addon = xbmcaddon.Addon()
    sort = str(data.get("sort") or "0")
    if sort not in {key for key, _label in SORTS}:
        sort = "0"
    allowed_content = {key for key, _label in CONTENT_FILTERS}
    allowed_types = {key for key, _label in TYPE_FILTERS}
    content = [value for value in data.get("content") or [] if value in allowed_content]
    types = [value for value in data.get("types") or [] if value in allowed_types]
    addon.setSetting("main_menu_website_sort", sort)
    addon.setSetting("main_menu_website_content_filter", json.dumps(content))
    addon.setSetting("main_menu_website_type_filter", json.dumps(types))
    return read_prefs()


def enable_library_menus():
    import xbmcaddon
    addon = xbmcaddon.Addon()
    for key in (
        "show_download_manager",
        "enable_offline_library",
        "enable_website_collections",
        "enable_playback_history",
    ):
        if addon.getSetting(key) != "true":
            addon.setSetting(key, "true")


def clean_label(text):
    text = re.sub(r"\[/?COLOR[^\]]*\]", "", text or "", flags=re.IGNORECASE)
    text = re.sub(r"\[/?B\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[/?I\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[CR\]", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def fetch_html(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": url,
        "Cookie": "accessAgeDisclaimerPH=1; age_verified=1",
    })
    return urllib.request.urlopen(req, timeout=8).read().decode("utf-8", "replace")


def _plugin_page(url, source):
    if not url:
        return ""
    if url.startswith("plugin://"):
        return url
    if not url.startswith("http"):
        return ""
    site = urllib.parse.parse_qs(urllib.parse.urlparse(source).query).get("website", [""])[0]
    return "plugin://plugin.video.adulthideout/?mode=2&website=%s&url=%s" % (
        urllib.parse.quote(site),
        urllib.parse.quote(url, safe=""),
    )


def _item_target(item):
    parsed = urllib.parse.urlparse(item.get("url") or "")
    values = urllib.parse.parse_qs(parsed.query)
    return urllib.parse.unquote((values.get("url") or [""])[0])


_PROFILE_HREF = re.compile(
    r"/(?:pornstars?|models?|channels?|users?|profiles?|porn-maker|creators?|uploader|amateurs?)/",
    re.I,
)
_GENERIC_LABEL = {
    "more", "see all", "see all categories", "pornstars", "pornstar", "channels", "channel",
    "categories", "category", "models", "model", "search", "member search", "tags", "tag",
    "users", "user", "amateurs", "amateur",
}


def _preview_url(value):
    text = html_unescape(value or "").strip()
    if text.startswith("//"):
        text = "https:" + text
    if not text.startswith("http"):
        return ""
    low = text.lower()
    if "rs:fit" in low or "rs:fill" in low or "/plain/" in low:
        return ""
    if not _VIDEO_URL.search(low):
        return ""
    return text


def _listing_fetch_url(query):
    page = query.get("url") or ""
    if page.startswith("http"):
        return page
    if page not in ("", "BOOTSTRAP"):
        return ""
    website = query.get("website") or ""
    if not website:
        return ""
    try:
        site = addon_main().load_single_website(website)
    except Exception:
        return ""
    if not site:
        return ""
    start = ""
    try:
        if hasattr(site, "get_start_url_and_label"):
            start, _label = site.get_start_url_and_label()
    except Exception:
        start = ""
    if not str(start).startswith("http"):
        start = getattr(site, "base_url", "") or ""
    if website == "youporn" and str(start).rstrip("/") in ("https://www.youporn.com", "http://www.youporn.com"):
        options = getattr(site, "sort_options", None) or []
        paths = getattr(site, "sort_paths", None) or {}
        if options and options[0] in paths:
            start = urllib.parse.urljoin(str(start), paths[options[0]])
    return start if str(start).startswith("http") else ""


def _video_marker(item):
    target = _item_target(item)
    for pattern in (
        r"(viewkey=[A-Za-z0-9]+)",
        r"(/watch/\d+)",
        r"(/video\.[A-Za-z0-9]+)",
        r"(/video-[A-Za-z0-9]+)",
        r"(/video\d{5,})",
        r"(/videos/\d+)",
        r"(/video/\d+)",
        r"(/\d{6,})(?:/|$|\?|#)",
    ):
        match = re.search(pattern, target)
        if match:
            return match.group(1)
    return ""


def _slug_key(text):
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


_CLIP_ATTRS = ("data-mediabook", "data-pvv", "data-preview", "data-trailer")


def _marker_pos(html, marker):
    positions = []
    start = 0
    tail_digit = marker[-1:].isdigit()
    while len(positions) < 6:
        pos = html.find(marker, start)
        if pos < 0:
            break
        after = html[pos + len(marker):pos + len(marker) + 1]
        if not (tail_digit and after.isdigit()):
            positions.append(pos)
        start = pos + max(1, len(marker))
    for pos in positions:
        chunk = html[max(0, pos - 2500):pos + 2500]
        if re.search(r"data-(?:mediabook|pvv|preview|trailer|cnt|thumbs)=", chunk, re.I):
            return pos
    return positions[0] if positions else -1


def _nearest_clip(window, offset, marker_pos):
    best = ""
    best_dist = 10 ** 9
    for attr in _CLIP_ATTRS:
        for match in re.finditer(attr + r'="([^"]+)"', window, re.I):
            url = _preview_url(match.group(1))
            if not url:
                continue
            dist = abs(offset + match.start() - marker_pos)
            if dist < best_dist:
                best_dist = dist
                best = url
    return best


def _frame_list(window, referer, offset=0, marker_pos=0):
    best = None
    best_dist = 10 ** 9
    for match in re.finditer(r'data-(?:cnt|thumbs)="(\d+)"', window, re.I):
        dist = abs(offset + match.start() - marker_pos)
        if dist < best_dist:
            best_dist = dist
            best = match
    if not best:
        return []
    try:
        total = int(best.group(1))
    except ValueError:
        return []
    total = min(total, 40)
    if total < 2:
        return []
    tag = window[max(0, best.start() - 500):best.end() + 500]
    src = re.search(r'data-(?:original|src|path)="([^"]+)"', tag, re.I)
    if not src:
        return []
    base = html_unescape(src.group(1))
    if base.startswith("//"):
        base = "https:" + base
    if "{index}" in base:
        urls = [base.replace("{index}", str(index)) for index in range(1, total + 1)]
    elif re.search(r"/1\.jpe?g", base, re.I):
        urls = [re.sub(r"/1\.jpe?g", "/%d.jpg" % index, base, count=1, flags=re.I) for index in range(1, total + 1)]
    else:
        return []
    return [media_url(url + "|Referer=" + referer) for url in urls if url.startswith("http")]


def _eporner_frames(window, referer):
    match = re.search(
        r'(https?://[^"\s]+/)(\d+)(_240\.jpg)(?:\?[^"]*)?"[^>]*data-st="\d+\|(\d+)\|',
        window,
        re.I,
    )
    if not match:
        return []
    try:
        total = min(int(match.group(4)), 40)
    except ValueError:
        return []
    if total < 2:
        return []
    urls = ["%s%d%s" % (match.group(1), index, match.group(3)) for index in range(1, total + 1)]
    return [media_url(url + "|Referer=" + referer) for url in urls]


def _shot_frames(window, referer):
    found = []
    seen = set()
    for raw in re.findall(r'data-(?:src|original)="([^"]+)"', window, re.I):
        url = html_unescape(raw)
        if url.startswith("//"):
            url = "https:" + url
        if not url.startswith("http") or not re.search(r"/\d+\.jpe?g(?:$|\?)", url, re.I):
            continue
        if url in seen:
            continue
        seen.add(url)
        found.append(url)
    if len(found) < 2:
        return []
    groups = {}
    for url in found:
        groups.setdefault(url.rsplit("/", 1)[0], []).append(url)
    best = max(groups.values(), key=len)
    if len(best) < 2:
        return []

    def index(url):
        number = re.search(r"/(\d+)\.jpe?g", url, re.I)
        return int(number.group(1)) if number else 0

    best.sort(key=index)
    return [media_url(url + "|Referer=" + referer) for url in best[:40]]


def _extra_frames(window, referer):
    frames = _eporner_frames(window, referer)
    if len(frames) > 1:
        return frames
    return _shot_frames(window, referer)


def _specific_profile(full):
    path = urllib.parse.urlparse(full).path
    if not _PROFILE_HREF.search(path + "/"):
        return False
    parts = [part for part in path.split("/") if part]
    if len(parts) < 2:
        return False
    if parts[-1].replace("+", " ").replace("-", " ").lower() in _GENERIC_LABEL:
        return False
    return True


def _name_matches(name, label, full):
    key = _slug_key(name)
    if len(key) < 3:
        return False
    if label and _slug_key(label) == key:
        return True
    segment = _slug_key(urllib.parse.urlparse(full).path.rstrip("/").split("/")[-1])
    if not segment:
        return False
    if segment == key:
        return True
    return segment.startswith(key) and len(segment) - len(key) <= 4


def _link_text(inner):
    cut = re.split(r"user-subscribe|class=\"duration\"", inner or "", maxsplit=1, flags=re.I)[0]
    text = re.sub(r"<[^>]*>", " ", html_unescape(cut))
    text = re.sub(r"<[^>]*$", " ", text)
    text = re.sub(r"\s+\d[\d.,]*\s*[kmb%]\s*$", "", text, flags=re.I)
    return clean_label(text)


def _uploader_in(window, page, offset=0, marker_pos=0):
    names = list(re.finditer(r'data-uploader-name="([^"]+)"', window, re.I))
    name = ""
    name_at = marker_pos
    if names:
        named = min(names, key=lambda match: abs(offset + match.start() - marker_pos))
        name = clean_label(html_unescape(named.group(1)))
        name_at = offset + named.start()
    links = []
    for match in re.finditer(r'href="([^"]+)"[^>]*>(.*?)</a>', window, re.I | re.S):
        href = html_unescape(match.group(1))
        full = urllib.parse.urljoin(page, href)
        if not _specific_profile(full):
            continue
        label = _link_text(match.group(2))
        if label:
            links.append((label, full, offset + match.start()))
    if name:
        ranked = []
        for label, full, at in links:
            if _name_matches(name, label, full):
                ranked.append((abs(at - name_at), full))
        if ranked:
            ranked.sort()
            return name, ranked[0][1]
    blocks = list(re.finditer(
        r'class="(?:uploader|main-uploader)"[^>]*>\s*<a href="([^"]+)"[^>]*>.*?class="name">(.*?)(?:</a>|user-subscribe)',
        window,
        re.I | re.S,
    ))
    if blocks:
        block = min(blocks, key=lambda match: abs(offset + match.start() - marker_pos))
        label = _link_text(block.group(2))
        full = urllib.parse.urljoin(page, html_unescape(block.group(1)))
        if label and _specific_profile(full) and "view_video" not in full:
            return label, full
    if name:
        return name, ""
    if links:
        links.sort(key=lambda item: abs(item[2] - marker_pos))
        return links[0][0], links[0][1]
    return "", ""


def _duration_in(window):
    text = window or ""
    for pattern in (
        r'class="[^"]*duration[^"]*"[^>]*>\s*(?:<[^>]+>\s*){0,3}(\d{1,2}:\d{2}(?::\d{2})?)',
        r'data-duration="(\d{2,5})"',
        r'data-time="(\d{2,5})"',
    ):
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        clock = _format_clock(match.group(1))
        if clock:
            return clock
    spot = re.search(r'duration', text, re.I)
    if spot:
        chunk = text[max(0, spot.start() - 40):spot.end() + 160]
        match = re.search(r'(\d{1,2}:\d{2}(?::\d{2})?)', chunk)
        if match:
            clock = _format_clock(match.group(1))
            if clock:
                return clock
    return ""


def _apply_listing_media(items, html, page, website):
    placed = []
    seen = set()
    for item in items:
        if item.get("folder"):
            continue
        marker = _video_marker(item)
        if not marker or marker in seen:
            continue
        pos = _marker_pos(html, marker)
        if pos >= 0:
            seen.add(marker)
            placed.append((pos, item))
    placed.sort(key=lambda pair: pair[0])
    origin = urllib.parse.urlsplit(page)
    referer = origin.scheme + "://" + origin.netloc + "/"
    last = len(html)
    for index, (pos, item) in enumerate(placed):
        prev = placed[index - 1][0] if index else max(0, pos - 4000)
        nxt = placed[index + 1][0] if index + 1 < len(placed) else min(last, pos + 8000)
        start = (prev + pos) // 2 if index else max(0, pos - 4000)
        end = (pos + nxt) // 2 if index + 1 < len(placed) else min(last, pos + 8000)
        start = max(0, min(start, pos))
        end = min(last, max(end, pos + 1))
        window = html[start:end]
        if not item.get("clip"):
            clip = _nearest_clip(window, start, pos)
            if clip:
                item["clip"] = _stream_page(clip, referer)
        if len(item.get("preview") or []) < 2:
            frames = _frame_list(window, referer, start, pos)
            if len(frames) < 2:
                frames = _extra_frames(window, referer)
            if len(frames) > 1:
                item["preview"] = frames
        if not item.get("duration"):
            clock = _duration_in(window)
            if clock:
                item["duration"] = clock
        if not item.get("uploader"):
            name, full = _uploader_in(window, page, start, pos)
            if name:
                item["uploader"] = name
                if full:
                    item["uploaderUrl"] = "plugin://plugin.video.adulthideout/?mode=2&website=%s&url=%s" % (
                        urllib.parse.quote(website),
                        urllib.parse.quote(full, safe=""),
                    )
                    item["channel"] = True


def _clean_clip(value):
    text = str(value or "").strip()[:800]
    if not text.startswith("http"):
        return ""
    parsed = urllib.parse.urlparse(text)
    host = (parsed.hostname or "").lower()
    if host in ("127.0.0.1", "localhost") and parsed.path == "/api/stream":
        return text
    return _preview_url(text)


def _clean_frames(raw):
    frames = []
    seen = set()
    for frame in raw or []:
        text = str(frame or "").strip()[:800]
        if not text.startswith("http") and not text.startswith("/api/image"):
            continue
        if "/logos/" in text or text in seen:
            continue
        seen.add(text)
        frames.append(text)
        if len(frames) >= 16:
            break
    return frames


def _plugin_values(raw):
    text = str(raw or "").strip()
    if text.startswith(PLUGIN):
        text = text[len(PLUGIN):]
    if text.startswith("?"):
        text = text[1:]
    return dict(urllib.parse.parse_qsl(text, keep_blank_values=True))


def _meta_property(text, prop):
    pattern = r'<meta\b[^>]*property="%s"[^>]*content="([^"]*)"' % re.escape(prop)
    match = re.search(pattern, text or "", re.I)
    if not match:
        pattern = r'<meta\b[^>]*content="([^"]*)"[^>]*property="%s"' % re.escape(prop)
        match = re.search(pattern, text or "", re.I)
    if not match:
        return ""
    return html_unescape(match.group(1)).strip()


def _path_video_id(page):
    match = re.search(r"/videos/(\d{3,})(?:/|$)", urllib.parse.urlparse(page).path)
    return match.group(1) if match else ""


def _best_id(url):
    parts = [part for part in urllib.parse.urlparse(url).path.split("/") if part.isdigit() and len(part) >= 5]
    if not parts:
        return ""
    longest = max(len(part) for part in parts)
    return [part for part in parts if len(part) == longest][-1]


def _page_media_id(html):
    for prop in ("og:image", "twitter:image", "og:video"):
        ident = _best_id(_meta_property(html, prop))
        if ident:
            return ident
    return ""


def _token_in_url(url, token):
    if not token:
        return False
    return ("/" + token + "/") in url or ("/" + token + ".") in url


def _own_clip(html, tokens):
    tokens = [token for token in tokens if token]
    if not tokens:
        return ""
    for attr in _CLIP_ATTRS:
        for match in re.finditer(attr + r'''=["']([^"']+)["']''', html, re.I):
            url = _preview_url(html_unescape(match.group(1)))
            if url and any(_token_in_url(url, token) for token in tokens):
                return url
    for prop in ("og:video:secure_url", "og:video"):
        url = _preview_url(_meta_property(html, prop))
        if url and any(_token_in_url(url, token) for token in tokens):
            return url
    return ""


def _own_shots(html, video_id, referer):
    if not video_id:
        return []
    found = {}
    pattern = re.compile(
        r'(https?://[^"\s]*?/' + re.escape(video_id) + r'/screenshots/(\d+)\.jpe?g)',
        re.I,
    )
    for match in pattern.finditer(html or ""):
        found[int(match.group(2))] = html_unescape(match.group(1))
    if len(found) < 2:
        return []
    urls = [found[index] for index in sorted(found)][:40]
    return [picture for picture in (media_url(url + "|Referer=" + referer) for url in urls) if picture]


_hover_cache = {}
_hover_cache_lock = threading.Lock()


def _hover_empty():
    return {"ok": False, "clip": "", "preview": []}


def hover_clip(raw):
    """Eine Vorschau für genau dieses Video. Kein Plugin-Lock, keine erfundenen Adressen."""
    query = _plugin_values(raw)
    if query.get("mode") not in ("", "4"):
        return _hover_empty()
    page = query.get("url") or ""
    if not page.startswith(("http://", "https://")) or len(page) > 500:
        return _hover_empty()
    parsed = urllib.parse.urlparse(page)
    host = (parsed.hostname or "").lower()
    if not host or host in ("127.0.0.1", "localhost", "0.0.0.0") or host.endswith(".local"):
        return _hover_empty()
    now = time.time()
    with _hover_cache_lock:
        cached = _hover_cache.get(page)
    if cached and cached[0] > now:
        return cached[1]
    try:
        html = fetch_html(page)
    except Exception:
        payload = _hover_empty()
        with _hover_cache_lock:
            _hover_cache[page] = (now + 120, payload)
        return payload
    video_id = _path_video_id(page)
    media_id = "" if video_id else _page_media_id(html)
    referer = parsed.scheme + "://" + host + "/"
    clip = _own_clip(html, [video_id or media_id])
    frames = _own_shots(html, video_id or media_id, referer)
    payload = {
        "ok": bool(clip or len(frames) > 1),
        "clip": _stream_page(clip, referer) if clip else "",
        "preview": frames,
    }
    with _hover_cache_lock:
        if len(_hover_cache) > 200:
            _hover_cache.clear()
        _hover_cache[page] = (now + (600 if payload["ok"] else 120), payload)
    return payload


def enrich_tube_media(payload, query):
    page = query.get("url") or ""
    if query.get("mode") == "4":
        _enrich_qualities(payload, page, query.get("website") or "")
        return
    items = payload.get("items") or []
    videos = [item for item in items if not item.get("folder")]
    if not videos:
        return
    if all(item.get("clip") and item.get("uploader") for item in videos):
        return
    fetch = _listing_fetch_url(query)
    if not fetch:
        return
    try:
        html = fetch_html(fetch)
    except Exception:
        return
    _apply_listing_media(items, html, fetch, query.get("website") or "")


def _attach_uploaders(items, html, page, website):
    pattern = re.compile(
        r'href="([^"]*(?:/model/|/models/|/channel/|/channels/|/user/|/users/|/profiles/)[^"]*)"[^>]*>([^<]{2,80})</a>',
        re.I,
    )
    fallback = re.compile(
        r'href="([^"]*(?:/pornstar/|/pornstars/)[^"]*)"[^>]*>([^<]{2,80})</a>',
        re.I,
    )
    for item in items:
        if item.get("folder") or item.get("channel"):
            continue
        target = _item_target(item)
        marker = ""
        viewkey = re.search(r"viewkey=([a-z0-9]+)", target, re.I)
        if viewkey:
            marker = viewkey.group(1)
        else:
            marker = urllib.parse.urlparse(target).path
        if not marker:
            continue
        index = html.find(marker)
        if index < 0:
            continue
        window = html[index:index + 7000]
        wrap = window.find("usernameWrap")
        chunk = window[wrap:wrap + 700] if wrap >= 0 else ""
        hit = re.search(r'href="([^"]+)"[^>]*>([^<]{2,80})</a>', chunk, re.I) if chunk else None
        if not hit:
            hit = pattern.search(window) or fallback.search(window)
        if not hit:
            continue
        name = clean_label(html_unescape(hit.group(2)))
        if not name:
            continue
        full = urllib.parse.urljoin(page, html_unescape(hit.group(1)))
        item["uploader"] = name
        item["uploaderUrl"] = "plugin://plugin.video.adulthideout/?mode=2&website=%s&url=%s" % (
            urllib.parse.quote(website),
            urllib.parse.quote(full, safe=""),
        )
        item["channel"] = wrap >= 0


def _uploader_cache_path():
    return os.path.join(CACHE_DIR, "uploaders.json")


def _read_uploader_cache():
    path = _uploader_cache_path()
    try:
        return json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_uploader_cache(data):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(_uploader_cache_path(), "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)


def _channel_from_html(html, page):
    wrap = html.find("usernameWrap")
    chunk = html[wrap:wrap + 900] if wrap >= 0 else ""
    hit = re.search(r'href="([^"]+)"[^>]*>([^<]{2,80})</a>', chunk, re.I) if chunk else None
    if not hit:
        scoped = _fact_slice(html)
        block = re.search(
            r'class="main-uploader".{0,800}?href="([^"]+)".{0,700}?class="name">(.*?)(?:user-subscribe|</a>)',
            scoped,
            re.I | re.S,
        ) if scoped else None
        if block:
            name = _link_text(block.group(2))
            full = urllib.parse.urljoin(page, html_unescape(block.group(1)))
            if name and full.startswith("http") and "view_video" not in full:
                return name, full
        return "", ""
    name = clean_label(html_unescape(hit.group(2)))
    full = urllib.parse.urljoin(page, html_unescape(hit.group(1)))
    if "view_video" in full or not re.search(r"/(model|models|channel|channels|user|users|pornstar|pornstars)/", full):
        return "", ""
    return name, full


def _fill_missing_uploaders(items, website):
    if "pornhub" not in (website or ""):
        return
    cache = _read_uploader_cache()
    pending = []
    for item in items:
        if item.get("folder") or item.get("channel"):
            continue
        target = _item_target(item)
        viewkey = re.search(r"viewkey=([a-z0-9]+)", target, re.I)
        if not viewkey:
            continue
        key = viewkey.group(1)
        cached = cache.get(key)
        if isinstance(cached, list) and len(cached) == 2 and cached[0]:
            item["uploader"] = cached[0]
            item["uploaderUrl"] = "plugin://plugin.video.adulthideout/?mode=2&website=%s&url=%s" % (
                urllib.parse.quote(website),
                urllib.parse.quote(cached[1], safe=""),
            )
            item["channel"] = True
            continue
        pending.append((item, key, target))
    pending = pending[:36]
    if not pending:
        return

    def load(entry):
        item, key, target = entry
        try:
            html = fetch_html(target)
        except Exception:
            return key, "", ""
        name, full = _channel_from_html(html, target)
        return key, name, full

    found = {}
    workers = min(8, len(pending))
    with futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for key, name, full in pool.map(load, pending):
            if name and full:
                found[key] = [name, full]
    if not found:
        return
    cache.update(found)
    _write_uploader_cache(cache)
    for item, key, _target in pending:
        pair = found.get(key)
        if not pair:
            continue
        item["uploader"] = pair[0]
        item["uploaderUrl"] = "plugin://plugin.video.adulthideout/?mode=2&website=%s&url=%s" % (
            urllib.parse.quote(website),
            urllib.parse.quote(pair[1], safe=""),
        )
        item["channel"] = True


def html_unescape(text):
    return html.unescape(text or "")


def _merge_facts(resolved, extra):
    """Leere Felder auffüllen. Vorhandene Pornhub-Angaben bleiben stehen."""
    if not extra:
        return
    current = resolved.get("facts") or {}
    merged = dict(current)
    for key, value in extra.items():
        if not value:
            continue
        if isinstance(value, list):
            if not current.get(key):
                merged[key] = value
            continue
        if not current.get(key):
            merged[key] = value
    if any(merged.values()):
        resolved["facts"] = merged


_RELATED_CAP = 18


def _balanced_json(text, open_at):
    if open_at < 0 or open_at >= len(text) or text[open_at] not in "[{":
        return ""
    closer = "]" if text[open_at] == "[" else "}"
    opener = text[open_at]
    depth = 0
    in_string = False
    escaped = False
    limit = min(len(text), open_at + 900000)
    for index in range(open_at, limit):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[open_at:index + 1]
    return ""


def _json_after(text, pattern):
    match = re.search(pattern, text or "", re.I)
    if not match:
        return None
    start = text.find("[", match.end() - 1)
    if start < 0 or start > match.end() + 8:
        return None
    blob = _balanced_json(text, start)
    if not blob:
        return None
    try:
        data = json.loads(blob)
    except ValueError:
        return None
    return data if isinstance(data, list) else None


def _abs_http(page, href):
    href = html_unescape(str(href or "")).replace("\\/", "/").strip()
    if href.startswith("//"):
        href = "https:" + href
    full = urllib.parse.urljoin(page or "", href).split("|", 1)[0]
    if not full.startswith(("http://", "https://")):
        return ""
    return full


def _same_watch(left, right):
    if not left or not right:
        return False
    a = urllib.parse.urlparse(left)
    b = urllib.parse.urlparse(right)
    if (a.hostname or "").lower() != (b.hostname or "").lower():
        return False
    a_key = (urllib.parse.parse_qs(a.query).get("viewkey") or [""])[0]
    b_key = (urllib.parse.parse_qs(b.query).get("viewkey") or [""])[0]
    if a_key or b_key:
        return a_key == b_key and bool(a_key)
    return a.path.rstrip("/") == b.path.rstrip("/")


def _clock_value(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = int(value)
        return _format_clock(seconds) if seconds > 0 else ""
    text = clean_label(html_unescape(str(value or "")))
    if not text:
        return ""
    if re.search(r"\d:\d{2}", text):
        found = re.search(r"\d{1,2}:\d{2}(?::\d{2})?", text)
        return found.group(0) if found else ""
    minutes = re.search(r"(\d{1,3})\s*min", text, re.I)
    if minutes:
        return _format_clock(int(minutes.group(1)) * 60)
    return ""


def _watch_plugin(website, page):
    return "plugin://plugin.video.adulthideout/?mode=4&website=%s&url=%s" % (
        urllib.parse.quote(website or ""),
        urllib.parse.quote(page, safe=""),
    )


def _related_entry(website, page, title, thumb, duration, clip, referer, current):
    page = _abs_http(page, page)
    title = clean_label(re.sub(r"<[^>]+>", " ", html_unescape(title or "")))[:180]
    if not page or not title or len(title) < 3 or _same_watch(page, current):
        return None
    if title.lower() in ("related video", "related videos", "ähnliche videos"):
        return None
    image = ""
    thumb_url = _abs_http(page, thumb)
    if thumb_url and not _is_video_url(thumb_url):
        image = media_url(thumb_url + "|Referer=" + urllib.parse.quote(referer, safe=""))
    preview = _preview_url(clip or "")
    return {
        "title": title,
        "url": _watch_plugin(website, page),
        "page": page,
        "thumb": image,
        "duration": _clock_value(duration),
        "clip": _stream_page(preview, referer) if preview else "",
        "site": website or "",
    }


def _related_key(page):
    parsed = urllib.parse.urlparse(page)
    vkey = (urllib.parse.parse_qs(parsed.query).get("viewkey") or [""])[0]
    host = (parsed.hostname or "").lower()
    if vkey:
        return host + "|v|" + vkey.lower()
    return host + parsed.path.rstrip("/").lower()


def _push_related(found, seen, entry):
    if not entry or len(found) >= _RELATED_CAP:
        return
    key = _related_key(entry["page"])
    if key in seen:
        return
    seen.add(key)
    found.append(entry)


def _related_xvideos(text, page, website, referer, current):
    data = _json_after(text, r"video_related\s*=\s*\[")
    if not data:
        return []
    found, seen = [], set()
    origin = urllib.parse.urlsplit(page)
    base = origin.scheme + "://" + origin.netloc + "/"
    for item in data:
        if not isinstance(item, dict):
            continue
        href = str(item.get("u") or "").replace("THUMBNUM/", "")
        _push_related(found, seen, _related_entry(
            website,
            _abs_http(base, href),
            item.get("tf") or item.get("t") or "",
            item.get("i") or item.get("il") or item.get("ip") or "",
            item.get("d") or "",
            item.get("ipu") or "",
            referer,
            current,
        ))
    return found


def _related_pornhub(text, page, website, referer, current):
    data = _json_after(text, r"relatedVideos(?:\"|')?\s*[:=]\s*\[")
    if not data:
        return []
    found, seen = [], set()
    origin = urllib.parse.urlsplit(page)
    base = origin.scheme + "://" + origin.netloc
    for item in data:
        if not isinstance(item, dict):
            continue
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else item
        vkey = str(fields.get("vkey") or fields.get("viewkey") or "")
        if not vkey:
            continue
        watch = base + "/view_video.php?viewkey=" + urllib.parse.quote(vkey)
        media = str(fields.get("media_path") or fields.get("image") or "")
        token = ""
        parts = [part for part in media.strip("/").split("/") if part.isdigit() and len(part) >= 5]
        if parts:
            token = parts[-1]
        thumb = fields.get("image") or fields.get("thumb") or fields.get("thumbnail") or ""
        if not thumb and token:
            hit = re.search(r"https?://[^\"'\s>]*%s[^\"'\s>]*\.(?:jpe?g|webp|png)" % re.escape(token), text, re.I)
            thumb = hit.group(0) if hit else ""
        clip = str(fields.get("mediabook") or fields.get("preview") or "")
        if clip and token and token not in clip and vkey not in clip:
            clip = ""
        if clip and not token and vkey not in clip:
            clip = ""
        _push_related(found, seen, _related_entry(
            website, watch, fields.get("title") or "", thumb, fields.get("duration") or "", clip, referer, current,
        ))
    return found


def _related_initials(text, page, website, referer, current):
    match = re.search(r"window\.initials\s*=\s*\{", text or "")
    if not match:
        return []
    blob = _balanced_json(text, match.end() - 1)
    if not blob:
        return []
    try:
        data = json.loads(blob)
    except ValueError:
        return []
    found, seen = [], set()

    def walk(node, related):
        if len(found) >= _RELATED_CAP:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, related or "related" in str(key).lower())
            if related:
                href = node.get("pageURL") or node.get("pageUrl") or node.get("page_url") or ""
                title = node.get("title") or node.get("name") or ""
                thumb = node.get("thumbURL") or node.get("imageURL") or node.get("posterURL") or node.get("thumb") or ""
                duration = node.get("duration") or node.get("durationStr") or ""
                clip = node.get("trailerURL") or node.get("spriteURL") or ""
                if href and title and re.search(r"/videos?/|viewkey=|/watch/", str(href), re.I):
                    _push_related(found, seen, _related_entry(website, _abs_http(page, href), title, thumb, duration, clip if _preview_url(str(clip)) else "", referer, current))
        elif isinstance(node, list) and related:
            for value in node[:40]:
                walk(value, True)

    walk(data, False)
    return found


def _related_cards(text, page, website, referer, current):
    markers = ("relatedVideos", "related-videos", "related_videos", "video_related", "data-role=\"related")
    start = -1
    lowered = text.lower()
    for marker in markers:
        at = lowered.find(marker.lower())
        if at >= 0 and (start < 0 or at < start):
            start = at
    if start < 0:
        return []
    chunk = text[start:start + 160000]
    found, seen = [], set()
    for match in re.finditer(r'<a\b[^>]*href="([^"]+)"[^>]*>', chunk, re.I):
        href = html_unescape(match.group(1))
        low = href.lower()
        if not re.search(r"viewkey=|/videos?/\d|/watch/|/video[./]", low):
            continue
        window = chunk[max(0, match.start() - 700):match.end() + 900]
        title = ""
        titled = re.search(r'title="([^"]{3,180})"', window, re.I)
        if titled:
            title = titled.group(1)
        if not title:
            text_hit = re.search(r">([^<]{8,180})<", chunk[match.end():match.end() + 400])
            title = text_hit.group(1) if text_hit else ""
        image = ""
        for attr in ("data-src", "data-thumb", "data-original", "src"):
            pic = re.search(attr + r'="([^"]+)"', window, re.I)
            if pic and not _is_video_url(pic.group(1)):
                image = pic.group(1)
                break
        duration = ""
        clock = re.search(r"(\d{1,2}:\d{2}(?::\d{2})?)", window)
        if clock:
            duration = clock.group(1)
        _push_related(found, seen, _related_entry(website, _abs_http(page, href), title, image, duration, "", referer, current))
        if len(found) >= _RELATED_CAP:
            break
    return found


def _related_from_html(html, page, website):
    text = (html or "").replace("\\/", "/")
    if not text or not str(page).startswith("http"):
        return []
    origin = urllib.parse.urlsplit(page)
    referer = origin.scheme + "://" + origin.netloc + "/"
    for parser in (_related_xvideos, _related_pornhub, _related_initials, _related_cards):
        try:
            found = parser(text, page, website, referer, page)
        except Exception:
            found = []
        if found:
            return found[:_RELATED_CAP]
    return []


def _quality_from_sources(resolved):
    facts = dict(resolved.get("facts") or {})
    if facts.get("quality"):
        return
    labels = []
    for source in resolved.get("sources") or []:
        label = clean_label(str((source or {}).get("label") or ""))
        if label and label not in labels:
            labels.append(label)
    if not labels:
        return
    facts["quality"] = ", ".join(labels[:8])[:80]
    resolved["facts"] = facts


def _enrich_qualities(payload, page, website=""):
    resolved = payload.get("resolved") or None
    if not resolved or not page.startswith("http"):
        return
    try:
        html_text = fetch_html(page)
    except Exception:
        html_text = ""
    if html_text:
        name, full = _channel_from_html(html_text, page)
        if name:
            resolved["uploader"] = name
            resolved["uploaderUrl"] = "plugin://plugin.video.adulthideout/?mode=2&website=%s&url=%s" % (
                urllib.parse.quote(website),
                urllib.parse.quote(full, safe=""),
            )
            resolved["channel"] = True
        _merge_facts(resolved, _page_facts(html_text, page))
        scrub = _scrub_from_html(html_text, page)
        if scrub:
            resolved["scrub"] = scrub
        related = _related_from_html(html_text, page, website)
        if related:
            resolved["related"] = related
    if len(resolved.get("sources") or []) > 1 or not html_text:
        _quality_from_sources(resolved)
        return
    origin = urllib.parse.urlsplit(page)
    referer = origin.scheme + "://" + origin.netloc + "/"
    license_match = re.search(r"license_code\s*:\s*'([^']+)'", html_text)
    license_code = license_match.group(1).strip() if license_match else ""
    decoder = None
    if license_code:
        try:
            from resources.lib.decoders.kvs_decoder import kvs_decode_url
            decoder = kvs_decode_url
        except Exception:
            decoder = None
    labels = dict(re.findall(r"((?:video_url|video_alt_url\d*)_text)\s*:\s*'([^']+)'", html_text, re.I))
    sources = []
    seen = set()
    for key, raw in re.findall(r"(video_url|video_alt_url\d*)\s*:\s*'([^']+)'", html_text, re.I):
        stream = html_unescape(raw.replace("\\/", "/").strip())
        if decoder:
            try:
                stream = decoder(stream, license_code)
            except Exception:
                continue
        if not stream.startswith("http") or stream in seen:
            continue
        seen.add(stream)
        label = html_unescape(labels.get(key + "_text") or labels.get(key.lower() + "_text") or "")
        if not label:
            label = "HD" if "alt" in key.lower() else "SD"
        sources.append({"label": label, "path": stream + "|Referer=" + urllib.parse.quote(referer, safe="") + "&Origin=" + urllib.parse.quote(referer, safe="")})
    if len(sources) > 1:
        resolved["sources"] = sources
    _quality_from_sources(resolved)


_FACT_MARKERS = (
    "video-detailed-info",
    "tm_categoriesWrapper",
    "video-metadata",
    "categoriesWrapper",
    "block-details",
    "video-info-tags",
    'id="video-info"',
)
_GENERIC_NAMES = {
    "categories", "category", "tags", "tag", "more", "see all", "see all categories",
    "pornstars", "pornstar", "channels", "channel", "models", "model", "home",
    "search", "subscribe", "all", "genres", "genre", "niches", "videos", "video",
    "keywords", "keyword",
}


def _fact_slice(html):
    text = html or ""
    chunks = []
    for marker in _FACT_MARKERS:
        at = text.find(marker)
        if at < 0:
            continue
        window = text[max(0, at - 8000):at + 16000]
        lower = window.lower()
        for cut_at in ('id="relatedvideos', 'id="related-videos', 'class="related-videos', 'class="relatedvideos'):
            cut = lower.find(cut_at)
            if cut > 500:
                window = window[:cut]
                lower = window.lower()
                break
        if window not in chunks:
            chunks.append(window)
    return "\n".join(chunks)


def _scrub_from_html(html, page):
    text = (html or "").replace("\\/", "/")
    origin = urllib.parse.urlsplit(page or "")
    referer = (origin.scheme + "://" + origin.netloc + "/") if origin.netloc else ""
    minute = re.search(r"setThumbSlideMinute\(\s*'([^']+)'\s*\)", text)
    if minute and "NUM" in minute.group(1):
        url = html_unescape(minute.group(1))
        if url.startswith("http"):
            return {"kind": "sheet", "pattern": url.replace("NUM", "{minute}"), "cols": 10, "rows": 6, "referer": referer}
    big = re.search(r"setThumbSlideBig\(\s*'([^']+)'\s*\)", text)
    if big:
        url = html_unescape(big.group(1))
        if url.startswith("http") and not _is_video_url(url):
            return {"kind": "mosaic", "pattern": url, "cols": 10, "rows": 10, "referer": referer}
    timeline = re.search(r"timeline_screenshots_url\s*:\s*'([^']+)'", text, re.I)
    if not timeline:
        timeline = re.search(r'timeline_screenshots_url\s*:\s*"([^"]+)"', text, re.I)
    if timeline:
        url = html_unescape(timeline.group(1))
        if url.startswith("http") and ("{time}" in url or "%d" in url) and not _is_video_url(url):
            count_match = re.search(r"timeline_screenshots_count\s*:\s*'(\d+)'", text, re.I)
            count = int(count_match.group(1)) if count_match else 12
            count = max(2, min(count, 40))
            return {"kind": "times", "pattern": url.replace("%d", "{time}"), "count": count, "referer": referer}
    frames = _screenshot_frames(text, referer)
    if frames:
        return frames
    return {}


def _screenshot_frames(text, referer):
    groups = {}
    for raw in re.findall(r"(?:https?:)?//[^\"'\s<>]+/\d+\.jpe?g", text, re.I):
        url = html_unescape(raw)
        if url.startswith("//"):
            url = "https:" + url
        lower = url.lower()
        if "videostimeline" in lower or _is_video_url(url):
            continue
        name = lower.rsplit("/", 1)[-1]
        if name.startswith("preview"):
            continue
        folder = url.rsplit("/", 1)[0] + "/"
        groups.setdefault(folder, {})[name] = url
    if not groups:
        return {}

    def rank(item):
        folder, members = item
        area = 0
        size = re.search(r"(\d{2,4})x(\d{2,4})", folder)
        if size:
            area = int(size.group(1)) * int(size.group(2))
        return (len(members), area)

    folder, members = max(groups.items(), key=rank)
    indexed = []
    for url in members.values():
        match = re.search(r"/(\d+)\.jpe?g$", url, re.I)
        if match:
            indexed.append((int(match.group(1)), url))
    indexed.sort()
    indexed = indexed[:40]
    if len(indexed) < 2:
        return {}
    numbers = [number for number, _url in indexed]
    ext = ".jpeg" if indexed[0][1].lower().endswith(".jpeg") else ".jpg"
    if numbers == list(range(numbers[0], numbers[0] + len(numbers))):
        return {
            "kind": "frames",
            "pattern": folder + "{index}" + ext,
            "start": numbers[0],
            "count": len(numbers),
            "referer": referer,
        }
    return {"kind": "frames", "urls": [url for _number, url in indexed], "referer": referer}


def _quoted_list(text, key):
    match = re.search(r"\b%s\s*:\s*'([^']*)'" % re.escape(key), text)
    if not match:
        match = re.search(r'\b%s\s*:\s*"([^"]*)"' % re.escape(key), text)
    if not match:
        return []
    names = []
    for part in re.split(r"\s*,\s*", html_unescape(match.group(1))):
        name = clean_label(part)
        if name:
            names.append(name)
    return names


def _iso_duration(value):
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", str(value or ""), re.I)
    if not match or not any(match.groups()):
        return ""
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    if hours:
        return "%d:%02d:%02d" % (hours, minutes, seconds)
    if minutes or seconds:
        return "%d:%02d" % (minutes, seconds)
    return ""


def _meta_content(text, key):
    needle = key.lower()
    for match in re.finditer(r"<meta\b[^>]*>", text or "", re.I):
        tag = match.group(0)
        if needle not in tag.lower():
            continue
        content = re.search(r'content="([^"]*)"', tag, re.I) or re.search(r"content='([^']*)'", tag, re.I)
        if content:
            return clean_label(html_unescape(content.group(1)))
    return ""


def _jsonld_video(text):
    for raw in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', text or "", re.I | re.S):
        try:
            data = json.loads(html_unescape(raw).strip())
        except ValueError:
            continue
        nodes = data if isinstance(data, list) else [data]
        flat = []
        for node in nodes:
            if isinstance(node, dict) and isinstance(node.get("@graph"), list):
                flat.extend(node["@graph"])
            else:
                flat.append(node)
        for node in flat:
            if not isinstance(node, dict):
                continue
            kind = node.get("@type") or ""
            kinds = kind if isinstance(kind, list) else [kind]
            if any("VideoObject" in str(item) for item in kinds):
                return node
    return {}


def _duration_of(text):
    itemprop = re.search(r'itemprop="duration"[^>]*content="([^"]+)"', text or "", re.I)
    if itemprop:
        iso = _iso_duration(itemprop.group(1))
        if iso:
            return iso
    for pattern in (
        r'class="[^"]*vid-length[^"]*"[^>]*>\s*([^<]{1,20})',
        r'class="[^"]*\bduration\b[^"]*"[^>]*>\s*(\d{1,2}:\d{2}(?::\d{2})?)',
        r"\bDuration\s*:\s*(?:<em[^>]*>\s*)?(\d{1,3}:\d{2}(?::\d{2})?|\d{1,3}\s*min)",
    ):
        match = re.search(pattern, text or "", re.I)
        if not match:
            continue
        value = clean_label(match.group(1))
        if re.search(r"\d", value):
            return value[:20]
    return ""


def _views_of(text, chunk):
    scoped = chunk or text or ""
    labeled = re.search(r"\bViews\s*:\s*(?:<em[^>]*>\s*)?([\d][\d\s.,]*\s*[KMBkmb]?)", scoped, re.I)
    if not labeled and text and text != scoped:
        labeled = re.search(r"\bViews\s*:\s*(?:<em[^>]*>\s*)?([\d][\d\s.,]*\s*[KMBkmb]?)", text, re.I)
    if labeled:
        return clean_label(labeled.group(1))[:40]
    itemprop = re.search(r'itemprop="interactionCount"[^>]*content="([^"]+)"', text or "", re.I)
    if itemprop:
        return clean_label(html_unescape(itemprop.group(1)))[:40]
    loose = re.search(r"([\d][\d.,]*\s*[KMBkmb]?)\s+views\b", scoped, re.I)
    if loose:
        return clean_label(loose.group(1))[:40]
    return ""


def _when_of(text):
    match = re.search(
        r"\b(?:Submitted|Uploaded|Added|Published|Date)\s*:\s*(?:<em[^>]*>\s*)?([^<]{2,48})",
        text or "",
        re.I,
    )
    if not match:
        return ""
    value = clean_label(match.group(1))
    if not value or re.search(r"function|http|\{|\}", value, re.I):
        return ""
    return value[:60]


def _rating_of(text):
    match = re.search(r"\b(?:Rating|Rated)\s*:\s*(?:<em[^>]*>\s*)?(\d{1,3}(?:[.,]\d+)?\s*%?)", text or "", re.I)
    if not match:
        return ""
    return clean_label(match.group(1))[:20]


def _quality_of(text):
    match = re.search(r'class="[^"]*vid-quality[^"]*"[^>]*>\s*([^<]{1,40})', text or "", re.I)
    if not match:
        return ""
    return clean_label(match.group(1))[:40]


def _page_facts(html, page):
    text = (html or "").replace("\\/", "/")
    stars, categories, tags = [], [], []
    seen = set()

    def add(bucket, name, href, limit):
        name = clean_label(re.sub(r"<[^>]+>", " ", html_unescape(name or "")))
        key = name.lower()
        if not name or len(name) < 2 or len(name) > 60 or key in _GENERIC_NAMES or "http" in key or "{" in name:
            return
        full = ""
        if href:
            joined = urllib.parse.urljoin(page or "", html_unescape(href))
            if joined.startswith("http"):
                full = joined
        if key in seen:
            if full:
                for item in bucket:
                    if item["name"].lower() == key and not item.get("url"):
                        item["url"] = full
            return
        if len(bucket) >= limit:
            return
        seen.add(key)
        item = {"name": name}
        if full:
            item["url"] = full
        bucket.append(item)

    chunk = _fact_slice(text)
    if chunk:
        for kind, href, inner in re.findall(r'<li class="([^"]*)"[^>]*>\s*<a href="([^"]+)"[^>]*>(.*?)</a>', chunk, re.I | re.S):
            low_kind = kind.lower()
            if "uploader" in low_kind:
                continue
            label = _link_text(inner)
            named = re.search(r'class="name">(.*?)</span>', inner, re.I | re.S)
            if named:
                label = _link_text(named.group(1))
            if any(word in low_kind for word in ("model", "star", "pornstar", "actor", "performer")):
                add(stars, label, href, 24)
            elif "categor" in low_kind or "genre" in low_kind or "niche" in low_kind:
                add(categories, label, href, 24)
            elif "tag" in low_kind or "keyword" in low_kind:
                add(tags, label, href, 40)
        for match in re.finditer(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', chunk, re.I | re.S):
            before = chunk[max(0, match.start() - 180):match.start()].lower()
            if "menu_elem" in before or "<nav" in before or "site-header" in before or "footer" in before:
                continue
            href, inner = match.group(1), _link_text(match.group(2))
            low = html_unescape(href).lower()
            tail = low.rstrip("/").split("/")[-1].split("?")[0]
            if re.search(r"/(?:pornstar|pornstars|models?|actress(?:es)?|actors?|performers?|stars?)/", low):
                if "uploader" in before:
                    continue
                add(stars, inner, href, 24)
            elif re.search(r"/(?:categor(?:y|ies)|cats|cat|genres?|niches?)/", low) and tail not in ("categories", "cats", "category", "genres", "genre", "niches", "niche", "all"):
                add(categories, inner, href, 24)
            elif re.search(r"/(?:tags?|keywords?)/", low) and tail not in ("tags", "tag", "keywords", "keyword", "all"):
                add(tags, inner, href, 40)
    for name in _quoted_list(text, "video_models"):
        add(stars, name, "", 24)
    for name in _quoted_list(text, "video_categories"):
        add(categories, name, "", 24)
    for name in _quoted_list(text, "video_tags"):
        add(tags, name, "", 40)
    node = _jsonld_video(text)
    if node:
        actors = node.get("actor") or node.get("actors") or []
        if isinstance(actors, dict):
            actors = [actors]
        if not isinstance(actors, list):
            actors = []
        for actor in actors:
            if isinstance(actor, dict):
                add(stars, str(actor.get("name") or ""), str(actor.get("url") or ""), 24)
            else:
                add(stars, str(actor), "", 24)
        genres = node.get("genre") or []
        if isinstance(genres, str):
            genres = [part.strip() for part in genres.split(",")]
        if not isinstance(genres, list):
            genres = []
        for genre in genres:
            add(categories, str(genre), "", 24)
        keywords = node.get("keywords") or ""
        if isinstance(keywords, str):
            for part in keywords.split(","):
                add(tags, part, "", 40)
    duration = _duration_of(chunk) or _duration_of(text) or _iso_duration(node.get("duration") if node else "")
    views = _views_of(text, chunk)
    if not views and node:
        stats = node.get("interactionStatistic") or []
        if isinstance(stats, dict):
            stats = [stats]
        if not isinstance(stats, list):
            stats = []
        for stat in stats:
            if isinstance(stat, dict) and stat.get("userInteractionCount"):
                views = clean_label(str(stat.get("userInteractionCount")))[:40]
                break
    from video_metadata import upload_date, video_details
    details = video_details(text, page, node)
    exact_upload = upload_date(text, node)
    when = exact_upload or _when_of(chunk) or _when_of(text)
    if not when and node:
        stamp = str(node.get("uploadDate") or "")[:10]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", stamp):
            when = stamp
    rating = _rating_of(chunk) or _rating_of(text)
    quality = _quality_of(chunk) or _quality_of(text)
    site = _meta_content(text, "og:site_name")
    if not site and isinstance(node.get("publisher"), dict):
        site = clean_label(str(node["publisher"].get("name") or ""))[:80]
    about = ""
    title = clean_label(str((node or {}).get("name") or "")) or _meta_content(text, "og:title")
    description = clean_label(str((node or {}).get("description") or ""))
    if not description:
        description = _meta_content(text, "og:description") or _meta_content(text, "description")
    if description and description != title and len(description) > len(title) + 8:
        about = description[:400]
    facts = {
        "views": views,
        "when": when,
        "uploadDate": exact_upload,
        "details": details,
        "about": about,
        "duration": duration,
        "rating": rating,
        "quality": quality,
        "site": site[:80],
        "stars": stars,
        "categories": categories,
        "tags": tags,
    }
    if not any(facts.values()):
        return {}
    return facts


def _stream_page(path, referer):
    if not path.startswith("http"):
        return ""
    params = {"url": path.split("|", 1)[0]}
    if referer:
        params["Referer"] = referer
    return "http://127.0.0.1:%d/api/stream?%s" % (MEDIA_PORT, urllib.parse.urlencode(params))


def _source_list(raw):
    try:
        payload = json.loads(raw or "[]")
    except ValueError:
        return []
    sources = []
    for item in payload if isinstance(payload, list) else []:
        path = str((item or {}).get("path") or "")
        if path:
            sources.append({"label": clean_label(str((item or {}).get("label") or "Stream")), "path": path})
    return sources


def _clean_facts(raw):
    from video_metadata import valid_upload_date, clean_details
    try:
        data = json.loads(raw or "")
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}

    def links(items, limit):
        cleaned = []
        seen = set()
        for item in items or []:
            if not isinstance(item, dict):
                continue
            name = clean_label(str(item.get("name") or ""))[:80]
            url = str(item.get("url") or "")[:500]
            key = name.lower()
            if not name or key in seen:
                continue
            if url and not url.startswith("http"):
                continue
            seen.add(key)
            entry = {"name": name}
            if url:
                entry["url"] = url
            cleaned.append(entry)
            if len(cleaned) >= limit:
                break
        return cleaned

    facts = {
        "views": clean_label(str(data.get("views") or ""))[:40],
        "when": clean_label(str(data.get("when") or ""))[:60],
        "uploadDate": valid_upload_date(data.get("uploadDate")),
        "details": clean_details(data.get("details")),
        "about": clean_label(str(data.get("about") or ""))[:4000],
        "duration": clean_label(str(data.get("duration") or ""))[:20],
        "rating": clean_label(str(data.get("rating") or ""))[:20],
        "quality": clean_label(str(data.get("quality") or ""))[:80],
        "site": clean_label(str(data.get("site") or ""))[:80],
        "stars": links(data.get("stars"), 24),
        "categories": links(data.get("categories"), 24),
        "tags": links(data.get("tags"), 40),
    }
    if not any(facts.values()):
        return {}
    return facts


def _format_clock(value):
    if value in (None, "", 0, "0", 0.0):
        return ""
    if isinstance(value, str) and re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", value.strip()):
        return value.strip()
    try:
        total = int(float(value))
    except (TypeError, ValueError):
        return ""
    if total <= 0 or total > 24 * 3600:
        return ""
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return "%d:%02d:%02d" % (hours, minutes, seconds)
    return "%d:%02d" % (minutes, seconds)


def _format_rating(value):
    if value in (None, "", 0, "0", 0.0):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        text = clean_label(str(value))[:20]
        return text if re.search(r"\d", text) else ""
    if number <= 0 or number > 100:
        return ""
    if number <= 5:
        shown = "%.1f" % number
        return shown[:-2] if shown.endswith(".0") else shown
    return "%d%%" % int(round(number))


def media_url(path):
    if not path:
        return ""
    if path.startswith(("http://", "https://")):
        if _is_video_url(path):
            return ""
        return "http://127.0.0.1:%d/api/image?url=%s" % (MEDIA_PORT, urllib.parse.quote(path, safe=""))
    logos = os.path.join(ADDON, "resources", "logos")
    try:
        if os.path.commonpath([os.path.abspath(path), os.path.abspath(logos)]) == os.path.abspath(logos):
            name = os.path.relpath(path, logos).replace("\\", "/")
            return "/logos/" + urllib.parse.quote(name)
    except ValueError:
        pass
    if os.path.isfile(path):
        return "/file?path=" + urllib.parse.quote(path, safe="")
    return ""


def item_payload(entry):
    item = entry["item"]
    info = (item.get("info") or {}).get("video") or {}
    art = item.get("art") or {}
    thumb = art.get("thumb") or art.get("poster") or art.get("icon") or ""
    title = clean_label(item.get("label") or info.get("title") or "Eintrag")
    duration = _format_clock(info.get("duration"))
    if not duration:
        trailing = re.search(r"\((\d{1,2}:\d{2}(?::\d{2})?)\)\s*$", title)
        if trailing:
            duration = trailing.group(1)
            title = title[:trailing.start()].strip()
    plot = clean_label(info.get("plot") or "")
    if not duration:
        lead = re.match(r"(\d{1,2}:\d{2}(?::\d{2})?)\b", plot)
        if lead:
            duration = lead.group(1)
    if not duration:
        minutes = re.search(r"\((\d{1,3})\s*min(?:utes?)?\)\s*$", title, re.I)
        if minutes:
            duration = _format_clock(int(minutes.group(1)) * 60)
            title = title[:minutes.start()].strip()
    if plot and plot.lower() == title.lower():
        plot = ""
    return {
        "title": title,
        "media": media_library.entry_media(entry),
        "url": entry.get("url") or "",
        "folder": bool(entry.get("isFolder")),
        "thumb": media_url(thumb),
        "preview": [
            picture for picture in (
                media_url(frame if "|" in frame else frame + "|Referer=" + ((item.get("properties") or {}).get("web_referer") or "https://www.pornhub.com/"))
                for frame in ((item.get("properties") or {}).get("web_preview") or "").split("|")
                if frame.startswith("http")
            ) if picture
        ],
        "clip": _stream_page((item.get("properties") or {}).get("web_clip") or "", (item.get("properties") or {}).get("web_referer") or ""),
        "plot": plot,
        "duration": duration,
        "rating": _format_rating(info.get("rating")),
        "channel": (item.get("properties") or {}).get("web_channel") == "1",
        "uploader": clean_label((item.get("properties") or {}).get("web_uploader") or ""),
        "uploaderUrl": _plugin_page((item.get("properties") or {}).get("web_uploader_url") or "", entry.get("url") or ""),
        "playable": (item.get("properties") or {}).get("IsPlayable") == "true" or not entry.get("isFolder"),
        "context": [
            {"label": clean_label(label), "command": command}
            for label, command in (item.get("context") or [])
            if isinstance(label, str)
        ],
    }


UI_PATH = os.path.join(PROFILE, "web_ui.json")
NAV_WORDS = {
    "search": ("search", "suche"),
    "categories": ("categor", "kategor", "tag"),
    "stars": ("pornstar", "model", "performer", "star", "actress"),
    "channels": ("channel", "uploader", "kanal"),
    "collections": ("collection", "playlist", "sammlung"),
}


PER_PAGE_CHOICES = (12, 18, 24, 30, 36, 48, 60, 90, 120)
TILE_CHOICES = ("s", "m", "l", "xl")


def _clamp_per_page(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 36
    return number if number in PER_PAGE_CHOICES else 36


def _clamp_tile(value):
    text = str(value or "").strip()
    return text if text in TILE_CHOICES else "s"


_GROUP_ID = re.compile(r"^[a-f0-9]{8,32}$")
_LOGO_NAME = re.compile(r"^[a-f0-9]{8,32}\.(?:jpg|png|gif|webp)$")
_LOGO_EXT = {"jpeg": ".jpg", "png": ".png", "gif": ".gif", "webp": ".webp"}
_BRAND_IDS = {
    "logo", "all", "home", "bookmarks", "sites", "search", "vault", "smart",
    "stars", "continue", "downloads", "offline", "collections", "profile",
    "stats", "multi", "settings", "browse", "watch",
}
_BRAND_FILE = re.compile(
    r"^(?:logo|all|home|bookmarks|sites|search|vault|smart|stars|continue|downloads|offline|collections|profile|stats|multi|settings|browse|watch)\.(?:jpg|png|gif|webp)$"
)


def _image_kind(data):
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return ""


def _clean_labels(raw, limit=16):
    cleaned = []
    seen = set()
    if not isinstance(raw, list):
        return cleaned
    for item in raw:
        if isinstance(item, dict):
            text = item.get("name") or item.get("title") or ""
        else:
            text = item
        text = re.sub(r"\s+", " ", str(text or "")).strip()[:40]
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _clean_group_item(entry):
    if not isinstance(entry, dict):
        return None
    url = str(entry.get("url") or "")[:800]
    if not url:
        return None
    kind = str(entry.get("kind") or "video")
    if kind not in ("video", "channel", "model", "other"):
        kind = "other"
    item = {
        "kind": kind,
        "mediaType": media_library.saved_kind(url, entry.get("mediaType")),
        "extension": re.sub(r"[^a-z0-9]", "", str(entry.get("extension") or "").lower())[:12],
        "title": str(entry.get("title") or "Eintrag")[:180],
        "url": url,
        "thumb": str(entry.get("thumb") or "")[:1500],
        "site": str(entry.get("site") or "")[:80],
        "plot": str(entry.get("plot") or "")[:180],
        "categories": _clean_labels(entry.get("categories")),
    }
    clip = _clean_clip(entry.get("clip"))
    frames = _clean_frames(entry.get("preview"))
    duration = str(entry.get("duration") or "").strip()[:20]
    if clip:
        item["clip"] = clip
    if frames:
        item["preview"] = frames
    if duration:
        item["duration"] = duration
    return item


def _clean_groups(raw, depth=0, state=None):
    if state is None:
        state = {"budget": 80, "seen": set()}
    cleaned = []
    if depth > 5 or not isinstance(raw, list):
        return cleaned
    for node in raw:
        if state["budget"] <= 0 or not isinstance(node, dict):
            continue
        gid = str(node.get("id") or "").strip().lower()
        if not _GROUP_ID.fullmatch(gid) or gid in state["seen"]:
            continue
        name = re.sub(r"\s+", " ", str(node.get("name") or "")).strip()[:60] or "Gruppe"
        logo = str(node.get("logo") or "").strip().lower()
        if not _LOGO_NAME.fullmatch(logo):
            logo = ""
        items = []
        seen_urls = set()
        for entry in node.get("items") or []:
            item = _clean_group_item(entry)
            if not item or item["url"] in seen_urls:
                continue
            seen_urls.add(item["url"])
            items.append(item)
            if len(items) >= 200:
                break
        state["seen"].add(gid)
        state["budget"] -= 1
        children = _clean_groups(node.get("children") or [], depth + 1, state)
        cleaned.append({"id": gid, "name": name, "logo": logo, "items": items, "children": children})
    return cleaned


def _logo_names(nodes, found):
    for node in nodes or []:
        if node.get("logo"):
            found.add(node["logo"])
        _logo_names(node.get("children"), found)


def _prune_group_logos(groups):
    used = set()
    _logo_names(groups, used)
    folder = os.path.join(PROFILE, "group_logos")
    if not os.path.isdir(folder):
        return
    for name in os.listdir(folder):
        if not _LOGO_NAME.fullmatch(name) or name in used:
            continue
        try:
            os.remove(os.path.join(folder, name))
        except OSError:
            pass


def _brand_dir():
    folder = os.path.join(PROFILE, "brand")
    os.makedirs(folder, exist_ok=True)
    return folder


def _brand_path(name):
    name = str(name or "").strip().lower()
    if not _BRAND_FILE.fullmatch(name):
        return ""
    folder = os.path.abspath(os.path.join(PROFILE, "brand"))
    path = os.path.abspath(os.path.join(folder, name))
    if not path.startswith(folder + os.sep) or not os.path.isfile(path):
        return ""
    return path


def save_brand_image(slot, raw):
    slot = str(slot or "").strip().lower()
    if slot not in _BRAND_IDS:
        raise ValueError("slot")
    limit = 1_500_000 if slot == "logo" else 4_000_000
    if not isinstance(raw, (bytes, bytearray)) or len(raw) < 32 or len(raw) > limit:
        raise ValueError("size")
    kind = _image_kind(bytes(raw))
    if not kind:
        raise ValueError("type")
    folder = _brand_dir()
    for ext in _LOGO_EXT.values():
        old = os.path.join(folder, slot + ext)
        if os.path.isfile(old):
            try:
                os.remove(old)
            except OSError:
                pass
    name = slot + _LOGO_EXT[kind]
    with open(os.path.join(folder, name), "wb") as handle:
        handle.write(raw)
    return name


def clear_brand_image(slot):
    slot = str(slot or "").strip().lower()
    if slot not in _BRAND_IDS:
        raise ValueError("slot")
    folder = os.path.join(PROFILE, "brand")
    if not os.path.isdir(folder):
        return
    for ext in _LOGO_EXT.values():
        old = os.path.join(folder, slot + ext)
        if os.path.isfile(old):
            try:
                os.remove(old)
            except OSError:
                pass


def _group_logo_path(name):
    name = str(name or "").strip().lower()
    if not _LOGO_NAME.fullmatch(name):
        return ""
    folder = os.path.abspath(os.path.join(PROFILE, "group_logos"))
    path = os.path.abspath(os.path.join(folder, name))
    if not path.startswith(folder + os.sep) or not os.path.isfile(path):
        return ""
    return path


def save_group_logo(group_id, raw):
    group_id = str(group_id or "").strip().lower()
    if not _GROUP_ID.fullmatch(group_id):
        raise ValueError("id")
    if not isinstance(raw, (bytes, bytearray)) or len(raw) < 32 or len(raw) > 1_500_000:
        raise ValueError("size")
    kind = _image_kind(bytes(raw))
    if not kind:
        raise ValueError("type")
    folder = os.path.join(PROFILE, "group_logos")
    os.makedirs(folder, exist_ok=True)
    for ext in _LOGO_EXT.values():
        old = os.path.join(folder, group_id + ext)
        if os.path.isfile(old):
            try:
                os.remove(old)
            except OSError:
                pass
    name = group_id + _LOGO_EXT[kind]
    with open(os.path.join(folder, name), "wb") as handle:
        handle.write(raw)
    return name


def _clean_star_thumb(value):
    text = str(value or "").strip()[:1500]
    if text.startswith("https://") or text.startswith("http://127.0.0.1:") or text.startswith("/api/"):
        if _is_video_url(text):
            return ""
        return text
    return ""


def _clean_star_favs(raw):
    cleaned = []
    seen = set()
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        ident = str(entry.get("id") or "").strip()[:80]
        name = re.sub(r"\s+", " ", str(entry.get("name") or "")).strip()[:120]
        if not ident or not name or ident in seen:
            continue
        seen.add(ident)
        cleaned.append({"id": ident, "name": name, "thumb": _clean_star_thumb(entry.get("thumb"))})
        if len(cleaned) >= 400:
            break
    return cleaned


_tube_consumption_service = None
_tube_consumption_lock = threading.Lock()


def _tube_consumption():
    global _tube_consumption_service
    with _tube_consumption_lock:
        if _tube_consumption_service is None:
            _tube_consumption_service = tube_consumption.ConsumptionStore(PROFILE)
        return _tube_consumption_service


def _tube_model_lookup(name):
    raw = _star_raw("", name)
    if not isinstance(raw, dict):
        return None
    result = dict(raw)
    for key in ("hair", "eyes", "build", "cup", "breast_type"):
        result[key] = _label_text(key, raw.get(key))
    born = _star_date(raw.get("birth_date"))
    if born:
        result["birth_date"] = born.isoformat()
    return result


def read_ui():
    data = {"pages": 3, "perPage": 36, "tile": "s", "view": "grid", "autoplay": True, "previews": 16, "favorites": [], "hiddenSites": [], "recent": [], "saved": [], "follows": [], "history": [], "events": [], "groups": [], "starFavs": []}
    if os.path.exists(UI_PATH):
        try:
            stored = json.load(open(UI_PATH, encoding="utf-8"))
            if isinstance(stored, dict):
                data.update(stored)
        except (OSError, ValueError):
            pass
    data["pages"] = max(1, min(20, int(data.get("pages") or 1)))
    try:
        data["previews"] = int(data.get("previews") or 16)
    except (TypeError, ValueError):
        data["previews"] = 16
    if data["previews"] not in (4, 8, 12, 16, 24, 32, 48, 64, 96, 128, 999):
        data["previews"] = 16
    data["perPage"] = _clamp_per_page(data.get("perPage") or 36)
    data["tile"] = _clamp_tile(data.get("tile") or "s")
    data["favorites"] = [str(name) for name in data.get("favorites") or []][:80]
    hidden = data.get("hiddenSites")
    data["hiddenSites"] = list(dict.fromkeys(name for name in (hidden if isinstance(hidden, list) else [])
                                           if isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", name)
                                           and name not in media_library.LIVE_SITES))[:2000]
    data["recent"] = [str(name) for name in data.get("recent") or []][:12]
    data["saved"] = _clean_entries(data.get("saved"), 200)
    data["follows"] = _clean_entries(data.get("follows"), 200)
    data["groups"] = _clean_groups(data.get("groups"))
    data["starFavs"] = _clean_star_favs(data.get("starFavs"))
    data["history"] = _clean_entries(data.get("history"), 400)
    data["events"] = _clean_events(data.get("events"), 2000)
    data["stats"] = _personal_stats(data)
    data["downloadFolder"] = _download_folder_text(data.get("downloadFolder"))
    folders = []
    seen_folders = set()
    for item in data.get("downloadFolders") or []:
        text = _download_folder_text(item)
        key = text.casefold()
        if text and key not in seen_folders:
            seen_folders.add(key)
            folders.append(text)
    data["downloadFolders"] = folders[:8]
    return data


def _clean_events(entries, limit):
    cleaned = []
    for entry in entries or []:
        if not isinstance(entry, dict) or not entry.get("title") and not entry.get("url"):
            continue
        try:
            hour = int(entry.get("hour"))
        except (TypeError, ValueError):
            hour = -1
        try:
            weekday = int(entry.get("weekday"))
        except (TypeError, ValueError):
            weekday = -1
        query = str(entry.get("url") or "")
        query = query.split("?", 1)[-1] if query.startswith("plugin:") else query.lstrip("?")
        provider = dict(urllib.parse.parse_qsl(query)).get("website", "").lower()
        live = (provider in media_library.LIVE_SITES or str(entry.get("site") or "").lower() in media_library.LIVE_SITES
                or entry.get("scope") == "live" or entry.get("source") == "live" or entry.get("kind") in ("live", "cam", "multicam")
                or entry.get("mediaType") == "live" or entry.get("liveCam") is True)
        cleaned.append({
            "models": tube_consumption.labels(entry.get("models"), 24),
            "tags": tube_consumption.labels(entry.get("tags")),
            "categories": tube_consumption.labels(entry.get("categories")),
            "duration": tube_consumption.number(entry.get("duration"), high=604800),
            "eventId": str(entry.get("eventId") or "")[:90],
            "scope": "live" if live else "tube",
            "source": entry.get("source") if entry.get("source") in ("player", "multitube") else "legacy",
            "thumb": _clean_star_thumb(entry.get("thumb")),
            "kind": "play" if entry.get("kind") != "open" else "open",
            "title": str(entry.get("title") or "")[:180],
            "url": str(entry.get("url") or "")[:800],
            "site": str(entry.get("site") or "")[:80],
            "category": str(entry.get("category") or "")[:120],
            "performer": str(entry.get("performer") or "")[:120],
            "hour": hour,
            "weekday": weekday,
            "at": str(entry.get("at") or "")[:32],
        })
        if len(cleaned) >= limit:
            break
    return cleaned


def _ranked(counts, limit=8):
    return [{"label": label, "count": count} for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])) if label][:limit]


def _personal_stats(data):
    events = [entry for entry in (data.get("events") or []) if entry.get("scope") != "live"]
    plays = [entry for entry in events if entry.get("kind") != "open"]
    counts = {}
    for entry in plays:
        site = entry.get("site") or ""
        if site:
            counts[site] = counts.get(site, 0) + 1
    hours = [0] * 24
    weekdays = [0] * 7
    titles, categories, performers, days = {}, {}, {}, {}
    genres = {}
    genre_of = {}
    try:
        for site in _catalog_sites():
            genre_of[site["id"]] = site.get("content") or []
    except Exception:
        genre_of = {}
    names = ["Sonntag", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag"]
    for entry in plays:
        hour = entry.get("hour")
        if isinstance(hour, int) and 0 <= hour <= 23:
            hours[hour] += 1
        weekday = entry.get("weekday")
        if isinstance(weekday, int) and 0 <= weekday <= 6:
            weekdays[weekday] += 1
        if entry.get("title"):
            titles[entry["title"]] = titles.get(entry["title"], 0) + 1
        if entry.get("category"):
            categories[entry["category"]] = categories.get(entry["category"], 0) + 1
        if entry.get("performer"):
            performers[entry["performer"]] = performers.get(entry["performer"], 0) + 1
        day = (entry.get("at") or "")[:10]
        if day:
            days[day] = days.get(day, 0) + 1
        for genre in genre_of.get(entry.get("site") or "", []):
            genres[genre] = genres.get(genre, 0) + 1
    for entry in events:
        if entry.get("kind") == "open" and entry.get("category"):
            categories[entry["category"]] = categories.get(entry["category"], 0) + 1
    peak_hour = hours.index(max(hours)) if any(hours) else None
    peak_day = weekdays.index(max(weekdays)) if any(weekdays) else None
    return {
        "watched": len(plays),
        "opens": sum(1 for entry in events if entry.get("kind") == "open"),
        "saved": len(data.get("saved") or []),
        "follows": len(data.get("follows") or []),
        "sites": len(data.get("favorites") or []),
        "top": [{"site": name, "count": count} for name, count in sorted(counts.items(), key=lambda item: -item[1])[:8]],
        "titles": _ranked(titles),
        "categories": _ranked(categories),
        "performers": _ranked(performers),
        "genres": _ranked(genres),
        "hours": [{"label": "%02d Uhr" % hour, "count": count} for hour, count in enumerate(hours)],
        "weekdays": [{"label": names[index], "count": count} for index, count in enumerate(weekdays)],
        "days": _ranked(days, 14),
        "peak_hour": None if peak_hour is None else "%02d Uhr" % peak_hour,
        "peak_day": None if peak_day is None else names[peak_day],
    }


def _clean_entries(entries, limit):
    cleaned = []
    seen = set()
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        url = str(entry.get("url") or "")[:800]
        if not url or url in seen:
            continue
        seen.add(url)
        cleaned.append({
            "title": str(entry.get("title") or "Eintrag")[:180],
            "mediaType": media_library.saved_kind(url, entry.get("mediaType")),
            "extension": re.sub(r"[^a-z0-9]", "", str(entry.get("extension") or "").lower())[:12],
            "url": url,
            "thumb": str(entry.get("thumb") or "")[:1500],
            "site": str(entry.get("site") or "")[:80],
            "plot": str(entry.get("plot") or "")[:180],
            "categories": _clean_labels(entry.get("categories")),
        })
        if len(cleaned) >= limit:
            break
    return cleaned


def _toggle_entries(data, key, entry, on):
    url = str((entry or {}).get("url") or "")
    items = [item for item in data[key] if item.get("url") != url]
    if on and url:
        items.insert(0, entry)
    data[key] = items


def _hex_color(value, fallback):
    text = str(value or "").strip()
    return text if re.fullmatch(r"#[0-9a-fA-F]{6}", text) else fallback


def _clamp_int(value, low, high, fallback):
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        number = fallback
    return max(low, min(high, number))


def _clamp_float(value, low, high, fallback):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = fallback
    return max(low, min(high, round(number, 2)))


def _theme_flag(raw, key, default):
    if key not in raw:
        return default
    return bool(raw.get(key))


def _clean_theme(raw):
    raw = raw or {}
    fonts = {"Segoe UI", "Arial", "Verdana", "Tahoma", "Georgia", "Palatino Linotype", "Cambria", "Trebuchet MS", "Consolas", "Candara"}
    menus = {"home", "sites", "search", "vault", "smart", "stars", "continue", "downloads", "offline", "collections", "profile", "stats", "multi", "bookmarks", "live"}
    homes = {"recent", "favs", "follows", "saved"}
    fact_keys = ["site", "duration", "views", "when", "rating", "quality", "about", "stars", "categories", "tags"]
    action_keys = ["save", "group", "multi", "follow"]
    speeds = {"0.5", "0.75", "1", "1.25", "1.5", "1.75", "2"}
    photo = str(raw.get("photo") or "").strip()
    if not photo.startswith("http://") and not photo.startswith("https://"):
        photo = ""
    logo = str(raw.get("logo") or "").strip().lower()
    if not _BRAND_FILE.fullmatch(logo) or not logo.startswith("logo."):
        logo = ""
    wall_mode = "menu" if raw.get("wallMode") == "menu" else "all"
    walls = {}
    for key, value in (raw.get("walls") or {}).items():
        if key not in _BRAND_IDS or key == "logo":
            continue
        name = str(value or "").strip().lower()
        if _BRAND_FILE.fullmatch(name) and name.startswith(key + "."):
            walls[key] = name
    wall_stamps = {}
    for key, value in (raw.get("wallStamps") or {}).items():
        if key in walls:
            wall_stamps[key] = _clamp_int(value, 0, 4_000_000_000, 0)
    labels = {}
    for key, value in (raw.get("labels") or {}).items():
        if key in menus:
            labels[key] = str(value or "").strip()[:40]
    if "facts" in raw:
        facts = [item for item in (raw.get("facts") or []) if item in fact_keys]
    else:
        facts = list(fact_keys)
    if "actions" in raw:
        actions = [item for item in (raw.get("actions") or []) if item in action_keys]
    else:
        actions = list(action_keys)
    speed = str(raw.get("speed") if raw.get("speed") is not None else "1")
    if speed not in speeds:
        speed = "1"
    cardbg = str(raw.get("cardbg") or "").strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", cardbg):
        cardbg = ""
    start = raw.get("start") if raw.get("start") in ("home", "sites", "bookmarks", "last") else "home"
    scrub_size = raw.get("scrubSize") if raw.get("scrubSize") in ("s", "m", "l") else "m"
    quality = raw.get("quality") if raw.get("quality") in ("high", "standard", "low", "auto") else "auto"
    cleaned = {
        "bg": _hex_color(raw.get("bg"), "#080807"),
        "panel": _hex_color(raw.get("panel"), "#141310"),
        "aside": _hex_color(raw.get("aside"), "#050505"),
        "line": _hex_color(raw.get("line"), "#3d3525"),
        "text": _hex_color(raw.get("text"), "#f4efe5"),
        "muted": _hex_color(raw.get("muted"), "#b2a894"),
        "accent": _hex_color(raw.get("accent"), "#d8b56a"),
        "grad2": _hex_color(raw.get("grad2"), "#1c170e"),
        "grad": bool(raw.get("grad")),
        "photo": photo[:400],
        "logo": logo,
        "logoStamp": _clamp_int(raw.get("logoStamp"), 0, 4_000_000_000, 0) if logo else 0,
        "wallMode": wall_mode,
        "walls": walls,
        "wallStamps": wall_stamps,
        "font": raw.get("font") if raw.get("font") in fonts else "Segoe UI",
        "scale": _clamp_int(raw.get("scale"), 13, 22, 16),
        "radius": _clamp_int(raw.get("radius"), 0, 24, 10),
        "side": _clamp_int(raw.get("side"), 160, 340, 268),
        "card": _clamp_int(raw.get("card"), 140, 600, 190),
        "thumb": _clamp_int(raw.get("thumb"), 70, 500, 110),
        "layout": "right" if raw.get("layout") == "right" else "left",
        "density": "compact" if raw.get("density") == "compact" else "normal",
        "showSearch": bool(raw.get("showSearch", True)),
        "hide": [item for item in (raw.get("hide") or []) if item in menus][:20],
        "labels": labels,
        "home": [item for item in (raw.get("home") or []) if item in homes],
        "gap": _clamp_int(raw.get("gap"), 6, 28, 12),
        "lines": _clamp_int(raw.get("lines"), 1, 4, 4),
        "shadow": _theme_flag(raw, "shadow", True),
        "lift": _theme_flag(raw, "lift", False),
        "player": _clamp_int(raw.get("player"), 50, 92, 78),
        "scrub": _theme_flag(raw, "scrub", True),
        "scrubSize": scrub_size,
        "facts": facts,
        "badges": _theme_flag(raw, "badges", True),
        "actions": actions,
        "start": start,
        "speed": speed,
        "volume": _clamp_float(raw.get("volume"), 0, 1, 1),
        "mute": _theme_flag(raw, "mute", False),
        "loop": _theme_flag(raw, "loop", False),
        "quality": quality,
        "shortcuts": _clamp_int(raw.get("shortcuts"), 4, 24, 12),
        "clock": _theme_flag(raw, "clock", False),
        "greet": _theme_flag(raw, "greet", False),
        "uploader": _theme_flag(raw, "uploader", True),
        "plot": _theme_flag(raw, "plot", True),
        "cardbg": cardbg,
    }

    cleaned["design"] = settings_design.clean_design(raw.get("design"))
    return cleaned


def write_ui(patch):
    with settings_design.LOCK:
        return _write_ui_impl(patch)


def _write_ui_impl(patch):
    data = read_ui()
    if isinstance(patch.get("theme"), dict):
        revision = int(data.get("themeRevision") or 0)
        if "expectedThemeRevision" in patch and patch["expectedThemeRevision"] != revision:
            raise settings_design.Conflict("Die Einstellungen wurden in einem anderen Fenster geändert. Dein Entwurf bleibt erhalten. Bitte den gespeicherten Stand laden oder den Entwurf als Design sichern.")
        data["themeRevision"] = revision + 1
    for key in ("pages", "perPage", "tile", "view", "autoplay", "previews", "multi"):
        if key in patch:
            data[key] = patch[key]
    if isinstance(patch.get("theme"), dict):
        data["theme"] = _clean_theme(patch.get("theme"))
    if "downloadFolder" in patch or "downloadFolders" in patch:
        if "downloadFolder" in patch:
            data["downloadFolder"] = _download_folder_text(patch.get("downloadFolder"))
        if "downloadFolders" in patch:
            data["downloadFolders"] = patch.get("downloadFolders")
        folder = _download_folder_text(data.get("downloadFolder"))
        folders = []
        seen_folders = set()
        for item in data.get("downloadFolders") or []:
            text = _download_folder_text(item)
            key = text.casefold()
            if text and key not in seen_folders:
                seen_folders.add(key)
                folders.append(text)
        data["downloadFolder"] = folder
        data["downloadFolders"] = folders[:8]
    if "favorite" in patch:
        name = str(patch["favorite"] or "")
        favs = [item for item in data["favorites"] if item != name]
        if patch.get("on") and name:
            favs.insert(0, name)
        data["favorites"] = favs[:80]
    if "hideSite" in patch:
        name = str(patch["hideSite"] or "")
        if re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", name) and name not in media_library.LIVE_SITES:
            hidden = [item for item in data["hiddenSites"] if item != name]
            if patch.get("on"):
                hidden.insert(0, name)
            data["hiddenSites"] = hidden[:2000]
    if "save" in patch:
        _toggle_entries(data, "saved", patch.get("save") or {}, patch.get("on"))
    if "follow" in patch:
        _toggle_entries(data, "follows", patch.get("follow") or {}, patch.get("on"))
    if "groups" in patch:
        data["groups"] = _clean_groups(patch.get("groups"))
        _prune_group_logos(data["groups"])
        debug_log("server", "groups", "gespeichert", {"n": len(data["groups"])})
    if "starFav" in patch:
        entry = patch.get("starFav") if isinstance(patch.get("starFav"), dict) else {}
        ident = str(entry.get("id") or "").strip()
        favs = [item for item in (data.get("starFavs") or []) if str(item.get("id") or "") != ident]
        if patch.get("on") and ident and str(entry.get("name") or "").strip():
            favs.insert(0, {"id": ident, "name": entry.get("name"), "thumb": entry.get("thumb") or ""})
        data["starFavs"] = _clean_star_favs(favs)
    if patch.get("forget"):
        target = str(patch.get("forget"))
        for key in ("saved", "follows", "history"):
            data[key] = [item for item in data[key] if item.get("url") != target]
    if isinstance(patch.get("offline"), dict):
        current = data.get("offline") if isinstance(data.get("offline"), dict) else {}
        for kind in _OFFLINE_KINDS:
            if kind in patch["offline"]:
                current[kind] = bool(patch["offline"][kind])
        data["offline"] = current
        _offline_flag_cache["mtime"] = None
    if "watch" in patch:
        entries = _clean_events([patch.get("watch")], 1)
        entry = entries[0] if entries else {}
        if entry and entry.get("scope") != "live":
            data.setdefault("events", [])
            data["events"].insert(0, entry)
            data["events"] = data["events"][:2000]
            if entry.get("kind") != "open" and entry.get("url"):
                data["history"] = [item for item in data["history"] if item.get("url") != entry.get("url")]
                data["history"].insert(0, entry)
    data["pages"] = max(1, min(20, int(data.get("pages") or 1)))
    data["view"] = "list" if data.get("view") == "list" else "grid"
    data["autoplay"] = bool(data.get("autoplay"))
    try:
        data["multi"] = max(1, min(6, int(data.get("multi") or 4)))
    except (TypeError, ValueError):
        data["multi"] = 4
    data["perPage"] = _clamp_per_page(data.get("perPage") or 36)
    data["tile"] = _clamp_tile(data.get("tile") or "s")
    with open(UI_PATH, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    return read_ui()


def remember_site(name):
    if not name or name in ("global_search",):
        return
    data = read_ui()
    recent = [item for item in data["recent"] if item != name]
    recent.insert(0, name)
    data["recent"] = recent[:12]
    with open(UI_PATH, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def item_role(item):
    title = (item.get("title") or "").lower()
    if item.get("folder") and (any(word in title for word in ("next page", "nächste", "weiter", ">>")) or title.strip() in ("next", "more")):
        return "next"
    if not item.get("folder"):
        return (item.get("media") or {}).get("kind") or "video"
    if (item.get("media") or {}).get("kind") == "gallery":
        return "gallery"
    for role, words in NAV_WORDS.items():
        if any(word in title for word in words):
            return role
    return "folder"


def plugin_query(url):
    marker = "plugin://plugin.video.adulthideout/"
    if not url:
        return ""
    if url.startswith(marker):
        return url[len(marker):].lstrip("?")
    return url.lstrip("?")


def _execute_plugin(query):
    main = addon_main()
    xbmcplugin._reset()
    xbmc._player_state.update(playing=False, file="")
    xbmcgui._notifications.clear()
    xbmcgui._redirects.clear()
    params = dict(urllib.parse.parse_qsl(query, keep_blank_values=True))
    typed = params.get("query") or params.get("q") or params.get("search") or ""
    xbmcgui._keyboard_override["text"] = typed or None
    sys.argv = [PLUGIN, "1", ("?" + query) if query else ""]
    error = ""
    try:
        if not media_library.virtual_directory(params, ADDON, main.load_single_website):
            main.handle_routing()
    except Exception:
        error = traceback.format_exc()
        print(error)
    notes, redirects = xbmcgui.drain_ui()
    xbmcgui._keyboard_override["text"] = None
    items = [item_payload(entry) for entry in xbmcplugin._state["items"]]
    for item in items:
        item["role"] = item_role(item)
    if params.get("mode") == "2" and params.get("url", "") in ("", "BOOTSTRAP"):
        section = media_library.photo_section(params.get("website", ""), ADDON)
        if section:
            items.insert(0, section)
    resolved = None
    raw = xbmcplugin._state["resolved"]
    if raw and raw.get("succeeded"):
        snap = raw["item"]
        resolved = {
            "path": snap.get("path") or "",
            "mime": snap.get("mimetype") or "",
            "title": clean_label(snap.get("label") or ""),
            "referer": (snap.get("properties") or {}).get("Referer")
            or (snap.get("properties") or {}).get("referer")
            or "",
            "sources": _source_list((snap.get("properties") or {}).get("web_sources") or ""),
        }
        facts = _clean_facts((snap.get("properties") or {}).get("web_facts") or "")
        if facts:
            resolved["facts"] = facts
    elif xbmc._player_state.get("playing") and xbmc._player_state.get("file"):
        resolved = {"path": xbmc._player_state["file"], "mime": "", "title": "", "referer": ""}
    return {
        "items": items,
        "category": xbmcplugin._state.get("category") or "",
        "notifications": notes,
        "redirect": redirects[-1] if redirects else "",
        "error": error,
        "resolved": resolved,
    }


CACHE_DIR = os.path.join(PROFILE, "cache")
LIST_TTL = 6 * 60 * 60
_catalog_static = {"stamp": None, "sites": None}


def cache_key(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_website_version_cache = {}


def website_cache_version(name):
    """Cache key part. Website modules may set cache_version. The default is 1."""
    name = (name or "").strip().lower()
    if not name:
        return "1"
    cached = _website_version_cache.get(name)
    if cached is not None:
        return cached
    version = "1"
    if re.fullmatch(r"[a-z0-9_]+", name):
        try:
            module = importlib.import_module("resources.websites." + name)
        except Exception:
            module = None
        if module is not None:
            for value in vars(module).values():
                if isinstance(value, type) and str(getattr(value, "name", "") or "") == name:
                    version = str(getattr(value, "cache_version", "1") or "1")
                    break
    _website_version_cache[name] = version
    return version


def _signed_media_stale(payload):
    now = time.time()
    checked = 0
    stale = 0
    for item in payload.get("items") or []:
        sources = [item.get("clip") or ""]
        sources.extend(item.get("preview") or [])
        for source in sources:
            match = re.search(r"(?:exp|validto)=(\d+)", urllib.parse.unquote(source or ""))
            if not match:
                continue
            checked += 1
            if int(match.group(1)) < now + 90:
                stale += 1
    return bool(checked) and stale * 2 >= checked


def read_list_cache(key, ttl=None):
    if not offline_keep("lists"):
        return None
    path = os.path.join(CACHE_DIR, "lists", key + ".json")
    if not os.path.isfile(path):
        return None
    if time.time() - os.path.getmtime(path) > (ttl or LIST_TTL):
        return None
    try:
        data = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return None
    data["cached"] = True
    data["cached_age"] = int(time.time() - os.path.getmtime(path))
    return data


def write_list_cache(key, data):
    if not offline_keep("lists"):
        return
    if data.get("error") or data.get("resolved") or not data.get("items"):
        return
    folder = os.path.join(CACHE_DIR, "lists")
    os.makedirs(folder, exist_ok=True)
    stored = dict(data)
    stored.pop("cached", None)
    with open(os.path.join(folder, key + ".json"), "w", encoding="utf-8") as handle:
        json.dump(stored, handle, ensure_ascii=False)


_model_sync = {"total": 0, "done": 0, "failed": 0, "running": False}


def model_sync_status():
    return dict(_model_sync)


_LABEL_GROUPS = {
    "gender": {"f": "weiblich", "female": "weiblich", "m": "männlich", "male": "männlich", "ts": "trans", "trans": "trans", "t": "trans"},
    "country": {
        "us": "USA", "united states": "USA", "usa": "USA", "ru": "Russland", "russia": "Russland",
        "de": "Deutschland", "germany": "Deutschland", "uk": "Großbritannien", "united kingdom": "Großbritannien", "gb": "Großbritannien", "england": "Großbritannien",
        "cz": "Tschechien", "czech republic": "Tschechien", "czechia": "Tschechien", "czech": "Tschechien",
        "jp": "Japan", "japan": "Japan", "fr": "Frankreich", "france": "Frankreich", "ca": "Kanada", "canada": "Kanada",
        "br": "Brasilien", "brazil": "Brasilien", "es": "Spanien", "spain": "Spanien", "it": "Italien", "italy": "Italien",
        "au": "Australien", "australia": "Australien", "pl": "Polen", "poland": "Polen", "ua": "Ukraine", "ukraine": "Ukraine",
        "hu": "Ungarn", "hungary": "Ungarn", "ro": "Rumänien", "romania": "Rumänien", "nl": "Niederlande", "netherlands": "Niederlande",
        "se": "Schweden", "sweden": "Schweden", "co": "Kolumbien", "colombia": "Kolumbien", "mx": "Mexiko", "mexico": "Mexiko",
        "ar": "Argentinien", "argentina": "Argentinien",
    },
    "hair": {"blonde": "blond", "brunette": "braun", "black": "schwarz", "red": "rot", "auburn": "rotbraun", "brown": "braun"},
    "eyes": {"blue": "blau", "brown": "braun", "green": "grün", "hazel": "bernstein", "grey": "grau", "gray": "grau", "black": "schwarz"},
    "ethnicity": {
        "caucasian": "europäisch", "white": "europäisch", "asian": "asiatisch", "latina": "lateinamerikanisch", "latin": "lateinamerikanisch",
        "hispanic": "lateinamerikanisch", "ebony": "schwarz", "black": "schwarz", "mixed": "gemischt", "middle eastern": "nahöstlich",
        "indian": "indisch", "arab": "arabisch",
    },
    "build": {"slim": "schlank", "athletic": "athletisch", "curvy": "kurvig", "average": "durchschnittlich", "muscular": "muskulös", "bbw": "vollschlank"},
    "breast": {"natural": "natürlich", "enhanced": "vergrößert", "fake": "vergrößert"},
}
_COUNTRY_FLAGS = {
    "usa": "🇺🇸", "russland": "🇷🇺", "deutschland": "🇩🇪", "großbritannien": "🇬🇧", "tschechien": "🇨🇿",
    "japan": "🇯🇵", "frankreich": "🇫🇷", "kanada": "🇨🇦", "brasilien": "🇧🇷", "spanien": "🇪🇸", "italien": "🇮🇹",
    "australien": "🇦🇺", "polen": "🇵🇱", "ukraine": "🇺🇦", "ungarn": "🇭🇺", "rumänien": "🇷🇴", "niederlande": "🇳🇱",
    "schweden": "🇸🇪", "kolumbien": "🇨🇴", "mexiko": "🇲🇽", "argentinien": "🇦🇷", "china": "🇨🇳", "südkorea": "🇰🇷",
    "korea": "🇰🇷", "indien": "🇮🇳", "thailand": "🇹🇭", "philippinen": "🇵🇭", "venezuela": "🇻🇪", "slowakei": "🇸🇰",
    "bulgarien": "🇧🇬", "serbien": "🇷🇸", "kroatien": "🇭🇷", "österreich": "🇦🇹", "schweiz": "🇨🇭", "belgien": "🇧🇪",
    "portugal": "🇵🇹", "irland": "🇮🇪", "norwegen": "🇳🇴", "dänemark": "🇩🇰", "finnland": "🇫🇮", "griechenland": "🇬🇷",
    "türkei": "🇹🇷", "israel": "🇮🇱", "südafrika": "🇿🇦", "neuseeland": "🇳🇿",
    "slovakia": "🇸🇰", "bulgaria": "🇧🇬", "serbia": "🇷🇸", "croatia": "🇭🇷", "austria": "🇦🇹",
    "switzerland": "🇨🇭", "belgium": "🇧🇪", "portugal": "🇵🇹", "ireland": "🇮🇪", "norway": "🇳🇴",
    "denmark": "🇩🇰", "finland": "🇫🇮", "greece": "🇬🇷", "turkey": "🇹🇷", "south africa": "🇿🇦",
    "new zealand": "🇳🇿", "china": "🇨🇳", "india": "🇮🇳", "thailand": "🇹🇭", "philippines": "🇵🇭",
    "venezuela": "🇻🇪", "korea": "🇰🇷", "south korea": "🇰🇷",
}


def _label_text(field, value):
    text = str(value or "").strip()
    if not text or text.lower() in ("none", "null", "unknown", "n/a", "-", "all"):
        return ""
    mapping = _LABEL_GROUPS.get(field) or {}
    return mapping.get(text.lower(), text)


def _country_flag(label):
    return _COUNTRY_FLAGS.get(str(label or "").lower(), "")


def _merge_labels(facts):
    groups = _LABEL_GROUPS
    flags = _COUNTRY_FLAGS
    for field, mapping in groups.items():
        totals = {}
        for row in facts.get(field) or []:
            label = mapping.get(str(row.get("label") or "").lower(), row.get("label"))
            totals[label] = totals.get(label, 0) + int(row.get("count") or 0)
        ranked = []
        for label, count in sorted(totals.items(), key=lambda item: -item[1]):
            item = {"label": label, "count": count}
            if field == "country":
                item["flag"] = flags.get(str(label).lower(), "")
            ranked.append(item)
        facts[field] = ranked
    return facts


def _top_counts(rows, field, limit=8):
    counts = {}
    for row in rows:
        value = str(row.get(field) or "").strip()
        if not value or value.lower() in ("none", "null", "unknown"):
            continue
        counts[value] = counts.get(value, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return [{"label": label, "count": count} for label, count in ranked]


_OFFLINE_KINDS = ("stats", "catalog", "stars", "terms", "lists", "images")
_offline_flag_cache = {"mtime": None, "flags": None}
_terms_memory = {}


def offline_keep(kind):
    """Ob diese Kopie auf der Platte bleiben soll. Standard ist an."""
    flags = _offline_flag_cache
    try:
        mtime = os.path.getmtime(UI_PATH)
    except OSError:
        mtime = None
    if flags.get("mtime") != mtime or not flags.get("flags"):
        current = {name: True for name in _OFFLINE_KINDS}
        if mtime is not None:
            try:
                stored = json.load(open(UI_PATH, encoding="utf-8")).get("offline") or {}
            except (OSError, ValueError):
                stored = {}
            if isinstance(stored, dict):
                for name in _OFFLINE_KINDS:
                    if name in stored:
                        current[name] = bool(stored[name])
        flags["mtime"] = mtime
        flags["flags"] = current
    return bool(flags["flags"].get(kind, True))


def library_facts(force=False):
    path = os.path.join(CACHE_DIR, "library_facts.json")
    facts = None
    index_path = os.path.join(ADDON, "resources", "data", "star_index.json.gz")
    stamp = int(os.path.getmtime(index_path)) if os.path.isfile(index_path) else 0
    keep = offline_keep("stats")
    if keep and not force and os.path.isfile(path):
        try:
            stored = json.load(open(path, encoding="utf-8"))
            if stored.get("stamp") == stamp and stored.get("version") == 2:
                facts = stored
        except (OSError, ValueError):
            facts = None
    if facts is None:
        import gzip
        rows = []
        if os.path.isfile(index_path):
            payload = json.load(gzip.open(index_path, "rt", encoding="utf-8"))
            rows = payload.get("performers") or []
        photos = sum(1 for row in rows if str(row.get("thumb") or "").startswith("http"))
        movies = [int(row.get("movie_count") or 0) for row in rows]
        years = []
        for row in rows:
            try:
                years.append(int(row.get("birth_year")))
            except (TypeError, ValueError):
                pass
        heights = []
        height_bands = {}
        birth_decades = {}
        career_decades = {}
        tags = {}
        for row in rows:
            try:
                cm = int(row.get("height_cm") or 0)
            except (TypeError, ValueError):
                cm = 0
            if 120 <= cm <= 220:
                heights.append(cm)
                band = "%s–%s cm" % ((cm // 5) * 5, (cm // 5) * 5 + 4)
                height_bands[band] = height_bands.get(band, 0) + 1
            try:
                birth_decades["%ss" % ((int(row.get("birth_year")) // 10) * 10)] = birth_decades.get("%ss" % ((int(row.get("birth_year")) // 10) * 10), 0) + 1
            except (TypeError, ValueError):
                pass
            try:
                career_decades["%ss" % ((int(row.get("career_start_year")) // 10) * 10)] = career_decades.get("%ss" % ((int(row.get("career_start_year")) // 10) * 10), 0) + 1
            except (TypeError, ValueError):
                pass
            for tag in row.get("tags") or []:
                text = str(tag).replace("_", " ").strip()
                if text:
                    tags[text] = tags.get(text, 0) + 1
        facts = {
            "version": 2,
            "stamp": stamp,
            "performers": len(rows),
            "photos": photos,
            "movies": sum(movies),
            "avg_movies": round(sum(movies) / len(rows), 1) if rows else 0,
            "avg_height": round(sum(heights) / len(heights)) if heights else 0,
            "birth_min": min(years) if years else 0,
            "birth_max": max(years) if years else 0,
            "gender": _top_counts(rows, "gender", 8),
            "country": _top_counts(rows, "country", 30),
            "hair": _top_counts(rows, "hair", 12),
            "eyes": _top_counts(rows, "eyes", 12),
            "ethnicity": _top_counts(rows, "ethnicity", 12),
            "build": _top_counts(rows, "build", 12),
            "decade": _top_counts(rows, "decade", 12),
            "cup": _top_counts(rows, "cup", 16),
            "breast": _top_counts(rows, "breast_type", 8),
            "heights": _ranked(height_bands, 16),
            "birth_decades": _ranked(birth_decades, 12),
            "career_decades": _ranked(career_decades, 12),
            "tags": _ranked(tags, 20),
            "stars": [{"label": row.get("name") or "", "count": int(row.get("movie_count") or 0)} for row in sorted(rows, key=lambda row: -int(row.get("movie_count") or 0))[:15]],
        }
        if keep:
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(facts, handle, ensure_ascii=False)
    usage = read_ui()
    from ui_performance import directory_summary
    image_summary = directory_summary.get(os.path.join(CACHE_DIR, "images"))
    image_files, image_bytes = image_summary["files"], image_summary["bytes"]
    catalog = catalog_payload()
    content_counts = {}
    type_counts = {}
    for site in catalog.get("sites") or []:
        for key in site.get("content") or ["ohne Zuordnung"]:
            content_counts[key] = content_counts.get(key, 0) + 1
        for key in site.get("types") or ["ohne Zuordnung"]:
            type_counts[key] = type_counts.get(key, 0) + 1
    payload = _merge_labels(dict(facts))
    payload.update({
        "sites": len(catalog.get("sites") or []),
        "content": [{"label": key, "count": content_counts[key]} for key in sorted(content_counts, key=lambda item: -content_counts[item])],
        "types": [{"label": key, "count": type_counts[key]} for key in sorted(type_counts, key=lambda item: -type_counts[item])],
        "usage": usage.get("stats") or {},
        "recent_sites": len(usage.get("recent") or []),
        "images": model_sync_status(),
        "image_files": image_files,
        "image_mb": round(image_bytes / 1024 / 1024, 1) if image_bytes is not None else None,
        "image_pending": image_summary["running"],
        "image_count_error": bool(image_summary.get("error")),
    })
    return payload


def sync_model_portraits():
    if _model_sync["running"]:
        return
    _model_sync["running"] = True
    try:
        import gzip
        path = os.path.join(ADDON, "resources", "data", "star_index.json.gz")
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        urls = []
        seen = set()
        for row in payload.get("performers") or []:
            thumb = str(row.get("thumb") or "")
            if thumb.startswith("http") and thumb not in seen:
                seen.add(thumb)
                urls.append(thumb)
        _model_sync["total"] = len(urls)
        for url in urls:
            _store_image(url)
        for url in _collect_known_image_urls():
            if url not in seen:
                seen.add(url)
                _model_sync["total"] += 1
                _store_image(url)
    finally:
        _model_sync["running"] = False


def _store_image(url):
    try:
        load_image(url)
        _model_sync["done"] += 1
    except Exception:
        _model_sync["failed"] += 1


def _collect_known_image_urls():
    found = []
    roots = [
        os.path.join(ADDON, "resources", "data"),
        os.path.join(CACHE_DIR, "lists"),
    ]
    pattern = re.compile(r"https?://[^\"'\s<>]+?\.(?:jpg|jpeg|png|webp|gif|avif)(?:\?[^\"'\s<>]*)?", re.I)
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [name for name in dirs if name != "star_movies"]
            for name in files:
                path = os.path.join(dirpath, name)
                try:
                    if name.endswith(".gz"):
                        import gzip
                        text = gzip.open(path, "rt", encoding="utf-8", errors="ignore").read()
                    elif name.endswith((".json", ".xml", ".txt", ".html")):
                        text = open(path, "r", encoding="utf-8", errors="ignore").read()
                    else:
                        continue
                except (OSError, ValueError):
                    continue
                found.extend(pattern.findall(text))
    return found


def _cache_site_listings(seen):
    folder = os.path.join(ADDON, "resources", "websites")
    if not os.path.isdir(folder):
        return
    names = [name[:-3] for name in os.listdir(folder) if name.endswith(".py") and name != "__init__.py"]
    for name in names:
        while _user_busy.is_set():
            time.sleep(0.3)
        try:
            result = run_plugin("mode=2&website=%s&url=BOOTSTRAP" % urllib.parse.quote(name), 1)
        except Exception:
            continue
        for item in result.get("items") or []:
            thumb = item.get("thumb") or ""
            if "/api/image?url=" not in thumb:
                continue
            remote = urllib.parse.parse_qs(urllib.parse.urlparse(thumb).query).get("url", [""])[0]
            if remote and remote not in seen:
                seen.add(remote)
                _model_sync["total"] += 1
                _store_image(remote)


def warm_images(items):
    urls = []
    for item in items:
        thumb = item.get("thumb") or ""
        if "/api/image?url=" in thumb:
            urls.append(urllib.parse.parse_qs(urllib.parse.urlparse(thumb).query).get("url", [""])[0])
    if not urls:
        return

    def fetch():
        for url in urls:
            try:
                load_image(url)
            except Exception:
                continue

    threading.Thread(target=fetch, name="AHImageWarm", daemon=True).start()


def _is_video_url(url):
    """Echte Videodateien. Pornhub-Vorschaubilder enthalten .mp4, sind aber kleine JPEGs."""
    base = (url or "").split("|", 1)[0]
    path = urllib.parse.urlparse(base).path.lower()
    if "rs:fit" in path or "rs:fill" in path or "/thumb" in path:
        return False
    last = path.rsplit("/", 1)[-1]
    if last.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp")):
        return False
    return bool(_VIDEO_URL.search(path))


def _looks_like_media_file(data):
    if not data or len(data) < 12:
        return False
    if data[4:8] == b"ftyp":
        if data[8:12] in (b"avif", b"avis", b"mif1"):
            return False
        return True
    if data.startswith(b"\x1a\x45\xdf\xa3") or data.startswith(b"ID3") or data.startswith(b"FLV"):
        return True
    return False


_cam_fresh_images = {}
_cam_fresh_lock = threading.Lock()


def _cam_fresh_ok(url):
    text = str(url or "").lower()
    if not text.startswith("https://"):
        return False
    marks = (
        "chaturbate.com",
        "highwebmedia.com",
        "mmcdn.com",
        "stripchat.com",
        "strpst.com",
        "bongacams.com",
        "bcvcdn.com",
        "bgicdn.com",
        "camsoda.com",
        "cam4.com",
        "xcdnpro.com",
        "xlovecam.com",
        "wlresources.com",
    )
    return any(mark in text for mark in marks)


def _cam_fresh_get(url):
    now = time.time()
    with _cam_fresh_lock:
        hit = _cam_fresh_images.get(url)
        if hit and now - hit[0] < 0.4:
            return hit[1], hit[2]
        if hit:
            _cam_fresh_images.pop(url, None)
    return None


def _cam_fresh_put(url, data, mime):
    with _cam_fresh_lock:
        _cam_fresh_images[url] = (time.time(), data, mime)
        if len(_cam_fresh_images) > 24:
            for old in sorted(_cam_fresh_images, key=lambda item: _cam_fresh_images[item][0])[:8]:
                _cam_fresh_images.pop(old, None)


def load_image(url, fresh=False):
    if _is_video_url(url):
        raise ValueError("video")
    if fresh:
        cached = _cam_fresh_get(url)
        if cached:
            return cached
    keep = offline_keep("images")
    folder = os.path.join(CACHE_DIR, "images")
    digest = cache_key(url)
    path = os.path.join(folder, digest)
    kind_path = path + ".type"
    if keep and not fresh and os.path.isfile(path) and os.path.isfile(kind_path):
        with open(kind_path, "r", encoding="utf-8") as handle:
            mime = handle.read().strip() or "image/jpeg"
        if not mime.startswith("image/"):
            raise ValueError("not-image")
        with open(path, "rb") as handle:
            data = handle.read()
        if _looks_like_media_file(data):
            raise ValueError("video")
        return data, mime
    if not _image_slots.acquire(timeout=0.3):
        raise TimeoutError("image-busy")
    try:
        clean_url, extra = split_kodi_url(url)
        headers = {"User-Agent": extra.get("User-Agent") or "Mozilla/5.0"}
        for key in ("Referer", "Origin", "Cookie"):
            if extra.get(key):
                headers[key] = extra[key]
        host = (urllib.parse.urlparse(clean_url).hostname or "").lower()
        if host.endswith(".donmai.us") and not extra.get("User-Agent"):
            headers["User-Agent"] = "AdultHideout/1.0 (local)"
            headers.setdefault("Referer", "https://danbooru.donmai.us/")
        elif host.endswith(".e926.net") and not extra.get("User-Agent"):
            headers["User-Agent"] = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            )
        if host and not headers.get("Referer"):
            headers["Referer"] = "https://%s/" % host
        req = urllib.request.Request(clean_url, headers=headers)
        if _cam_fresh_ok(url):
            from live_cam_http import open_cam_media
            opened = open_cam_media(clean_url, headers, timeout=6)
        else:
            opened = urllib.request.urlopen(req, timeout=6)
        with closing(opened) as response:
            mime = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if mime.startswith("video/") or mime in ("application/vnd.apple.mpegurl", "application/x-mpegurl"):
                raise ValueError("video")
            data = response.read(32)
            if _looks_like_media_file(data):
                raise ValueError("video")
            data += response.read(500_000)
        image_magic = data.startswith((b"\xff\xd8", b"\x89PNG", b"GIF8", b"RIFF"))
        if not data or not (mime.startswith("image/") or image_magic):
            raise ValueError("not-image")
        if not mime.startswith("image/"):
            mime = "image/jpeg"
        if fresh:
            _cam_fresh_put(url, data, mime)
            return data, mime
        if keep:
            os.makedirs(folder, exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(data)
            with open(kind_path, "w", encoding="utf-8") as handle:
                handle.write(mime)
        return data, mime
    finally:
        _image_slots.release()


def run_plugin(query, depth=None, priority=False, preview=False):
    query = (query or "").lstrip("?")
    params = dict(urllib.parse.parse_qsl(query, keep_blank_values=True))
    if depth is None:
        depth = read_ui()["pages"] if params.get("mode") == "2" else 1
    depth = max(1, min(20, int(depth or 1)))
    if priority:
        _user_busy.set()
    try:
        if preview:
            return _run_plugin_locked(query, params, 1, preview=True)
        return _run_plugin_locked(query, params, depth)
    finally:
        if priority:
            _user_busy.clear()


def _one_plugin_page(query):
    # Eine langsame Liste darf die nächste nicht ewig aufhalten.
    if not _lock.acquire(timeout=2.5):
        return None
    try:
        return _execute_plugin(query)
    finally:
        _lock.release()


def _run_plugin_locked(query, params, depth, preview=False):
    result = _one_plugin_page(query)
    if result is None:
        return {"items": [], "busy": True, "error": "busy", "pages": 0}
    if params.get("website") and not preview:
        with _lock:
            remember_site(params.get("website"))
    seen = {item["url"] for item in result["items"]}
    extra = 1
    while extra < depth:
        nxt = next((item for item in result["items"] if item["role"] == "next"), None)
        if not nxt:
            break
        result["items"] = [item for item in result["items"] if item is not nxt]
        more = _one_plugin_page(plugin_query(nxt["url"]))
        if more is None or (more.get("error") and not more.get("items")):
            break
        for item in more["items"]:
            if item["url"] in seen:
                continue
            seen.add(item["url"])
            result["items"].append(item)
        extra += 1
    result["pages"] = extra
    if not preview:
        enrich_listing(params.get("website") or "", [item for item in result["items"] if item.get("role") == "video"])
        enrich_star_movies(query, result["items"])
    return result


def _thumb_keys(name):
    name = (name or "").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", name).strip("-")
    keys = [name, name.replace(" ", "-"), slug]
    reduced = slug
    for _ in range(4):
        for suffix in ("-lesbian", "-gay", "-straight", "-uncensored", "-1"):
            if reduced.endswith(suffix):
                reduced = reduced[: -len(suffix)].strip("-")
                keys.append(reduced)
    return [key for key in keys if key]


def pornhub_category_thumbs():
    path = os.path.join(CACHE_DIR, "pornhub_categories.json")
    if os.path.isfile(path) and time.time() - os.path.getmtime(path) < 7 * 24 * 3600:
        try:
            stored = json.load(open(path, encoding="utf-8"))
            if stored.get("version") == 2 and stored.get("thumbs"):
                return stored["thumbs"]
        except (OSError, ValueError):
            pass
    headers = {"User-Agent": "Mozilla/5.0", "Cookie": "accessAgeDisclaimerPH=1; age_verified=1"}
    html = ""
    for page in ("https://www.pornhub.com/categories", "https://www.pornhub.com/gay/categories"):
        req = urllib.request.Request(page, headers=headers)
        html += "\n" + urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "replace")
    thumbs = {}
    pattern = re.compile(
        r'<img\b[^>]*?\bsrc="(https://[^"]+)"[^>]*?\balt="([^"]*?Porn Category)"',
        re.I,
    )
    for src, alt in pattern.findall(html):
        name = re.sub(r"\s+porn category$", "", alt, flags=re.I).strip().lower()
        for key in _thumb_keys(name):
            if key:
                thumbs[key] = src
    api_req = urllib.request.Request("https://www.pornhub.com/webmasters/categories", headers=headers)
    api = json.loads(urllib.request.urlopen(api_req, timeout=40).read().decode("utf-8", "replace"))
    missing = []
    for cat in api.get("categories") or []:
        name = (cat.get("category") or "").lower()
        if name and not any(thumbs.get(key) for key in _thumb_keys(name)):
            missing.append(name)

    def first_thumb(name):
        url = "https://www.pornhub.com/webmasters/search?category=%s&ordering=newest" % urllib.parse.quote(name)
        try:
            payload = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=25).read().decode("utf-8", "replace"))
        except Exception:
            return name, ""
        videos = payload.get("videos") or []
        if not videos:
            return name, ""
        return name, videos[0].get("default_thumb") or ""

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as pool:
        for name, src in pool.map(first_thumb, missing):
            if src:
                for key in _thumb_keys(name):
                    thumbs[key] = src
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"version": 2, "thumbs": thumbs}, handle)
    threading.Thread(target=lambda: [load_image(url) for url in list(dict.fromkeys(thumbs.values()))[:240]], daemon=True).start()
    return thumbs


_star_thumbs = None
_star_index = None
_star_index_lock = threading.Lock()
_people_gen = 0
_people_card_cache = {"gen": -1, "cards": None}
_people_positions = {"list":None,"size":-1,"positions":{}}
_av_wake = threading.Event()
_av_net = threading.Lock()
_av_run = {"running": False, "started": False}
_av_letters = {}
_av_letter_wait = {}
_av_letter_lock = threading.Lock()
_star_trend = {"at": 0, "items": None, "ok": False}
_star_trend_lock = threading.Lock()
_star_extra_lock = threading.RLock()
_star_extra = None
_star_store = None
_star_runtime = None
_star_fetch_lock = threading.Lock()
_star_fetching = {}
_star_stats = {}
_star_stats_lock = threading.Lock()
_star_db = None
_STAR_PAGE_SIZES = (12, 24, 36, 48, 60, 90, 120, 180, 240, 360, 480, 720, 1000, 1500, 2000, 3000, 5000)
_STAR_SORTS = ("rank", "name", "movies", "year", "photo", "updated", "images", "new")


def _star_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _star_letter(name):
    char = (name or " ").strip()[:1].upper()
    if char in "Ä":
        return "A"
    if char in "Ö":
        return "O"
    if char in "Ü":
        return "U"
    if char in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        return char
    return "#"


def _star_words(value, limit):
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",")]
    if not isinstance(value, list):
        return []
    found = []
    seen = set()
    for item in value:
        text = re.sub(r"\s+", " ", str(item or "").replace("_", " ")).strip()
        key = text.casefold()
        if not text or key in seen or key in ("none", "null", "unknown", "n/a"):
            continue
        seen.add(key)
        found.append(text)
        if len(found) >= limit:
            break
    return found


def _star_facet(cards, field, limit):
    counts = {}
    for card in cards:
        label = card.get(field) or ""
        if label:
            counts[label] = counts.get(label, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    if limit:
        ranked = ranked[:limit]
    rows = []
    for label, count in ranked:
        item = {"label": label, "count": count}
        if field == "country":
            item["flag"] = _country_flag(label)
        rows.append(item)
    return rows


class _NameDesc:
    """Z–A. tuple-Vergleich braucht die vollen Operatoren."""

    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value

    def __eq__(self, other):
        return isinstance(other, _NameDesc) and self.value == other.value

    def __lt__(self, other):
        return self.value > other.value

    def __le__(self, other):
        return self.value >= other.value

    def __gt__(self, other):
        return self.value < other.value

    def __ge__(self, other):
        return self.value <= other.value


def _star_known_year(year):
    """1, 1000 und 1900 stehen in der Datei, sind aber keine Geburtsjahre."""
    year = year or 0
    if year < 1920 or year > time.localtime().tm_year - 18:
        return 0
    return year


def _star_sort_key(card, kind, flipped=False):
    """Standard ist die bisherige Richtung. Fehlende Jahre, Ränge und Filmzahlen bleiben am Ende."""
    name = card["name_key"]
    if kind == "name":
        if flipped:
            return (_NameDesc(name),)
        return (name,)
    if kind == "movies":
        movies = card["movies"] or 0
        if flipped:
            return (movies <= 0, movies, name)
        return (-movies, name)
    if kind == "year":
        year = _star_known_year(card["year"])
        if flipped:
            return (year <= 0, year, name)
        return (year <= 0, -year, name)
    if kind == "photo":
        has = bool(card["photo"])
        rank = card["rank"] or 10 ** 9
        if flipped:
            return (has, rank, name)
        return (not has, rank, name)
    rank = card["rank"] or 0
    if flipped:
        return (rank <= 0, -rank, name)
    return (rank or 10 ** 9, name)


def _star_thumb_ok(url):
    text = str(url or "").strip()
    if not text.startswith("http"):
        return False
    lower = text.casefold().split("?", 1)[0]
    if "upload.wikimedia.org" in lower and "/thumb/" in lower and not re.search(r"/\d+px-[^/]+$", lower):
        return False
    return True


def star_index():
    """Einmal die lokale Star-Datei. Hält nicht die Plugin-Sperre."""
    global _star_index, _star_thumbs
    if _star_index is not None:
        return _star_index
    with _star_index_lock:
        if _star_index is not None:
            return _star_index
        import gzip
        path = os.path.join(ADDON, "resources", "data", "star_index.json.gz")
        rows = []
        if os.path.isfile(path):
            payload = json.load(gzip.open(path, "rt", encoding="utf-8"))
            rows = payload.get("performers") or []
        cards = []
        kept = []
        by_id = {}
        by_name = {}
        thumbs = {}
        photos = 0
        bios = 0
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            if not name:
                continue
            born_on = _star_date(raw.get("birth_date"))
            if born_on:
                today = datetime.date.today()
                age = today.year - born_on.year - ((today.month, today.day) < (born_on.month, born_on.day))
                if age < 18:
                    continue
            thumb = str(raw.get("thumb") or "")
            if not _star_thumb_ok(thumb):
                thumb = ""
            aliases = _star_words(raw.get("aliases"), 24)
            tags = [tag for tag in _star_words(raw.get("tags"), 24) if tag.casefold() not in ("trending", "live")]
            country = _label_text("country", raw.get("country"))
            card = {
                "id": str(raw.get("id") or ""),
                "name": name,
                "name_key": name.casefold(),
                "blob": "\n".join([name.casefold()] + [alias.casefold() for alias in aliases]),
                "letter": _star_letter(name),
                "thumb": thumb,
                "photo": bool(thumb),
                "country": country,
                "flag": _country_flag(country),
                "gender": _label_text("gender", raw.get("gender")),
                "hair": _label_text("hair", raw.get("hair")),
                "ethnicity": _label_text("ethnicity", raw.get("ethnicity")),
                "cup": _label_text("cup", raw.get("cup")),
                "year": _star_int(raw.get("birth_year")),
                "age": _star_age(raw),
                "height": _star_height(raw),
                "rank": _star_int(raw.get("rank")),
                "movies": _star_int(raw.get("movie_count")),
                "fame": any(tag.casefold() in ("hall of fame", "legend") for tag in tags),
                "has_bio": bool(str(raw.get("bio") or "").strip()),
            }
            if thumb:
                photos += 1
            if str(raw.get("bio") or "").strip():
                bios += 1
            index = len(cards)
            cards.append(card)
            kept.append(raw)
            for key in (raw.get("id"), raw.get("legacy_id")):
                if key:
                    by_id.setdefault(str(key), index)
                    if thumb:
                        thumbs.setdefault(str(key), thumb)
            by_name.setdefault(name.casefold(), index)
            for alias in aliases:
                by_name.setdefault(alias.casefold(), index)
        order = {}
        order_flip = {}
        for kind in _STAR_SORTS:
            order[kind] = sorted(cards, key=lambda card, kind=kind: _star_sort_key(card, kind))
            order_flip[kind] = sorted(cards, key=lambda card, kind=kind: _star_sort_key(card, kind, True))
        stand = ""
        if os.path.isfile(path):
            stand = time.strftime("%d.%m.%Y", time.localtime(os.path.getmtime(path)))
        _star_thumbs = thumbs
        _star_index = {
            "rows": kept,
            "cards": cards,
            "by_id": by_id,
            "by_name": by_name,
            "order": order,
            "order_flip": order_flip,
            "count": len(cards),
            "photos": photos,
            "bios": bios,
            "stand": stand,
            "facets": {
                "gender": _star_facet(cards, "gender", 8),
                "hair": _star_facet(cards, "hair", 16),
                "country": _star_facet(cards, "country", 40),
                "ethnicity": _star_facet(cards, "ethnicity", 16),
                "cup": _star_facet(cards, "cup", 24),
            },
        }
        return _star_index


def star_portrait(performer_id):
    star_index()
    return (_star_thumbs or {}).get(str(performer_id or ""), "")


def _star_card_payload(card):
    cover = _star_cover_media(card.get("id") or "", card.get("name") or "")
    library = card.get("thumb") or ""
    if not _star_thumb_ok(library):
        library = ""
    saved = _star_saved_image(card.get("id") or "", card.get("name") or "")
    if not _star_thumb_ok(saved):
        saved = ""
    thumb = library or saved
    alt = saved if library and saved and saved != library else ""
    payload = {
        "id": card["id"],
        "name": card["name"],
        "thumb": cover or (media_url(thumb) if thumb else ""),
        "thumb_alt": "" if cover or not alt else media_url(alt),
        "country": card["country"],
        "flag": card["flag"],
        "birth_year": card["year"],
        "age": card["age"] if 18 <= int(card.get("age") or 0) <= 99 else 0,
        "hair": card["hair"],
        "gender": card["gender"],
        "rank": card["rank"],
        "movie_count": card["movies"],
        "first_seen": card.get("first_seen"),
    }
    scenes = _star_int(card.get("scenes"))
    if scenes:
        payload["scenes"] = scenes
    if card.get("source"):
        payload["source"] = card["source"]
    blurb = _star_card_blurb(card)
    if blurb:
        payload["about"] = blurb
    return payload


def _star_card_blurb(card):
    ident = str(card.get("id") or "").strip()[:80]
    rec = _star_lang_get(ident)
    if not isinstance(rec, dict) or not rec.get("ok"):
        return ""
    text = re.sub(r"\s+", " ", str(rec.get("about") or rec.get("bio") or "")).strip()
    if len(text) < 24:
        return ""
    if len(text) > 160:
        text = text[:159].rstrip() + "…"
    return text


def _star_face_blocked(star_id, name):
    keys = []
    ident = str(star_id or "").strip()
    if ident:
        keys.append(ident)
    if name:
        keys.append(_star_trend_id(name))
    for key in keys:
        rec = _star_extra_get(key)
        if isinstance(rec, dict) and rec.get("reason") == "age":
            return True
    return False


def _star_face_public(card, query):
    payload = _star_card_payload(card)
    ident = str(payload.get("id") or "")
    name = str(payload.get("name") or query or "").strip()
    if not ident or not name or _star_face_blocked(ident, name):
        return {"query": query, "name": query, "id": "", "thumb": "", "thumb_alt": "", "local": False, "about": "", "line": ""}
    bits = []
    if payload.get("country"):
        bits.append(str(payload["country"]))
    year = _star_int(payload.get("birth_year"))
    if 1920 <= year <= today_year() - 18:
        bits.append(str(year))
    movies = _star_int(payload.get("movie_count"))
    if movies > 0:
        bits.append("%s Filme" % f"{movies:,}".replace(",", "."))
    return {
        "query": query,
        "name": name,
        "id": ident,
        "thumb": payload.get("thumb") or "",
        "thumb_alt": payload.get("thumb_alt") or "",
        "local": True,
        "about": payload.get("about") or "",
        "line": " · ".join(bits),
    }


def star_faces(names):
    """Profilkarten zu Namen von einer Videoseite. Kein Netz, keine Plugin-Sperre."""
    index = star_index()
    cleaned = []
    seen = set()
    for raw in names or []:
        name = clean_label(str(raw or ""))[:80]
        key = name.casefold()
        if len(name) < 2 or key in seen:
            continue
        seen.add(key)
        cleaned.append(name)
        if len(cleaned) >= 24:
            break
    items = []
    pending = []
    for name in cleaned:
        pos = index["by_name"].get(name.casefold())
        if pos is None:
            pending.append(name)
            items.append({"query": name, "name": name, "id": "", "thumb": "", "thumb_alt": "", "local": False, "about": "", "line": ""})
            continue
        items.append(_star_face_public(index["cards"][pos], name))
    if pending:
        need = {name.casefold() for name in pending}
        found = {}
        for row in _star_extra_load().get("people") or []:
            if not isinstance(row, dict):
                continue
            key = str(row.get("name") or "").strip().casefold()
            if key in need and key not in found:
                found[key] = row
        for item in items:
            if item.get("local"):
                continue
            row = found.get(item["query"].casefold())
            if not row:
                continue
            ident = str(row.get("id") or "")
            name = str(row.get("name") or item["query"]).strip()
            thumb = str(row.get("thumb") or "")
            if not thumb.startswith("https://") or _is_video_url(thumb):
                thumb = ""
            item.update(_star_face_public({
                "id": ident,
                "name": name,
                "thumb": thumb,
                "country": "",
                "flag": "",
                "year": 0,
                "hair": "",
                "gender": "",
                "rank": 0,
                "movies": 0,
            }, item["query"]))
    return {"ok": True, "items": items}


def _star_catalog_record(ident):
    rec = _star_extra_get(ident) or {}
    coverage = _star_service().source_coverage(ident)
    if not coverage:
        return rec
    return {**rec,"external_images":coverage.get("images",0),"external_text":coverage.get("text",False)}


def star_catalog(query):
    index = star_index()
    text = (query.get("q") or "").strip()
    letter = (query.get("letter") or "").strip().upper()[:1]
    if letter and letter not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ#":
        letter = ""
    gender = (query.get("gender") or "").strip()
    hair = (query.get("hair") or "").strip()
    country = (query.get("country") or "").strip()
    ethnicity = (query.get("ethnicity") or "").strip()
    cup = (query.get("cup") or "").strip()
    photo = (query.get("photo") or "") in ("1", "true", "ja")
    fame = (query.get("fame") or "") in ("1", "true", "ja")
    sort = query.get("sort") or "rank"
    if sort not in _STAR_SORTS:
        sort = "rank"
    flipped = (query.get("rev") or "") in ("1", "true", "ja")
    try:
        page = max(1, int(query.get("page") or 1))
    except ValueError:
        page = 1
    try:
        per = int(query.get("per") or 36)
    except ValueError:
        per = 36
    if per not in _STAR_PAGE_SIZES:
        per = 36
    fav = (query.get("fav") or "") in ("1", "true", "ja")
    age_min = _star_age_bound(query, "age_min")
    age_max = _star_age_bound(query, "age_max")
    if age_min and age_max and age_min > age_max:
        age_min, age_max = age_max, age_min
    height_min = _star_height_bound(query, "height_min")
    height_max = _star_height_bound(query, "height_max")
    if height_min and height_max and height_min > height_max:
        height_min, height_max = height_max, height_min
    words = [part.casefold() for part in text.split() if part]
    # Typing searches the local snapshot. External discovery is an explicit,
    # coalesced background action, never part of this response's latency.
    orders = index.get("order_flip") if flipped else index.get("order")
    ordered = (orders or {}).get(sort) or index["cards"]
    cover_ids = _star_cover_ids()

    def keep(card):
        if letter and card["letter"] != letter:
            return False
        if gender and card["gender"] != gender:
            return False
        if hair and card["hair"] != hair:
            return False
        if country and card["country"] != country:
            return False
        if ethnicity and card["ethnicity"] != ethnicity:
            return False
        if cup and card["cup"] != cup:
            return False
        if photo and not card["photo"] and str(card.get("id") or "") not in cover_ids and not _star_saved_image(card.get("id"),card.get("name")):
            return False
        if fame and not card["fame"]:
            return False
        if words and any(word not in card["blob"] for word in words):
            return False
        return _star_in_bounds(card, age_min, age_max, height_min, height_max)

    def keep_trend(card):
        if gender or hair or country or ethnicity or cup or fame:
            return False
        if not _star_in_bounds(card, age_min, age_max, height_min, height_max):
            return False
        if letter and card["letter"] != letter:
            return False
        if photo and not card["photo"] and str(card.get("id") or "") not in cover_ids and not _star_saved_image(card.get("id"),card.get("name")):
            return False
        if words and any(word not in card["blob"] for word in words):
            return False
        return True

    def keep_person(card):
        if hair or country or ethnicity or cup or fame:
            return False
        if not _star_in_bounds(card, age_min, age_max, height_min, height_max):
            return False
        if gender and card["gender"] != gender:
            return False
        if letter and card["letter"] != letter:
            return False
        if photo and not card["photo"] and str(card.get("id") or "") not in cover_ids and not _star_saved_image(card.get("id"),card.get("name")):
            return False
        if words and any(word not in card["blob"] for word in words):
            return False
        return True

    def sort_key(card, sort=sort, flipped=flipped):
        return _star_sort_key(card, sort, flipped)

    matched = [card for card in ordered if keep(card)]
    trends = [card for card in _star_trend_cards() if keep_trend(card)]
    if trends:
        trends.sort(key=sort_key)
        matched = _star_merge_sorted(matched, trends, sort_key)
    people = [card for card in _star_people_cards() if keep_person(card)]
    if people:
        have = {card["name_key"] for card in matched}
        have.update(card["name_key"] for card in trends)
        people = [card for card in people if card["name_key"] not in have]
        people.sort(key=sort_key)
        matched = _star_merge_sorted(matched, people, sort_key)
    # Source identities are independent of names: homonyms must remain visible.
    source_cards=[card for card in _star_service().library.cards() if keep(card)]
    if source_cards:
        source_cards.sort(key=sort_key)
        matched=_star_merge_sorted(matched,source_cards,sort_key)
    if fav:
        fav_ids = {str(item.get("id") or "") for item in read_ui().get("starFavs") or []}
        matched = [card for card in matched if str(card.get("id") or "") in fav_ids]
    matched = [card for card in matched if not _star_face_blocked(card.get("id"),card.get("name"))]
    if query.get("coverage") or query.get("source") or query.get("min_movies") or sort in ("updated", "images", "new"):
        matched = star_finder.filter_catalog(matched, query, _star_catalog_record, _star_lang_get)
    if query.get("rules"):
        matched = _star_service().filters.filter(matched,query)
    total = len(matched)
    pages = max(1, (total + per - 1) // per) if total else 1
    if page > pages:
        page = pages
    start = (page - 1) * per
    return {
        "total": total,
        "page": page,
        "pages": pages,
        "per": per,
        "rev": flipped,
        "stand": index["stand"],
        "library": index["count"],
        "photos": index["photos"],
        "bios": index["bios"],
        "people": len(_star_extra_load().get("people") or []),
        "sync": None if query.get("compact") else av_sync_status(),
        "items": [_star_card_payload(card) for card in matched[start:start + per]],
        "facets": index["facets"],
    }


def _star_raw(star_id, name):
    if str(star_id or '').startswith('src:'):return None
    index = star_index()
    pos = None
    if star_id:
        pos = index["by_id"].get(str(star_id))
    if pos is None and name:
        pos = index["by_name"].get(str(name).casefold())
    if pos is None:
        return None
    rows = index["rows"]
    if pos < 0 or pos >= len(rows):
        return None
    raw = rows[pos]
    return raw if isinstance(raw, dict) else None


def _star_in_bounds(card, age_min, age_max, height_min, height_max):
    if age_min or age_max:
        age = int(card.get("age") or 0)
        if age < 18 or (age_min and age < age_min) or (age_max and age > age_max):
            return False
    if height_min or height_max:
        height = int(card.get("height") or 0)
        if height < 120 or (height_min and height < height_min) or (height_max and height > height_max):
            return False
    return True


def _star_age(raw):
    """Genaues Alter nur aus einem vollständigen Geburtsdatum. Unter 18 bleibt 0."""
    born = _star_date(raw.get("birth_date"))
    if not born:
        return 0
    today = datetime.date.today()
    age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    return age if 18 <= age <= 99 else 0


def _star_height(raw):
    cm = _star_int(raw.get("height_cm"))
    return cm if 120 <= cm <= 220 else 0


def _star_age_bound(query, key):
    raw = str(query.get(key) or "").strip()
    if not raw:
        return 0
    try:
        value = int(raw)
    except ValueError:
        return 0
    if value < 18:
        value = 18
    if value > 99:
        value = 99
    return value


def _star_height_bound(query, key):
    raw = str(query.get(key) or "").strip()
    if not raw:
        return 0
    try:
        value = int(raw)
    except ValueError:
        return 0
    if value < 120 or value > 220:
        return 0
    return value


def _star_date(value):
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d.%m.%Y"):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _star_fact(facts, label, value, flag=""):
    text = str(value or "").strip()
    if not text or text in ("0", "0 cm"):
        return
    item = {"label": label, "value": text}
    if flag:
        item["flag"] = flag
    facts.append(item)


def _star_person_profile(person, enrich):
    name = str(person.get("name") or "").strip()
    ident = str(person.get("id") or "")
    thumb = str(person.get("thumb") or "")
    if not thumb.startswith("https://") or _is_video_url(thumb):
        thumb = ""
    scenes = _star_int(person.get("scenes"))
    facts = []
    if scenes > 0:
        _star_fact(facts, "Szenen", f"{scenes:,}".replace(",", "."))
    source_label = "Babepedia" if str(person.get("site") or "") == "babepedia" or ident.startswith("bp:") else "AnalVids"
    _star_fact(facts, "Quelle", source_label)
    profile = {
        "local": False,
        "id": ident,
        "name": name,
        "thumb": media_url(thumb) if thumb else "",
        "bio": "",
        "aliases": [],
        "tags": [],
        "facts": facts,
        "movie_count": 0,
        "scene_count": scenes,
        "rank": 0,
        "movies_query": "",
        "source": source_label,
        "source_url": str(person.get("source") or ""),
    }
    _star_finish_profile(profile, enrich)
    return profile


def star_profile(star_id, name, enrich=False):
    if str(star_id or '').startswith('src:'):
        source_profile=_star_service().library.profile(star_id)
        if source_profile is None:
            source_profile={'id':str(star_id),'name':str(name or ''),'error':'missing','local':False,'thumb':'','bio':'',
                            'aliases':[],'tags':[],'facts':[],'movie_count':0,'scene_count':0,'source':'','source_url':''}
        _star_finish_profile(source_profile,enrich)
        return source_profile
    raw = _star_raw(star_id, name)
    display = str(name or "").strip()
    if raw is None:
        person = _star_person(star_id, display)
        if person:
            return _star_person_profile(person, enrich)
        profile = {
            "error": "missing",
            "local": False,
            "id": str(star_id or "").strip() or _star_trend_id(display),
            "name": display,
            "thumb": "",
            "bio": "",
            "aliases": [],
            "tags": [],
            "facts": [],
            "movie_count": 0,
            "scene_count": 0,
            "rank": 0,
            "movies_query": "",
        }
        _star_finish_profile(profile, enrich)
        return profile
    display = str(raw.get("name") or display).strip()
    thumb = str(raw.get("thumb") or "")
    if not thumb.startswith("http"):
        thumb = ""
    bio = str(raw.get("bio") or "").strip()
    if len(bio) > 4000:
        bio = bio[:3999].rstrip() + "…"
    aliases = _star_words(raw.get("aliases"), 24)
    tags = [tag for tag in _star_words(raw.get("tags"), 24) if tag.casefold() not in ("trending", "live")]
    facts = []
    gender = _label_text("gender", raw.get("gender"))
    country = _label_text("country", raw.get("country"))
    _star_fact(facts, "Geschlecht", gender)
    _star_fact(facts, "Land", country, _country_flag(country))
    born = _star_date(raw.get("birth_date"))
    year = _star_int(raw.get("birth_year"))
    if born:
        _star_fact(facts, "Geburtsdatum", born.strftime("%d.%m.%Y"))
        today = datetime.date.today()
        age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        if 18 <= age <= 99:
            _star_fact(facts, "Alter", str(age))
    elif 1940 <= year <= today_year():
        _star_fact(facts, "Geburtsjahr", str(year))
    _star_fact(facts, "Haar", _label_text("hair", raw.get("hair")))
    _star_fact(facts, "Augen", _label_text("eyes", raw.get("eyes")))
    _star_fact(facts, "Herkunft", _label_text("ethnicity", raw.get("ethnicity")))
    _star_fact(facts, "Statur", _label_text("build", raw.get("build")))
    height_cm = _star_int(raw.get("height_cm"))
    if 120 <= height_cm <= 220:
        _star_fact(facts, "Größe", "%d cm" % height_cm)
    else:
        _star_fact(facts, "Größe", _label_text("height", raw.get("height")))
    cup = _label_text("cup", raw.get("cup"))
    breast = _label_text("breast", raw.get("breast_type"))
    if cup and breast:
        _star_fact(facts, "Oberweite", cup + " · " + breast)
    else:
        _star_fact(facts, "Oberweite", cup or breast)
    career = _star_int(raw.get("career_start_year"))
    if 1950 <= career <= datetime.date.today().year:
        _star_fact(facts, "Karrierestart", str(career))
    decade = str(raw.get("decade") or "").strip()
    decade_match = re.fullmatch(r"(\d{4})s", decade)
    if decade_match:
        _star_fact(facts, "Jahrzehnt", decade_match.group(1) + "er")
    elif decade and decade.lower() not in ("none", "null", "unknown"):
        _star_fact(facts, "Jahrzehnt", decade)
    rank = _star_int(raw.get("rank"))
    if rank > 0:
        _star_fact(facts, "Rang", str(rank))
    movies = _star_int(raw.get("movie_count"))
    scenes = _star_int(raw.get("scene_count"))
    if movies > 0:
        _star_fact(facts, "Filme", f"{movies:,}".replace(",", "."))
    if scenes > 0:
        _star_fact(facts, "Szenen", f"{scenes:,}".replace(",", "."))
    performer_id = str(raw.get("id") or star_id or "")
    movies_query = ""
    if movies > 0 and performer_id:
        movies_query = urllib.parse.urlencode({
            "mode": "60",
            "action": "movies",
            "id": performer_id,
            "name": display,
        })
    profile = {
        "local": True,
        "id": performer_id,
        "name": display,
        "thumb": media_url(thumb) if thumb else "",
        "bio": bio,
        "aliases": aliases,
        "tags": tags,
        "facts": facts,
        "movie_count": movies,
        "scene_count": scenes,
        "rank": rank,
        "movies_query": movies_query,
    }
    _star_finish_profile(profile, enrich)
    return profile


def today_year():
    return datetime.date.today().year


def star_trending():
    """Eine Eporner-Seite, ohne Porträt-Download und ohne die Plugin-Sperre."""
    now = time.time()
    with _star_trend_lock:
        cached = _star_trend.get("items")
        age = now - (_star_trend.get("at") or 0)
        ttl = 1800 if _star_trend.get("ok") else 120
        if cached is not None and age < ttl:
            return {"items": cached, "live": bool(_star_trend.get("ok")), "cached": True}
        items = []
        ok = False
        try:
            req = urllib.request.Request(
                "https://www.eporner.com/pornstars/",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            with urllib.request.urlopen(req, timeout=6) as response:
                page = response.read(800_000).decode("utf-8", "replace")
            index = star_index()
            seen = set()
            for _link, text in re.findall(r'<a[^>]+href=["\'](/pornstar/[^"\']+)["\'][^>]*>(.*?)</a>', page, re.I | re.S):
                clean = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))).strip()
                clean = re.sub(r"\s+\d+(?:\s+»)?$", "", clean).strip()
                key = clean.casefold()
                if len(clean) < 3 or key in seen or key in ("pornstars", "pornstar", "female", "male", "all", "home", "next", "previous", "trending", "models"):
                    continue
                seen.add(key)
                pos = index["by_name"].get(key)
                if pos is None:
                    ident = _star_trend_id(clean)
                    saved = _star_saved_image(ident, clean)
                    items.append({
                        "id": ident,
                        "name": clean,
                        "thumb": media_url(saved) if saved else "",
                        "local": False,
                    })
                else:
                    card = index["cards"][pos]
                    items.append({
                        "id": card["id"],
                        "name": card["name"],
                        "thumb": media_url(card["thumb"]) if card["thumb"] else "",
                        "local": True,
                    })
                if len(items) >= 24:
                    break
            ok = bool(items)
            if ok:
                _star_remember_trends(items)
        except Exception:
            ok = False
            items = []
        _star_trend["at"] = time.time()
        _star_trend["ok"] = ok
        _star_trend["items"] = items
        return {"items": items, "live": ok, "cached": False}


def _star_trend_id(name):
    slug = re.sub(r"[^a-z0-9]+", "-", str(name or "").casefold()).strip("-")
    return "trend:" + (slug[:80] or "name")


def _star_extra_path():
    return os.path.join(PROFILE, "star_extra.json")


def _star_runtime_hub():
    global _star_runtime
    _star_extra_load()
    with _star_extra_lock:
        if _star_runtime is None:
            _star_runtime = star_runtime.StarRuntime(_star_store)
        return _star_runtime


def _star_drain(inflight):
    for future in inflight:
        try:
            future.result()
        except Exception:
            debug_log("server", "star", "Hintergrundabfrage fehlgeschlagen")
    inflight.clear()


def _star_commit_cursor(job, work, cursor, inflight):
    _star_drain(inflight)
    _job_cursor_put(job, {"index":cursor,"total":len(work),"key":work[cursor-1][0] if cursor else "", "done":False,"checkpoint":time.time()})


def _star_extra_load():
    global _star_extra, _star_store
    if _star_extra is not None:
        return _star_extra
    with _star_extra_lock:
        if _star_extra is not None:
            return _star_extra
        _star_store = star_store.StarStore(PROFILE)
        _star_extra = _star_store.load()
        return _star_extra


def _star_extra_save(force=False):
    """Only changed profile/translation records are written; commits stay atomic."""
    global _extra_saved_mono, _extra_dirty
    if _star_extra is None:
        return
    now = time.monotonic()
    gap = 15.0 if now - _ui_touch > 20 else 45.0
    if not force and _extra_saved_mono and now - _extra_saved_mono < gap:
        _extra_dirty = True
        return
    if _star_store is not None:
        _star_store.flush()
    _extra_dirty = False
    _extra_saved_mono = now


def _extra_flush_loop():
    while True:
        time.sleep(8)
        pending = _star_store is not None and _star_store.dirty
        if not _extra_dirty and not pending:
            continue
        try:
            with _star_extra_lock:
                if (_extra_dirty or pending) and _star_extra is not None:
                    _star_extra_save(force=True)
        except Exception:
            time.sleep(5)


def _star_extra_get(key):
    if not key:
        return None
    rec = _star_extra_load()["profiles"].get(key)
    return rec if isinstance(rec, dict) else None


def _star_extra_put(key, rec, save=True):
    if not key or not isinstance(rec, dict):
        return
    with _star_extra_lock:
        profiles = _star_extra_load()["profiles"]
        profiles[key] = rec
        global _extra_trim_mono
        now = time.monotonic()
        if now - _extra_trim_mono < 90:
            if save:
                _star_extra_save()
            return
        _extra_trim_mono = now
        misses = []
        ages = []
        for item, row in profiles.items():
            row = row or {}
            if row.get("reason") == "age" and str(item).startswith("age:"):
                ages.append(item)
            elif not row.get("ok"):
                misses.append(item)
        if len(misses) > 4000:
            misses.sort(key=lambda item: float((profiles.get(item) or {}).get("at") or 0))
            for old_key in misses[:len(misses) - 4000]:
                profiles.pop(old_key, None)
        if len(ages) > 20000:
            ages.sort(key=lambda item: float((profiles.get(item) or {}).get("at") or 0))
            for old_key in ages[:len(ages) - 20000]:
                profiles.pop(old_key, None)
        # Successful profiles are durable library data, not an evictable cache.
        if save:
            _star_extra_save()


def _star_extra_stale(rec):
    if not isinstance(rec, dict):
        return True
    if rec.get("last_error") and time.time()-float(rec.get("last_attempt") or 0)<1800:
        return False
    age = time.time() - float(rec.get("at") or 0)
    reason = rec.get("reason") or ""
    if rec.get("ok"):
        limit = int(_star_runtime.config["interval"] if _star_runtime is not None else 24)*3600
    elif reason in ("timeout", "rate-limit"):
        limit = 5 * 60
    elif reason in ("http", "blocked", "redirect"):
        limit = 30 * 60
    elif reason == "age":
        limit = 30 * 24 * 3600
    else:
        limit = 24 * 3600
    return age > limit


def _star_saved_image(star_id, name):
    keys = []
    ident = str(star_id or "").strip()
    if ident:
        keys.append(ident)
    if name:
        keys.append(_star_trend_id(name))
    for key in keys:
        rec = _star_extra_get(key)
        images = (rec or {}).get("images") or []
        if rec and rec.get("ok") and images:
            return images[0]
    return ""


def _star_remember_trends(items):
    today = datetime.date.today().isoformat()
    with _star_extra_lock:
        trends = _star_extra_load().setdefault("trends", [])
        if not isinstance(trends, list):
            trends = []
            _star_extra["trends"] = trends
        by_key = {}
        for row in trends:
            if isinstance(row, dict):
                by_key[str(row.get("name") or "").casefold()] = row
        for item in items:
            name = str(item.get("name") or "").strip()
            key = name.casefold()
            if len(name) < 3:
                continue
            row = by_key.get(key)
            if row:
                row["last_seen"] = today
                if item.get("local") and item.get("id"):
                    row["id"] = item["id"]
                    row["local"] = True
                elif not row.get("id"):
                    row["id"] = item.get("id") or _star_trend_id(name)
            else:
                row = {
                    "name": name,
                    "id": item.get("id") or _star_trend_id(name),
                    "local": bool(item.get("local")),
                    "first_seen": today,
                    "last_seen": today,
                }
                trends.append(row)
                by_key[key] = row
        if len(trends) > 400:
            trends.sort(key=lambda row: (1 if row.get("local") else 0, str(row.get("last_seen") or "")))
            del trends[:len(trends) - 400]
        _star_extra_save()


def _star_trend_cards():
    index = star_index()
    cards = []
    seen = set()
    for row in _star_extra_load().get("trends") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        key = name.casefold()
        if not name or key in seen or key in index["by_name"]:
            continue
        seen.add(key)
        ident = str(row.get("id") or "")
        if not ident.startswith("trend:"):
            ident = _star_trend_id(name)
        if index["by_id"].get(ident) is not None:
            continue
        thumb = _star_saved_image(ident, name)
        cards.append({
            "id": ident,
            "name": name,
            "name_key": key,
            "blob": key,
            "letter": _star_letter(name),
            "thumb": thumb,
            "photo": bool(thumb),
            "country": "",
            "flag": "",
            "gender": "",
            "hair": "",
            "ethnicity": "",
            "cup": "",
            "year": 0,
            "rank": 0,
            "movies": 0,
            "fame": False,
        })
    return cards


def _star_merge_sorted(left, right, key):
    merged = []
    i = 0
    j = 0
    while i < len(left) and j < len(right):
        if key(left[i]) <= key(right[j]):
            merged.append(left[i])
            i += 1
        else:
            merged.append(right[j])
            j += 1
    if i < len(left):
        merged.extend(left[i:])
    if j < len(right):
        merged.extend(right[j:])
    return merged


# grey/gray und belly/bella nur bei den nachgeladenen Namen, nicht in den 25.000 Bibliothekszeilen.
_NAME_FOLDS = {"grey": "gray", "gray": "grey", "belly": "bella", "bella": "belly"}
_AV_CARD = re.compile(
    r'href="(?:https://www\.analvids\.com)?(/model/\d+/[^"]+)"[^>]*class="model-top__img"[^>]*>\s*<img src="([^"]+)"[\s\S]{0,600}?class="model-top__name" title="([^"]+)"[\s\S]{0,500}?<b>(\d+)</b>\s*scenes',
    re.I,
)


def _people_blob(name):
    base = re.sub(r"\s+", " ", str(name or "").casefold()).strip()
    words = base.split()
    alt = [_NAME_FOLDS.get(word, word) for word in words]
    if alt == words:
        return base
    return base + "\n" + " ".join(alt)


def _star_person(star_id, name):
    people = _star_extra_load().get("people") or []
    if not isinstance(people, list):
        return None
    ident = str(star_id or "").strip()
    if ident and _star_store is not None:
        found = _star_store.people.get(ident)
        if found is not None:
            return found
    if ident:
        for row in people:
            if isinstance(row, dict) and str(row.get("id") or "") == ident:
                return row
    key = str(name or "").strip().casefold()
    if not key:
        return None
    for row in people:
        if isinstance(row, dict) and str(row.get("name") or "").casefold() == key:
            return row
    return None


def _star_people_cards():
    index = star_index()
    with _star_extra_lock:
        gen = _people_gen
        people = list(_star_extra_load().get("people") or [])
    if _people_card_cache.get("gen") == gen and _people_card_cache.get("cards") is not None:
        return _people_card_cache["cards"]
    cards = []
    seen = set()
    for row in people:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        key = name.casefold()
        ident = str(row.get("id") or "")
        if not name or not ident.startswith(("av:", "bp:")) or key in seen or key in index["by_name"]:
            continue
        if index["by_id"].get(ident) is not None:
            continue
        seen.add(key)
        thumb = str(row.get("thumb") or "")
        if not thumb.startswith("https://") or _is_video_url(thumb):
            thumb = ""
        site = "babepedia" if ident.startswith("bp:") else "analvids"
        cards.append({
            "id": ident,
            "name": name,
            "name_key": key,
            "first_seen": row.get("first_seen"),
            "blob": _people_blob(name),
            "letter": _star_letter(name),
            "thumb": thumb,
            "photo": bool(thumb),
            "country": "",
            "flag": "",
            "gender": "weiblich" if site == "analvids" else "",
            "hair": "",
            "ethnicity": "",
            "cup": "",
            "year": 0,
            "rank": 0,
            "movies": 0,
            "scenes": _star_int(row.get("scenes")),
            "fame": False,
            "source": site,
        })
    _people_card_cache["gen"] = gen
    _people_card_cache["cards"] = cards
    return cards


def _av_store_cards_locked(cards, index):
    global _people_gen
    data = _star_extra_load()
    people = data.get("people")
    if not isinstance(people, list):
        people = []
        data["people"] = people
    if _people_positions["list"] is not people or _people_positions["size"] != len(people):
        _people_positions.update({"list":people,"size":len(people),"positions":{str(row["id"]):pos for pos,row in enumerate(people) if isinstance(row,dict) and row.get("id")}})
    by_id = _people_positions["positions"]
    today = datetime.date.today().isoformat()
    added = updated = 0
    for card in cards:
        name = str(card.get("name") or "").strip()
        ident = str(card.get("id") or "")
        if not name or not ident.startswith(("av:", "bp:")):
            continue
        if name.casefold() in index["by_name"]:
            continue
        row = {
            "id": ident,
            "name": name,
            "thumb": card.get("thumb") or "",
            "source": card.get("source") or "",
            "scenes": _star_int(card.get("scenes")),
            "site": "babepedia" if ident.startswith("bp:") else "analvids",
            "last_seen": today,
        }
        pos = by_id.get(ident)
        if pos is None:
            row["first_seen"] = time.time()
            people.append(row)
            by_id[ident] = len(people) - 1
            added += 1
        else:
            if people[pos].get("first_seen"):
                row["first_seen"] = people[pos]["first_seen"]
            if row == people[pos]:
                continue
            people[pos] = row
            updated += 1
        if _star_store is not None:
            _star_store.put_person(row)
    _people_positions["size"] = len(people)
    if added or updated:
        _people_gen += 1
        _people_card_cache["gen"] = -1
    return added, updated


def _av_store_cards(cards, row=None, save=False):
    index = star_index()
    with _star_extra_lock:
        added, updated = _av_store_cards_locked(cards, index)
        if row is not None:
            sync = _star_extra_load().setdefault("sync", {})
            if not isinstance(sync, dict):
                sync = {}
                _star_extra["sync"] = sync
            sync["analvids"] = row
        if save:
            _star_extra_save()
    return added, updated


def _star_drop_person_name(name):
    global _people_gen
    key = str(name or "").strip().casefold()
    if not key:
        return
    with _star_extra_lock:
        people = _star_extra_load().get("people") or []
        if not isinstance(people, list):
            return
        kept = [row for row in people if not isinstance(row, dict) or str(row.get("name") or "").casefold() != key]
        if len(kept) == len(people):
            return
        if _star_store is not None:
            _star_store.remove_people(row["id"] for row in people if isinstance(row,dict) and row.get("id") and str(row.get("name") or "").casefold() == key)
        _star_extra["people"] = kept
        _people_gen += 1
        _people_card_cache["gen"] = -1
        _star_extra_save(force=True)


def _av_sync_row():
    with _star_extra_lock:
        sync = _star_extra_load().get("sync")
        if not isinstance(sync, dict):
            return {}
        row = sync.get("analvids")
        return dict(row) if isinstance(row, dict) else {}


_job_samples = {}
_job_samples_lock = threading.Lock()


def _job_pack(job_id, title, running, what, done, total, note="", eta=None, eta_kind="left"):
    done = max(0, int(done or 0))
    total = max(0, int(total or 0))
    percent = int(round(100.0 * done / total)) if total else 0
    if percent > 100:
        percent = 100
    now = time.time()
    with _job_samples_lock:
        marks = _job_samples.setdefault(job_id, [])
        if marks and done < marks[-1][1]:
            del marks[:]
        if not marks or now - marks[-1][0] >= 4:
            marks.append((now, done))
        if len(marks) > 15:
            del marks[:-15]
        if eta is None and len(marks) >= 2 and total > done:
            span = marks[-1][0] - marks[0][0]
            delta = marks[-1][1] - marks[0][1]
            if span >= 10 and delta > 0:
                eta = int((total - done) / (delta / span))
    if eta is not None:
        eta = max(0, int(eta))
    return {
        "id": job_id,
        "title": title,
        "running": bool(running),
        "what": what or "",
        "done": done,
        "total": total,
        "percent": percent,
        "eta": eta,
        "eta_kind": eta_kind if eta else "",
        "note": note or "",
    }


def _star_activity_jobs(texts, lang, row, people):
    jobs = []
    ready = int(lang.get("ready") or 0) + int(lang.get("skipped") or 0)
    failed = int(lang.get("failed") or 0)
    total = int(lang.get("total") or 0)
    seen = ready + failed
    if total and seen > total:
        seen = total
    current = str(lang.get("current") or "").strip()
    note = ("%s Texte werden erneut versucht" % failed) if failed else "Schon gespeicherte deutsche Texte werden übersprungen"
    lang_next = float(lang.get("next") or 0)
    cool = float(lang.get("cool") or 0)
    lang_now = time.time()
    if lang.get("running") and cool > lang_now:
        jobs.append(_job_pack(
            "lang", "Deutsche Texte", True, "Übersetzung pausiert, gleich wieder weiter",
            seen, total, note, eta=int(cool - lang_now), eta_kind="starts",
        ))
    elif (not lang.get("running")) and lang_next > lang_now and total and ready >= total:
        jobs.append(_job_pack(
            "lang", "Deutsche Texte", False, "Diese Runde ist durch", total, total, note,
            eta=int(lang_next - lang_now), eta_kind="starts",
        ))
    else:
        if lang.get("running") and current:
            what = "Übersetzt " + current
        elif lang.get("running"):
            what = "Übersetzt gespeicherte Texte"
        elif total and ready >= total:
            what = "Diese Runde ist durch"
        else:
            what = "Wartet auf Texte"
        jobs.append(_job_pack("lang", "Deutsche Texte", lang.get("running"), what, seen, total, note))

    cursor = int(texts.get("cursor") or 0)
    queue = int(texts.get("queue") or 0)
    name = str(texts.get("current") or "").strip()
    mode = texts.get("mode") or ""
    lib_next = float(texts.get("library_next") or 0)
    lib_now = time.time()
    if lib_next > lib_now and queue and cursor >= queue:
        what = "Diese Runde ist durch"
        jobs.append(_job_pack(
            "texts", "Beschreibungen suchen", False, what, queue, queue,
            "%s Beschreibungen gespeichert" % int(texts.get("about") or 0),
            eta=int(lib_next - lib_now), eta_kind="starts",
        ))
    else:
        if texts.get("library") and name:
            what = "Sucht eine Beschreibung für " + name
        elif texts.get("library"):
            what = "Geht die Model-Liste durch"
        elif mode == "fertig":
            what = "Diese Runde ist durch"
        else:
            what = "Wartet"
        jobs.append(_job_pack(
            "texts", "Beschreibungen suchen", bool(texts.get("library")),
            what, cursor, queue,
            "%s Beschreibungen gespeichert" % int(texts.get("about") or 0),
        ))

    seen = int(texts.get("seen") or 0)
    locs = int(texts.get("locs") or 0)
    nxt = float(texts.get("next") or 0)
    now = time.time()
    if nxt > now:
        what = "Pausiert bis " + time.strftime("%d.%m. %H:%M", time.localtime(nxt))
        jobs.append(_job_pack(
            "names", "Neue Namen", False, what, seen, locs,
            "%s neue Namen übernommen" % int(texts.get("added") or 0),
            eta=int(nxt - now), eta_kind="starts",
        ))
    else:
        who = str(texts.get("name_current") or "").strip()
        what = ("Prüft " + who) if who else "Liest neue Namen"
        jobs.append(_job_pack(
            "names", "Neue Namen", bool(texts.get("names")), what, seen, locs,
            "%s neue Namen übernommen" % int(texts.get("added") or 0),
        ))

    more_name = str(texts.get("more_current") or "").strip()
    more_cursor = int(texts.get("more_cursor") or 0)
    more_queue = int(texts.get("more_queue") or 0)
    more_next = float(texts.get("more_next") or 0)
    more_now = time.time()
    if more_next > more_now and more_queue and more_cursor >= more_queue:
        jobs.append(_job_pack(
            "more", "Zweite Quelle", False, "Diese Runde ist durch",
            more_queue, more_queue,
            "%s mit vielen Bildern" % int(texts.get("photos") or 0),
            eta=int(more_next - more_now), eta_kind="starts",
        ))
    else:
        if texts.get("more") and more_name:
            what = "Holt Text und Bilder für " + more_name
        elif texts.get("more"):
            what = "Geht die Models für die zweite Quelle durch"
        else:
            what = "Wartet"
        jobs.append(_job_pack(
            "more", "Zweite Quelle", texts.get("more"), what,
            more_cursor, more_queue,
            "%s mit vielen Bildern" % int(texts.get("photos") or 0),
        ))

    page = int(row.get("page") or 0)
    pages = int(row.get("pages") or 0)
    av_next = float(row.get("next") or 0)
    stored = "%s Namen gespeichert" % int(people or 0)
    if _av_run.get("running"):
        jobs.append(_job_pack("analvids", "AnalVids-Namen", True, "Liest Seite %s" % page, page, pages, stored))
    elif av_next > now:
        jobs.append(_job_pack(
            "analvids", "AnalVids-Namen", False,
            "Weiter am " + time.strftime("%d.%m. %H:%M", time.localtime(av_next)),
            page, pages, stored, eta=int(av_next - now), eta_kind="starts",
        ))
    else:
        jobs.append(_job_pack("analvids", "AnalVids-Namen", False, "Wartet", page, pages, stored))
    return jobs


def av_sync_status():
    row = _av_sync_row()
    people = _star_extra_load().get("people") or []
    texts = _babe_status()
    lang = _star_lang_batch_public()
    count = len(people) if isinstance(people, list) else 0
    return {
        "ok": True,
        "site": "analvids",
        "running": bool(_av_run.get("running")),
        "page": int(row.get("page") or 0),
        "pages": int(row.get("pages") or 0),
        "added": int(row.get("added") or 0),
        "updated": int(row.get("updated") or 0),
        "people": count,
        "next": int(float(row.get("next") or 0)),
        "error": str(row.get("error") or ""),
        "texts": texts,
        "lang": lang,
        "jobs": _star_activity_jobs(texts, lang, row, count),
        "library_bios": int((_star_index or {}).get("bios") or 0),
        "library": int((_star_index or {}).get("count") or 0),
    }


def av_sync_kick():
    with _star_extra_lock:
        row = _av_sync_row()
        row["next"] = 0
        row["error"] = ""
        sync = _star_extra_load().setdefault("sync", {})
        if not isinstance(sync, dict):
            sync = {}
            _star_extra["sync"] = sync
        sync["analvids"] = row
        _star_extra_save(force=True)
    _av_wake.set()
    return av_sync_status()


def _av_get(url):
    if (urllib.parse.urlsplit(url).hostname or '').lower() not in ('analvids.com','www.analvids.com'):
        raise RuntimeError('redirect')
    with _av_net:
        response = _star_runtime_hub().request(url,{'User-Agent':'Mozilla/5.0','Accept':'text/html,application/xhtml+xml','Accept-Language':'en'},ttl=3600,limit=500000)
    if (urllib.parse.urlsplit(response['url']).hostname or '').lower() not in ('analvids.com','www.analvids.com'):
        raise RuntimeError('redirect')
    return response['body']


def _av_parse_cards(page):
    found = []
    seen = set()
    for path, thumb, title, scenes in _AV_CARD.findall(page or ""):
        ident_m = re.search(r"/model/(\d+)/", path)
        if not ident_m:
            continue
        ident = ident_m.group(1)
        if ident in seen:
            continue
        name = re.sub(r"\s+", " ", html.unescape(title)).strip()
        if not name or len(name) > 120:
            continue
        seen.add(ident)
        raw_thumb = html.unescape(thumb).strip()
        if raw_thumb.startswith("//"):
            raw_thumb = "https:" + raw_thumb
        if not raw_thumb.startswith("https://") or _is_video_url(raw_thumb):
            raw_thumb = ""
        found.append({
            "id": "av:" + ident,
            "name": name,
            "thumb": raw_thumb,
            "source": "https://www.analvids.com" + path.split("?", 1)[0],
            "scenes": int(scenes),
            "site": "analvids",
        })
        if len(found) >= 60:
            break
    return found


def _av_page_count(page):
    nums = [int(number) for number in re.findall(r"/models/page/(\d+)/", page or "")]
    if not nums:
        return 0
    count = max(nums)
    return count if count <= 2000 else 2000


def _av_models_url(page):
    if page <= 1:
        return "https://www.analvids.com/models/"
    return "https://www.analvids.com/models/page/%d/" % page


def _av_fetch_letter(letter):
    letter = (letter or "").lower()[:1]
    if letter not in "abcdefghijklmnopqrstuvwxyz":
        return
    now = time.time()
    with _av_letter_lock:
        cached = _av_letters.get(letter)
        if cached and now - float(cached.get("at") or 0) < (6 * 3600 if cached.get("ok") else 120):
            return
        pending = _av_letter_wait.get(letter)
        if pending is None:
            pending = threading.Event()
            _av_letter_wait[letter] = pending
            owner = True
        else:
            owner = False
    if not owner:
        pending.wait(14)
        return
    ok = False
    try:
        url = "https://www.analvids.com/models/?" + urllib.parse.urlencode([("sex", "female"), ("first-letter[]", letter)])
        cards = _av_parse_cards(_av_get(url))
        if cards:
            _av_store_cards(cards, save=True)
            ok = True
    except Exception:
        debug_log("server", "star", "analvids buchstabe", {"letter": letter})
        ok = False
    finally:
        with _av_letter_lock:
            _av_letters[letter] = {"at": time.time(), "ok": ok}
            event = _av_letter_wait.pop(letter, None)
        if event:
            event.set()


def _av_lookup_query(text, index):
    words = [part for part in re.split(r"\s+", str(text or "").strip()) if part]
    if not words:
        return
    long_enough = len("".join(words)) >= 5 or (len(words) >= 2 and len(words[0]) >= 3 and len(words[1]) >= 3)
    if not long_enough:
        return
    full = " ".join(part.casefold() for part in words)
    if full in index["by_name"]:
        return
    folded = " ".join(_NAME_FOLDS.get(part.casefold(), part.casefold()) for part in words)
    people = _star_extra_load().get("people") or []
    if isinstance(people, list):
        for row in people:
            if not isinstance(row, dict):
                continue
            key = str(row.get("name") or "").casefold()
            if key == full or key == folded:
                return
    letter = ""
    for char in words[0]:
        if char.isalpha():
            letter = char.lower()
            break
    if letter:
        _av_fetch_letter(letter)


def _av_walk():
    if not _av_wake.wait(2):
        pass
    _av_wake.clear()
    while True:
        try:
            row = _av_sync_row()
            nxt = _star_runtime_hub().due("analvids", float(row.get("next") or 0))
            now = time.time()
            if nxt > now:
                _av_run["running"] = False
                _av_wake.wait(min(5, nxt - now))
                _av_wake.clear()
                continue
            _av_run["running"] = True
            page = int(row.get("page") or 0) + 1
            if page < 1:
                page = 1
            pages_known = int(row.get("pages") or 0)
            job_wait()
            try:
                html = _av_get(_av_models_url(page))
            finally:
                job_done()
            cards = _av_parse_cards(html)
            found = _av_page_count(html)
            pages = max(pages_known, found, 1)
            if pages > 2000:
                pages = 2000
            if not cards:
                if found and page > found:
                    done_row = {
                        "page": 0,
                        "pages": found,
                        "at": time.time(),
                        "added": int(row.get("added") or 0),
                        "updated": int(row.get("updated") or 0),
                        "next": time.time() + _star_runtime_hub().interval(),
                        "error": "",
                    }
                    _av_store_cards([], done_row, save=True)
                    _av_run["running"] = False
                    continue
                raise RuntimeError("empty")
            added = 0 if page == 1 else int(row.get("added") or 0)
            updated = 0 if page == 1 else int(row.get("updated") or 0)
            new_row = {
                "page": page,
                "pages": pages,
                "at": time.time(),
                "added": added,
                "updated": updated,
                "next": 0,
                "error": "",
            }
            new_added, new_updated = _av_store_cards(cards, new_row, save=False)
            done = page >= pages
            new_row["added"] = added + new_added
            new_row["updated"] = updated + new_updated
            new_row["page"] = 0 if done else page
            new_row["next"] = time.time() + _star_runtime_hub().interval() if done else 0
            save = done or page % 5 == 0
            _av_store_cards([], new_row, save=save)
            if save:
                debug_log("server", "star", "analvids", {"page": page, "pages": pages, "added": new_row["added"]})
            if done:
                _av_run["running"] = False
                continue
            time.sleep(1.2)
        except Exception:
            debug_log("server", "star", "analvids seite", {"err": traceback.format_exc()[-240:]})
            try:
                row = _av_sync_row()
                row["error"] = "seite"
                row["at"] = time.time()
                _av_store_cards([], row, save=False)
            except Exception:
                pass
            _av_run["running"] = True
            time.sleep(30)



def av_sync_start():
    with _av_letter_lock:
        if _av_run.get("started"):
            return av_sync_status()
        _av_run["started"] = True
    threading.Thread(target=_av_walk, name="analvids-names", daemon=True).start()
    return av_sync_status()


def _star_plain(fragment):
    text = re.sub(r"(?i)<br\s*/?>", " ", fragment or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _star_value_text(fragment):
    titles = re.findall(r'title="([^"]+)"', fragment or "")
    text = _star_plain(fragment)
    text = re.sub(r"show conversions", "", text, flags=re.I)
    text = re.sub(r"\s+,", ",", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    text = re.sub(r"\s+", " ", text).strip(" -")
    if text.startswith("(") and text.endswith(")") and text.count("(") == 1:
        text = text[1:-1].strip()
    for title in titles:
        note = html.unescape(title).strip()
        if note and "Ranked #" in note and note not in text and len(note) < 90:
            text = (text + " · " + note).strip()
    return text


def _star_blank_value(value):
    return str(value or "").strip().casefold() in ("", "none", "n/a", "unknown", "null", "-", "no", "keine")


def _star_same_name(asked, found):
    left = re.sub(r"\s+", " ", str(asked or "")).strip().casefold()
    right = re.sub(r"\s+", " ", str(found or "")).strip().casefold()
    if not left or not right:
        return False
    if left == right or left in right or right in left:
        return True
    words = [word for word in left.split() if len(word) > 2]
    return bool(words) and all(word in right for word in words)


_STAR_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def _star_born_parts(text):
    raw = str(text or "")
    year_m = re.search(r"\b((?:19|20)\d{2})\b", raw)
    if not year_m:
        return 0, 0, 0
    year = int(year_m.group(1))
    low = raw.casefold()
    month = next((number for name, number in _STAR_MONTHS.items() if name in low), 0)
    day = 0
    if month:
        day_m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", low)
        if day_m:
            day = int(day_m.group(1))
            if not 1 <= day <= 31:
                day = 0
    return year, month, day


def _star_blocks_images(born_text):
    year, month, day = _star_born_parts(born_text)
    if not year:
        return False
    today = datetime.date.today()
    if month and day:
        try:
            born = datetime.date(year, month, day)
        except ValueError:
            return year >= today.year - 17
        age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        return age < 18
    return year >= today.year - 17


def _star_born_facts(born_text):
    """Volles Datum nur anzeigen, wenn die Person 18 bis 99 ist."""
    year, month, day = _star_born_parts(born_text)
    if not (year and month and day):
        return []
    try:
        born = datetime.date(year, month, day)
    except ValueError:
        return []
    today = datetime.date.today()
    age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    if not 18 <= age <= 99:
        return []
    return [
        {"label": "Geburtsdatum", "value": born.strftime("%d.%m.%Y")},
        {"label": "Alter", "value": str(age)},
    ]


def _star_text_underage(text):
    match = re.search(
        r"born(?:\s+on)?\s+([A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})",
        str(text or ""),
        re.I,
    )
    if not match:
        return False
    return _star_blocks_images(match.group(1))


_STAR_EXTRA_REV = 2
_STAR_IMAGE_CAP = 2400
_STAR_GALLERY_CAP = 60


def _star_profile_underage(profile):
    for fact in profile.get("facts") or []:
        if fact.get("label") != "Geburtsdatum":
            continue
        born = _star_date(fact.get("value"))
        if not born:
            continue
        today = datetime.date.today()
        age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        return age < 18
    return False


def _star_babe_abs(path):
    raw = html.unescape(str(path or "")).strip()
    if not raw or raw.startswith("data:"):
        return ""
    if raw.startswith("//"):
        raw = "https:" + raw
    elif raw.startswith("/"):
        raw = "https://www.babepedia.com" + raw
    parsed = urllib.parse.urlsplit(raw)
    if (parsed.netloc or "").casefold() not in ("www.babepedia.com", "babepedia.com"):
        return ""
    parts = urllib.parse.unquote(parsed.path or "")
    lower = parts.casefold()
    if not lower.endswith((".jpg", ".jpeg", ".png", ".webp")):
        return ""
    if "/pics/" not in lower and "/user-uploads/" not in lower:
        return ""
    if "thumb" in lower or "/images/" in lower or "/img/" in lower:
        return ""
    return "https://www.babepedia.com" + urllib.parse.quote(parts, safe="/%")


def _star_images(page, limit=None):
    found = []
    seen = set()
    for pattern in (
        r'<a href="(/pics/[^"]+\.(?:jpe?g|png|webp))"',
        r'<a href="(/user-uploads/[^"]+\.(?:jpe?g|png|webp))"',
    ):
        for path in re.findall(pattern, page, re.I):
            url = _star_babe_abs(path)
            key = url.casefold()
            if not url or key in seen:
                continue
            seen.add(key)
            found.append(url)
            if limit is not None and len(found) >= limit:
                return found
    return found


def _star_stored_images(rec):
    stored = []
    if not isinstance(rec, dict) or not rec.get("ok"):
        return stored
    for url in rec.get("images") or []:
        if isinstance(url, str) and url.startswith("https://") and not _is_video_url(url):
            stored.append(url)
    return stored


def star_image_slice(star_id, name, start):
    """Die nächsten 12 Bilder. Ist die Liste leer, wird die nächste Fotoserie geholt."""
    profile = star_profile(star_id, name, enrich=False)
    if profile.get("underage"):
        return {"ok": False, "reason": "age", "images": [], "total": 0, "more": False}
    key = str(profile.get("id") or star_id or "").strip() or _star_trend_id(name)
    display = str(profile.get("name") or name or "").strip()
    try:
        start = max(0, int(start))
    except (TypeError, ValueError):
        start = 0
    rec = _star_extra_get(key)
    if rec and rec.get("reason") == "age":
        return {"ok": False, "reason": "age", "images": [], "total": 0, "more": False}
    stored = _star_stored_images(rec)
    if display and start >= len(stored) and isinstance(rec, dict) and rec.get("ok"):
        if "image_next" not in rec:
            try:
                found = _star_freeones_galleries(display)
            except Exception:
                found = []
            with _star_gallery_lock:
                current = _star_extra_get(key) or rec
                if isinstance(current, dict) and current.get("ok") and "image_next" not in current:
                    current["image_next"] = found
                    current["image_full"] = not found
                    _star_extra_put(key, current, save=True)
                    rec = current
        if rec.get("image_next") and start >= len(_star_stored_images(rec)):
            _star_gallery_step(key)
            rec = _star_extra_get(key)
            if isinstance(rec, dict) and rec.get("image_next") and start >= len(_star_stored_images(rec)):
                _star_gallery_step(key)
                rec = _star_extra_get(key)
        stored = _star_stored_images(rec)
    if start > len(stored):
        start = len(stored)
    chunk = stored[start:start + 12]
    images = []
    for url in chunk:
        proxied = media_url(url)
        if proxied:
            images.append(proxied)
    pages = []
    known = False
    if isinstance(rec, dict) and rec.get("ok"):
        pages = [item for item in (rec.get("image_next") or []) if isinstance(item, str)]
        known = "image_next" in rec or rec.get("more_rev") == 1
    more = (start + len(chunk) < len(stored)) or bool(pages) or not known
    return {
        "ok": True,
        "images": images,
        "total": len(stored),
        "from": start,
        "next": start + len(chunk),
        "more": more,
    }


def _star_jobs(value):
    jobs = []
    for part in str(value or "").split(","):
        text = re.sub(r"\(former\)", "(früher)", part.strip(), flags=re.I)
        text = re.sub(r"\s+", " ", text).strip()
        if text and not _star_blank_value(text):
            jobs.append(text)
        if len(jobs) >= 16:
            break
    return jobs


def _star_career(value):
    text = str(value or "").strip()
    span = re.search(r"(\d{4})\s*[-–—]\s*(present|\d{4})", text, re.I)
    active = ""
    if span:
        end = "heute" if span.group(2).casefold() == "present" else span.group(2)
        active = span.group(1) + "–" + end
    bits = []
    age = re.search(r"started around\s+(\d+)", text, re.I)
    years = re.search(r"(\d+)\s+years active", text, re.I)
    if age:
        bits.append("Start mit etwa " + age.group(1) + " Jahren")
    if years:
        bits.append(years.group(1) + " Jahre aktiv")
    if not active and text:
        active = text
    return active, ", ".join(bits)


def _star_about_text(fragment):
    text = re.sub(r"(?i)<br\s*/?>", "\n", fragment or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    cut = re.search(r"\n\s*(?:TWISTYS biography|From [a-z0-9.]+)\s*:", text, re.I)
    if cut:
        text = text[:cut.start()].strip()
    return text


def _star_sentences(text):
    found = []
    for para in re.split(r"\n+", text or ""):
        para = re.sub(r"\s+", " ", para).strip()
        if not para:
            continue
        found.extend(part.strip() for part in re.split(r"(?<=[.!])\s+", para) if part.strip())
    return found


_STAR_AWARD = re.compile(r"\b(AVN|XBIZ|award|awards|trophy|nominat\w*|Fleshlight|Penthouse Pet|Twistys Treat)\b", re.I)


def _star_award_lines(text):
    lines = []
    seen = set()
    for sentence in _star_sentences(text):
        if len(sentence) < 40 or len(sentence) > 600:
            continue
        if not re.search(r"\b(AVN|XBIZ|Fleshlight|Penthouse|Twistys|trophy)\b", sentence, re.I):
            continue
        key = sentence.casefold()
        if key in seen:
            continue
        seen.add(key)
        lines.append(sentence)
        if len(lines) >= 8:
            break
    return lines


def _star_production_lines(text):
    lines = []
    for sentence in _star_sentences(text):
        low = sentence.casefold()
        produced = re.search(r"\b(producing|produced|producer|directing)\b", low)
        if produced and 30 < len(sentence) < 500:
            lines.append(sentence)
        if len(lines) >= 2:
            break
    return " ".join(lines)


def _star_known_for(text):
    for sentence in _star_sentences(text):
        if "best known for" in sentence.casefold() and len(sentence) < 500:
            return sentence
    return ""


def _star_named_films(text):
    flat = re.sub(r"\s+", " ", text or "")
    match = re.search(r"notable titles including (.+?)(?:\.|$)", flat, re.I)
    if not match:
        return []
    films = []
    for title, year in re.findall(r"([^,]+?)\s*\((\d{4})\)", match.group(1)):
        title = re.sub(r"^(?:and|und)\s+", "", title.strip(" ."), flags=re.I)
        if len(title) < 2:
            continue
        films.append({"title": title, "year": year})
        if len(films) >= 8:
            break
    return films


def _star_credits(text):
    flat = re.sub(r"\s+", " ", text or "")
    match = re.search(
        r"\d[\d,]*\s+performer credits on the International Adult Film Database \(IAFD\) as of [A-Za-z]+ \d{4}",
        flat,
        re.I,
    )
    return match.group(0) if match else ""


def _star_social_text(text):
    flat = re.sub(r"\s+", " ", text or "")
    rows = []
    for match in re.finditer(r"As of ([A-Za-z]+ \d{4}),", flat):
        window = re.split(r"\.\s", flat[match.end():match.end() + 500], maxsplit=1)[0]
        found = re.findall(
            r"([\d.,]+\s*(?:million|thousand)?)\s+(followers|subscribers)\s+on\s+(?:her\s+)?(Instagram|TikTok|YouTube|Twitch)",
            window,
            re.I,
        )
        if not found:
            continue
        for count, kind, network in found:
            rows.append({
                "label": network,
                "value": re.sub(r"\s+", " ", count).strip() + " " + kind,
                "note": "laut Text, Stand " + match.group(1),
            })
        break
    return rows


def _star_follower_field(value):
    match = re.search(r"^(.*?)\s*\(as of\s+([^)]+)\)\s*$", value, re.I)
    if not match:
        return value, ""
    return match.group(1).strip(), "Stand " + re.sub(r"\s+", " ", match.group(2)).strip()


def _star_split_list(value, limit):
    items = []
    seen = set()
    for part in str(value or "").split(","):
        text = re.sub(r"\s+", " ", part).strip()
        key = text.casefold()
        if not text or key in seen or _star_blank_value(text):
            continue
        seen.add(key)
        items.append(text)
        if len(items) >= limit:
            break
    return items


_STAR_LINK_LABELS = {
    "instagram": "Instagram",
    "onlyfans": "OnlyFans",
    "onlyfansfree": "OnlyFans",
    "tiktok": "TikTok",
    "youtube": "YouTube",
    "twitch": "Twitch",
    "imdb": "IMDb",
    "iafd": "IAFD",
    "x": "X",
    "twitter": "X",
}


def _star_links(page):
    block = re.search(r'id="socialicons"(.*?)</div>', page, re.S | re.I)
    if not block:
        return []
    links = []
    seen = set()
    for tag in re.findall(r"<a\b[^>]*>", block.group(1), re.I):
        href_m = re.search(r"""href=['"]([^'"]+)['"]""", tag)
        class_m = re.search(r"""class=['"]([^'"]+)['"]""", tag)
        if not href_m or not class_m:
            continue
        href = html.unescape(href_m.group(1)).strip()
        if not href.startswith("https://"):
            continue
        host = urllib.parse.urlparse(href).netloc.casefold()
        if any(bad in host for bad in ("asldating", "lkstrck", "impactradius", "sjv.io", "doubleclick")):
            continue
        classes = class_m.group(1).split()
        kind = next((item for item in classes if item != "proficon"), "")
        label = _STAR_LINK_LABELS.get(kind)
        if not label or label.casefold() in seen:
            continue
        seen.add(label.casefold())
        links.append({"label": label, "url": href})
    return links


def _star_aliases(page, name):
    boxes = re.findall(
        r'<span class="aliasname">(.*?)</span>\s*-\s*<span class="aliassite">(.*?)</span>\s*<span class="aliasnote">(.*?)</span>',
        page,
        re.I | re.S,
    )
    aliases = []
    studios = []
    real_name = ""
    seen_alias = set()
    seen_studio = set()
    own = set(str(name or "").casefold().split())
    own.add(str(name or "").casefold())
    for alias_html, site_html, note_html in boxes:
        alias = _star_plain(alias_html)
        site = _star_plain(site_html)
        note = _star_plain(note_html)
        real = "real name" in note.casefold()
        if alias and real and not real_name:
            real_name = alias
        if alias and alias.casefold() not in own and alias.casefold() not in seen_alias and len(alias) <= 40:
            seen_alias.add(alias.casefold())
            if len(aliases) < 12:
                aliases.append(alias)
        if site and not real and site.casefold() not in seen_studio and len(site) <= 60:
            seen_studio.add(site.casefold())
            if len(studios) < 80:
                studios.append(site)
    if real_name and real_name.casefold() not in seen_alias:
        aliases.insert(0, real_name)
    return aliases[:12], real_name, studios, len(seen_studio)


def _star_rating(page):
    rating = ""
    votes = 0
    favorites = 0
    rank_high = 0
    box = re.search(r'class="rating-box rating-global"(.*?)</div>', page, re.S)
    if box:
        plain = _star_plain(box.group(1))
        score = re.search(r"(\d+(?:[.,]\d+)?)\s*/\s*10", plain)
        if score:
            rating = score.group(1).replace(".", ",") + "/10"
        vote_m = re.search(r"([\d.,]+)\s+votes", plain, re.I)
        if vote_m:
            votes = _star_int(vote_m.group(1).replace(".", "").replace(",", ""))
    fav = re.search(r'class="rating-box rating-fav"(.*?)</div>', page, re.S)
    if fav:
        fav_m = re.search(r"([\d.,]+)", _star_plain(fav.group(1)))
        if fav_m:
            favorites = _star_int(fav_m.group(1).replace(".", "").replace(",", ""))
    high = re.search(r"Highest rank:\s*([\d.,]+)", page, re.I)
    if high:
        rank_high = _star_int(high.group(1).replace(".", "").replace(",", ""))
    return rating, votes, favorites, rank_high


_STAR_BABE_FACTS = {
    "birthplace": "Geburtsort",
    "nationality": "Nationalität",
    "ethnicity": "Herkunft (Babepedia)",
    "sexuality": "Sexualität",
    "hair color": "Haar (Babepedia)",
    "eye color": "Augen (Babepedia)",
    "height": "Größe (Babepedia)",
    "weight": "Gewicht",
    "body type": "Figur (Babepedia)",
    "measurements": "Maße",
    "bra/cup size": "BH",
    "boobs": "Brust (Babepedia)",
    "tattoos": "Tattoos",
    "piercings": "Piercings",
}


def _star_info_rows(grid):
    rows = []
    for match in re.finditer(r"<h3>([^<]+)</h3>|<span class=\"label\">([^<]+)</span>", grid, re.I):
        if match.group(1):
            rows.append(("h", _star_plain(match.group(1)), ""))
            continue
        start = match.end()
        value_m = re.search(r'<span class="value">', grid[start:], re.I)
        if not value_m:
            continue
        value_start = start + value_m.end()
        depth = 1
        index = value_start
        lower = grid.casefold()
        while index < len(grid) and depth:
            next_open = lower.find("<span", index)
            next_close = lower.find("</span>", index)
            if next_close < 0:
                break
            if 0 <= next_open < next_close:
                depth += 1
                index = next_open + 5
            else:
                depth -= 1
                if depth == 0:
                    rows.append(("f", match.group(2), grid[value_start:next_close]))
                    break
                index = next_close + 7
    return rows


def _star_parse_babepedia(page, name, url):
    h1_m = re.search(r'<h1 id="babename">([^<]+)</h1>', page, re.I)
    h1 = _star_plain(h1_m.group(1)) if h1_m else ""
    if not h1 or not _star_same_name(name, h1):
        return {"ok": False, "reason": "missing", "url": url, "images": [], "image_full": True}
    grid_m = re.search(r'id="personal-info-block"(.*?)id="vote-modal"', page, re.S | re.I)
    grid = grid_m.group(1) if grid_m else ""
    section = ""
    born = ""
    facts = []
    performances = []
    achievements = []
    social = []
    professions = []
    active = ""
    detail = ""
    for kind, label_html, value_html in _star_info_rows(grid):
        if kind == "h":
            section = label_html.casefold()
            continue
        label = _star_plain(label_html).rstrip(":").casefold()
        value = _star_value_text(value_html)
        if not label or _star_blank_value(value):
            continue
        if label == "born":
            born = value
            continue
        if label == "age":
            continue
        if label == "years active":
            active, detail = _star_career(value)
            continue
        if label == "professions":
            professions = _star_jobs(value)
            continue
        if label == "achievements":
            achievements = _star_split_list(value, 24)
            continue
        if "follower count" in label:
            amount, note = _star_follower_field(value)
            network = label.replace(" follower count", "").strip().title() or "Follower"
            if amount:
                social.append({"label": network, "value": amount, "note": note})
            continue
        if section == "performances":
            performances.append({"label": _star_plain(label_html).rstrip(":"), "acts": value})
            continue
        fact_label = _STAR_BABE_FACTS.get(label)
        if fact_label:
            facts.append({"label": fact_label, "value": value})
    if _star_blocks_images(born):
        return {"ok": False, "reason": "age", "url": url, "images": [], "image_full": True}
    facts.extend(_star_born_facts(born))
    bio_m = re.search(r'<p id="biotext">(.*?)</p>', page, re.S | re.I)
    about_full = _star_about_text(bio_m.group(1) if bio_m else "")
    about = about_full
    aliases, real_name, studios, studio_total = _star_aliases(page, h1 or name)
    rating, votes, favorites, rank_high = _star_rating(page)
    social.extend(_star_social_text(about_full))
    return {
        "ok": True,
        "reason": "",
        "url": url,
        "images": _star_images(page),
        "image_full": False,
        "aliases": aliases,
        "real_name": real_name,
        "facts": facts,
        "career": {"active": active, "detail": detail, "professions": professions},
        "awards": _star_award_lines(about_full),
        "achievements": achievements,
        "performances": performances,
        "known_for": _star_known_for(about_full),
        "films": _star_named_films(about_full),
        "production": _star_production_lines(about_full),
        "credits": _star_credits(about_full),
        "rating": rating,
        "votes": votes,
        "favorites": favorites,
        "rank_high": rank_high,
        "social": social[:8],
        "links": _star_links(page),
        "studios": studios,
        "studio_total": studio_total,
        "about": about,
    }


def _star_babe_url(name):
    slug = re.sub(r"\s+", "_", str(name or "").strip()).replace("/", "").replace("\\", "")
    if len(slug) < 2:
        return ""
    return "https://www.babepedia.com/babe/" + urllib.parse.quote(slug, safe="_-'")


def _star_fetch_html(url):
    return _star_fetch_host(url, ('www.babepedia.com', 'babepedia.com'), 1_200_000)


def _star_extra_public(rec):
    if not isinstance(rec, dict):
        return None
    if not rec.get("ok"):
        return {
            "ok": False,
            "stale": _star_extra_stale(rec),
            "source": "",
            "reason": rec.get("reason") or "",
            "images": [],
            "image_total": 0,
            "image_more": False,
        }
    stored = []
    for url in rec.get("images") or []:
        if isinstance(url, str) and url.startswith("https://") and not _is_video_url(url):
            stored.append(url)
    images = []
    for url in stored[:12]:
        proxied = media_url(url)
        if proxied:
            images.append(proxied)
    pages = [item for item in (rec.get("image_next") or []) if isinstance(item, str)]
    pending = rec.get("more_rev") != 1 or str(rec.get("about") or "").lstrip().startswith("class=")
    career = rec.get("career") if isinstance(rec.get("career"), dict) else {}
    return {
        "ok": True,
        "stale": _star_extra_stale(rec),
        "source": rec.get("source") or ("Babepedia" if (urllib.parse.urlsplit(rec.get("url") or "").hostname or "").lower() in ("babepedia.com","www.babepedia.com") else rec.get("about_source") or "Gespeichertes Zusatzprofil"),
        "source_url": rec.get("url") or "",
        "images": images,
        "image_total": len(stored),
        "image_more": (len(stored) > len(images)) or bool(pages) or pending,
        "about_source": rec.get("about_source") or "",
        "biographies": rec.get("biographies") or {},
        "last_error": rec.get("last_error") or "",
        "last_attempt": rec.get("last_attempt"),
        "more_pending": pending,
        "needs_rev": rec.get("rev") != _STAR_EXTRA_REV,
        "aliases": rec.get("aliases") or [],
        "real_name": rec.get("real_name") or "",
        "facts": rec.get("facts") or [],
        "career": {
            "active": career.get("active") or "",
            "detail": career.get("detail") or "",
            "professions": career.get("professions") or [],
        },
        "awards": rec.get("awards") or [],
        "achievements": rec.get("achievements") or [],
        "performances": rec.get("performances") or [],
        "known_for": rec.get("known_for") or "",
        "films": rec.get("films") or [],
        "production": rec.get("production") or "",
        "credits": rec.get("credits") or "",
        "rating": rec.get("rating") or "",
        "votes": _star_int(rec.get("votes")),
        "favorites": _star_int(rec.get("favorites")),
        "rank_high": _star_int(rec.get("rank_high")),
        "social": rec.get("social") or [],
        "links": rec.get("links") or [],
        "studios": rec.get("studios") or [],
        "studio_total": _star_int(rec.get("studio_total")),
        "about": rec.get("about") or "",
    }


def _star_add_fact(facts, label, value):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text or any(isinstance(item, dict) and item.get("label") == label for item in facts):
        return
    facts.append({"label": label, "value": text})


def _star_fetch_host(url, hosts, limit=900_000):
    allowed = {str(host).casefold() for host in hosts}
    if (urllib.parse.urlsplit(url).hostname or '').casefold() not in allowed:
        return '', 'redirect'
    try:
        result = _star_runtime_hub().request(url, {'Accept-Language':'en'}, ttl=12*3600, limit=limit)
        if (urllib.parse.urlsplit(result['url']).hostname or '').casefold() not in allowed:
            return '', 'redirect'
        return result['body'], ''
    except star_runtime.SourceError as error:
        return '', error.reason


def _star_slug_hyphen(name):
    slug = re.sub(r"[^a-z0-9]+", "-", str(name or "").casefold()).strip("-")
    if not 2 <= len(slug) <= 80:
        return ""
    return slug


def _star_keep_extra(old, rec):
    """Eine neue Babepedia-Fassung behält Text, Fakten und Fotoserien, die schon da sind."""
    if not isinstance(old, dict) or not old.get("ok"):
        return rec
    if not str(rec.get("about") or "").strip() and str(old.get("about") or "").strip():
        rec["about"] = old.get("about") or ""
        rec["about_source"] = old.get("about_source") or ""
    labels = {(item.get("label"),item.get("source") or "Babepedia") for item in (rec.get("facts") or []) if isinstance(item, dict)}
    facts = list(rec.get("facts") or [])
    for item in old.get("facts") or []:
        if isinstance(item, dict) and item.get("label") and (item.get("label"),item.get("source") or "Babepedia") not in labels:
            facts.append(item)
            labels.add((item.get("label"),item.get("source") or "Babepedia"))
    rec["facts"] = facts
    images = []
    seen = set()
    for url in list(rec.get("images") or []) + list(old.get("images") or []):
        if not isinstance(url, str):
            continue
        key = url.casefold()
        if key in seen:
            continue
        seen.add(key)
        images.append(url)
    rec["images"] = images
    rec["more_at"] = old.get("more_at")
    rec["biographies"] = old.get("biographies") or {}
    if isinstance(old.get("image_next"), list):
        rec["image_next"] = old.get("image_next")
    if old.get("more_rev") == 1:
        rec["more_rev"] = 1
    if old.get("image_seed") == 1:
        rec["image_seed"] = 1
    rec["about_source"] = rec.get("about_source") or old.get("about_source") or ""
    rec["image_full"] = not rec.get("image_next") and rec.get("more_rev") == 1
    return rec


def _star_freeones_bio(name):
    slug = _star_slug_hyphen(name)
    if not slug:
        return {}, []
    page, reason = _star_fetch_host(
        "https://www.freeones.com/%s/bio" % slug,
        ("www.freeones.com", "freeones.com"),
    )
    if not page:
        return {"reason": reason or "missing"}, []
    title_m = re.search(r"<title>([^<]+)</title>", page, re.I)
    title = _star_plain(title_m.group(1) if title_m else "")
    if not _star_same_name(name, title):
        return {"reason": "miss"}, []
    block = re.search(r'data-test="biography"[^>]*>(.*?)</div>', page, re.S | re.I)
    text = re.sub(r"\s+", " ", _star_about_text(block.group(1) if block else "")).strip()
    if _star_text_underage(text):
        return {"age": True}, []
    facts = []
    rank = re.search(r"ranked\s+#([\d,]+)", text, re.I)
    if rank:
        _star_add_fact(facts, "Rang (FreeOnes)", "#" + rank.group(1))
    sets = re.search(r"(\d+)\s+photo sets", text, re.I)
    if sets:
        _star_add_fact(facts, "Fotoserien", sets.group(1))
    videos = re.search(r"(\d+)\s+videos", text, re.I)
    if videos:
        _star_add_fact(facts, "Videos (FreeOnes)", videos.group(1))
    about = text if len(text) >= 80 else ""
    url = "https://www.freeones.com/%s/bio" % slug
    observed = getattr(_star_runtime_hub().local,"observed_at",None) or time.time()
    return {"about": about, "source": "FreeOnes", "url":url,"at":observed}, [{**row,"source":"FreeOnes","url":url,"at":observed} for row in facts]


def _star_grok_about(name):
    slug = re.sub(r"\s+", "_", str(name or "").strip()).replace("/", "").replace("\\", "")
    if len(slug) < 2:
        return ""
    url = "https://grokipedia.com/page/" + urllib.parse.quote(slug, safe="_-'")
    page, reason = _star_fetch_host(url, ("grokipedia.com", "www.grokipedia.com"), limit=400_000)
    if not page:
        return {"reason": reason or "missing"}
    title_m = re.search(r"<title>([^<]+)</title>", page, re.I)
    title = _star_plain(title_m.group(1) if title_m else "")
    if not _star_same_name(name, title.split("—")[0]):
        return ""
    start = page.casefold().find('class="article-body"')
    if start < 0:
        return ""
    start = page.find(">", start)
    if start < 0:
        return ""
    start += 1
    end = page.casefold().find("references", start)
    chunk = page[start:end if end > start else start + 24000]
    chunk = re.sub(r"(?i)</(p|div|h2|h3|li)>", "\n", chunk)
    text = _star_about_text(chunk).replace("''", "")
    text = re.sub(r"\[\d+\]", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if _star_text_underage(text):
        return {"age": True}
    if len(text) < 180:
        return ""
    return text


def _star_iafd_bits(url):
    if "iafd.com" not in str(url or "").casefold():
        return {}, []
    page, _reason = _star_fetch_host(url, ("www.iafd.com", "iafd.com"))
    if not page:
        return {}, []
    facts = []
    birthday = re.search(r'class="bioheading">\s*Birthday\s*</p>\s*<p class="biodata">(.*?)</p>', page, re.S | re.I)
    if birthday:
        born = _star_plain(birthday.group(1))
        if _star_blocks_images(born):
            year, month, day = _star_born_parts(born)
            if year and month and day:
                return {"age": True}, []
        for fact in _star_born_facts(born):
            _star_add_fact(facts, fact["label"], fact["value"])
    credits = re.search(r"Performer Credits\s*\((\d[\d,]*)\)", page, re.I)
    if credits:
        count = _star_int(credits.group(1).replace(",", ""))
        if count > 0:
            _star_add_fact(facts, "Einträge (IAFD)", f"{count:,}".replace(",", "."))
    observed = getattr(_star_runtime_hub().local,"observed_at",None) or time.time()
    return {}, [{**row,"source":"IAFD","url":url,"at":observed} for row in facts]


def _star_freeones_galleries(name):
    slug = _star_slug_hyphen(name)
    if not slug:
        return []
    page, _reason = _star_fetch_host(
        "https://www.freeones.com/%s/photos" % slug,
        ("www.freeones.com", "freeones.com"),
    )
    if not page:
        return None
    title_m = re.search(r"<title>([^<]+)</title>", page, re.I)
    if not title_m or not _star_same_name(name, _star_plain(title_m.group(1))):
        return []
    found = []
    seen = set()
    needle = "/%s/photos/" % slug
    for href in re.findall(r'href="([^"]+)"', page, re.I):
        path = href.split("?", 1)[0]
        if needle not in path.casefold():
            continue
        if path.startswith("/"):
            path = "https://www.freeones.com" + path
        if not path.startswith("https://www.freeones.com/") and not path.startswith("https://freeones.com/"):
            continue
        key = path.casefold()
        if key in seen:
            continue
        seen.add(key)
        found.append(path)
    found.extend(_star_freeones_page_links(page,'https://www.freeones.com/'+slug+'/photos'))
    found=list(dict.fromkeys(found))
    return found


def _star_freeones_page_links(page,url):
    """Follow only this performer's published album and index-page links."""
    parsed=urllib.parse.urlsplit(url);parts=parsed.path.strip('/').split('/')
    if len(parts)<2 or parts[1]!='photos':return []
    base='/'+parts[0]+'/photos';found=[]
    for href in re.findall(r'href=["\']([^"\']+)["\']',page or '',re.I):
        target=urllib.parse.urlsplit(urllib.parse.urljoin(url,html_unescape(href)))
        if target.scheme!='https' or target.hostname not in ('www.freeones.com','freeones.com'):continue
        if target.path.rstrip('/')!=base and not target.path.startswith(base+'/'):continue
        query=urllib.parse.parse_qs(target.query)
        if query and (set(query)-{'page'} or not all(re.fullmatch(r'\d+',v) for v in query.get('page',[]))):continue
        normalized=urllib.parse.urlunsplit((target.scheme,target.netloc,target.path,target.query,''))
        if normalized!=url:found.append(normalized)
    return list(dict.fromkeys(found))


def _star_gallery_urls(page):
    found = []
    seen = set()
    for url in re.findall(r"https://thumbs\.freeones\.com/photo/[^\"\s<>]+", page or "", re.I):
        lower = url.casefold()
        if any(bad in lower for bad in ("favicon", "static-assets", "fit-in/", "350x350", "0x230")):
            continue
        if not re.search(r"/(?:1\d{3}|[2-9]\d{3})x0/", lower):
            continue
        clean = url.split("?", 1)[0]
        name = clean.rsplit("/", 1)[-1].casefold()
        if not name or name in seen:
            continue
        seen.add(name)
        found.append(clean)
    return found


_star_more_queue = []
_star_more_lock = threading.Lock()
_star_more_started = False
_star_gallery_lock = threading.Lock()
_star_more_skip = None
_star_more_fail = {}
_star_more_skip_at = {}
_star_more_run = {"seen": 0, "filled": 0, "empty": 0}
_star_more_saved_at = 0
_STAR_PREFETCH_STEPS = 2
_STAR_PREFETCH_IMAGES = 24


def _star_more_load_skip():
    global _star_more_skip
    if _star_more_skip is not None:
        return
    sync = _star_extra_load().get("sync")
    row = sync.get("more") if isinstance(sync, dict) else {}
    if not isinstance(row, dict):
        row = {}
    _star_more_skip = {str(item) for item in (row.get("skip") or []) if item}
    _star_more_skip_at.update(row.get("skip_at") or {})
    fail = row.get("fail") if isinstance(row.get("fail"), dict) else {}
    _star_more_fail.clear()
    for item, tries in fail.items():
        try:
            _star_more_fail[str(item)] = int(tries)
        except (TypeError, ValueError):
            continue


def _star_more_note_fail(key):
    _star_more_load_skip()
    tries = int(_star_more_fail.get(key) or 0) + 1
    if tries >= 3:
        _star_more_fail.pop(key, None)
        _star_more_skip.add(key)
        _star_more_skip_at[key] = time.time()
        _star_more_run["empty"] = int(_star_more_run.get("empty") or 0) + 1
        return
    _star_more_fail[key] = tries


def _star_more_note_skip(key):
    _star_more_load_skip()
    _star_more_fail.pop(key, None)
    _star_more_skip.add(key)
    _star_more_skip_at[key] = time.time()
    _star_more_run["empty"] = int(_star_more_run.get("empty") or 0) + 1


def _star_more_flush(force=False):
    global _star_more_saved_at
    now = time.time()
    if not force and now - _star_more_saved_at < 30:
        return
    _star_more_load_skip()
    with _star_extra_lock:
        sync = _star_extra_load().setdefault("sync", {})
        if not isinstance(sync, dict):
            sync = {}
            _star_extra["sync"] = sync
        sync["more"] = {
            "skip": list(_star_more_skip),
            "skip_at":dict(_star_more_skip_at),
            "fail": dict(_star_more_fail),
            "seen": int(_star_more_run.get("seen") or 0),
        }
        _star_extra_save()
    _star_more_saved_at = now


def _star_more_images_due(rec):
    if not isinstance(rec, dict) or not rec.get("ok"):
        return False
    images = [
        item for item in (rec.get("images") or [])
        if isinstance(item, str) and item.startswith("https://") and not _is_video_url(item)
    ]
    if len(images) >= int(_star_runtime_hub().config["prefetch"]):
        return False
    if any(isinstance(item, str) and item for item in (rec.get("image_next") or [])):
        return True
    return "image_next" not in rec


def _star_more_needs(key):
    _star_more_load_skip()
    rec = _star_extra_get(key)
    if isinstance(rec, dict) and rec.get("reason") == "age":
        return False
    if _star_service().sources_due(key):
        return True
    if int(_star_more_fail.get(key) or 0) >= 3:
        return False
    if isinstance(rec, dict) and rec.get("ok"):
        if _star_about_dirty(rec) or rec.get("more_rev") != 1 or time.time()-float(rec.get("more_at") or 0)>_star_runtime_hub().interval():
            return True
        return _star_more_images_due(rec)
    _star_more_load_skip()
    if key in _star_more_skip and time.time()-float(_star_more_skip_at.get(key) or 0)>7*86400:
        _star_more_skip.discard(key)
        _star_more_fail.pop(key,None)
    return key not in _star_more_skip


def _star_more_ensure():
    global _star_more_started
    with _star_more_lock:
        if _star_more_started:
            return
        _star_more_started = True
    threading.Thread(target=_star_more_loop, name="star-more", daemon=True).start()


def _star_more_schedule(key, name, front=False):
    key = str(key or "").strip()
    name = str(name or "").strip()
    if not key or not name:
        return
    with _star_more_lock:
        if any(item[0] == key for item in _star_more_queue):
            return
        if not front and len(_star_more_queue) >= 80:
            return
        if front:
            _star_more_queue.insert(0, (key, name))
        else:
            _star_more_queue.append((key, name))
    _star_more_ensure()


def _more_fetch(key, name):
    job_wait()
    try:
        _star_more_one(key, name, prefetch=_STAR_PREFETCH_STEPS, save=False)
        _star_more_flush()
    except Exception:
        debug_log("server", "star", "mehr quelle fehler", {"err": traceback.format_exc()[-240:]})
    finally:
        job_done()


def _star_more_loop():
    saved = _job_cursor_get("more")
    resume_saved = saved if not saved.get("done") else {}
    cursor = int(saved.get("index") or 0)
    names = []
    nxt = float(saved.get("next") or 0)
    reset_on_wake = bool(saved.get("done"))
    if saved.get("done") and nxt > time.time():
        _star_more_run["next"] = nxt
        _star_more_run["cursor"] = int(saved.get("total") or saved.get("index") or 0)
        _star_more_run["queue"] = int(saved.get("total") or 0)
    else:
        _star_more_run["cursor"] = cursor
        _star_more_run["queue"] = int(saved.get("total") or 0)
    pool = futures.ThreadPoolExecutor(max_workers=3, thread_name_prefix="star-more")
    inflight = []
    while True:
        nxt = _star_runtime_hub().due("more", nxt)
        with _star_more_lock:
            item = _star_more_queue.pop(0) if _star_more_queue else None
        if item:
            job_wait()
            try:
                try:
                    _star_more_one(item[0], item[1], prefetch=_STAR_PREFETCH_STEPS, save=True)
                except Exception:
                    debug_log("server", "star", "mehr quelle fehler", {"err": traceback.format_exc()[-240:]})
            finally:
                job_done()
            time.sleep(0.05)
            continue
        if nxt > time.time():
            time.sleep(5)
            continue
        if reset_on_wake:
            cursor = 0
            names = []
            reset_on_wake = False
            nxt = 0
            _star_more_run["next"] = 0
        if cursor >= len(names):
            for fut in inflight:
                try:
                    fut.result()
                except Exception:
                    pass
            inflight = []
            if names:
                when = time.time() + _star_runtime_hub().interval()
                nxt = when
                _star_more_run["next"] = when
                _star_more_run["cursor"] = len(names)
                _star_more_run["queue"] = len(names)
                _star_more_run["current"] = ""
                _job_cursor_put("more", {
                    "index": len(names),
                    "total": len(names),
                    "done": True,
                    "next": when,
                    "key": "",
                }, force=True)
                names = []
                cursor = 0
                continue
            try:
                names = _babe_queue()
                if resume_saved:
                    cursor = star_store.resume_position(names, resume_saved)
                    resume_saved = {}
            except Exception:
                names = []
                debug_log("server", "star", "mehr quelle liste", {"err": traceback.format_exc()[-200:]})
            nxt = 0
            _star_more_run["next"] = 0
            if cursor > len(names):
                cursor = 0
            if not names:
                time.sleep(20)
            continue
        key, name = names[cursor]
        cursor += 1
        _star_more_run["cursor"] = cursor
        _star_more_run["queue"] = len(names)
        try:
            due = _star_more_needs(key)
        except Exception:
            due = False
        if not due:
            if cursor % 200 == 0:
                _star_commit_cursor("more", names, cursor, inflight)
                time.sleep(0.002)
            continue
        _star_more_run["current"] = name
        _star_more_run["seen"] = int(_star_more_run.get("seen") or 0) + 1
        inflight.append(pool.submit(_more_fetch, key, name))
        if len(inflight) >= 3:
            try:
                inflight.pop(0).result()
            except Exception:
                pass
        if cursor % 8 == 0:
            _star_commit_cursor("more", names, cursor, inflight)



def _star_more_prefetch(key, steps, save):
    if int(steps)<=0:
        return
    target = int(_star_runtime_hub().config["prefetch"])
    steps = max(int(steps),min(8,(target+11)//12))
    for _ in range(max(0, int(steps))):
        rec = _star_extra_get(key) or {}
        images = [item for item in (rec.get("images") or []) if isinstance(item, str)]
        pages = [item for item in (rec.get("image_next") or []) if isinstance(item, str)]
        if len(images) >= target or not pages:
            break
        _star_gallery_step(key, save=False)
    with _star_gallery_lock:
        rec = _star_extra_get(key)
        if isinstance(rec, dict) and rec.get("ok") and "image_next" in rec:
            rec["image_seed"] = 1
            _star_extra_put(key, rec, save=save)


def _star_more_one(key, name, prefetch=2, save=True):
    rec = _star_extra_get(key)
    if isinstance(rec, dict) and rec.get("reason") == "age":
        return
    if isinstance(rec, dict) and rec.get("ok") and _star_about_dirty(rec):
        rec["about"] = ""
        rec["about_source"] = ""
        rec["more_rev"] = 0
        rec["facts"] = [
            item for item in (rec.get("facts") or [])
            if not (isinstance(item, dict) and item.get("label") == "Rang (FreeOnes)")
        ]
        _star_extra_put(key, rec, save=False)
        rec = _star_extra_get(key) or rec
    fresh_more = isinstance(rec,dict) and time.time()-float(rec.get("more_at") or 0)<_star_runtime_hub().interval()
    if isinstance(rec, dict) and rec.get("ok") and rec.get("more_rev") == 1 and not _star_about_dirty(rec) and fresh_more:
        if not _star_more_images_due(rec):
            return
        if "image_next" not in rec:
            try:
                found = _star_freeones_galleries(name)
            except Exception:
                found = None
            if found is None:
                _star_more_note_fail(key)
                return
            with _star_gallery_lock:
                current = _star_extra_get(key) or rec
                if isinstance(current, dict) and current.get("ok") and "image_next" not in current:
                    current["image_next"] = found
                    current["image_full"] = not found
                    _star_extra_put(key, current, save=False)
        _star_more_prefetch(key, prefetch, save)
        return
    about = str(rec.get("about") or "").strip() if isinstance(rec, dict) and rec.get("ok") and fresh_more else ""
    source = str(rec.get("about_source") or "") if isinstance(rec, dict) and rec.get("ok") else ""
    facts = []
    texts = {}
    age = False
    timeouts = 0
    if not about:
        try:
            got, extra_facts = _star_freeones_bio(name)
        except Exception:
            got, extra_facts = {"reason": "timeout"}, []
        if got.get("age"):
            age = True
        elif got.get("reason") in ("timeout","http","rate-limit","blocked","redirect"):
            timeouts += 1
        else:
            facts.extend(extra_facts)
            if got.get("about"):
                about = got["about"]
                source = got.get("source") or "FreeOnes"
                texts["freeones"] = {"text":about,"source":source,"url":got.get("url"),"at":got.get("at")}
    if not age:
        try:
            long_text = _star_grok_about(name)
        except Exception:
            long_text = {"reason": "timeout"}
        if isinstance(long_text, dict) and long_text.get("age"):
            age = True
        elif isinstance(long_text, dict) and long_text.get("reason") in ("timeout","http","rate-limit","blocked","redirect"):
            timeouts += 1
        elif isinstance(long_text, str) and long_text:
            texts["grokipedia"] = {"text":long_text,"source":"Grokipedia","url":"https://grokipedia.com/page/"+urllib.parse.quote(name.replace(" ","_"),safe="_-"),"at":getattr(_star_runtime_hub().local,"observed_at",None) or time.time()}
            if len(long_text)>len(about)+80:
                about = long_text
                source = "Grokipedia"
    if not age and isinstance(rec, dict):
        for link in rec.get("links") or []:
            if not isinstance(link, dict) or link.get("label") != "IAFD":
                continue
            try:
                got, extra_facts = _star_iafd_bits(link.get("url") or "")
            except Exception:
                got, extra_facts = {}, []
            if got.get("age"):
                age = True
                break
            facts.extend(extra_facts)
            break
    galleries = None
    if not age:
        try:
            galleries = _star_freeones_galleries(name)
        except Exception:
            galleries = None
    if age:
        dropped = {
            "ok": False,
            "reason": "age",
            "url": (rec or {}).get("url") or "" if isinstance(rec, dict) else "",
            "images": [],
            "image_full": True,
            "image_seed": 1,
            "at": time.time(),
            "rev": _STAR_EXTRA_REV,
            "more_rev": 1,
        }
        _star_extra_put(key, dropped, save=True)
        _star_more_note_skip(key)
        _star_drop_person_name(name)
        debug_log("server", "star", "mehr quelle", {"ok": False, "reason": "age"})
        return
    text_done = bool(about) or timeouts == 0
    useful = bool(about or facts or galleries)
    had_ok = isinstance(rec, dict) and rec.get("ok")
    if not had_ok and not useful:
        if text_done and galleries is not None:
            _star_more_note_skip(key)
        else:
            _star_more_note_fail(key)
        return
    wrote_about = False
    with _star_gallery_lock:
        current = _star_extra_get(key)
        if not isinstance(current, dict) or not current.get("ok"):
            current = {
                "ok": True,
                "url": "",
                "images": [],
                "facts": [],
                "at": time.time(),
                "rev": _STAR_EXTRA_REV,
            }
        if not str(current.get("about") or "").strip() and about:
            current["about"] = about
            current["about_source"] = source
            wrote_about = True
        elif about and len(about) > len(str(current.get("about") or "")) + 80:
            current["about"] = about
            current["about_source"] = source
            wrote_about = True
        current["biographies"] = {**(current.get("biographies") or {}),**texts}
        labels = {(item.get("label"),item.get("source")) for item in (current.get("facts") or []) if isinstance(item, dict)}
        merged = list(current.get("facts") or [])
        for fact in facts:
            pair = (fact.get("label"),fact.get("source"))
            if pair in labels:
                merged = [row for row in merged if (row.get("label"),row.get("source"))!=pair]
            merged.append(fact)
            labels.add(pair)
        current["facts"] = merged
        if galleries is not None and "image_next" not in current:
            current["image_next"] = galleries
        if text_done:
            current["more_rev"] = 1
            current["more_at"] = time.time()
            current["more_pending"] = False
        current["image_full"] = "image_next" in current and not current.get("image_next")
        current["rev"] = current.get("rev") or _STAR_EXTRA_REV
        _star_extra_put(key, current, save=False)
        stored_about = str(current.get("about") or "")
        gallery_count = len(current.get("image_next") or [])
        have_index = "image_next" in current
    if have_index:
        _star_more_prefetch(key, prefetch, False)
    if text_done or useful:
        _star_more_load_skip()
        _star_more_skip.discard(key)
        _star_more_fail.pop(key, None)
    elif timeouts or galleries is None:
        _star_more_note_fail(key)
    if wrote_about:
        _star_more_run["filled"] = int(_star_more_run.get("filled") or 0) + 1
        _babe_translate(key, name)
    if save:
        _star_more_flush(force=True)
    debug_log("server", "star", "mehr quelle", {
        "name": name,
        "about": len(stored_about),
        "source": source,
        "galleries": gallery_count,
    })


_star_more_one_unlocked = _star_more_one


def _star_more_one(key, name, prefetch=2, save=True):
    with _star_runtime_hub().key_lock("profile-more:"+key):
        result = _star_more_one_unlocked(key,name,prefetch,save)
        _star_service().enrich_sources(key,name)
        return result


def _star_gallery_step(key, save=True):
    with _star_gallery_lock:
        rec = _star_extra_get(key)
        if not isinstance(rec, dict) or not rec.get("ok"):
            return
        pages = [item for item in (rec.get("image_next") or []) if isinstance(item, str)]
        if not pages:
            rec["image_full"] = True
            rec["image_seed"] = 1
            _star_extra_put(key, rec, save=save)
            return
        url = pages[0]
    page, _reason = _star_fetch_host(url, ("www.freeones.com", "freeones.com"))
    if not page:
        # Keep the pending URL on transient errors instead of losing an album.
        if _reason in ("timeout","http","blocked","rate-limit","redirect"):
            raise ValueError("Die Galerieseite konnte nicht geladen werden.")
        urls = []
    else:
        urls = _star_gallery_urls(page)
    with _star_gallery_lock:
        rec = _star_extra_get(key)
        if not isinstance(rec, dict) or not rec.get("ok"):
            return
        pages = [item for item in (rec.get("image_next") or []) if isinstance(item, str) and item != url]
        visited=set(rec.get('image_pages_seen') or []);visited.add(url)
        for target in _star_freeones_page_links(page,url) if page else []:
            if target not in visited and target not in pages:pages.append(target)
        images = [item for item in (rec.get("images") or []) if isinstance(item, str)]
        have = {item.casefold() for item in images}
        for image in urls:
            if image.casefold() in have:
                continue
            have.add(image.casefold())
            images.append(image)
        rec["images"] = images
        rec["image_next"] = pages
        rec['image_pages_seen']=list(visited)
        rec["image_full"] = not pages
        _star_extra_put(key, rec, save=save)


def _star_enrich(key, name, force=False, save=True, log=True):
    cached = _star_extra_get(key)
    fresh = cached and not _star_extra_stale(cached) and cached.get("rev") == _STAR_EXTRA_REV
    if cached and fresh and not force:
        if log and _star_more_due(key):
            _star_more_schedule(key, name, front=True)
        return _star_extra_public(cached)
    if cached and force and fresh and cached.get("image_full") and cached.get("more_rev") == 1:
        return _star_extra_public(cached)
    with _star_fetch_lock:
        pending = _star_fetching.get(key)
        if pending is None:
            pending = threading.Event()
            _star_fetching[key] = pending
            owner = True
        else:
            owner = False
    if not owner:
        pending.wait(12)
        cached = _star_extra_get(key)
        return _star_extra_public(cached) if cached else {"ok": False, "stale": True, "source": ""}
    started = time.time()
    try:
        url = _star_babe_url(name)
        if not url:
            rec = {"ok": False, "reason": "missing", "url": "", "images": [], "image_full": True, "at": time.time(), "rev": _STAR_EXTRA_REV}
        else:
            page, reason = _star_fetch_html(url)
            if not page:
                rec = {
                    "ok": False,
                    "reason": reason or "missing",
                    "url": url,
                    "images": [],
                    "image_full": reason != "timeout",
                    "at": time.time(),
                    "rev": _STAR_EXTRA_REV,
                }
            else:
                rec = _star_parse_babepedia(page, name, url)
                rec["at"] = getattr(_star_runtime_hub().local,"observed_at",None) or time.time()
                rec["rev"] = _STAR_EXTRA_REV
                rec["facts"] = [{**row,"source":"Babepedia","url":url,"at":rec["at"]} for row in rec.get("facts") or []]
                rec = _star_keep_extra(cached, rec)
        if not rec.get("ok") and rec.get("reason") != "age" and isinstance(cached,dict) and cached.get("ok"):
            rec = {**cached,"last_error":rec.get("reason") or "missing","last_attempt":time.time()}
        with _star_gallery_lock:
            latest = _star_extra_get(key)
            if rec.get("ok") and isinstance(latest,dict) and latest.get("ok"):
                rec = _star_keep_extra(latest,rec)
            _star_extra_put(key, rec, save=save)
        if rec.get("reason") == "age":
            _star_drop_person_name(name)
            if log:
                debug_log("server", "star", "enrich", {
                    "ok": False,
                    "reason": "age",
                    "ms": int((time.time() - started) * 1000),
                })
        else:
            if log and rec.get("reason") != "age" and (_star_more_due(key) or not rec.get("ok")):
                _star_more_schedule(key, name, front=True)
            if log:
                debug_log("server", "star", "enrich", {
                    "name": name,
                    "ok": bool(rec.get("ok")),
                    "images": len(rec.get("images") or []),
                    "reason": rec.get("reason") or "",
                    "ms": int((time.time() - started) * 1000),
                })
        return _star_extra_public(rec)
    finally:
        with _star_fetch_lock:
            event = _star_fetching.pop(key, None)
        if event:
            event.set()


_DE_MARKERS = {"und", "der", "die", "das", "sie", "ist", "mit", "für", "von", "eine", "einer", "nicht", "auch", "auf", "den", "dem", "ein", "als", "bei", "nach", "aus", "wurde", "ihre", "ihr", "sind", "wird", "oder", "dass"}
_EN_MARKERS = {"the", "and", "she", "her", "his", "with", "for", "from", "was", "were", "that", "this", "born", "actress", "actor", "model", "known", "began", "career", "who", "has"}
_DE_PHRASES = (
    ("pornografische Schauspielerin", "Pornodarstellerin"),
    ("pornografischer Schauspieler", "Pornodarsteller"),
    ("Pornografische Schauspielerin", "Pornodarstellerin"),
    ("Pornografischer Schauspieler", "Pornodarsteller"),
    ("Erwachsenenfilmstar", "Pornostar"),
    ("Erwachsenenfilme", "Pornofilme"),
    ("Erwachsenenfilm", "Pornofilm"),
    ("Erwachsenenunterhaltungsindustrie", "Pornoindustrie"),
    ("erwachsene Unterhaltungsindustrie", "Pornoindustrie"),
    ("Erwachsenenunterhalterin", "Darstellerin"),
    ("Erwachsenenunterhalter", "Darsteller"),
)
_CHIP_DE = {
    "pornstar": "Pornostar",
    "porn star": "Pornostar",
    "adult model": "Model",
    "model": "Model",
    "actress": "Darstellerin",
    "actor": "Darsteller",
    "adult film actress": "Pornodarstellerin",
    "adult film actor": "Pornodarsteller",
    "director": "Regie",
    "producer": "Produktion",
    "solo": "Solo",
    "girl/girl": "Frau/Frau",
    "boy/girl": "Mann/Frau",
    "anal": "Anal",
    "oral": "Oral",
    "lesbian": "Lesbisch",
    "threesome": "Dreier",
    "group": "Gruppe",
    "present": "heute",
    "russian": "Russisch",
    "caucasian": "Kaukasisch",
    "straight": "Hetero",
    "brown": "Braun",
    "blue": "Blau",
    "slim": "Schlank",
    "petite": "Zierlich",
    "real/natural": "Echt",
    "natural": "Natürlich",
    "adult model": "Model",
    "porn star": "Pornostar",
    "nudity": "Nacktheit",
    "nudity (full)": "Nacktheit (voll)",
    "masturbation": "Masturbation",
    "blonde": "Blond",
    "black": "Schwarz",
    "green": "Grün",
    "hazel": "Grünbraun",
    "gray": "Grau",
    "grey": "Grau",
    "red": "Rot",
    "shaved": "Rasiert",
    "hairy": "Behaart",
    "curvy": "Kurvig",
    "athletic": "Athletisch",
    "average": "Durchschnitt",
    "enhanced": "Vergrößert",
    "bisexual": "Bisexuell",
    "gay": "Schwul",
}
_star_lang_lock = threading.Lock()
_star_lang_jobs = {}


def _word_hits(text, words):
    found = re.findall(r"[A-Za-zÄÖÜäöüß']+", str(text or "").casefold())
    return sum(1 for word in found if word in words)


def _mostly_german(text):
    if len(str(text or "")) < 24:
        return False
    return _word_hits(text, _DE_MARKERS) >= 4 and _word_hits(text, _DE_MARKERS) > _word_hits(text, _EN_MARKERS)


def _should_translate(text):
    text = str(text or "").strip()
    if len(text) < 3 or _mostly_german(text):
        return False
    if re.fullmatch(r"[\d\s.,:/%+\-–—cm]+", text, re.I):
        return False
    return bool(re.search(r"[A-Za-z]{3,}", text))


def _polish_german(text):
    text = str(text or "").strip()
    for old, new in _DE_PHRASES:
        text = text.replace(old, new)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text.strip()


def _split_chunks(text, limit):
    text = str(text or "").strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    parts = []
    buf = ""
    for piece in re.split(r"(?<=[.!?])\s+|\n+", text):
        piece = piece.strip()
        if not piece:
            continue
        if len(piece) > limit:
            if buf:
                parts.append(buf)
                buf = ""
            for start in range(0, len(piece), limit):
                parts.append(piece[start:start + limit])
            continue
        if buf and len(buf) + 1 + len(piece) > limit:
            parts.append(buf)
            buf = piece
        else:
            buf = (buf + " " + piece).strip()
    if buf:
        parts.append(buf)
    return parts


def _gtx_text(payload):
    if isinstance(payload, dict):
        parts = []
        for row in payload.get("sentences") or []:
            if isinstance(row, dict) and row.get("trans"):
                parts.append(str(row["trans"]))
        return "".join(parts).strip()
    parts = []
    rows = payload[0] if isinstance(payload, list) and payload else []
    for row in rows or []:
        if isinstance(row, list) and row and row[0]:
            parts.append(str(row[0]))
    return "".join(parts).strip()


_tr_cool_until = 0.0
_tr_strikes = 0


def _tr_blocked():
    return time.time() < _tr_cool_until


def _tr_note_limit():
    global _tr_cool_until
    _tr_cool_until = max(_tr_cool_until, time.time() + 75)


def _gtx(text):
    if _tr_blocked():
        return ""
    query = urllib.parse.urlencode({
        "client": "at",
        "dt": "t",
        "dj": "1",
        "sl": "en",
        "tl": "de",
        "q": text,
    })
    try:
        payload = _star_runtime_hub().json('https://translate.googleapis.com/translate_a/single?' + query, {'User-Agent':'Mozilla/5.0'}, ttl=0)
    except star_runtime.SourceError as error:
        if error.reason == 'rate-limit':
            _tr_note_limit()
        return ''
    return _gtx_text(payload)


def _mymemory(text):
    if _tr_blocked():
        return ""
    query = urllib.parse.urlencode({"q": text[:450], "langpair": "en|de"})
    try:
        payload = _star_runtime_hub().json('https://api.mymemory.translated.net/get?' + query, {'User-Agent':'Mozilla/5.0'}, ttl=0)
    except star_runtime.SourceError as error:
        if error.reason == 'rate-limit':
            _tr_note_limit()
        return ''
    out = str((payload.get("responseData") or {}).get("translatedText") or "").strip()
    if not out or "MYMEMORY WARNING" in out.upper() or "QUERY LENGTH" in out.upper():
        return ""
    return out


def _translate_en_de(text, deadline):
    text = str(text or "").strip()
    if not text or time.time() > deadline:
        return ""
    chip = _CHIP_DE.get(text.casefold())
    if chip:
        return chip
    if not _should_translate(text):
        return text if _mostly_german(text) else ""
    pieces = []
    for chunk in _split_chunks(text, 1400):
        if time.time() > deadline:
            return ""
        key = star_store.text_key(chunk)
        cached = _star_runtime_hub().store.cached("translation", key)
        piece = cached.get("text") if cached else ""
        if not piece:
            piece = _gtx(chunk)
            if not piece and not _tr_blocked():
                # MyMemory accepts shorter input. Never silently cut a long
                # paragraph to its first 450 characters and call that complete.
                translated = []
                for part in star_store.utf8_chunks(chunk, 450):
                    part_key = star_store.text_key("mymemory:"+part)
                    previous = _star_runtime_hub().store.cached("translation",part_key)
                    got = previous.get("text") if previous else _mymemory(part)
                    if got and not previous:
                        _star_runtime_hub().store.cache("translation",part_key,{"text":got},365*86400)
                    if not got:
                        translated = []
                        break
                    translated.append(got)
                piece = " ".join(translated)
        if not piece:
            _tr_note_limit()
            return ""
        if piece.strip() == chunk.strip() and _word_hits(chunk, _EN_MARKERS) >= 3:
            return ""
        if not cached:
            _star_runtime_hub().store.cache("translation", key, {"text":piece}, 365*86400)
        pieces.append(piece.strip())
    joiner = "\n" if "\n" in text else " "
    return _polish_german(joiner.join(pieces))


def _star_lang_key(profile):
    ident = str(profile.get("id") or "").strip()
    if ident:
        return ident[:80]
    return _star_trend_id(profile.get("name") or "")


def _star_lang_blob(profile):
    extra = profile.get("extra") if isinstance(profile.get("extra"), dict) and profile["extra"].get("ok") else {}
    career = extra.get("career") if isinstance(extra.get("career"), dict) else {}
    bits = [
        profile.get("bio") or "",
        extra.get("about") or "",
        extra.get("credits") or "",
        extra.get("production") or "",
        extra.get("known_for") or "",
        career.get("active") or "",
        career.get("detail") or "",
    ]
    bits.extend(career.get("professions") or [])
    bits.extend(extra.get("awards") or [])
    bits.extend(extra.get("achievements") or [])
    for row in extra.get("performances") or []:
        if isinstance(row, dict):
            bits.append(row.get("label") or "")
            bits.append(row.get("acts") or "")
    for row in extra.get("facts") or []:
        if isinstance(row, dict):
            bits.append(row.get("value") or "")
    for row in extra.get("social") or []:
        if isinstance(row, dict):
            bits.append(row.get("note") or "")
    return "\n".join(str(bit or "") for bit in bits)


def _star_lang_stamp(profile):
    return hashlib.sha256(_star_lang_blob(profile).encode("utf-8")).hexdigest()[:20]


def _star_lang_get(key):
    if not key:
        return None
    rec = _star_extra_load().get("lang", {}).get(key)
    return rec if isinstance(rec, dict) else None


_STAR_LANG_CAP = 48000
_star_lang_batch = {
    "running": False,
    "total": 0,
    "ready": 0,
    "failed": 0,
    "skipped": 0,
}
_star_lang_batch_lock = threading.Lock()
_lang_batch_alive = False


def _star_lang_put(key, rec, save=True):
    if not key or not isinstance(rec, dict):
        return
    with _star_extra_lock:
        store = _star_extra_load()
        lang = store.get("lang")
        if not isinstance(lang, dict):
            lang = {}
            store["lang"] = lang
        lang[key] = rec
        if save:
            _star_extra_save()


def _star_lang_fresh(rec, stamp):
    if not isinstance(rec, dict) or rec.get("stamp") != stamp:
        return False
    age = time.time() - float(rec.get("at") or 0)
    if rec.get("ok"):
        return age < 30 * 24 * 3600
    return age < 2 * 3600


def _star_lang_public(rec):
    if not isinstance(rec, dict) or not rec.get("ok"):
        return {"ok": False, "reason": (rec or {}).get("reason") or "missing"}
    return {
        "ok": True,
        "bio": rec.get("bio") or "",
        "about": rec.get("about") or "",
        "credits": rec.get("credits") or "",
        "production": rec.get("production") or "",
        "known_for": rec.get("known_for") or "",
        "career": {
            "active": rec.get("active") or "",
            "detail": rec.get("detail") or "",
            "professions": rec.get("professions") or [],
        },
        "awards": rec.get("awards") or [],
        "achievements": rec.get("achievements") or [],
        "performances": rec.get("performances") or [],
        "facts": rec.get("facts") or [],
        "social": rec.get("social") or [],
    }


def _lang_field_done(source, translated):
    source = str(source or "").strip()
    translated = str(translated or "").strip()
    if not source or not _should_translate(source):
        return True
    folded = source.casefold()
    chip = _CHIP_DE.get(folded)
    if chip:
        return translated.casefold() == chip.casefold()
    if "," in source and len(source) < 160:
        parts = [part.strip() for part in source.split(",") if part.strip()]
        if parts and all(len(part) < 48 for part in parts):
            for part in parts:
                word = _CHIP_DE.get(part.casefold())
                if word and word.casefold() not in translated.casefold():
                    return False
            if any(_CHIP_DE.get(part.casefold()) for part in parts):
                return True
    if len(source) < 48 and _word_hits(source, _EN_MARKERS) < 2:
        return True
    if not translated:
        return False
    if _mostly_german(translated):
        return True
    if translated.casefold() == folded and _word_hits(source, _EN_MARKERS) >= 2:
        return False
    if _word_hits(translated, _EN_MARKERS) >= 3 and _word_hits(translated, _EN_MARKERS) > _word_hits(translated, _DE_MARKERS):
        return False
    return True


def _lang_record_covers(rec, profile):
    if not isinstance(rec, dict):
        return False
    extra = profile.get("extra") if isinstance(profile.get("extra"), dict) and profile["extra"].get("ok") else {}
    career = extra.get("career") if isinstance(extra.get("career"), dict) else {}
    pairs = (
        (profile.get("bio"), rec.get("bio")),
        (extra.get("about"), rec.get("about")),
        (extra.get("credits"), rec.get("credits")),
        (extra.get("production"), rec.get("production")),
        (extra.get("known_for"), rec.get("known_for")),
        (career.get("active"), rec.get("active")),
        (career.get("detail"), rec.get("detail")),
    )
    for source, translated in pairs:
        if not _lang_field_done(source, translated):
            return False
    stored_rows = rec.get("performances") or []
    for index, row in enumerate(extra.get("performances") or []):
        if not isinstance(row, dict):
            continue
        got = stored_rows[index] if index < len(stored_rows) and isinstance(stored_rows[index], dict) else {}
        if not _lang_field_done(row.get("acts") or "", got.get("acts") or ""):
            return False
    stored_facts = rec.get("facts") or []
    for index, row in enumerate(extra.get("facts") or []):
        if not isinstance(row, dict):
            continue
        got = stored_facts[index] if index < len(stored_facts) and isinstance(stored_facts[index], dict) else {}
        if not _lang_field_done(row.get("value") or "", got.get("value") or ""):
            return False
    return True


def _star_lang_cached(key, profile):
    rec = _star_lang_get(key)
    if not isinstance(rec, dict) or not rec.get("ok"):
        return None
    if not _star_lang_fresh(rec, _star_lang_stamp(profile)):
        return None
    if not _lang_record_covers(rec, profile):
        return None
    return _star_lang_public(rec)


def _translate_one(text, deadline):
    text = str(text or "").strip()
    if not text:
        return ""
    if not _should_translate(text):
        return text
    if len(text) < 160 and "," in text:
        parts = [part.strip() for part in text.split(",") if part.strip()]
        if parts and all(len(part) < 48 for part in parts):
            done = []
            for part in parts:
                chip = _CHIP_DE.get(part.casefold())
                if chip:
                    done.append(chip)
                elif _should_translate(part):
                    done.append(_translate_en_de(part, deadline) or part)
                else:
                    done.append(part)
            return ", ".join(done)
    return _translate_en_de(text, deadline)


def _translate_keep(source, old, deadline):
    source = str(source or "")
    old = str(old or "")
    if old and _lang_field_done(source, old):
        return old
    return _translate_one(source, deadline)


def _translate_profile(profile, deadline, previous=None):
    extra = profile.get("extra") if isinstance(profile.get("extra"), dict) and profile["extra"].get("ok") else {}
    career = extra.get("career") if isinstance(extra.get("career"), dict) else {}
    previous = previous if isinstance(previous, dict) else {}
    old_career = {
        "active": previous.get("active") or "",
        "detail": previous.get("detail") or "",
        "professions": previous.get("professions") or [],
    }
    rec = {
        "ok": False,
        "reason": "",
        "stamp": _star_lang_stamp(profile),
        "at": time.time(),
        "about": _translate_keep(extra.get("about") or "", previous.get("about") or "", deadline),
        "bio": _translate_keep(profile.get("bio") or "", previous.get("bio") or "", deadline),
        "credits": _translate_keep(extra.get("credits") or "", previous.get("credits") or "", deadline),
        "production": _translate_keep(extra.get("production") or "", previous.get("production") or "", deadline),
        "known_for": _translate_keep(extra.get("known_for") or "", previous.get("known_for") or "", deadline),
        "active": _translate_keep(career.get("active") or "", old_career["active"], deadline),
        "detail": _translate_keep(career.get("detail") or "", old_career["detail"], deadline),
        "professions": [],
        "awards": [],
        "achievements": [],
        "performances": [],
        "facts": [],
        "social": [],
    }
    old_names = old_career["professions"] if isinstance(old_career["professions"], list) else []
    for index, name in enumerate(career.get("professions") or []):
        old = old_names[index] if index < len(old_names) else ""
        rec["professions"].append(_translate_keep(name, old, deadline) or str(name))
    old_lines = previous.get("awards") if isinstance(previous.get("awards"), list) else []
    for index, line in enumerate(extra.get("awards") or []):
        old = old_lines[index] if index < len(old_lines) else ""
        rec["awards"].append(_translate_keep(line, old, deadline) or str(line))
    old_lines = previous.get("achievements") if isinstance(previous.get("achievements"), list) else []
    for index, line in enumerate(extra.get("achievements") or []):
        old = old_lines[index] if index < len(old_lines) else ""
        rec["achievements"].append(_translate_keep(line, old, deadline) or str(line))
    old_rows = previous.get("performances") if isinstance(previous.get("performances"), list) else []
    for index, row in enumerate(extra.get("performances") or []):
        if not isinstance(row, dict):
            continue
        old = old_rows[index] if index < len(old_rows) and isinstance(old_rows[index], dict) else {}
        rec["performances"].append({
            "label": _translate_keep(row.get("label") or "", old.get("label") or "", deadline) or str(row.get("label") or ""),
            "acts": _translate_keep(row.get("acts") or "", old.get("acts") or "", deadline) or str(row.get("acts") or ""),
        })
    old_rows = previous.get("facts") if isinstance(previous.get("facts"), list) else []
    for index, row in enumerate(extra.get("facts") or []):
        if not isinstance(row, dict):
            continue
        old = old_rows[index] if index < len(old_rows) and isinstance(old_rows[index], dict) else {}
        value = str(row.get("value") or "")
        rec["facts"].append({
            "label": str(row.get("label") or ""),
            "value": _translate_keep(value, old.get("value") or "", deadline) or value,
        })
    old_rows = previous.get("social") if isinstance(previous.get("social"), list) else []
    for index, row in enumerate(extra.get("social") or []):
        if not isinstance(row, dict):
            continue
        old = old_rows[index] if index < len(old_rows) and isinstance(old_rows[index], dict) else {}
        note = str(row.get("note") or "")
        rec["social"].append({
            "label": str(row.get("label") or ""),
            "value": str(row.get("value") or ""),
            "note": _translate_keep(note, old.get("note") or "", deadline) or note,
        })
    blob = _star_lang_blob(profile).strip()
    if not blob:
        rec["ok"] = True
        rec["reason"] = "empty"
    elif _lang_record_covers(rec, profile):
        rec["ok"] = True
    else:
        rec["ok"] = False
        rec["reason"] = "timeout"
    return rec


def _star_lang_run(key, profile, event):
    try:
        previous = _star_lang_get(key)
        rec = _translate_profile(profile, time.time() + 40, previous if isinstance(previous, dict) else None)
        _star_lang_put(key, rec)
        debug_log("server", "star", "sprache", {
            "name": profile.get("name") or "",
            "ok": bool(rec.get("ok")),
            "reason": rec.get("reason") or "",
        })
    except Exception:
        debug_log("server", "star", "sprache fehler", {"err": traceback.format_exc()[-400:]})
    finally:
        with _star_lang_lock:
            _star_lang_jobs.pop(key, None)
        event.set()


def star_lang_payload(star_id, name, fresh=False):
    profile = star_profile(star_id, name, enrich=False)
    if profile.get("underage"):
        return {"ok": False, "pending": False, "lang": {"ok": False, "reason": "age"}}
    key = _star_lang_key(profile)
    stamp = _star_lang_stamp(profile)
    cached = _star_lang_get(key)
    good = (
        isinstance(cached, dict)
        and cached.get("ok")
        and _star_lang_fresh(cached, stamp)
        and _lang_record_covers(cached, profile)
    )
    if good:
        return {"ok": True, "pending": False, "lang": _star_lang_public(cached)}
    if not _star_lang_blob(profile).strip():
        empty = {"ok": True, "reason": "empty", "stamp": stamp, "at": time.time(), "bio": "", "about": ""}
        _star_lang_put(key, empty)
        return {"ok": True, "pending": False, "lang": _star_lang_public(empty)}
    with _star_lang_lock:
        running = _star_lang_jobs.get(key)
    if running is not None and not running.is_set():
        return {"ok": True, "pending": True, "lang": None}
    if (
        not fresh
        and isinstance(cached, dict)
        and not cached.get("ok")
        and cached.get("stamp") == stamp
        and time.time() - float(cached.get("at") or 0) < 90
    ):
        return {"ok": True, "pending": False, "lang": _star_lang_public(cached)}
    with _star_lang_lock:
        event = _star_lang_jobs.get(key)
        if event is None or event.is_set():
            event = threading.Event()
            _star_lang_jobs[key] = event
            threading.Thread(target=_star_lang_run, args=(key, profile, event), name="star-lang", daemon=True).start()
    if event.wait(0.05):
        cached = _star_lang_get(key)
        if isinstance(cached, dict) and cached.get("ok") and _star_lang_fresh(cached, stamp) and _lang_record_covers(cached, profile):
            return {"ok": True, "pending": False, "lang": _star_lang_public(cached)}
        if isinstance(cached, dict) and not cached.get("ok") and cached.get("stamp") == stamp:
            return {"ok": True, "pending": False, "lang": _star_lang_public(cached)}
    return {"ok": True, "pending": True, "lang": None}


def _star_lang_targets():
    """Profile mit vorhandenem Text. Kein Babepedia-Lauf und keine leeren Karten."""
    index = star_index()
    work = []
    seen = set()
    for raw in index.get("rows") or []:
        if not str(raw.get("bio") or "").strip():
            continue
        ident = str(raw.get("id") or "").strip()
        if not ident or ident in seen:
            continue
        seen.add(ident)
        work.append((ident, str(raw.get("name") or "").strip()))
    for key, rec in list((_star_extra_load().get("profiles") or {}).items()):
        if key in seen or not isinstance(rec, dict) or not rec.get("ok"):
            continue
        if not any(str(rec.get(name) or "").strip() for name in ("about", "credits", "production", "known_for")):
            continue
        seen.add(str(key))
        work.append((str(key), str(rec.get("name") or "").strip()))
    for ident,name in _star_service().translation_targets():
        if ident not in seen:
            seen.add(ident)
            work.append((ident,name))
    return work


def _star_lang_batch_public():
    with _star_lang_batch_lock:
        payload = dict(_star_lang_batch)
    payload["ok"] = True
    return payload


def _star_lang_batch_mark(**values):
    with _star_lang_batch_lock:
        _star_lang_batch.update(values)


def _star_lang_translate_stored(profile):
    if profile.get("underage") or profile.get("error") == "missing":
        return "skip"
    if not _star_lang_blob(profile).strip():
        return "skip"
    key = _star_lang_key(profile)
    stamp = _star_lang_stamp(profile)
    cached = _star_lang_get(key)
    if cached and _star_lang_fresh(cached, stamp) and cached.get("ok") and _lang_record_covers(cached, profile):
        return "cached"
    rec = None
    for attempt in range(2):
        rec = _translate_profile(profile, time.time() + 40, cached if isinstance(cached, dict) else None)
        if rec.get("ok") or _tr_blocked():
            break
        time.sleep(1.2)
    if not rec or not rec.get("ok"):
        if rec:
            _star_lang_put(key, rec, save=False)
        return "fail"
    _star_lang_put(key, rec, save=False)
    return "ready"


def _lang_already(profile):
    if profile.get("underage") or profile.get("error") == "missing":
        return "skip"
    if not _star_lang_blob(profile).strip():
        return "skip"
    key = _star_lang_key(profile)
    stamp = _star_lang_stamp(profile)
    cached = _star_lang_get(key)
    if cached and cached.get("ok") and _star_lang_fresh(cached, stamp) and _lang_record_covers(cached, profile):
        return "cached"
    return ""


def _lang_fetch(profile):
    global _tr_strikes
    job_wait()
    try:
        state = _star_lang_translate_stored(profile)
    finally:
        job_done()
    if state == "ready":
        _tr_strikes = 0
    elif state == "fail" and _tr_blocked():
        _tr_strikes += 1
    return state


def _star_lang_batch_pass():
    from concurrent.futures import ThreadPoolExecutor
    import threading
    result_lock = threading.Lock()
    saved = _job_cursor_get("lang")
    now = time.time()
    wait_until = float(saved.get("cool") or saved.get("next") or 0)
    wait_until = _star_runtime_hub().due("lang", wait_until)
    if wait_until > now:
        _star_lang_batch_mark(running=not saved.get("done"), total=int(saved.get("total") or 0),
            ready=int(saved.get("ready") or 0), skipped=int(saved.get("skipped") or 0),
            failed=int(saved.get("failed") or 0), current="", next=wait_until if saved.get("done") else 0,
            cool=0 if saved.get("done") else wait_until)
        return False
    work = _star_lang_targets()
    if not work:
        return False
    if saved.get("done"):
        saved = {}
    start = star_store.resume_position(work, saved)
    ready = int(saved.get("ready") or 0) if start else 0
    skipped = int(saved.get("skipped") or 0) if start else 0
    failures = {str(key):str(name) for key,name in (saved.get("failures") or {}).items()}
    if start and not failures and int(saved.get("failed") or 0):
        failures = {ident:name for ident,name in work[:start] if not (_star_lang_get(ident) or {}).get("ok")}
    if not start and saved.get("phase") != "retry":
        failures = {}
    total = len(work)
    last = start
    last_key = work[start-1][0] if start else ""
    phase = "main"
    remaining = []

    def checkpoint(done=False, cool=0, next_at=0):
        _job_cursor_put("lang", {"index":last,"id":last_key,"key":last_key,"total":total,
            "ready":ready,"skipped":skipped,"failed":len(failures),"failures":failures,
            "phase":phase,"retry":list(remaining),"done":done,"next":next_at,"cool":cool,
            "checkpoint":time.time()}, force=True)
        _star_lang_batch_mark(running=not done,total=total,ready=ready,skipped=skipped,
            failed=len(failures),cool=cool,next=next_at,current="")

    def translate(ident, name):
        nonlocal ready, skipped
        _star_runtime_hub().wait("lang")
        _star_lang_batch_mark(running=True,total=total,current=name or ident,cool=0,next=0)
        try:
            profile = star_profile(ident,name,enrich=False)
            state = _lang_already(profile) or _lang_fetch(profile)
            if not _star_service().translate_sources(ident):
                state = "fail"
        except Exception:
            state = "fail"
            debug_log("server","star","Übersetzung fehlgeschlagen",{"id":ident})
        with result_lock:
            if state in ("ready","cached"):
                ready += 1
                failures.pop(ident,None)
            elif state == "skip":
                skipped += 1
                failures.pop(ident,None)
            else:
                failures[ident] = name
            _star_lang_batch_mark(ready=ready,skipped=skipped,failed=len(failures))

    def batch_size():
        return getattr(_star_runtime_hub(),'limit',lambda lane:1)('translations')

    def translate_many(rows):
        if len(rows)==1:
            translate(*rows[0])
        elif rows:
            with ThreadPoolExecutor(max_workers=len(rows),thread_name_prefix='star-lang-batch-worker') as pool:
                pending=[pool.submit(translate,*row) for row in rows]
                for future in pending:future.result()

    if saved.get("phase") == "retry":
        last = min(total,int(saved.get("index") or total))
        last_key = work[last-1][0] if last else ""
    else:
        position=start
        while position<total:
            if _tr_blocked():
                checkpoint(cool=_tr_cool_until)
                return False
            rows=work[position:position+batch_size()]
            translate_many(rows)
            position+=len(rows)
            last,last_key = position,rows[-1][0]
            if len(rows)>1 or last % 8 == 0 or _tr_blocked():
                checkpoint(cool=_tr_cool_until if _tr_blocked() else 0)
            if _tr_blocked():
                return False
    phase = "retry"
    remaining = list(saved.get("retry",[])) if saved.get("phase") == "retry" else list(failures.keys())
    # A failed identity survives restarts and retains its own partial text cache.
    # One retry pass per round avoids repeatedly hammering a failing source.
    while remaining:
        ident = remaining[0]
        if ident not in failures:
            remaining.pop(0)
            continue
        if _tr_blocked():
            checkpoint(cool=_tr_cool_until)
            return False
        chosen=remaining[:batch_size()]
        translate_many([(key,failures[key]) for key in chosen if key in failures])
        del remaining[:len(chosen)]
        checkpoint(cool=_tr_cool_until if _tr_blocked() else 0)
        if _tr_blocked():
            return False
    when = time.time()+_star_runtime_hub().interval()
    checkpoint(done=True,next_at=when)
    return True



def _star_lang_batch_run():
    global _lang_batch_alive
    try:
        while True:
            try:
                if not _star_lang_batch_pass():
                    with _star_runtime_hub().condition:
                        _star_runtime_hub().condition.wait(5)
            except Exception:
                debug_log("server", "star", "sprache sammel fehler", {"err": traceback.format_exc()[-400:]})
                time.sleep(20)
    finally:
        _lang_batch_alive = False
        _star_lang_batch_mark(running=False)


def star_lang_batch_start():
    global _lang_batch_alive
    with _star_lang_batch_lock:
        if _lang_batch_alive:
            payload = dict(_star_lang_batch)
            payload["ok"] = True
            payload["already"] = True
            return payload
        _lang_batch_alive = True
        _star_lang_batch["running"] = True
    threading.Thread(target=_star_lang_batch_run, name="star-lang-batch", daemon=True).start()
    return _star_lang_batch_public()


_BABE_SITEMAPS = (
    "https://www.babepedia.com/sitemapmain3.xml",
    "https://www.babepedia.com/sitemapmain4.xml",
    "https://www.babepedia.com/sitemapmain5.xml",
)
_babe_run = {"running": False, "done": 0, "hit": 0, "added": 0, "skipped": 0}
_babe_pos = {"file": 0, "seen": 0, "next": 0}
_babe_guard = threading.Lock()
_babe_started = False
_babe_saved_at = 0


def _babe_profile_counts():
    now = time.monotonic()
    fresh_for = 90.0 if _ui_hot() else 20.0
    if _babe_counts["at"] and now - _babe_counts["at"] < fresh_for:
        return _babe_counts["about"], _babe_counts["photos"]
    about = photos = 0
    with _star_extra_lock:
        profiles = _star_extra_load().get("profiles") or {}
        if isinstance(profiles, dict):
            for rec in profiles.values():
                if not isinstance(rec, dict) or not rec.get("ok"):
                    continue
                if str(rec.get("about") or "").strip():
                    about += 1
                images = rec.get("images") or []
                kept = 0
                for item in images:
                    if isinstance(item, str) and item.startswith("https://"):
                        kept += 1
                        if kept >= 12:
                            photos += 1
                            break
    _babe_counts["at"] = now
    _babe_counts["about"] = about
    _babe_counts["photos"] = photos
    return about, photos


def _babe_status():
    with _babe_guard:
        payload = dict(_babe_run)
        payload["file"] = int(_babe_pos.get("file") or 0)
        payload["seen"] = int(_babe_pos.get("seen") or 0)
        payload["locs"] = int(_babe_pos.get("locs") or 0)
        payload["next"] = float(_babe_pos.get("next") or 0)
    about, photos = _babe_profile_counts()
    payload["about"] = about
    payload["photos"] = photos
    payload["more"] = bool(_star_more_started)
    payload["more_seen"] = int(_star_more_run.get("seen") or 0)
    payload["more_cursor"] = int(_star_more_run.get("cursor") or 0)
    payload["more_queue"] = int(_star_more_run.get("queue") or 0)
    payload["more_current"] = str(_star_more_run.get("current") or "")
    payload["more_skip"] = len(_star_more_skip or ())
    payload["more_next"] = float(_star_more_run.get("next") or 0)
    payload["ok"] = True
    return payload


def _babe_queue():
    index = star_index()
    ranked = sorted(index["cards"], key=lambda card: (-(card.get("movies") or 0), card.get("name") or ""))
    rows = []
    seen = set()
    for card in ranked:
        ident = str(card.get("id") or "")
        name = str(card.get("name") or "").strip()
        if ident and name and ident not in seen:
            seen.add(ident)
            rows.append((ident, name))
    with _star_extra_lock:
        people = list(_star_extra_load().get("people") or [])
    for row in people:
        if not isinstance(row, dict):
            continue
        ident = str(row.get("id") or "")
        name = str(row.get("name") or "").strip()
        if ident and name and ident not in seen:
            seen.add(ident)
            rows.append((ident, name))
    return rows


def _babe_fresh(key):
    return bool(key) and not _star_extra_stale(_star_extra_get(key))


def _star_about_dirty(rec):
    return str((rec or {}).get("about") or "").lstrip().startswith("class=")


def _star_more_due(key):
    rec = _star_extra_get(key)
    if not isinstance(rec, dict) or not rec.get("ok") or rec.get("reason") == "age":
        return False
    if _star_about_dirty(rec):
        return True
    return rec.get("more_rev") != 1


def _babe_remember(force=False):
    global _babe_saved_at
    now = time.time()
    if not force and now - _babe_saved_at < 30:
        return
    with _babe_guard:
        row = {
            "file": int(_babe_pos.get("file") or 0),
            "seen": int(_babe_pos.get("seen") or 0),
            "next": float(_babe_pos.get("next") or 0),
            "added": int(_babe_run.get("added") or 0),
            "hit": int(_babe_run.get("hit") or 0),
            "done": int(_babe_run.get("done") or 0),
            "skipped": int(_babe_run.get("skipped") or 0),
        }
    with _star_extra_lock:
        sync = _star_extra_load().setdefault("sync", {})
        if not isinstance(sync, dict):
            sync = {}
            _star_extra["sync"] = sync
        sync["babepedia"] = row
        _star_extra_save()
    _babe_saved_at = now


def _babe_sitemap_ready(path):
    try:
        size = os.path.getsize(path)
        if size < 16:
            return False
        with open(path, "rb") as handle:
            handle.seek(max(0, size - 240))
            tail = handle.read().decode("utf-8", "replace").casefold()
    except OSError:
        return False
    return "</urlset>" in tail or "</sitemapindex>" in tail


def _babe_sitemap(index):
    folder = os.path.join(CACHE_DIR, "babepedia")
    os.makedirs(folder, exist_ok=True)
    filename = urllib.parse.urlsplit(_BABE_SITEMAPS[index]).path.rsplit("/",1)[-1].removeprefix("sitemap")
    if not re.fullmatch(r"main\d+\.xml",filename):
        raise ValueError("Ungültige Sitemap-Adresse.")
    path = os.path.join(folder, filename)
    if os.path.isfile(path) and time.time() - os.path.getmtime(path) < _star_runtime_hub().interval() and _babe_sitemap_ready(path):
        return path
    try:
        response = _star_runtime_hub().request(_BABE_SITEMAPS[index], {'User-Agent':'Mozilla/5.0','Accept':'application/xml,*/*'}, ttl=_star_runtime_hub().interval(), limit=24000000, timeout=30, cooldown_host=False)
    except star_runtime.SourceError:
        if _babe_sitemap_ready(path):
            _babe_run['sitemap_error'] = 'Eine aktuelle Profilliste antwortet nicht; der letzte vollständige Stand wird weiterverwendet.'
            return path
        raise
    temp = path + '.tmp'
    with open(temp,'w',encoding='utf-8') as handle:
        handle.write(response['body'])
    if not star_discovery.valid_sitemap(temp):
        os.remove(temp)
        _star_runtime_hub().store.discard_cache('http',hashlib.sha256((_BABE_SITEMAPS[index]+'\0').encode()).hexdigest())
        raise ValueError('Die Sitemap ist unvollständig; die bisherige Datei bleibt erhalten.')
    os.replace(temp, path)
    return path


def _babe_count_locs(path):
    total = 0
    with open(path, encoding="utf-8", errors="replace") as handle:
        buf = ""
        while True:
            chunk = handle.read(65536)
            if chunk:
                buf += chunk
            parts = buf.split("<loc>")
            buf = parts[-1] if chunk else ""
            ready = parts[:-1] if chunk else parts
            for part in ready:
                if "/babe/" in part and "</loc>" in part:
                    total += 1
            if not chunk:
                break
    return total


def _babe_locs(path, skip):
    skipped = 0
    with open(path, encoding="utf-8", errors="replace") as handle:
        buf = ""
        while True:
            chunk = handle.read(65536)
            if chunk:
                buf += chunk
            parts = buf.split("<loc>")
            if chunk:
                buf = parts[-1]
                ready = parts[:-1]
            else:
                buf = ""
                ready = parts
            for part in ready:
                if "</loc>" not in part:
                    continue
                loc = part.split("</loc>", 1)[0].strip()
                if "/babe/" not in loc:
                    continue
                if skipped < skip:
                    skipped += 1
                    continue
                yield loc
            if not chunk:
                break


def _babe_slug(url):
    slug = urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]).strip()
    if not slug or len(slug) > 80 or any(ch in slug for ch in "/\\ \t"):
        return ""
    return slug


_babe_lang_wait = []
_babe_lang_tries = {}


def _babe_queue_lang(key, name):
    if not key or _babe_lang_tries.get(key, 0) >= 3:
        return
    if len(_babe_lang_wait) >= 400 or (key, name) in _babe_lang_wait:
        return
    _babe_lang_wait.append((key, name))


def _babe_needs_lang(key):
    if not key or _babe_lang_tries.get(key, 0) >= 3:
        return False
    rec = _star_extra_get(key)
    about = str(rec.get("about") or "").strip() if isinstance(rec, dict) else ""
    if not isinstance(rec, dict) or not rec.get("ok") or len(about) < 40 or not _should_translate(about):
        return False
    stored = _star_lang_get(str(key)[:80])
    if not isinstance(stored, dict) or not stored.get("ok"):
        return True
    return not _lang_field_done(about, stored.get("about") or "")


def _babe_translate(key, name):
    _babe_queue_lang(key, name)


def _babe_translate_now(key, name):
    if _babe_lang_tries.get(key, 0) >= 3:
        return
    cached = _star_extra_get(key)
    if not isinstance(cached, dict) or not cached.get("ok"):
        return
    try:
        profile = star_profile(key, name or cached.get("name") or "", enrich=False)
        state = _star_lang_translate_stored(profile)
    except Exception:
        debug_log("server", "star", "text nachzug sprache", {"err": traceback.format_exc()[-240:]})
        state = "fail"
    if state == "fail":
        _babe_lang_tries[key] = _babe_lang_tries.get(key, 0) + 1
        if _babe_lang_tries[key] < 3:
            _babe_queue_lang(key, name)


def _babe_note(public, key, name):
    with _babe_guard:
        _babe_run["done"] += 1
        hit = bool(public and public.get("ok") and str(public.get("about") or "").strip())
        if hit:
            _babe_run["hit"] += 1
        elif public and public.get("reason") == "age":
            _babe_run["skipped"] += 1
    if hit:
        _babe_translate(key, name)


def _babe_pull_loc(stream):
    """Nächste Sitemap-Adresse. None heißt: Datei gewechselt oder Runde zu Ende."""
    with _babe_guard:
        file_index = int(_babe_pos.get("file") or 0)
    if file_index >= len(_BABE_SITEMAPS):
        return None
    if stream.get("file") != file_index or stream.get("gen") is None:
        path = _babe_sitemap(file_index)
        with _babe_guard:
            skip = int(_babe_pos.get("seen") or 0)
            need_count = int(_babe_pos.get("loc_file") or -1) != file_index
        if need_count:
            counted = _babe_count_locs(path)
            with _babe_guard:
                _babe_pos["locs"] = counted
                _babe_pos["loc_file"] = file_index
        stream["file"] = file_index
        stream["gen"] = _babe_locs(path, skip)
        with _babe_guard:
            _babe_run["names"] = True
            _babe_run["name_current"] = ""
    try:
        loc = next(stream["gen"])
    except StopIteration:
        with _babe_guard:
            _babe_pos["file"] = file_index + 1
            if file_index + 1 < len(_BABE_SITEMAPS):
                _babe_pos["seen"] = 0
        stream["gen"] = None
        return None
    with _babe_guard:
        _babe_pos["seen"] = int(_babe_pos.get("seen") or 0) + 1
    return loc


def _babe_take_loc(loc):
    slug = _babe_slug(loc)
    if not slug:
        return False
    name = re.sub(r"\s+", " ", slug.replace("_", " ")).strip()
    with _babe_guard:
        _babe_run["names"] = True
        _babe_run["name_current"] = name
    ident = "bp:" + slug
    age_key = "age:" + hashlib.sha256(slug.encode("utf-8")).hexdigest()[:20]
    if _babe_fresh(age_key):
        return False
    index = star_index()
    known = index["by_name"].get(name.casefold())
    if known is not None:
        card = index["cards"][known]
        key = str(card.get("id") or "")
        if key and not _babe_fresh(key):
            job_wait()
            try:
                _babe_note(_star_enrich(key, card.get("name") or name, save=False, log=False), key, card.get("name") or name)
            finally:
                job_done()
            return True
        if key and _babe_needs_lang(key):
            _babe_translate(key, card.get("name") or name)
        return False
    if _babe_fresh(ident):
        if _babe_needs_lang(ident):
            _babe_translate(ident, name)
        return False
    url = loc if loc.startswith("https://www.babepedia.com/babe/") else (_star_babe_url(name) or "")
    job_wait()
    try:
        page, reason = _star_fetch_html(url) if url else ("", "missing")
    finally:
        job_done()
    if not page:
        _star_extra_put(ident, {
            "ok": False,
            "reason": reason or "missing",
            "url": "",
            "images": [],
            "image_full": reason != "timeout",
            "at": time.time(),
        }, save=False)
        with _babe_guard:
            _babe_run["done"] += 1
        return True
    rec = _star_parse_babepedia(page, name, url)
    rec["image_full"] = True
    rec["at"] = time.time()
    if rec.get("reason") == "age":
        _star_extra_put(age_key, {"ok": False, "reason": "age", "at": time.time(), "images": []}, save=False)
        with _babe_guard:
            _babe_run["skipped"] += 1
        return True
    _star_extra_put(ident, rec, save=False)
    with _babe_guard:
        _babe_run["done"] += 1
    if not rec.get("ok"):
        return True
    thumb = ""
    for image in rec.get("images") or []:
        if isinstance(image, str) and image.startswith("https://") and not _is_video_url(image):
            thumb = image
            break
    added, _updated = _av_store_cards([{
        "id": ident,
        "name": name,
        "thumb": thumb,
        "source": url,
        "scenes": 0,
    }], save=False)
    if added:
        with _babe_guard:
            _babe_run["added"] += 1
    if str(rec.get("about") or "").strip():
        with _babe_guard:
            _babe_run["hit"] += 1
        _babe_translate(ident, name)
    return True


def _babe_queue_stored_lang():
    with _star_extra_lock:
        profiles = list((_star_extra_load().get("profiles") or {}).items())
    for key, _rec in profiles:
        if str(key).startswith("age:"):
            continue
        if _babe_needs_lang(key):
            _babe_translate(key, "")
        if len(_babe_lang_wait) >= 400:
            break


def _babe_names_row():
    with _babe_guard:
        return {
            "file": int(_babe_pos.get("file") or 0),
            "seen": int(_babe_pos.get("seen") or 0),
            "next": float(_babe_pos.get("next") or 0),
            "locs": int(_babe_pos.get("locs") or 0),
        }


def _babe_load_saved_pos():
    saved = {}
    try:
        with _star_extra_lock:
            loaded = (_star_extra_load().get("sync") or {}).get("babepedia") or {}
        if isinstance(loaded, dict):
            saved = loaded
    except Exception:
        debug_log("server", "star", "text nachzug stand", {"err": traceback.format_exc()[-200:]})
    cursor = _job_cursor_get("names")
    file_index = int(saved.get("file") or 0)
    seen = int(saved.get("seen") or 0)
    nxt = float(saved.get("next") or 0)
    cursor_file = int(cursor.get("file") or 0)
    cursor_seen = int(cursor.get("seen") or 0)
    cursor_next = float(cursor.get("next") or 0)
    locs = int(cursor.get("locs") or 0)
    if cursor_file == file_index:
        seen = max(seen, cursor_seen)
    elif cursor_file > file_index:
        file_index = cursor_file
        seen = cursor_seen
    if cursor_next > nxt:
        nxt = cursor_next
        if cursor_file >= file_index:
            file_index = cursor_file
            seen = cursor_seen if cursor_file > file_index else max(seen, cursor_seen)
    with _babe_guard:
        _babe_pos["file"] = file_index
        _babe_pos["seen"] = seen
        _babe_pos["next"] = nxt
        if locs:
            _babe_pos["locs"] = locs
        for key in ("added", "hit", "done", "skipped"):
            if key in saved:
                _babe_run[key] = int(saved.get(key) or 0)


def _library_fetch(key, name):
    job_wait()
    try:
        _babe_note(_star_enrich(key, name, save=False, log=False), key, name)
    except Exception:
        debug_log("server", "star", "text nachzug", {"err": traceback.format_exc()[-240:]})
    finally:
        job_done()


def _babe_stored_lang_once():
    try:
        _babe_queue_stored_lang()
    except Exception:
        debug_log("server", "star", "text nachzug sprache", {"err": traceback.format_exc()[-200:]})


def _babe_lang_drain():
    while True:
        if not _babe_lang_wait:
            time.sleep(1.5)
            continue
        try:
            key, name = _babe_lang_wait.pop(0)
        except IndexError:
            continue
        job_wait()
        try:
            _babe_translate_now(key, name)
        except Exception:
            debug_log("server", "star", "text nachzug sprache", {"err": traceback.format_exc()[-240:]})
        finally:
            job_done()


def _babe_library_loop():
    with _babe_guard:
        _babe_run["running"] = True
        _babe_run["library"] = True
    threading.Thread(target=_babe_stored_lang_once, name="star-text-backfill", daemon=True).start()
    saved = _job_cursor_get("library")
    resume_saved = saved if not saved.get("done") else {}
    cursor = int(saved.get("index") or 0)
    nxt = float(saved.get("next") or 0)
    if saved.get("done") and nxt > time.time():
        total = int(saved.get("total") or saved.get("index") or 0)
        with _babe_guard:
            _babe_run["library"] = False
            _babe_run["library_next"] = nxt
            _babe_run["mode"] = "fertig"
            _babe_run["current"] = ""
            _babe_run["cursor"] = total
            _babe_run["queue"] = total
    else:
        with _babe_guard:
            _babe_run["library"] = True
            _babe_run["mode"] = "bibliothek"
            _babe_run["cursor"] = cursor
            _babe_run["queue"] = int(saved.get("total") or 0)
    queue = []
    pool = futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="star-text")
    inflight = []
    while True:
        try:
            nxt = _star_runtime_hub().due("texts", nxt)
            if nxt > time.time():
                time.sleep(5)
                continue
            if nxt:
                cursor = 0
                queue = []
                nxt = 0
                with _babe_guard:
                    _babe_run["library"] = True
                    _babe_run["library_next"] = 0
                    _babe_run["mode"] = "bibliothek"
            if cursor >= len(queue):
                for fut in inflight:
                    try:
                        fut.result()
                    except Exception:
                        pass
                inflight = []
                if queue:
                    when = time.time() + _star_runtime_hub().interval()
                    nxt = when
                    with _babe_guard:
                        _babe_run["library"] = False
                        _babe_run["library_next"] = when
                        _babe_run["mode"] = "fertig"
                        _babe_run["current"] = ""
                        _babe_run["cursor"] = len(queue)
                        _babe_run["queue"] = len(queue)
                    _job_cursor_put("library", {
                        "index": len(queue),
                        "total": len(queue),
                        "key": "",
                        "done": True,
                        "next": when,
                    }, force=True)
                    queue = []
                    cursor = 0
                    continue
                try:
                    queue = _babe_queue()
                    if resume_saved:
                        cursor = star_store.resume_position(queue, resume_saved)
                        resume_saved = {}
                except Exception:
                    queue = []
                    debug_log("server", "star", "text nachzug liste", {"err": traceback.format_exc()[-200:]})
                with _babe_guard:
                    _babe_run["library"] = True
                    _babe_run["library_next"] = 0
                    _babe_run["mode"] = "bibliothek"
                    _babe_run["cursor"] = min(cursor, len(queue))
                    _babe_run["queue"] = len(queue)
                if cursor > len(queue):
                    cursor = 0
                if not queue:
                    time.sleep(20)
                continue
            key, name = queue[cursor]
            cursor += 1
            fresh = _babe_fresh(key)
            with _babe_guard:
                _babe_run["cursor"] = cursor
                _babe_run["queue"] = len(queue)
                _babe_run["library"] = True
                _babe_run["mode"] = "bibliothek"
                if fresh:
                    _babe_run["current"] = ""
                else:
                    _babe_run["current"] = name
            if fresh:
                if _babe_needs_lang(key):
                    _babe_translate(key, name)
                if cursor % 200 == 0:
                    _star_commit_cursor("library", queue, cursor, inflight)
                    time.sleep(0.004)
                continue
            inflight.append(pool.submit(_library_fetch, key, name))
            if len(inflight) >= 4:
                try:
                    inflight.pop(0).result()
                except Exception:
                    pass
            if cursor % 8 == 0:
                _star_commit_cursor("library", queue, cursor, inflight)
            if cursor % 40 == 0:
                _babe_remember()
        except Exception:
            debug_log("server", "star", "text nachzug", {"err": traceback.format_exc()[-240:]})
            time.sleep(4)



def _babe_names_loop():
    star_discovery.run(sys.modules[__name__])



def babe_sync_start():
    global _babe_started
    with _babe_guard:
        if _babe_started:
            return _babe_status()
        _babe_started = True
    threading.Thread(target=_babe_library_loop, name="star-text-fill", daemon=True).start()
    threading.Thread(target=_babe_names_loop, name="star-names", daemon=True).start()
    threading.Thread(target=_babe_lang_drain, name="star-text-lang", daemon=True).start()
    _star_more_ensure()
    return _babe_status()


def _star_database():
    global _star_db
    if _star_db is None:
        lib = os.path.join(ADDON, "resources", "lib")
        if lib not in sys.path:
            sys.path.append(lib)
        from star_database import StarDatabase
        _star_db = StarDatabase(ADDON)
    return _star_db


def _star_stats_mem(performer_id):
    if not performer_id:
        return None
    return _star_stats.get(str(performer_id))


def _star_clock_rows(rows, limit):
    picked = []
    for row in rows[:limit]:
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        picked.append({
            "title": title,
            "year": _star_int(row.get("release_year")),
            "seconds": _star_int(row.get("duration_seconds")),
        })
    return picked


def _star_movie_stats(performer_id, name):
    ident = str(performer_id or "")
    if not ident or ident.startswith(("trend:", "av:", "bp:", "site:")):
        return None
    with _star_stats_lock:
        cached = _star_stats.get(ident)
        if cached is not None:
            return cached
        try:
            rows = _star_database().movies(ident)
        except Exception:
            return None
        if not rows:
            payload = {"count": 0}
            _star_stats[ident] = payload
            return payload
        years = []
        durations = []
        for row in rows:
            year = _star_int(row.get("release_year"))
            seconds = _star_int(row.get("duration_seconds"))
            if 1950 <= year <= today_year():
                years.append(year)
            if seconds > 0:
                durations.append((row, seconds))
        by_year = {}
        decades = {}
        for year in years:
            by_year[year] = by_year.get(year, 0) + 1
            label = str((year // 10) * 10) + "er"
            decades[label] = decades.get(label, 0) + 1
        typical = [(row, seconds) for row, seconds in durations if seconds <= 3 * 3600]
        boxes = [seconds for _row, seconds in durations if seconds > 3 * 3600]
        avg = int(round(sum(seconds for _row, seconds in typical) / len(typical))) if typical else 0
        ordered = sorted(seconds for _row, seconds in typical)
        median = ordered[len(ordered) // 2] if ordered else 0
        longest = [row for row, _seconds in sorted(durations, key=lambda item: -item[1])[:5]]
        early = min(years) if years else 0
        recent = max(years) if years else 0
        earliest_rows = [row for row in rows if _star_int(row.get("release_year")) == early] if early else []
        recent_rows = [row for row in rows if _star_int(row.get("release_year")) == recent] if recent else []
        busiest = sorted(by_year.items(), key=lambda item: (-item[1], -item[0]))[:6]
        payload = {
            "count": len(rows),
            "with_year": len(years),
            "with_duration": len(durations),
            "typical": len(typical),
            "box_sets": len(boxes),
            "year_from": early,
            "year_to": recent,
            "avg_seconds": avg,
            "median_seconds": median,
            "longest": _star_clock_rows(longest, 5),
            "recent": _star_clock_rows(recent_rows, 6),
            "earliest": _star_clock_rows(earliest_rows, 5) if early and early != recent else [],
            "busiest": [{"year": year, "count": count} for year, count in busiest],
            "decades": [{"label": label, "count": decades[label]} for label in sorted(decades)],
        }
        _star_stats[ident] = payload
        return payload


def _star_hide_underage(profile):
    profile["underage"] = True
    profile["name"] = ""
    profile["bio"] = ""
    profile["thumb"] = ""
    profile["aliases"] = []
    profile["tags"] = []
    profile["facts"] = []
    profile["extra"] = None
    profile["movies"] = None
    profile["lang"] = None
    profile["movies_query"] = ""
    profile["source"] = ""
    profile["source_url"] = ""


def _star_finish_profile(profile, enrich):
    """Lokales Profil sofort. Babepedia nur für dieses eine Profil, Filme nur als Auftritte."""
    if _star_profile_underage(profile):
        _star_hide_underage(profile)
        return
    key = str(profile.get("id") or "").strip() or _star_trend_id(profile.get("name") or "")
    if enrich and profile.get("name"):
        profile["extra"] = _star_enrich(key, profile["name"])
        profile["movies"] = _star_movie_stats(profile.get("id") or "", profile.get("name") or "") if profile.get("local") else None
    else:
        cached = _star_extra_get(key)
        profile["extra"] = _star_extra_public(cached) if cached else None
        profile["movies"] = _star_stats_mem(profile.get("id") or "") if profile.get("local") else None
        if (
            isinstance(cached, dict)
            and cached.get("ok")
            and cached.get("reason") != "age"
            and cached.get("rev") == _STAR_EXTRA_REV
            and _star_more_due(key)
        ):
            _star_more_schedule(key, profile.get("name") or "", front=True)
    extra = profile.get("extra") or {}
    if isinstance(extra, dict) and extra.get("reason") == "age":
        _star_hide_underage(profile)
        return
    if not profile.get("thumb") and extra.get("images"):
        profile["thumb"] = extra["images"][0]
    _star_apply_cover(profile)
    profile["lang"] = _star_lang_cached(key, profile)


def _star_cover_key(star_id, name):
    ident = str(star_id or "").strip()
    if ident:
        return ident[:80]
    if name:
        return _star_trend_id(name)
    return ""


def _star_cover_ids():
    covers = _star_extra_load().get("covers") or {}
    return {str(key) for key, row in covers.items() if isinstance(row, dict) and row.get("file")}


def _star_cover_file(name):
    name = str(name or "").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{20}\.(?:jpg|png|gif|webp)", name):
        return ""
    folder = os.path.abspath(os.path.join(PROFILE, "star_covers"))
    path = os.path.abspath(os.path.join(folder, name))
    if not path.startswith(folder + os.sep) or not os.path.isfile(path):
        return ""
    return path


def _star_cover_row(star_id, name):
    key = _star_cover_key(star_id, name)
    if not key:
        return "", None
    row = (_star_extra_load().get("covers") or {}).get(key)
    if not isinstance(row, dict) or not row.get("file"):
        return key, None
    if not _star_cover_file(row.get("file")):
        return key, None
    return key, row


def _star_cover_media(star_id, name):
    _key, row = _star_cover_row(star_id, name)
    if not row:
        return ""
    return "http://127.0.0.1:%d/api/star-cover?file=%s" % (MEDIA_PORT, urllib.parse.quote(row["file"]))


def _star_apply_cover(profile):
    media = _star_cover_media(profile.get("id") or "", profile.get("name") or "")
    profile["cover"] = bool(media)
    if media:
        profile["thumb"] = media


def _star_cover_remote(url):
    raw = str(url or "").strip()
    if raw.startswith("http://127.0.0.1:") and "/api/image?" in raw:
        parsed = urllib.parse.urlparse(raw)
        raw = urllib.parse.parse_qs(parsed.query).get("url", [""])[0].split("|", 1)[0]
    if not raw.startswith(("http://", "https://")):
        raise ValueError("url")
    host = (urllib.parse.urlsplit(raw).hostname or "").casefold()
    if host in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("url")
    return raw


def _star_cover_bytes(raw):
    if not isinstance(raw, (bytes, bytearray)) or len(raw) < 32 or len(raw) > 8_000_000:
        raise ValueError("size")
    kind = _image_kind(bytes(raw))
    if not kind:
        raise ValueError("type")
    return bytes(raw), kind


def _star_cover_store(star_id, name, blob):
    key = _star_cover_key(star_id, name)
    if not key:
        raise ValueError("name")
    profile = star_profile(star_id, name, enrich=False)
    if profile.get("underage"):
        raise ValueError("age")
    data, kind = _star_cover_bytes(blob)
    ext = {"jpeg": ".jpg", "png": ".png", "gif": ".gif", "webp": ".webp"}[kind]
    filename = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20] + ext
    folder = os.path.join(PROFILE, "star_covers")
    os.makedirs(folder, exist_ok=True)
    for old_ext in (".jpg", ".png", ".gif", ".webp"):
        old = os.path.join(folder, hashlib.sha256(key.encode("utf-8")).hexdigest()[:20] + old_ext)
        if os.path.isfile(old):
            try:
                os.remove(old)
            except OSError:
                pass
    with open(os.path.join(folder, filename), "wb") as handle:
        handle.write(data)
    with _star_extra_lock:
        covers = _star_extra_load().setdefault("covers", {})
        covers[key] = {"file": filename, "at": int(time.time())}
        _star_extra_save(force=True)
    debug_log("server", "star-cover", "gespeichert", {"id": key[:40], "bytes": len(data)})
    return _star_cover_media(star_id, name)


def _star_cover_clear(star_id, name):
    key, row = _star_cover_row(star_id, name)
    if row:
        path = _star_cover_file(row.get("file"))
        if path:
            try:
                os.remove(path)
            except OSError:
                pass
    if key:
        with _star_extra_lock:
            covers = _star_extra_load().setdefault("covers", {})
            covers.pop(key, None)
            _star_extra_save(force=True)
    profile = star_profile(star_id, name, enrich=False)
    return profile.get("thumb") or ""


def _star_cover_fetch(url):
    remote = _star_cover_remote(url)
    request = urllib.request.Request(remote, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=8) as response:
        data = response.read(8_000_001)
    return _star_cover_bytes(data)[0]


_DOWNLOAD_EXT = {"mp4", "webm", "mkv", "m4v", "mov", "ts"}
_download_lock = threading.RLock()
_download_jobs = None
_download_stop = set()
_download_flush = 0.0
_download_option_cache = {}


def _download_folder_text(raw):
    text = str(raw or "").strip().strip('"')[:260]
    if not text or any(char in text for char in "\r\n\x00"):
        return ""
    return text


def _download_dir(raw, create=False):
    text = _download_folder_text(raw)
    if not text:
        raise ValueError("leer")
    path = os.path.abspath(os.path.expandvars(text))
    if not os.path.isabs(path):
        raise ValueError("pfad")
    lowered = path.casefold()
    blocked = []
    for prefix in (
        os.environ.get("WINDIR") or os.environ.get("SystemRoot") or "",
        os.environ.get("ProgramFiles") or "",
        os.environ.get("ProgramFiles(x86)") or "",
        ADDON,
        ROOT,
    ):
        if prefix:
            blocked.append(os.path.abspath(prefix).casefold())
    for prefix in blocked:
        if lowered == prefix or lowered.startswith(prefix + os.sep):
            raise ValueError("gesperrt")
    if create and not os.path.isdir(path):
        parent = os.path.dirname(path)
        if not parent or not os.path.isdir(parent):
            raise ValueError("ordner")
        os.makedirs(path, exist_ok=True)
    if not os.path.isdir(path):
        raise ValueError("ordner")
    probe = os.path.join(path, ".ah-write-test")
    try:
        with open(probe, "wb") as handle:
            handle.write(b"ok")
        os.remove(probe)
    except OSError as exc:
        raise ValueError("ordner") from exc
    return path


def _download_message(code):
    return {
        "leer": "Trag einen Ordner ein.",
        "pfad": "Das ist kein vollständiger Ordnerpfad.",
        "gesperrt": "Dieser Ordner ist gesperrt. Wähl einen eigenen Ordner, nicht Windows oder den Programmordner.",
        "ordner": "Der Ordner lässt sich nicht anlegen oder beschreiben.",
    }.get(code, "Der Ordner geht nicht.")


def _download_load():
    global _download_jobs
    if _download_jobs is not None:
        return _download_jobs
    with _download_lock:
        if _download_jobs is not None:
            return _download_jobs
        jobs = []
        path = os.path.join(PROFILE, "download_jobs.json")
        try:
            with open(path, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, list):
                jobs = [item for item in loaded if isinstance(item, dict) and item.get("id")]
        except (OSError, ValueError):
            jobs = []
        changed = False
        for job in jobs:
            if job.get("status") in ("queued", "running"):
                partial = str(job.get("file") or "") + ".part"
                kept = partial != ".part" and os.path.isfile(partial) and os.path.getsize(partial) > 0
                job["status"] = "cancelled" if kept else "failed"
                job["error"] = "" if kept else "Der Server wurde neu gestartet, bevor die Datei fertig war."
                job["note"] = "Angehalten. Fortsetzen holt den Rest." if kept else job.get("note") or ""
                if not kept and partial != ".part" and os.path.isfile(partial):
                    try:
                        os.remove(partial)
                    except OSError:
                        pass
                changed = True
        _download_jobs = jobs[-100:]
        if changed:
            _download_save_locked()
        return _download_jobs


def _download_save_locked():
    path = os.path.join(PROFILE, "download_jobs.json")
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(_download_jobs[-100:], handle, ensure_ascii=False)
    os.replace(temp, path)


def _download_update(job_id, force=False, **fields):
    global _download_flush
    with _download_lock:
        job = next((item for item in _download_load() if item.get("id") == job_id), None)
        if not job:
            return
        job.update(fields)
        job["updated"] = time.time()
        now = time.time()
        if force or fields.get("status") or now - _download_flush >= 0.4:
            _download_flush = now
            _download_save_locked()


def _download_resumable(job):
    if (job or {}).get("status") not in ("cancelled", "failed"):
        return False
    dest = str((job or {}).get("file") or "")
    partial = dest + ".part"
    return bool(dest and os.path.isfile(partial) and os.path.getsize(partial) > 0)


def _download_public(job):
    name = os.path.basename(str(job.get("file") or ""))
    return {
        "id": job.get("id") or "",
        "title": job.get("title") or "",
        "folder": job.get("folder") or "",
        "file": name,
        "label": job.get("label") or "",
        "kind": job.get("kind") or "",
        "status": job.get("status") or "",
        "bytes": int(job.get("bytes") or 0),
        "total": int(job.get("total") or 0),
        "part": int(job.get("part") or 0),
        "parts": int(job.get("parts") or 0),
        "resumable": _download_resumable(job),
        "error": job.get("error") or "",
        "note": job.get("note") or "",
    }


def _remember_download_folder(folder):
    data = read_ui()
    folders = [folder]
    for item in data.get("downloadFolders") or []:
        text = str(item or "")
        if text and text.casefold() != folder.casefold():
            folders.append(text)
    write_ui({"downloadFolder": folder, "downloadFolders": folders[:8]})


def _ffmpeg_bin():
    configured = ""
    try:
        import xbmcaddon
        configured = (xbmcaddon.Addon().getSetting("ffmpeg_path") or "").strip().strip('"')
    except Exception:
        configured = ""
    if configured and os.path.isfile(configured):
        return configured
    return shutil.which("ffmpeg") or ""


def _download_headers(path):
    base, extra = split_kodi_url(path)
    headers = {"User-Agent": extra.get("User-Agent") or "Mozilla/5.0"}
    for key in ("Referer", "Origin", "Cookie"):
        value = str(extra.get(key) or "").replace("\r", "").replace("\n", "")
        if value:
            headers[key] = value
    return base, headers


def _fetch_text(url, headers, limit=1_500_000):
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=8) as response:
        return response.read(limit).decode("utf-8", "replace")


def _pack_stream(url, headers):
    extra = []
    for key in ("Referer", "Origin", "Cookie"):
        value = headers.get(key) or ""
        if value:
            extra.append(urllib.parse.quote(key) + "=" + urllib.parse.quote(value))
    if not extra:
        return url
    return url + "|" + "&".join(extra)


def _stream_log_url(url):
    host = urllib.parse.urlparse(str(url or "")).netloc.lower()
    if any(part in host for part in ("doppiocdn", "chaturbate", "highwebmedia", "mmcdn", "camsoda", "bongacams", "bcvcdn", "cam4", "xcdnpro", "xlovecam", "wlresources")):
        return host[:80]
    return str(url or "")[:160]


def _cam_pack(url, headers):
    packed = _pack_stream(url, headers)
    agent = str(headers.get("User-Agent") or "").replace("\r", "").replace("\n", "")[:200]
    if not agent:
        return packed
    return packed + ("&" if "|" in packed else "|") + "User-Agent=" + urllib.parse.quote(agent)


def _hls_variants(text, playlist_url, headers):
    variants = []
    pending = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#EXT-X-STREAM-INF"):
            resolution = re.search(r"RESOLUTION=(\d+)x(\d+)", stripped)
            bandwidth = re.search(r"BANDWIDTH=(\d+)", stripped)
            name = re.search(r'NAME="([^"]+)"', stripped)
            height = int(resolution.group(2)) if resolution else 0
            label = name.group(1) if name else (resolution.group(0).split("=", 1)[-1] if resolution else "")
            if not label and bandwidth:
                label = "%d kbps" % (int(bandwidth.group(1)) // 1000)
            pending = {"label": label or "Stream", "height": height}
            continue
        if pending and stripped and not stripped.startswith("#"):
            absolute = urllib.parse.urljoin(playlist_url, stripped)
            variants.append({
                "label": pending["label"],
                "path": _pack_stream(absolute, headers),
                "kind": "hls",
                "height": pending["height"],
            })
            pending = None
    variants.sort(key=lambda item: item.get("height") or 0)
    return variants


def _expand_download_sources(sources):
    expanded = []
    seen = set()
    for source in sources:
        path = str(source.get("path") or "")
        base, headers = _download_headers(path)
        if not base.startswith(("http://", "https://")):
            continue
        label = clean_label(str(source.get("label") or "Stream")) or "Stream"
        if ".m3u8" not in base.lower():
            key = base
            if key not in seen:
                seen.add(key)
                expanded.append({"label": label, "path": path, "kind": "file"})
            continue
        try:
            text = _fetch_text(base, headers)
        except Exception:
            text = ""
        if text and ("#EXT-X-MAP" in text or "METHOD=AES" in text or "METHOD=SAMPLE" in text) and "Stückliste" not in label:
            label = label + " · verschlüsselt"
        elif "Stückliste" not in label:
            label = label + " · Stückliste"
        variants = _hls_variants(text, base, headers) if "#EXT-X-STREAM-INF" in text else []
        if not variants:
            if base not in seen:
                seen.add(base)
                expanded.append({"label": label, "path": path, "kind": "hls"})
            continue
        for variant in variants:
            variant_base = _download_headers(variant["path"])[0]
            if variant_base in seen:
                continue
            seen.add(variant_base)
            if "Stückliste" not in variant["label"] and "verschlüsselt" not in variant["label"]:
                variant["label"] = variant["label"] + " · Stückliste"
            expanded.append(variant)
    for index, item in enumerate(expanded):
        item["label"] = item["label"] or ("Qualität %d" % (index + 1))
        item.pop("height", None)
    return expanded


def _resolved_sources(resolved):
    sources = []
    for source in (resolved or {}).get("sources") or []:
        path = str((source or {}).get("path") or "")
        if path.startswith("http"):
            sources.append({"label": (source or {}).get("label") or "Stream", "path": path})
    if not sources:
        path = str((resolved or {}).get("path") or "")
        if path.startswith("http"):
            quality = str(((resolved or {}).get("facts") or {}).get("quality") or "").split(",")[0].strip()
            sources.append({"label": quality or "Original", "path": path})
    return sources


def download_options(query):
    query = (query or "").lstrip("?")
    if not query or len(query) > 8000:
        return {"error": "query", "message": "Das Video hat keine Adresse."}
    ui = read_ui()
    cached = _download_option_cache.get(query)
    if cached and time.time() - cached["at"] < 600:
        payload = dict(cached["payload"])
        payload["folder"] = ui.get("downloadFolder") or ""
        payload["folders"] = ui.get("downloadFolders") or []
        payload["ffmpeg"] = bool(_ffmpeg_bin())
        payload["cached"] = True
        return payload
    result = run_plugin(query, depth=1, priority=True)
    if result.get("busy"):
        return {"error": "busy", "message": "Eine andere Liste wird noch geladen. Gleich noch einmal."}
    resolved = result.get("resolved") or {}
    if not resolved.get("path") and not resolved.get("sources"):
        return {"error": "stream", "message": "Für dieses Video liegt kein herunterladbarer Stream vor."}
    sources = _expand_download_sources(_resolved_sources(resolved))
    if not sources:
        return {"error": "stream", "message": "Für dieses Video liegt kein herunterladbarer Stream vor."}
    title = clean_label(resolved.get("title") or "")
    params = dict(urllib.parse.parse_qsl(query, keep_blank_values=True))
    if not title:
        title = clean_label(params.get("name") or params.get("title") or "") or "Video"
    payload = {"title": title, "sources": sources}
    _download_option_cache[query] = {"at": time.time(), "payload": payload}
    if len(_download_option_cache) > 40:
        oldest = sorted(_download_option_cache, key=lambda item: _download_option_cache[item]["at"])[:10]
        for item in oldest:
            _download_option_cache.pop(item, None)
    payload = dict(payload)
    payload["folder"] = ui.get("downloadFolder") or ""
    payload["folders"] = ui.get("downloadFolders") or []
    payload["ffmpeg"] = bool(_ffmpeg_bin())
    return payload


def _safe_download_name(title, label, ext):
    text = re.sub(r'[\\/:*?"<>|]+', " ", title or "")
    text = re.sub(r"\s+", " ", text).strip(" .") or "Video"
    quality = re.sub(r'[\\/:*?"<>|]+', " ", label or "").strip()
    if quality and quality.lower() not in text.lower():
        text = text + " " + quality
    text = text[:140].strip(" .") or "Video"
    ext = ext if ext in _DOWNLOAD_EXT else "mp4"
    return text + "." + ext


def _unique_download_path(folder, filename):
    candidate = os.path.join(folder, filename)
    if not os.path.exists(candidate):
        return candidate
    root, ext = os.path.splitext(filename)
    index = 2
    while True:
        candidate = os.path.join(folder, "%s (%d)%s" % (root, index, ext))
        if not os.path.exists(candidate):
            return candidate
        index += 1


def _download_extension(url, mime):
    path = urllib.parse.urlparse(url).path.lower()
    match = re.search(r"\.([a-z0-9]{2,4})$", path)
    if match and match.group(1) in _DOWNLOAD_EXT:
        return match.group(1)
    mime = (mime or "").lower()
    if "webm" in mime:
        return "webm"
    if "mp4" in mime or "mpeg" in mime:
        return "mp4"
    return "mp4"


class _DownloadStop(Exception):
    pass


def _download_stopped(job_id):
    return job_id in _download_stop


def _download_file(job, url, headers):
    dest = str(job.get("file") or "")
    partial = dest + ".part" if dest else ""
    existing = os.path.getsize(partial) if dest and os.path.isfile(partial) else 0
    request_headers = dict(headers)
    if existing:
        request_headers["Range"] = "bytes=%d-" % existing
    request = urllib.request.Request(url, headers=request_headers)
    try:
        response = urllib.request.urlopen(request, timeout=30)
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and existing and dest:
            os.replace(partial, dest)
            _download_update(job["id"], force=True, file=dest, bytes=existing, total=existing)
            return
        raise
    with response:
        status = getattr(response, "status", 200) or 200
        if existing and status != 206:
            existing = 0
        length = int(response.headers.get("Content-Length") or 0)
        if not dest or existing == 0:
            ext = _download_extension(url, response.headers.get("Content-Type") or "")
            dest = _unique_download_path(job["folder"], _safe_download_name(job.get("title"), job.get("label"), ext))
            partial = dest + ".part"
            total = length
        else:
            total = existing + length if status == 206 else length
        _download_update(job["id"], force=True, status="running", file=dest, total=total, bytes=existing, note="Fortsetzen holt den Rest, wenn du abbrichst." if not existing else "Setzt bei den vorhandenen Bytes fort.")
        done = existing
        with open(partial, "ab" if existing and status == 206 else "wb") as handle:
            while True:
                if _download_stopped(job["id"]):
                    raise _DownloadStop()
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                done += len(chunk)
                _download_update(job["id"], bytes=done, total=total)
        os.replace(partial, dest)
        _download_update(job["id"], force=True, bytes=done, total=total or done, file=dest, note="")


def _download_hls_ffmpeg(job, url, headers, ffmpeg):
    dest = _unique_download_path(job["folder"], _safe_download_name(job.get("title"), job.get("label"), "mp4"))
    partial = dest + ".part.mp4"
    header_blob = "".join("%s: %s\r\n" % (key, value) for key, value in headers.items())
    command = [ffmpeg, "-y", "-headers", header_blob, "-i", url, "-c", "copy", "-bsf:a", "aac_adtstoasc", partial]
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _download_update(job["id"], force=True, status="running", file=dest, bytes=0, total=0)
    while process.poll() is None:
        if _download_stopped(job["id"]):
            process.kill()
            raise _DownloadStop()
        size = os.path.getsize(partial) if os.path.isfile(partial) else 0
        _download_update(job["id"], bytes=size)
        time.sleep(0.5)
    if process.returncode != 0 or not os.path.isfile(partial) or os.path.getsize(partial) < 1024:
        if os.path.isfile(partial):
            try:
                os.remove(partial)
            except OSError:
                pass
        raise RuntimeError("FFmpeg konnte diese Qualität nicht speichern.")
    os.replace(partial, dest)
    _download_update(job["id"], force=True, file=dest, bytes=os.path.getsize(dest))


def _hls_media(url, headers):
    text = _fetch_text(url, headers)
    if "#EXT-X-STREAM-INF" in text:
        variants = _hls_variants(text, url, headers)
        if not variants:
            raise RuntimeError("Die Qualitätsliste enthält keine Datei.")
        url, headers = _download_headers(variants[-1]["path"])
        text = _fetch_text(url, headers)
    if "#EXT-X-MAP" in text or "METHOD=AES" in text or "METHOD=SAMPLE" in text:
        raise RuntimeError("Dieser Stream ist verschlüsselt oder kein einfaches Video. Dafür braucht der PC FFmpeg.")
    if "#EXT-X-ENDLIST" not in text:
        raise RuntimeError("Livestreams werden nicht gespeichert.")
    segments = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        segments.append(urllib.parse.urljoin(url, stripped))
    if not segments:
        raise RuntimeError("Die Playlist enthält keine Abschnitte.")
    return url, headers, segments


def _hls_state_path(dest):
    return dest + ".part.json"


def _download_hls_segments(job, url, headers):
    media, headers, segments = _hls_media(url, headers)
    dest = str(job.get("file") or "")
    done_segments = 0
    if dest and os.path.isfile(dest + ".part") and os.path.isfile(_hls_state_path(dest)):
        try:
            state = json.load(open(_hls_state_path(dest), encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
        if state.get("url") == media and int(state.get("total") or 0) == len(segments):
            done_segments = min(int(state.get("done") or 0), len(segments))
        else:
            done_segments = 0
    if done_segments <= 0:
        dest = _unique_download_path(job["folder"], _safe_download_name(job.get("title"), job.get("label"), "ts"))
        done_segments = 0
        with open(dest + ".part", "wb") as handle:
            handle.write(b"")
    partial = dest + ".part"
    done = os.path.getsize(partial) if os.path.isfile(partial) else 0
    note = "Als TS gespeichert, weil FFmpeg fehlt. Ein Abbruch lässt sich fortsetzen."
    _download_update(job["id"], force=True, status="running", file=dest, bytes=done, total=0, part=done_segments, parts=len(segments), note=note)
    with open(partial, "ab") as handle:
        for index, segment in enumerate(segments):
            if index < done_segments:
                continue
            if _download_stopped(job["id"]):
                raise _DownloadStop()
            request = urllib.request.Request(segment, headers=headers)
            with urllib.request.urlopen(request, timeout=30) as response:
                while True:
                    if _download_stopped(job["id"]):
                        raise _DownloadStop()
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    _download_update(job["id"], bytes=done, part=index, parts=len(segments))
            done_segments = index + 1
            handle.flush()
            with open(_hls_state_path(dest), "w", encoding="utf-8") as state_file:
                json.dump({"url": media, "done": done_segments, "total": len(segments)}, state_file)
            _download_update(job["id"], bytes=done, part=done_segments, parts=len(segments))
    os.replace(partial, dest)
    try:
        os.remove(_hls_state_path(dest))
    except OSError:
        pass
    _download_update(job["id"], force=True, file=dest, bytes=done, part=len(segments), parts=len(segments), note="Als TS gespeichert, weil FFmpeg fehlt.")


def _download_partial(job, keep_part=False):
    name = str(job.get("file") or "")
    if not name:
        return
    suffixes = (".part.mp4",) if keep_part else (".part", ".part.mp4", ".part.json")
    for suffix in suffixes:
        partial = name + suffix
        if os.path.isfile(partial):
            try:
                os.remove(partial)
            except OSError:
                pass


def _download_run(job_id):
    try:
        with _download_lock:
            job = next((item for item in _download_load() if item.get("id") == job_id), None)
            if not job:
                return
            snapshot = dict(job)
        url, headers = _download_headers(snapshot.get("path") or "")
        if not url.startswith(("http://", "https://")):
            raise RuntimeError("Die Streamadresse fehlt.")
        if snapshot.get("kind") == "hls" or ".m3u8" in url.lower():
            ffmpeg = _ffmpeg_bin()
            if ffmpeg:
                _download_hls_ffmpeg(snapshot, url, headers, ffmpeg)
            else:
                _download_hls_segments(snapshot, url, headers)
        else:
            _download_file(snapshot, url, headers)
        _download_update(job_id, force=True, status="done", error="")
    except _DownloadStop:
        kept = False
        with _download_lock:
            job = next((item for item in _download_load() if item.get("id") == job_id), None)
            if job:
                partial = str(job.get("file") or "") + ".part"
                kept = partial != ".part" and os.path.isfile(partial) and os.path.getsize(partial) > 0
                _download_partial(job, keep_part=kept)
        _download_update(job_id, force=True, status="cancelled", error="", note="Angehalten. Fortsetzen holt den Rest." if kept else "")
    except Exception as exc:
        kept = False
        with _download_lock:
            job = next((item for item in _download_load() if item.get("id") == job_id), None)
            if job:
                partial = str(job.get("file") or "") + ".part"
                kept = partial != ".part" and os.path.isfile(partial) and os.path.getsize(partial) > 0
                _download_partial(job, keep_part=kept)
        _download_update(job_id, force=True, status="failed", error=str(exc)[:240], note="Fortsetzen versucht den Rest noch einmal." if kept else "")
    finally:
        _download_stop.discard(job_id)
        _download_kick()


def _download_kick():
    started = []
    with _download_lock:
        jobs = _download_load()
        active = sum(1 for job in jobs if job.get("status") == "running")
        while active < 2:
            nxt = next((job for job in jobs if job.get("status") == "queued"), None)
            if not nxt:
                break
            nxt["status"] = "running"
            nxt["updated"] = time.time()
            started.append(nxt["id"])
            active += 1
        if started:
            _download_save_locked()
    for job_id in started:
        threading.Thread(target=_download_run, args=(job_id,), daemon=True).start()


def start_download(title, path, label, kind, folder):
    try:
        target = _download_dir(folder, create=True)
    except ValueError as exc:
        return {"error": str(exc), "message": _download_message(str(exc))}
    url, _headers = _download_headers(path)
    if not url.startswith(("http://", "https://")) or len(url) > 4000:
        return {"error": "stream", "message": "Diese Qualität hat keine ladbare Adresse."}
    kind = "hls" if kind == "hls" or ".m3u8" in url.lower() else "file"
    job = {
        "id": hashlib.sha256(os.urandom(16)).hexdigest()[:16],
        "title": clean_label(title or "")[:180] or "Video",
        "folder": target,
        "file": "",
        "label": clean_label(label or "")[:40],
        "kind": kind,
        "path": path,
        "status": "queued",
        "bytes": 0,
        "total": 0,
        "error": "",
        "note": "",
        "created": time.time(),
        "updated": time.time(),
    }
    with _download_lock:
        jobs = _download_load()
        jobs.append(job)
        del jobs[:-100]
        _download_save_locked()
    _remember_download_folder(target)
    _download_kick()
    ui = read_ui()
    return {"ok": True, "job": _download_public(job), "folder": ui.get("downloadFolder") or "", "folders": ui.get("downloadFolders") or []}


def _offline_download_folders():
    ui = read_ui()
    folders = [ui.get("downloadFolder", ""), *(ui.get("downloadFolders") or [])]
    with _download_lock:
        folders.extend(job.get("folder", "") for job in _download_load())
    try:
        import xbmcaddon
        addon = xbmcaddon.Addon()
        folders.extend([addon.getSetting("offline_library_folder"), addon.getSetting("download_folder")])
    except Exception:
        pass
    return folders


_download_library = DownloadLibrary(_offline_download_folders, "http://127.0.0.1:%d" % MEDIA_PORT)


def download_jobs_public():
    with _download_lock:
        jobs = list(_download_load())
    jobs.reverse()
    return {"jobs": [_download_public(job) for job in jobs], "ffmpeg": bool(_ffmpeg_bin())}


def cancel_download(job_id):
    job_id = str(job_id or "")
    with _download_lock:
        job = next((item for item in _download_load() if item.get("id") == job_id), None)
        if not job:
            return {"ok": False}
        if job.get("status") == "queued":
            job["status"] = "cancelled"
            _download_save_locked()
            return {"ok": True}
        if job.get("status") == "running":
            _download_stop.add(job_id)
            return {"ok": True}
    return {"ok": True}


def forget_download(job_id):
    job_id = str(job_id or "")
    with _download_lock:
        jobs = _download_load()
        kept = []
        for job in jobs:
            if job.get("id") == job_id and job.get("status") in ("done", "failed", "cancelled"):
                _download_partial(job)
                continue
            kept.append(job)
        _download_jobs[:] = kept
        _download_save_locked()
    return {"ok": True}


def resume_download(job_id):
    job_id = str(job_id or "")
    with _download_lock:
        job = next((item for item in _download_load() if item.get("id") == job_id), None)
        if not job or not _download_resumable(job):
            return {"ok": False, "message": "Diese Datei lässt sich nicht fortsetzen."}
        job["status"] = "queued"
        job["error"] = ""
        job["updated"] = time.time()
        _download_save_locked()
    _download_kick()
    return {"ok": True}


def reveal_download(job_id):
    with _download_lock:
        job = next((item for item in _download_load() if item.get("id") == job_id), None)
        path = str((job or {}).get("file") or "")
    if not path or not os.path.isfile(path):
        return {"ok": False, "message": "Die Datei liegt nicht mehr in dem Ordner."}
    subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    return {"ok": True}


def enrich_star_movies(query, items):
    params = dict(urllib.parse.parse_qsl(query or "", keep_blank_values=True))
    if params.get("mode") != "60" or params.get("action") != "movies":
        return
    portrait = star_portrait(params.get("id"))
    if not portrait:
        return
    picture = media_url(portrait)
    for item in items:
        if item.get("role") == "video":
            continue
        item["thumb"] = picture


def enrich_listing(website, items):
    if website != "pornhub":
        return
    try:
        thumbs = pornhub_category_thumbs()
    except Exception as exc:
        print("[cache] pornhub categories", exc)
        return
    for item in items:
        if item.get("role") == "video":
            continue
        title = (item.get("title") or "").strip().lower()
        src = next((thumbs.get(candidate) for candidate in _thumb_keys(title) if thumbs.get(candidate)), "")
        if src:
            item["thumb"] = media_url(src + "|Referer=https://www.pornhub.com/")


def _folder_pages(query, limit_pages=40, depth=0):
    found = []
    seen = set()
    media_count = 0
    current = query
    page = 0
    while current and page < limit_pages:
        result = run_plugin(current, 1)
        page += 1
        nxt = ""
        for item in result.get("items") or []:
            if item.get("role") == "next":
                nxt = plugin_query(item.get("url"))
                continue
            if item.get("role") in ("video", "image", "animation", "audio", "document", "file", "gallery"):
                media_count += 1
                continue
            if item.get("role") in ("search", "stars", "channels", "collections") or not item.get("folder"):
                continue
            if (item.get("title") or "").strip().lower() in ("categories", "tags", "genres", "kategorien"):
                continue
            title = item.get("title") or ""
            target = plugin_query(item.get("url"))
            if not title or not target or target in seen:
                continue
            seen.add(target)
            found.append({"title": title, "query": target})
        if media_count:
            break
        current = nxt
    if depth < 2 and media_count == 0:
        letters = [
            entry for entry in found
            if _is_term_index(entry["title"]) and "/search" not in (entry.get("query") or "")
        ]
        if letters and len(letters) <= 40:
            nested = []
            nested_seen = set()
            for entry in letters:
                for child in _folder_pages(entry["query"], limit_pages, depth + 1):
                    if child["query"] in nested_seen:
                        continue
                    nested_seen.add(child["query"])
                    nested.append(child)
            if nested:
                skip = {entry["query"] for entry in letters}
                found = [entry for entry in found if entry["query"] not in skip] + nested
    return found


def _is_term_index(title):
    text = (title or "").strip().lower()
    if text.startswith("letter "):
        return True
    if text in ("all tags", "all categories", "categories", "tags", "genres", "kategorien"):
        return True
    return len(text) == 1


def _term_kind(title):
    text = (title or "").lower()
    if any(word in text for word in ("tag", "keyword", "niche")) and "categor" not in text and "kategor" not in text and "genre" not in text:
        return "tags"
    if any(word in text for word in ("categor", "kategor", "genre", "studio", "series", "network", "movie", "film")):
        return "categories"
    return ""


def _pornhub_headers():
    return {"User-Agent": "Mozilla/5.0", "Cookie": "accessAgeDisclaimerPH=1; age_verified=1"}


def pornhub_official_categories():
    req = urllib.request.Request("https://www.pornhub.com/webmasters/categories", headers=_pornhub_headers())
    payload = json.loads(urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "replace"))
    found = []
    seen = set()
    for cat in payload.get("categories") or []:
        name = clean_label(str(cat.get("category") or ""))
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        slug = name.lower().replace(" ", "-")
        href = "https://www.pornhub.com/video?category_slug=%s" % urllib.parse.quote(slug)
        found.append({
            "title": name,
            "query": "mode=2&website=pornhub&url=%s" % urllib.parse.quote(href, safe=""),
        })
    return found


def pornhub_tag_hits(needle, limit=400):
    needle = (needle or "").strip().lower()
    if len(needle) < 2:
        return [], 0
    letter = next((char for char in needle if char.isalnum()), "")
    if not letter:
        return [], 0
    path = os.path.join(CACHE_DIR, "terms", "pornhub-tags-%s.json" % letter)
    names = _terms_memory.get(path)
    if names is None and offline_keep("terms") and os.path.isfile(path) and time.time() - os.path.getmtime(path) < 14 * 24 * 3600:
        try:
            names = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError):
            names = None
    if not isinstance(names, list):
        req = urllib.request.Request(
            "https://www.pornhub.com/webmasters/tags?list=%s" % urllib.parse.quote(letter),
            headers=_pornhub_headers(),
        )
        payload = json.loads(urllib.request.urlopen(req, timeout=90).read().decode("utf-8", "replace"))
        names = [str(name) for name in (payload.get("tags") or []) if name]
        _terms_memory[path] = names
        if offline_keep("terms"):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(names, handle, ensure_ascii=False)
    hits = []
    for name in names:
        if needle not in name.lower():
            continue
        href = "https://www.pornhub.com/video/search?search=%s" % urllib.parse.quote(name)
        hits.append({
            "title": name,
            "query": "mode=2&website=pornhub&url=%s" % urllib.parse.quote(href, safe=""),
        })
        if len(hits) >= limit:
            break
    return hits, len(names)


def site_terms(website, needle=""):
    website = re.sub(r"[^a-z0-9_]", "", (website or "").lower())
    needle = (needle or "").strip()
    if not website:
        return {"categories": [], "tags": [], "tagTotal": 0}
    if website == "pornhub":
        path = os.path.join(CACHE_DIR, "terms", "pornhub.json")
        categories = []
        if os.path.isfile(path) and time.time() - os.path.getmtime(path) < 7 * 24 * 3600:
            try:
                categories = json.load(open(path, encoding="utf-8")).get("categories") or []
            except (OSError, ValueError):
                categories = []
        if len(categories) < 50:
            try:
                categories = pornhub_official_categories()
            except Exception as exc:
                print("[terms] pornhub categories", exc)
                categories = []
            if categories:
                _terms_memory[path] = {"categories": categories, "tags": []}
                if offline_keep("terms"):
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "w", encoding="utf-8") as handle:
                        json.dump({"categories": categories, "tags": []}, handle, ensure_ascii=False)
        tags, scanned = pornhub_tag_hits(needle) if needle else ([], 0)
        visible = categories
        if needle:
            q = needle.lower()
            visible = [item for item in categories if q in (item.get("title") or "").lower()]
        return {
            "categories": visible,
            "tags": tags,
            "tagTotal": scanned,
            "truncated": bool(tags) and len(tags) >= 400,
        }
    path = os.path.join(CACHE_DIR, "terms", website + ".v2-media.json")
    remembered = _terms_memory.get(path)
    if isinstance(remembered, dict) and (remembered.get("categories") or remembered.get("tags")):
        return _filter_terms(remembered, needle)
    if offline_keep("terms") and os.path.isfile(path) and time.time() - os.path.getmtime(path) < 7 * 24 * 3600:
        try:
            payload = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError):
            payload = None
        if payload:
            return _filter_terms(payload, needle)
    home = run_plugin("mode=2&website=%s&url=BOOTSTRAP" % urllib.parse.quote(website), 1)
    categories = []
    tags = []
    for item in home.get("items") or []:
        if not item.get("folder") or item.get("role") in ("gallery", "next", "search", "stars", "channels", "collections"):
            continue
        query = plugin_query(item.get("url"))
        if not query or query == home.get("query"):
            continue
        kind = _term_kind(item.get("title") or "")
        if not kind and item.get("role") == "categories":
            kind = "categories"
        if kind == "tags":
            tags.extend(_folder_pages(query, 40))
        elif kind == "categories":
            categories.extend(_folder_pages(query, 40))
    if not categories:
        categories = _folder_pages("mode=8&website=%s&url=" % urllib.parse.quote(website), 40)
    categories = _unique_terms(categories)
    tags = _unique_terms(tags)
    if not categories and not tags:
        return {"categories": [], "tags": [], "tagTotal": 0, "truncated": False}
    payload = {"categories": categories, "tags": tags, "tagTotal": len(tags)}
    _terms_memory[path] = payload
    if offline_keep("terms"):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
    return _filter_terms(payload, needle)


def _unique_terms(items):
    found = []
    seen = set()
    for item in items:
        title = item.get("title") or ""
        if title.lower() in seen:
            continue
        seen.add(title.lower())
        found.append(item)
    return found


def _filter_terms(payload, needle):
    needle = (needle or "").strip().lower()
    categories = payload.get("categories") or []
    tags = payload.get("tags") or []
    if needle:
        categories = [item for item in categories if needle in (item.get("title") or "").lower()]
        tags = [item for item in tags if needle in (item.get("title") or "").lower()]
    return {
        "categories": categories,
        "tags": tags,
        "tagTotal": payload.get("tagTotal") or len(payload.get("tags") or []),
        "truncated": False,
    }


def _path_bytes(path):
    if os.path.isfile(path):
        try:
            return os.path.getsize(path), 1
        except OSError:
            return 0, 0
    if not os.path.isdir(path):
        return 0, 0
    total = 0
    files = 0
    for dirpath, _dirs, names in os.walk(path):
        for name in names:
            if name.endswith(".tmp"):
                continue
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
                files += 1
            except OSError:
                pass
    return total, files


def _catalog_disk_path():
    return os.path.join(CACHE_DIR, "catalog.json")


def _catalog_sites_from_disk(stamp):
    if not offline_keep("catalog"):
        return None
    path = _catalog_disk_path()
    if not os.path.isfile(path):
        return None
    try:
        stored = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if stored.get("stamp") != stamp or not isinstance(stored.get("sites"), list) or not stored["sites"]:
        return None
    return stored["sites"]


def _catalog_sites_save(stamp, sites):
    if not offline_keep("catalog") or not sites:
        return
    os.makedirs(CACHE_DIR, exist_ok=True)
    temp = _catalog_disk_path() + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump({"stamp": stamp, "sites": sites}, handle, ensure_ascii=False)
    os.replace(temp, _catalog_disk_path())


def _clear_offline(kind):
    if kind == "stats":
        path = os.path.join(CACHE_DIR, "library_facts.json")
        if os.path.isfile(path):
            os.remove(path)
    elif kind == "catalog":
        path = _catalog_disk_path()
        if os.path.isfile(path):
            os.remove(path)
        _catalog_static["stamp"] = None
        _catalog_static["sites"] = None
    elif kind == "stars":
        with _star_extra_lock:
            store = _star_extra_load()
            store["profiles"] = {}
            store["lang"] = {}
            _star_extra_save(force=True)
    elif kind == "terms":
        folder = os.path.join(CACHE_DIR, "terms")
        if os.path.isdir(folder):
            shutil.rmtree(folder, ignore_errors=True)
        _terms_memory.clear()
    elif kind == "lists":
        folder = os.path.join(CACHE_DIR, "lists")
        if os.path.isdir(folder):
            shutil.rmtree(folder, ignore_errors=True)
    elif kind == "images":
        for name in ("images", "star_images"):
            folder = os.path.join(CACHE_DIR, name)
            if os.path.isdir(folder):
                shutil.rmtree(folder, ignore_errors=True)


def offline_report():
    from ui_performance import directory_summary
    pending = False
    def size(path):
        nonlocal pending
        if os.path.isfile(path):return _path_bytes(path)
        summary = directory_summary.get(path)
        pending = pending or summary['running']
        return summary['bytes'], summary['files']
    flags = {kind: offline_keep(kind) for kind in _OFFLINE_KINDS}
    specs = [
        ("stats", "Statistik", os.path.join(CACHE_DIR, "library_facts.json"), True,
         "Zahlen der lokalen Bibliothek. Aktualisieren liest sie neu von diesem PC."),
        ("catalog", "Seitenliste", _catalog_disk_path(), True,
         "Namen und Arten der Seiten. Wird benutzt, solange der Addon-Ordner gleich bleibt."),
        ("stars", "Star-Profile und deutsche Texte", os.path.join(PROFILE, "star_data.sqlite3") if os.path.isfile(os.path.join(PROFILE,"star_data.sqlite3")) else os.path.join(PROFILE, "star_extra.json"), False,
         "Dauerhafte Profilbibliothek; Abrufe und Pausen steuerst du unter Sprache & Models. Leeren entfernt Zusatzprofile und Übersetzungen. Notizen, Quellenbelege, eigene Cover und Namen bleiben erhalten."),
        ("terms", "Kategorien und Tags", os.path.join(CACHE_DIR, "terms"), False,
         "Nur von Seiten, die du geöffnet hast. Es wird nicht jede Seite im Voraus geholt."),
        ("lists", "Zuletzt geöffnete Listen", os.path.join(CACHE_DIR, "lists"), False,
         "Videolisten für etwa sechs Stunden. Die nächste Liste kommt sonst live."),
        ("images", "Schon geladene Vorschaubilder", os.path.join(CACHE_DIR, "images"), False,
         "Schon geladene Vorschauen einschließlich Star-Finder-Bildern. Originaldateien werden beim Öffnen geladen."),
    ]
    items = []
    total = 0
    for kind, label, path, can_refresh, note in specs:
        amount, files = size(path)
        unknown = amount is None
        amount, files = amount or 0, files or 0
        if kind == "stars" and path.endswith(".sqlite3"):
            wal_bytes, wal_files = _path_bytes(path+"-wal")
            amount += wal_bytes;files += wal_files
        if kind == "images":
            image_bytes,image_files = size(os.path.join(CACHE_DIR,"star_images"))
            unknown = unknown or image_bytes is None
            amount += image_bytes or 0;files += image_files or 0
        total += amount
        items.append({
            "id": kind,
            "label": label,
            "note": note,
            "bytes": amount,
            "files": files,
            "count_pending": unknown,
            "keep": True if kind == "stars" else flags.get(kind, True),
            "keep_toggle": kind != "stars",
            "refresh": can_refresh,
            "clear": True,
        })
    extras = [
        ("Eigene Star-Cover", os.path.join(PROFILE, "star_covers"), "Bilder, die du als Cover gesetzt hast."),
        ("Gruppenlogos", os.path.join(PROFILE, "group_logos"), "Logos deiner Gruppen."),
        ("Logo und Hintergründe", os.path.join(PROFILE, "brand"), "Eigenes Logo und Hintergrundbilder."),
    ]
    for label, path, note in extras:
        amount, files = size(path)
        unknown = amount is None
        amount, files = amount or 0, files or 0
        total += amount
        items.append({
            "id": "",
            "label": label,
            "note": note,
            "bytes": amount,
            "files": files,
            "count_pending": unknown,
            "keep": True,
            "refresh": False,
            "clear": False,
        })
    return {"items": items, "total": total, "count_pending": pending}


def offline_apply(body):
    body = body if isinstance(body, dict) else {}
    keep_patch = body.get("keep") if isinstance(body.get("keep"), dict) else {}
    if keep_patch:
        write_ui({"offline": keep_patch})
        _offline_flag_cache["mtime"] = None
    for kind in body.get("clear") or []:
        if kind in _OFFLINE_KINDS:
            _clear_offline(kind)
    for kind in _OFFLINE_KINDS:
        if keep_patch.get(kind) is False:
            _clear_offline(kind)
    refreshed = []
    for kind in body.get("refresh") or []:
        if kind == "stats" and offline_keep("stats"):
            _clear_offline("stats")
            library_facts(force=True)
            refreshed.append("stats")
        elif kind == "catalog" and offline_keep("catalog"):
            _clear_offline("catalog")
            catalog_payload()
            refreshed.append("catalog")
    from ui_performance import directory_summary
    directory_summary.invalidate()
    report = offline_report()
    report["refreshed"] = refreshed
    return report


def _catalog_sites():
    """Seitenliste ohne read_ui. Sonst ruft die Statistik den Katalog und der wieder die Statistik."""
    main = addon_main()
    folder = main.WEBSITES_DIR
    stamp = int(os.path.getmtime(folder)) if os.path.isdir(folder) else 0
    cached = _catalog_static["sites"]
    if _catalog_static["stamp"] == stamp and cached:
        return cached
    disk = _catalog_sites_from_disk(stamp)
    if disk:
        _catalog_static["stamp"] = stamp
        _catalog_static["sites"] = disk
        return disk
    names = sorted(
        filename[:-3]
        for filename in os.listdir(folder)
        if filename.endswith(".py") and filename != "__init__.py"
    )
    hidden = main.get_hidden_websites()
    sites = []
    for name in names:
        if name in hidden:
            continue
        content, types = main.get_website_taxonomy(name)
        sites.append({
            "id": name,
            "title": main.get_website_label(name),
            "content": content,
            "types": types,
            "logo": "/logos/%s.png" % name,
        })
    _catalog_static["stamp"] = stamp
    _catalog_static["sites"] = sites
    _catalog_sites_save(stamp, sites)
    return sites


def catalog_payload():
    ui = read_ui()
    sites = []
    live_sites = []
    capabilities = media_library.provider_capabilities(ADDON)
    order = {}
    lookup = globals().get("addon_main")
    if lookup:
        try:
            order = lookup().get_website_catalog_order() or {}
        except Exception:
            order = {}
    for site in _catalog_sites():
        item = dict(site)
        item.update(capabilities.get(site["id"], {"mediaTypes": ["video"]}))
        item["favorite"] = site["id"] in ui["favorites"]
        item["catalogId"] = int(order.get(site["id"], 0) or 0)
        if item["id"] in media_library.LIVE_SITES:
            live_sites.append(item)
            continue
        item["hidden"] = site["id"] in ui.get("hiddenSites", [])
        sites.append(item)
    return {"sites": sites, "liveSites": live_sites, "recent": ui["recent"], "favorites": ui["favorites"], "hiddenSites": ui.get("hiddenSites", []), "mediaSchema": 1}


def _site_preview_cached(query):
    params = dict(urllib.parse.parse_qsl(query))
    key = cache_key("v19-quality|" + query + "|cv=" + website_cache_version(params.get("website")) + "|depth=1")
    payload = read_list_cache(key, 300)
    return payload if payload and not _signed_media_stale(payload) else None


_site_previews = site_previews.SitePreviews(
    lambda query: run_plugin(query, depth=1, preview=True),
    _site_preview_cached, enrich_tube_media, _user_busy.is_set,
)


def site_meta(name):
    main = addon_main()
    with _lock:
        site = main.load_single_website(name)
    if not site:
        return {"options": [], "current": "0"}
    options = [str(option) for option in (getattr(site, "sort_options", None) or getattr(site, "sorting_options", None) or [])]
    periods = [str(option) for option in (getattr(site, "period_options", None) or [])]
    current = site.addon.getSetting("%s_sort_by" % name) or "0"
    try:
        current_index = options.index(current)
    except ValueError:
        current_index = int(current) if str(current).isdigit() else 0
    return {
        "options": options,
        "current": str(current_index),
        "periods": periods,
        "categories": hasattr(site, "process_categories"),
        "stars": hasattr(site, "process_pornstars") or hasattr(site, "process_actresses_list"),
        "channels": hasattr(site, "process_channels"),
    }


def _listing_query(name, url, label):
    return {
        "ok": True,
        "label": clean_label(label),
        "query": "mode=2&website=%s&url=%s" % (urllib.parse.quote(name), urllib.parse.quote(url, safe="")),
    }


def _rewrite_query(url, updates):
    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(parsed.query)
    params.pop("page", None)
    for key, value in updates.items():
        params[key] = [value]
    return parsed._replace(query=urllib.parse.urlencode(params, doseq=True)).geturl()


def apply_site_sort(name, index, current_url=""):
    main = addon_main()
    with _lock:
        site = main.load_single_website(name)
        if not site:
            return {"ok": False}
        named = list(getattr(site, "sorting_options", None) or [])
        indexed = list(getattr(site, "sort_options", None) or [])
        index = int(index)
        if named and not indexed:
            if not 0 <= index < len(named):
                return {"ok": False}
            sort_key = named[index]
            site.addon.setSetting("%s_sort_by" % name, sort_key)
            sort_val = (getattr(site, "sorting_paths", None) or {}).get(sort_key, "")
            base = current_url or site.get_start_url_and_label()[0]
            if "category" not in base and "/video" not in base:
                base = site.get_start_url_and_label()[0]
            url = _rewrite_query(base, {"o": sort_val}) if sort_val else site.get_start_url_and_label()[0]
            return _listing_query(name, url, sort_key)
        if not indexed or not 0 <= index < len(indexed):
            return {"ok": False}
        site.addon.setSetting("%s_sort_by" % name, str(index))
        url, label = site.get_start_url_and_label()
    return _listing_query(name, url, label)


def apply_site_period(name, index, current_url=""):
    main = addon_main()
    with _lock:
        site = main.load_single_website(name)
        periods = list(getattr(site, "period_options", None) or [])
        index = int(index)
        if not site or not 0 <= index < len(periods):
            return {"ok": False}
        period_key = periods[index]
        period_val = (getattr(site, "period_paths", None) or {}).get(period_key, "")
        base = current_url or site.get_start_url_and_label()[0]
        url = _rewrite_query(base, {"p": period_val}) if period_val else base
    return _listing_query(name, url, period_key)


_SORT_PHRASES = (
    (re.compile(r"^(?:most\s+recent|recent\s+videos?|recent|newest|latest|neueste?)$", re.I), "Neueste"),
    (re.compile(r"^(?:most\s+viewed|most\s+popular|popular|trending|meistgesehen)$", re.I), "Meistgesehen"),
    (re.compile(r"^(?:top\s+rated|highest\s+rated|best\s+rated|am\s+besten\s+bewertet)$", re.I), "Am besten bewertet"),
    (re.compile(r"^(?:longest|long\s+movies|long\s+videos|am\s+längsten|am\s+laengsten)$", re.I), "Am längsten"),
    (re.compile(r"^(?:high\s+definition|ultra\s+hd|4k)$", re.I), "HD"),
    (re.compile(r"^(?:most\s+favou?rited|favou?rites|meist\s+gemerkt)$", re.I), "Meist gemerkt"),
)
_page_sort_cache = {}
_page_sort_lock = threading.Lock()


def _sort_phrase(text):
    label = re.sub(r"<[^>]+>", " ", html_unescape(text or ""))
    label = re.sub(r"\s+", " ", label).strip()
    if not label or len(label) > 40:
        return ""
    for pattern, german in _SORT_PHRASES:
        if pattern.match(label):
            return german
    return ""


def _listing_key(url):
    parts = urllib.parse.urlsplit(url or "")
    path = re.sub(r"/page/\d+/?$", "/", parts.path or "/")
    kept = [
        (key, value)
        for key, value in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in ("page", "from", "from_videos")
    ]
    return "%s://%s%s?%s" % (
        parts.scheme,
        parts.netloc.lower(),
        path,
        urllib.parse.urlencode(kept),
    )


def _sorts_from_html(page_html, page):
    host = urllib.parse.urlsplit(page).netloc.lower()
    best = []
    for match in re.finditer(r"<(ul|ol|div|nav)\b([^>]*)>", page_html or "", re.I):
        attrs = match.group(2)
        if not re.search(r"subfilter|\bsort|order-by|orderby|data-filter", attrs, re.I):
            continue
        if re.search(r"\bfilterMenu\b|\bfilter-menu\b", attrs, re.I):
            continue
        chunk = (page_html or "")[match.end():match.end() + 4500]
        close = re.search(r"</%s>" % match.group(1), chunk, re.I)
        if close:
            chunk = chunk[:close.end()]
        options = []
        seen = set()
        for anchor in re.finditer(r"<a\b([^>]*)>(.*?)</a>", chunk, re.I | re.S):
            label = _sort_phrase(anchor.group(2))
            href_match = re.search(r"""href=["']([^"']+)["']""", anchor.group(1), re.I)
            if not label or not href_match or label in seen:
                continue
            absolute = urllib.parse.urljoin(page, html_unescape(href_match.group(1)))
            parts = urllib.parse.urlsplit(absolute)
            if parts.scheme not in ("http", "https") or parts.netloc.lower() != host:
                continue
            before = chunk[max(0, anchor.start() - 120):anchor.start()]
            current = bool(re.search(r"\bactive\b", anchor.group(1) + before, re.I))
            options.append({"label": label, "url": absolute, "current": current})
            seen.add(label)
            if len(options) >= 8:
                break
        if len(options) >= 2 and len(options) > len(best):
            best = options
    return best


def _site_sort_state(name):
    main = addon_main()
    with _lock:
        site = main.load_single_website(name)
        if not site:
            return {"options": [], "current": "0", "urls": []}
        raw_options = [str(option) for option in (getattr(site, "sort_options", None) or getattr(site, "sorting_options", None) or [])]
        paths = getattr(site, "sort_paths", None) or {}
        base = str(getattr(site, "base_url", "") or "")
        urls = [base] if base.startswith("http") else []
        options = []
        for index, option in enumerate(raw_options):
            path = paths.get(option) or ""
            if path and base.startswith("http"):
                urls.append(urllib.parse.urljoin(base, path))
            options.append({"index": index, "label": _sort_phrase(option) or option})
        current = site.addon.getSetting("%s_sort_by" % name) or "0"
    try:
        current_index = raw_options.index(current)
    except ValueError:
        current_index = int(current) if str(current).isdigit() else 0
    if not 0 <= current_index < len(options):
        current_index = 0
    return {"options": options, "current": str(current_index), "urls": urls}


def page_sorts(website, url):
    website = str(website or "").strip()
    if not website or website == "global_search":
        return {"mode": "none", "options": []}
    raw_url = str(url or "").strip()
    page = raw_url if raw_url.startswith("http") else ""
    state = None
    if page:
        key = _listing_key(page)
        now = time.time()
        with _page_sort_lock:
            cached = _page_sort_cache.get(key)
        if cached and now - cached[0] < 6 * 60 * 60:
            found = cached[1]
        else:
            try:
                found = _sorts_from_html(fetch_html(page), page)
            except Exception:
                found = None
            if found is not None:
                with _page_sort_lock:
                    if len(_page_sort_cache) > 200:
                        _page_sort_cache.clear()
                    _page_sort_cache[key] = (now, found)
            else:
                found = []
        if len(found) >= 2:
            current = ""
            for item in found:
                if item.get("current") or _listing_key(item.get("url") or "") == key:
                    current = item["url"]
                    break
            if not current:
                current = found[0]["url"]
            return {
                "mode": "page",
                "options": [{"label": item["label"], "url": item["url"]} for item in found],
                "current": current,
            }
        state = _site_sort_state(website)
        page_key = _listing_key(page)
        on_root = any(_listing_key(item) == page_key for item in state["urls"] if item)
        if not on_root:
            return {"mode": "none", "options": []}
    else:
        state = _site_sort_state(website)
    if not state["options"]:
        return {"mode": "none", "options": []}
    return {"mode": "site", "options": state["options"], "current": state["current"]}


_film_opener = None
_film_lock = threading.Lock()
_film_ready = False


def _film_http():
    global _film_opener
    with _film_lock:
        if _film_opener is None:
            _film_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        return _film_opener


def _film_read(url, data=None):
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })
    with _film_http().open(req, timeout=8) as response:
        final = response.geturl()
        body = response.read(1_200_000)
    return final, body.decode("utf-8", "replace")


def _film_prepare():
    global _film_ready
    if _film_ready:
        return
    final, page = _film_read("https://www.adultempire.com/")
    if "AgeConfirmation" in final or "age-confirmation" in page[:4000].lower():
        _film_read("https://www.adultempire.com/Account/AgeConfirmation?ageConfirmationClicked=true")
    _film_ready = True


def _film_query_text(title):
    text = clean_label(title)
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", text)
    text = re.sub(r"\b(?:1080p|720p|480p|2160p|4k|uhd|hd|sd|xxx|full\s+movie|scene)\b", " ", text, flags=re.I)
    text = re.sub(r"[^0-9A-Za-z&'+.: -]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:80]


def _film_norm(text):
    text = (text or "").casefold().replace("#", " ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _film_score(query, title):
    left = _film_norm(query)
    right = _film_norm(title)
    if len(right) < 8 or not left:
        return 0
    if left == right:
        return 100
    if left.startswith(right + " ") or left.startswith(right):
        return 90
    if (" " + right + " ") in (" " + left + " ") and right.count(" ") >= 1:
        return 80
    return 0


def _film_cards(page_html):
    cards = []
    for match in re.finditer(r'Label="Title"', page_html or ""):
        window = page_html[max(0, match.start() - 1800):match.end() + 240]
        title_match = re.search(r'Label="Title"[^>]*>\s*([^<]+)', window, re.I)
        hrefs = re.findall(r'href="(/[0-9]+/[^"]+)"', window)
        poster_match = re.search(r'src="(https://imgs\dcdn\.adultempire\.com/movie/[^"]+)"', window)
        if not title_match or not hrefs:
            continue
        name = re.sub(r"\s+", " ", html_unescape(title_match.group(1))).strip()
        cards.append({
            "title": name,
            "url": urllib.parse.urljoin("https://www.adultempire.com", hrefs[-1]),
            "poster": html_unescape(poster_match.group(1)) if poster_match else "",
        })
        if len(cards) >= 12:
            break
    return cards


def _film_plain(match):
    if not match:
        return ""
    return re.sub(r"\s+", " ", html_unescape(match.group(1))).strip()


def _film_runtime(text):
    hours = re.search(r"(\d+)\s*hrs?", text or "", re.I)
    mins = re.search(r"(\d+)\s*mins?", text or "", re.I)
    parts = []
    if hours:
        parts.append(hours.group(1) + " Std.")
    if mins:
        parts.append(mins.group(1) + " Min.")
    if parts:
        return " ".join(parts)
    return re.sub(r"\s+", " ", text or "").strip()[:40]


def _film_poster(url):
    if not str(url).startswith("https://"):
        return ""
    if "adultempire.com" in url:
        url = re.sub(r"([?&])w=\d+", r"\1w=220", url)
        url = re.sub(r"([?&])h=\d+", r"\1h=310", url)
    return media_url(url)



def _film_categories(page_html, page_url, title):
    """Movie-specific evidence only: never the website's navigation categories."""
    found=[]
    def add(value):
        if not isinstance(value,(str,list,tuple)):return
        for label in ([value] if isinstance(value,str) else value or []):
            if isinstance(label,str) and clean_label(label).strip():
                name=clean_label(label).strip()
                if name.casefold() not in {row['name'].casefold() for row in found}:found.append({'name':name})
    for block in re.findall(r'<script[^>]+type=[\"\']application/ld\+json[\"\'][^>]*>(.*?)</script>',page_html,re.I|re.S):
        try:data=json.loads(block)
        except ValueError:continue
        nodes=data if isinstance(data,list) else [data]
        for node in nodes:
            if isinstance(node,dict) and isinstance(node.get('@graph'),list):nodes=nodes+node['@graph']
        for node in nodes:
            if not isinstance(node,dict):continue
            kinds=node.get('@type') or [];kinds=[kinds] if isinstance(kinds,str) else kinds
            if any(str(kind).rsplit('/',1)[-1] in ('Movie','VideoObject') for kind in kinds) and (star_finder.normal(node.get('name'))==star_finder.normal(title) or str(node.get('url') or '').split('?',1)[0]==page_url.split('?',1)[0]):add(node.get('genre'))
    heading=re.search(r'class=[\"\']movie-page__heading__title[\"\']',page_html,re.I)
    if heading:
        body=page_html[heading.start():]
        body=re.split(r'<(?:section|div|h2)[^>]*(?:related-movies|recommended-movies|recommendations)',body,maxsplit=1,flags=re.I)[0]
        for anchor in re.finditer(r'<a\b([^>]*)>(.*?)</a>',body,re.I|re.S):
            if re.search(r'(?:Label=[\"\']Categor(?:y|yName)[\"\']|itemprop=[\"\']genre[\"\'])',anchor[1],re.I):add(re.sub(r'<[^>]+>',' ',html_unescape(anchor[2])))
    return found


def _film_details(page_html, page_url, poster):
    if "adultempire.com" not in urllib.parse.urlsplit(page_url).netloc.lower():
        return None
    title = _film_plain(re.search(r'class="movie-page__heading__title"[^>]*>\s*([^<]+)', page_html, re.I))
    studio = _film_plain(re.search(r'Label="Studio"[^>]*>\s*([^<]+)', page_html, re.I))
    director = _film_plain(re.search(r'Label="Director"[^>]*>\s*([^<]+)', page_html, re.I))
    if director.casefold() in ("", "unknown", "n/a"):
        director = ""
    year_match = re.search(r"Production Year:\s*</small>\s*(\d{4})", page_html, re.I)
    if not year_match:
        year_match = re.search(r"<small>\s*\((\d{4})\)\s*</small>", page_html)
    year = year_match.group(1) if year_match else ""
    length_match = re.search(r"Length:\s*</small>\s*([^<]+)", page_html, re.I)
    runtime = _film_runtime(length_match.group(1) if length_match else "")
    cast = []
    seen = set()
    cast_at = re.search(r"<h2[^>]*>\s*Cast\s*</h2>", page_html, re.I)
    chunk = page_html[cast_at.end():cast_at.end() + 9000] if cast_at else ""
    next_heading = re.search(r"<h2\b", chunk, re.I)
    if next_heading:
        chunk = chunk[:next_heading.start()]
    for anchor in re.finditer(r"<a\b([^>]*)>(.*?)</a>", chunk, re.I | re.S):
        attrs = anchor.group(1)
        if not re.search(r"PerformerName", attrs, re.I):
            continue
        if re.search(r"interview", attrs, re.I):
            continue
        name = re.sub(r"<[^>]+>", " ", anchor.group(2))
        clean = re.sub(r"\s+", " ", html_unescape(name)).strip()
        key = clean.casefold()
        if len(clean) < 2 or len(clean) > 80 or key in seen:
            continue
        seen.add(key)
        cast.append(clean)
        if len(cast) >= 16:
            break
    picture = poster or ""
    image_match = re.search(r'property=[\'"]og:image[\'"]\s+content=[\'"]([^\'"]+)[\'"]', page_html, re.I)
    if image_match:
        picture = html_unescape(image_match.group(1))
    filled = [item for item in (studio, director, year, runtime, cast) if item]
    if not title or len(filled) < 2:
        return None
    return {
        "ok": True,
        "title": title[:180],
        "studio": studio[:80],
        "director": director[:80],
        "year": year,
        "runtime": runtime,
        "poster": _film_poster(picture),
        "cast": cast,
        "categories": _film_categories(page_html,page_url,title),
        "source": "AdultEmpire",
        "url": page_url if page_url.startswith("https://") else "",
    }


def film_facts(title):
    query = _film_query_text(title)
    if len(_film_norm(query)) < 8:
        return {"ok": False}
    folder = os.path.join(CACHE_DIR, "film")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, hashlib.sha256(query.casefold().encode("utf-8")).hexdigest() + ".json")
    try:
        with open(path, encoding="utf-8") as handle:
            cached = json.load(handle)
        age = time.time() - float(cached.get("at") or 0)
        ttl = 14 * 24 * 3600 if cached.get("ok") else 24 * 3600
        if age < ttl:
            payload = dict(cached)
            payload.pop("at", None)
            return payload
    except (OSError, ValueError, TypeError):
        cached = None
    facts = {"ok": False}
    searched = False
    try:
        _film_prepare()
        search_url = "https://www.adultempire.com/allsearch/search?q=" + urllib.parse.quote_plus(query)
        _final, page_html = _film_read(search_url)
        searched = True
        best = None
        best_score = 0
        for card in _film_cards(page_html):
            score = _film_score(query, card["title"])
            if card["url"].endswith("-porn-movies.html"):
                score += 3
            if score > best_score:
                best_score = score
                best = card
        if best and best_score >= 80:
            _final, detail = _film_read(best["url"])
            parsed = _film_details(detail, best["url"], best.get("poster") or "")
            if parsed:
                facts = parsed
    except Exception:
        facts = {"ok": False}
        searched = False
    if searched:
        stored = dict(facts)
        stored["at"] = time.time()
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(stored, handle, ensure_ascii=False)
        except OSError:
            pass
    return facts


INDEX = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Adult Client</title>
<style>
  :root { color-scheme: dark; --bg:#100d12; --card:#1c1620; --line:#3a2c3d; --text:#f4eef6; --muted:#b7a8b8; --accent:#e23d6b; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: "Segoe UI", sans-serif; background: radial-gradient(1200px 500px at 10% -10%, #3a1830, transparent), var(--bg); color: var(--text); }
  header { display:flex; gap:10px; align-items:center; flex-wrap:wrap; padding:14px 18px; border-bottom:1px solid var(--line); position:sticky; top:0; background:rgba(16,13,18,.94); backdrop-filter:blur(8px); z-index:2; }
  h1 { font-size:20px; margin:0 8px 0 0; letter-spacing:.04em; }
  .tools { display:flex; gap:8px; flex-wrap:wrap; width:100%; align-items:center; }
  .tools label { color:var(--muted); font-size:13px; display:flex; gap:6px; align-items:center; }
  select { border:1px solid var(--line); background:#241c28; color:var(--text); border-radius:10px; padding:8px 10px; font:inherit; }
  h1 span { color: var(--accent); }
  input, button { border:1px solid var(--line); background:#241c28; color:var(--text); border-radius:10px; padding:10px 12px; font:inherit; }
  button { cursor:pointer; }
  button.primary { background:var(--accent); border-color:transparent; color:white; }
  main { padding:18px 22px 40px; }
  .crumbs { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px; }
  .crumbs button { padding:6px 10px; }
  .grid { display:grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap:14px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:14px; overflow:hidden; text-align:left; padding:0; display:flex; flex-direction:column; min-height:210px; }
  .card img { width:100%; height:120px; object-fit:cover; background:#2a2230; }
  .card .meta { padding:10px 12px 12px; }
  .card strong { display:block; font-size:14px; line-height:1.3; }
  .card em { color:var(--muted); font-style:normal; font-size:12px; }
  .player { margin:0 0 16px; background:#000; border-radius:14px; overflow:hidden; }
  video { width:100%; max-height:70vh; background:#000; }
  .note { color: var(--muted); padding:8px 0; }
  .gate { min-height:100vh; display:grid; place-items:center; padding:24px; }
  .gate form { width:min(460px, 100%); background:var(--card); border:1px solid var(--line); border-radius:16px; padding:22px; }
  .hidden { display:none; }
</style>
</head>
<body>
<div id="gate" class="gate">
  <form id="gate-form">
    <h1>Adult<span>Hideout</span></h1>
    <p>Lokale Oberfläche für das installierte Kodi-Addon. Nur für Erwachsene ab 18 Jahren. Es werden keine Videos von diesem Programm gehostet.</p>
    <button class="primary" type="submit">Ich bin 18 oder älter</button>
  </form>
</div>
<div id="app" class="hidden">
  <header>
    <h1>Adult<span>Hideout</span></h1>
    <button id="home" type="button">Start</button>
    <button type="button" data-go="mode=20&website=global_search">Suche</button>
    <button type="button" data-go="mode=60">Star Finder</button>
    <button type="button" data-go="mode=31">Downloads</button>
    <button type="button" data-go="mode=32">Offline</button>
    <input id="search" placeholder="Suche auf der aktuellen Seite oder global" style="flex:1; min-width:220px">
    <button id="go" class="primary" type="button">Suchen</button>
    <div class="tools">
      <label>Sortierung <select id="sort"></select></label>
      <label>Inhalt <span id="content-filters"></span></label>
      <label>Art <span id="type-filters"></span></label>
      <input id="filter-text" placeholder="Diese Seite filtern">
      <span id="count" class="note"></span>
    </div>
  </header>
  <main>
    <div id="player" class="player hidden"></div>
    <div id="notes" class="note"></div>
    <div id="crumbs" class="crumbs"></div>
    <div id="grid" class="grid"></div>
  </main>
</div>
<script src="/static/hls.min.js"></script>
<script>
const state = { stack: [{ title: "Start", query: "" }], site: "", items: [], prefs: null };
const $ = (id) => document.getElementById(id);

function pluginQuery(url) {
  const marker = "plugin://plugin.video.adulthideout/";
  if (!url) return "";
  if (url.startsWith(marker)) return url.slice(marker.length).replace(/^\?/, "");
  const run = url.match(/RunPlugin\((.*)\)/) || url.match(/Container\.Update\((.*?)(?:,replace)?\)/);
  if (run) return pluginQuery(run[1]);
  return url.replace(/^\?/, "");
}

async function load(query, push) {
  $("notes").textContent = "Lade…";
  $("grid").innerHTML = "";
  const res = await fetch("/api/browse?" + (query || ""));
  const data = await res.json();
  if (push) state.stack.push({ title: data.category || "Seite", query });
  const params = new URLSearchParams(query || "");
  if (params.get("website")) state.site = params.get("website");
  renderCrumbs();
  const notes = (data.notifications || []).map(n => n.title + ": " + n.message).join(" · ");
  $("notes").textContent = data.error ? "Diese Funktion hat einen Fehler gemeldet." : notes;
  state.items = data.items || [];
  renderGrid();
  if (data.resolved && data.resolved.path) play(data.resolved);
  if (data.redirect && !(data.items || []).length) {
    load(pluginQuery(data.redirect), true);
    return;
  }
  if (!state.items.length && !(data.resolved && data.resolved.path)) {
    $("notes").textContent = notes || "Keine Einträge.";
  }
}

function renderGrid() {
  const needle = ($("filter-text").value || "").trim().toLowerCase();
  const visible = state.items.filter(item => !needle || item.title.toLowerCase().includes(needle));
  $("grid").innerHTML = "";
  $("count").textContent = visible.length + " von " + state.items.length;
  for (const item of visible) {
    const card = document.createElement("button");
    card.className = "card";
    card.type = "button";
    const img = document.createElement("img");
    img.alt = "";
    img.src = item.thumb || "/logos/icon.png";
    const meta = document.createElement("div");
    meta.className = "meta";
    const title = document.createElement("strong");
    title.textContent = item.title;
    const kind = document.createElement("em");
    kind.textContent = item.folder ? "Ordner" : "Abspielen";
    meta.append(title, kind);
    card.append(img, meta);
    card.onclick = () => openItem(item);
    $("grid").append(card);
  }
}

function chip(name, id, label, selected) {
  const box = document.createElement("label");
  const input = document.createElement("input");
  input.type = "checkbox";
  input.dataset.group = name;
  input.value = id;
  input.checked = selected;
  input.onchange = savePrefs;
  box.append(input, document.createTextNode(" " + label));
  return box;
}

async function loadPrefs() {
  const res = await fetch("/api/prefs");
  state.prefs = await res.json();
  $("sort").innerHTML = "";
  for (const option of state.prefs.sorts) {
    const node = document.createElement("option");
    node.value = option.id;
    node.textContent = option.label;
    node.selected = option.id === state.prefs.sort;
    $("sort").append(node);
  }
  $("content-filters").innerHTML = "";
  $("type-filters").innerHTML = "";
  for (const option of state.prefs.contentOptions) {
    $("content-filters").append(chip("content", option.id, option.label, state.prefs.content.includes(option.id)));
  }
  for (const option of state.prefs.typeOptions) {
    $("type-filters").append(chip("types", option.id, option.label, state.prefs.types.includes(option.id)));
  }
}

async function savePrefs() {
  const body = {
    sort: $("sort").value,
    content: [...document.querySelectorAll('input[data-group="content"]:checked')].map(node => node.value),
    types: [...document.querySelectorAll('input[data-group="types"]:checked')].map(node => node.value),
  };
  await fetch("/api/prefs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if ((state.stack[state.stack.length - 1] || {}).query === "") {
    state.stack = [{ title: "Start", query: "" }];
    load("", false);
  }
}

function openItem(item) {
  const query = pluginQuery(item.url);
  if (!item.folder && /(?:^|&)mode=4(?:&|$)/.test(query)) {
    load(query, false);
    return;
  }
  load(query, true);
}

function play(resolved) {
  const box = $("player");
  box.classList.remove("hidden");
  box.innerHTML = "";
  const video = document.createElement("video");
  video.controls = true;
  video.autoplay = true;
  box.append(video);
  let src = resolved.path;
  const pipe = src.indexOf("|");
  const headerText = pipe >= 0 ? src.slice(pipe + 1) : "";
  if (pipe >= 0) src = src.slice(0, pipe);
  if (/^https?:/i.test(src) && !src.includes("127.0.0.1") && !src.includes("localhost")) {
    const q = new URLSearchParams({ url: src });
    if (resolved.referer) q.set("Referer", resolved.referer);
    for (const part of headerText.split("&")) {
      const eq = part.indexOf("=");
      if (eq > 0) q.append(decodeURIComponent(part.slice(0, eq)), decodeURIComponent(part.slice(eq + 1)));
    }
    src = "/api/stream?" + q.toString();
  }
  const hls = resolved.mime.includes("mpegurl") || src.includes(".m3u8");
  if (hls && window.Hls && Hls.isSupported()) {
    const engine = new Hls();
    engine.loadSource(src);
    engine.attachMedia(video);
  } else {
    video.src = src;
  }
  video.onended = () => fetch("/api/stop", { method: "POST" });
}

function renderCrumbs() {
  $("crumbs").innerHTML = "";
  state.stack.forEach((entry, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = index === 0 ? "Start" : (entry.title || "Zurück");
    button.onclick = () => { state.stack = state.stack.slice(0, index + 1); load(entry.query, false); };
    $("crumbs").append(button);
  });
}

$("gate-form").onsubmit = (event) => {
  event.preventDefault();
  localStorage.setItem("ah-adult", "1");
  enterApp();
};
$("home").onclick = () => { state.stack = [{ title: "Start", query: "" }]; state.site = ""; load("", false); };
document.querySelectorAll("[data-go]").forEach(button => {
  button.onclick = () => load(button.dataset.go, true);
});
$("sort").onchange = savePrefs;
$("filter-text").addEventListener("input", renderGrid);
$("go").onclick = () => {
  const query = $("search").value.trim();
  if (query.length < 3) { $("notes").textContent = "Mindestens 3 Zeichen."; return; }
  const target = state.site
    ? "mode=6&action=direct_site_search&website=" + encodeURIComponent(state.site) + "&query=" + encodeURIComponent(query)
    : "mode=21&website=global_search&query=" + encodeURIComponent(query) + "&search_mode=selected";
  load(target, true);
};
$("search").addEventListener("keydown", (event) => { if (event.key === "Enter") $("go").click(); });
async function enterApp() {
  $("gate").classList.add("hidden");
  $("app").classList.remove("hidden");
  await loadPrefs();
  load("", false);
}
if (localStorage.getItem("ah-adult") === "1") enterApp();
</script>
</body>
</html>
"""


_tube_lock = threading.Lock()
_tube_jobs = {}
_tube_slots = threading.BoundedSemaphore(6)
_TUBE_PRIORITY = (
    "pornhub", "xvideos", "xnxx", "xhamster", "spankbang", "eporner",
    "youporn", "redtube", "tnaflix", "youjizz", "tube8", "hclips", "txxx", "empflix",
)
_TUBE_DEADLINE = 240
_TUBE_PER_SITE = 48
_TUBE_CAP = 3000


def _tube_sources():
    catalog = catalog_payload()
    rank = {name: index for index, name in enumerate(_TUBE_PRIORITY)}
    sites = [site for site in (catalog.get("sites") or []) if "tube" in (site.get("types") or [])]
    sites.sort(key=lambda site: (rank.get(site.get("id"), 1000), (site.get("title") or site.get("id") or "").lower()))
    return sites


def _tube_search_page(site, query):
    template = getattr(site, "search_url", "") or ""
    if not isinstance(template, str) or ("{" not in template and "%s" not in template):
        return ""
    quoted = urllib.parse.quote_plus(query)
    try:
        if "%s" in template and "{" not in template:
            return template % quoted
        return template.format(quoted)
    except Exception:
        try:
            return template.format(query=quoted)
        except Exception:
            return ""


def _tube_title_ok(title, query):
    label = re.sub(r"[^a-z0-9]+", " ", (title or "").lower())
    tokens = [token for token in re.sub(r"[^a-z0-9]+", " ", (query or "").lower()).split() if len(token) > 2]
    return not tokens or all(token in label for token in tokens)


def _tube_flat(job):
    front = []
    rest = []
    buckets = job.get("buckets") or {}
    for name in job.get("order") or []:
        bucket = buckets.get(name) or []
        front.extend(bucket[:4])
        rest.extend(bucket[4:])
    return front + rest


def _search_one_tube(name, query, label):
    from resources.lib import global_search as search_mod
    site = addon_main().load_single_website(name)
    if site is None or not callable(getattr(site, "search", None)):
        return [], "unavailable"
    captured = []
    search_mod._THREAD_LOCAL.captured = captured
    try:
        site.search(query)
    except Exception as exc:
        return [], str(exc)[:180]
    finally:
        search_mod._THREAD_LOCAL.captured = None
    items = []
    seen = set()
    for url, listitem, is_folder in captured:
        if is_folder or "mode=4" not in (url or ""):
            continue
        if url in seen:
            continue
        seen.add(url)
        item = item_payload({"url": url, "isFolder": False, "item": xbmcplugin._snapshot_item(listitem)})
        title = item.get("title") or ""
        if not title or "next page" in title.lower() or not _tube_title_ok(title, query):
            continue
        item["role"] = "video"
        item["site"] = name
        item["siteTitle"] = label or name
        items.append(item)
        if len(items) >= _TUBE_PER_SITE:
            break
    if items and any(not item.get("clip") or not item.get("uploader") or len(item.get("preview") or []) < 2 for item in items):
        page = _tube_search_page(site, query)
        if page:
            try:
                html_text = fetch_html(page)
            except Exception:
                html_text = ""
            if html_text:
                _apply_listing_media(items, html_text, page, name)
    return items, ""


def _finish_tube_job(job):
    with _tube_lock:
        if not job["running"]:
            return
        job["stop"] = True
        missing = max(0, job["total"] - job["done"])
        if len(job.get("seen") or []) < _TUBE_CAP:
            job["failed"] += missing
        job["done"] = job["total"]
        job["running"] = False
        job["finished"] = time.time()


def _run_tube_job(job):
    try:
        import resources.lib.global_search  # noqa: F401  installs the list capture hook
        addon_main()
        sources = _tube_sources()
        labels = {site.get("id"): site.get("title") or site.get("id") for site in sources}
        names = [site.get("id") for site in sources if site.get("id")]
        with _tube_lock:
            job["total"] = len(names)
            job["order"] = list(names)
        debug_log("server", "search", "start", {"q": job["query"], "sites": len(names)})
        if not names:
            return
        deadline = time.time() + _TUBE_DEADLINE

        def one(name):
            if job.get("stop"):
                return name, [], "stopped"
            if not _tube_slots.acquire(timeout=1):
                while not job.get("stop"):
                    if _tube_slots.acquire(timeout=1):
                        break
                else:
                    return name, [], "stopped"
            try:
                if job.get("stop"):
                    return name, [], "stopped"
                return name, *_search_one_tube(name, job["query"], labels.get(name) or name)
            except Exception as exc:
                return name, [], str(exc)[:180]
            finally:
                _tube_slots.release()

        pool = futures.ThreadPoolExecutor(max_workers=6)
        pending = {pool.submit(one, name): name for name in names}
        try:
            while pending and time.time() < deadline and not job.get("stop"):
                done, pending = futures.wait(pending, timeout=0.4, return_when=futures.FIRST_COMPLETED)
                for future in done:
                    if future.cancelled():
                        continue
                    try:
                        _name, items, err = future.result()
                    except Exception as exc:
                        items, err = [], str(exc)[:180]
                    with _tube_lock:
                        if not job["running"]:
                            continue
                        job["done"] += 1
                        if err and err != "stopped":
                            job["failed"] += 1
                        elif items:
                            bucket = job["buckets"].setdefault(_name, [])
                            added = False
                            for item in items:
                                url = item.get("url") or ""
                                if not url or url in job["seen"]:
                                    continue
                                job["seen"].add(url)
                                bucket.append(item)
                                added = True
                                if len(job["seen"]) >= _TUBE_CAP:
                                    job["stop"] = True
                                    break
                            if added:
                                job["withHits"] += 1
        finally:
            job["stop"] = True
            try:
                pool.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                pool.shutdown(wait=False)
        debug_log("server", "search", "fertig", {
            "q": job["query"],
            "n": len(job["seen"]),
            "hits": job["withHits"],
            "failed": job["failed"],
            "done": job["done"],
            "ms": int((time.time() - job["started"]) * 1000),
        })
    except Exception:
        debug_log("server", "search", "fehler", {"q": job.get("query") or "", "err": traceback.format_exc()[-500:]})
    finally:
        _finish_tube_job(job)


def _tube_snapshot(job, page, per_page):
    with _tube_lock:
        items = _tube_flat(job)
        running = bool(job["running"])
        done = job["done"]
        total = job["total"]
        failed = job["failed"]
        hits = job["withHits"]
        query = job["query"]
        capped = len(job.get("seen") or []) >= _TUBE_CAP
    count = len(items)
    pages = max(1, (count + per_page - 1) // per_page) if count else 1
    page = min(max(1, page), pages)
    start = (page - 1) * per_page
    return {
        "query": query,
        "items": items[start:start + per_page],
        "running": running,
        "done": done,
        "total": total,
        "failed": failed,
        "withHits": hits,
        "capped": capped,
        "page": page,
        "pages": pages,
        "count": count,
    }


def tube_search_payload(query, page, per_page, fresh=False):
    query = " ".join((query or "").split())[:80]
    key = query.casefold()
    if len(key) < 3:
        return {"query": query, "items": [], "running": False, "done": 0, "total": 0, "failed": 0, "withHits": 0, "capped": False, "page": 1, "pages": 1, "count": 0}
    per_page = _clamp_per_page(per_page)
    try:
        page = int(page or 1)
    except (TypeError, ValueError):
        page = 1
    with _tube_lock:
        job = _tube_jobs.get(key)
        stale = False
        if job and not job["running"]:
            stale = time.time() - (job["finished"] or job["started"]) > LIST_TTL
        if fresh or job is None or stale:
            if job is not None:
                job["stop"] = True
            for other in _tube_jobs.values():
                if other.get("running"):
                    other["stop"] = True
            job = {
                "query": query,
                "buckets": {},
                "order": [],
                "seen": set(),
                "running": True,
                "stop": False,
                "done": 0,
                "total": 0,
                "failed": 0,
                "withHits": 0,
                "started": time.time(),
                "finished": 0,
            }
            _tube_jobs[key] = job
            if len(_tube_jobs) > 6:
                for old in sorted(_tube_jobs, key=lambda name: _tube_jobs[name].get("started") or 0)[:-6]:
                    _tube_jobs.pop(old, None)
            threading.Thread(target=_run_tube_job, args=(job,), name="tube-search", daemon=True).start()
    return _tube_snapshot(job, page, per_page)


_TOOLS_DIR = os.path.join(PROFILE, "tools")
_TOOLS_STATE = os.path.join(PROFILE, "tools_state.json")
_tools_lock = threading.Lock()
_tool_jobs = []
_TOOL_MODELS = {
    "tiny": {"file": "ggml-tiny.bin", "disk": "75 MB", "ram": "etwa 300 MB", "limit": 90_000_000},
    "base": {"file": "ggml-base.bin", "disk": "142 MB", "ram": "etwa 400 MB", "limit": 180_000_000},
    "small": {"file": "ggml-small.bin", "disk": "466 MB", "ram": "etwa 900 MB", "limit": 520_000_000},
}
_FFMPEG_ZIP = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
_WHISPER_ZIP = "https://github.com/ggml-org/whisper.cpp/releases/download/v1.9.5/whisper-bin-x64.zip"


def _tools_read():
    try:
        with open(_TOOLS_STATE, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    model = data.get("model") if data.get("model") in _TOOL_MODELS else "tiny"
    return {
        "subs": bool(data.get("subs")),
        "strips": bool(data.get("strips")),
        "model": model,
        "phase": str(data.get("phase") or "")[:180],
        "error": str(data.get("error") or "")[:240],
        "busy": bool(data.get("busy")),
    }


def _tools_write(data):
    os.makedirs(PROFILE, exist_ok=True)
    temp = _TOOLS_STATE + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)
    os.replace(temp, _TOOLS_STATE)


def _tools_update(**fields):
    with _tools_lock:
        data = _tools_read()
        data.update(fields)
        _tools_write(data)
        return data


def _tool_find(folder, names):
    if not os.path.isdir(folder):
        return ""
    wanted = {name.lower() for name in names}
    for root, _dirs, files in os.walk(folder):
        for name in files:
            if name.lower() in wanted:
                return os.path.join(root, name)
    return ""


def _tool_ffmpeg():
    found = _tool_find(os.path.join(_TOOLS_DIR, "ffmpeg"), ("ffmpeg.exe",))
    return found or _ffmpeg_bin() or ""


def _tool_whisper():
    return _tool_find(os.path.join(_TOOLS_DIR, "whisper"), ("whisper-cli.exe", "main.exe", "whisper.exe"))


def _tool_model_path(model):
    spec = _TOOL_MODELS.get(model) or _TOOL_MODELS["tiny"]
    return os.path.join(_TOOLS_DIR, "models", spec["file"])


def _https_download(url, dest, limit):
    if not str(url).startswith("https://"):
        raise RuntimeError("Die Quelle ist nicht sicher.")
    request = urllib.request.Request(url, headers={"User-Agent": "AdultClient"})
    with urllib.request.urlopen(request, timeout=60) as response:
        final = str(response.geturl() or "")
        if not final.startswith("https://"):
            raise RuntimeError("Die Quelle ist nicht sicher.")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        partial = dest + ".part"
        total = 0
        with open(partial, "wb") as handle:
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise RuntimeError("Die Datei ist größer als erwartet.")
                handle.write(chunk)
        if total < 100000:
            raise RuntimeError("Die Datei ist unvollständig.")
        os.replace(partial, dest)
    return total


def _unzip_into(archive, folder):
    os.makedirs(folder, exist_ok=True)
    with zipfile.ZipFile(archive) as packed:
        for info in packed.infolist():
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/"):
                continue
            target = os.path.abspath(os.path.join(folder, name))
            if not target.startswith(os.path.abspath(folder) + os.sep) and target != os.path.abspath(folder):
                continue
            packed.extract(info, folder)


def _ensure_ffmpeg(state_model):
    if _tool_ffmpeg():
        return
    _tools_update(busy=True, phase="FFmpeg wird geladen, etwa 100 MB.", error="", model=state_model)
    archive = os.path.join(_TOOLS_DIR, "ffmpeg.zip")
    _https_download(_FFMPEG_ZIP, archive, 250_000_000)
    _unzip_into(archive, os.path.join(_TOOLS_DIR, "ffmpeg"))
    try:
        os.remove(archive)
    except OSError:
        pass
    if not _tool_ffmpeg():
        raise RuntimeError("FFmpeg liegt nach dem Entpacken nicht im Ordner.")


def _ensure_whisper(model):
    if not _tool_whisper():
        _tools_update(busy=True, phase="Spracherkennung wird geladen, etwa 9 MB.", error="", model=model)
        archive = os.path.join(_TOOLS_DIR, "whisper.zip")
        _https_download(_WHISPER_ZIP, archive, 30_000_000)
        _unzip_into(archive, os.path.join(_TOOLS_DIR, "whisper"))
        try:
            os.remove(archive)
        except OSError:
            pass
        if not _tool_whisper():
            raise RuntimeError("Das Spracherkennungsprogramm liegt nach dem Entpacken nicht im Ordner.")
    path = _tool_model_path(model)
    if os.path.isfile(path) and os.path.getsize(path) > 1_000_000:
        return
    spec = _TOOL_MODELS[model]
    _tools_update(busy=True, phase="Sprachmodell %s wird geladen, %s." % (model, spec["disk"]), error="", model=model)
    _https_download(
        "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/" + spec["file"],
        path,
        spec["limit"],
    )


def _tools_install(kind, model):
    try:
        if kind == "strips":
            _ensure_ffmpeg(model)
            _tools_update(strips=True, busy=False, phase="", error="")
            return
        _ensure_ffmpeg(model)
        _ensure_whisper(model)
        _tools_update(subs=True, busy=False, phase="", error="", model=model)
    except Exception as exc:
        failed = {"busy": False, "phase": "", "error": str(exc)[:240]}
        if kind == "strips":
            failed["strips"] = False
        else:
            failed["subs"] = False
        _tools_update(**failed)


def _tools_remove(kind):
    with _tools_lock:
        data = _tools_read()
        if data.get("busy"):
            return data
        if kind == "subs":
            data["subs"] = False
            shutil.rmtree(os.path.join(_TOOLS_DIR, "whisper"), ignore_errors=True)
            shutil.rmtree(os.path.join(_TOOLS_DIR, "models"), ignore_errors=True)
        else:
            data["strips"] = False
        if not data.get("subs") and not data.get("strips"):
            shutil.rmtree(os.path.join(_TOOLS_DIR, "ffmpeg"), ignore_errors=True)
        data["phase"] = ""
        data["error"] = ""
        _tools_write(data)
        return data


def tools_status():
    data = _tools_read()
    model = data["model"]
    spec = _TOOL_MODELS[model]
    ffmpeg = bool(_tool_ffmpeg())
    whisper = bool(_tool_whisper())
    model_ready = os.path.isfile(_tool_model_path(model)) and os.path.getsize(_tool_model_path(model)) > 1_000_000
    jobs = []
    for job in _tool_jobs[-4:]:
        item = {
            "id": job.get("id") or "",
            "kind": job.get("kind") or "",
            "status": job.get("status") or "",
            "error": job.get("error") or "",
            "phase": job.get("phase") or "",
            "frames": job.get("frames") or [],
        }
        srt = job.get("srt") or ""
        if srt and len(srt) <= 200000:
            item["srt"] = srt
        jobs.append(item)
    data.update({
        "ffmpeg": ffmpeg,
        "whisper": whisper,
        "modelReady": model_ready,
        "subsReady": bool(data["subs"] and ffmpeg and whisper and model_ready),
        "stripsReady": bool(data["strips"] and ffmpeg),
        "models": [
            {"id": key, "disk": value["disk"], "ram": value["ram"]}
            for key, value in _TOOL_MODELS.items()
        ],
        "chosen": {"disk": spec["disk"], "ram": spec["ram"]},
        "jobs": jobs,
    })
    return data


def tools_apply(body):
    action = str((body or {}).get("action") or "")
    kind = str((body or {}).get("id") or (body or {}).get("kind") or "")
    model = str((body or {}).get("model") or "")
    if model not in _TOOL_MODELS:
        model = _tools_read()["model"]
    if action in ("", "status"):
        return tools_status()
    if action == "disable" and kind in ("subs", "strips"):
        _tools_update(**{kind: False, "error": "", "model": model})
        return tools_status()
    if action == "delete" and kind in ("subs", "strips"):
        _tools_remove(kind)
        return tools_status()
    if action == "enable" and kind in ("subs", "strips"):
        current = _tools_read()
        if current.get("busy"):
            status = tools_status()
            status["error"] = "Es wird schon etwas geladen."
            return status
        _tools_update(busy=True, phase="Startet den Download.", error="", model=model)
        threading.Thread(target=_tools_install, args=(kind, model), daemon=True).start()
        return tools_status()
    if action == "run":
        return _tools_start_job(body if isinstance(body, dict) else {})
    return tools_status()


def _stream_target(raw):
    url, headers = _download_headers(str(raw or ""))
    if not url.startswith(("http://", "https://")) or len(url) > 4000:
        return "", {}
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if host in ("127.0.0.1", "localhost", "0.0.0.0") or host.endswith(".local"):
        return "", {}
    return url, headers


def _tool_header_blob(headers):
    lines = []
    for key in ("Referer", "Origin", "User-Agent", "Cookie"):
        value = str((headers or {}).get(key) or "").replace("\r", "").replace("\n", "")
        if value:
            lines.append("%s: %s" % (key, value))
    return "\r\n".join(lines)


def _tools_start_job(body):
    kind = str(body.get("kind") or "")
    status = tools_status()
    if kind == "strips" and not status.get("stripsReady"):
        return {"ok": False, "message": "Bilderstreifen sind aus oder FFmpeg fehlt. Das schaltest du unter Einstellungen, Zusatz ein."}
    if kind == "subs" and not status.get("subsReady"):
        return {"ok": False, "message": "Untertitel sind aus oder das Sprachmodell fehlt. Das schaltest du unter Einstellungen, Zusatz ein."}
    if kind not in ("subs", "strips"):
        return {"ok": False, "message": "Unbekannt."}
    url, headers = _stream_target(body.get("path") or "")
    if not url:
        return {"ok": False, "message": "Für dieses Video liegt keine lesbare Datei vor."}
    job = {
        "id": hashlib.sha256(os.urandom(16)).hexdigest()[:12],
        "kind": kind,
        "status": "running",
        "phase": "Startet.",
        "error": "",
        "frames": [],
        "srt": "",
        "path": url,
        "headers": headers,
        "duration": int(body.get("duration") or 0) if str(body.get("duration") or "").isdigit() else 0,
    }
    _tool_jobs.append(job)
    del _tool_jobs[:-8]
    threading.Thread(target=_tools_run_job, args=(job,), daemon=True).start()
    return {"ok": True, "job": job["id"]}


def _tools_run_job(job):
    try:
        if job["kind"] == "strips":
            _tools_strips(job)
        else:
            _tools_subs(job)
        job["status"] = "done"
        job["phase"] = ""
    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)[:240]
        job["phase"] = ""


def _tools_strips(job):
    ffmpeg = _tool_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("FFmpeg fehlt.")
    folder = os.path.join(_TOOLS_DIR, "strips", hashlib.sha256(job["path"].encode("utf-8")).hexdigest()[:16])
    os.makedirs(folder, exist_ok=True)
    duration = job.get("duration") or 0
    if duration > 20:
        times = [int(duration * (index + 1) / 9) for index in range(8)]
    else:
        times = [5, 15, 30, 60, 120, 180, 300, 600]
    header_blob = _tool_header_blob(job.get("headers"))
    frames = []
    for index, second in enumerate(times, start=1):
        dest = os.path.join(folder, "%02d.jpg" % index)
        command = [ffmpeg, "-y", "-ss", str(second)]
        if header_blob:
            command.extend(["-headers", header_blob])
        command.extend(["-i", job["path"], "-frames:v", "1", "-q:v", "5", dest])
        try:
            subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=25, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if os.path.isfile(dest) and os.path.getsize(dest) > 1000:
            frames.append("/file?path=" + urllib.parse.quote(dest))
        job["phase"] = "Bild %d." % index
    if len(frames) < 2:
        raise RuntimeError("Aus diesem Video ließen sich keine Bilder schneiden.")
    job["frames"] = frames[:8]


def _tools_subs(job):
    ffmpeg = _tool_ffmpeg()
    whisper = _tool_whisper()
    model = _tool_model_path(_tools_read()["model"])
    if not ffmpeg or not whisper or not os.path.isfile(model):
        raise RuntimeError("Spracherkennung ist nicht vollständig geladen.")
    folder = os.path.join(_TOOLS_DIR, "subs", job["id"])
    os.makedirs(folder, exist_ok=True)
    wav = os.path.join(folder, "audio.wav")
    header_blob = _tool_header_blob(job.get("headers"))
    command = [ffmpeg, "-y"]
    if header_blob:
        command.extend(["-headers", header_blob])
    command.extend(["-i", job["path"], "-vn", "-ac", "1", "-ar", "16000", "-t", "3600", wav])
    job["phase"] = "Ton wird gelesen, höchstens 60 Minuten."
    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=900, check=False)
    if not os.path.isfile(wav) or os.path.getsize(wav) < 8000:
        raise RuntimeError("Der Ton ließ sich nicht lesen.")
    base = os.path.join(folder, "captions")
    job["phase"] = "Text wird erkannt. Auf einem schwachen PC dauert das länger als der Film."
    subprocess.run(
        [whisper, "-m", model, "-f", wav, "-osrt", "-of", base],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=2700,
        check=False,
        cwd=folder,
    )
    srt = base + ".srt"
    if not os.path.isfile(srt):
        raise RuntimeError("Es wurde kein Untertitel erzeugt.")
    with open(srt, encoding="utf-8", errors="replace") as handle:
        job["srt"] = handle.read(200000)


CAM_PATH = os.path.join(PROFILE, "cam.json")
CAM_LIBRARY = os.path.join(PROFILE, "cam_library.json")
CAM_SESSION = os.path.join(PROFILE, "cam_sessions.json")
_CAM_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
_CAM_NAME = re.compile(r"^[A-Za-z0-9_-]{2,40}$")
_CAM_STREAM = re.compile(r"^[A-Za-z0-9_-]{2,80}$")
_CAM_KEY = re.compile(r"^[A-Za-z0-9_-]{4,80}$")
_CAM_CHILD = re.compile(r"\b(?:preteen|underage|jailbait|lolita|child\s*porn|nyo)\b", re.I)
_CAM_KEY_HINT = "Chaturbate braucht deinen eigenen Affiliate-Schlüssel. Den holst du im Affiliate-Programm von Chaturbate. Er bleibt auf diesem PC."
_SC_TAGS = {"f": ("girls",), "m": ("men",), "t": ("trans",), "c": ("couples",), "": ("girls", "men", "trans", "couples"), "all": ("girls", "men", "trans", "couples")}
_SC_GENDER = {"female": "weiblich", "females": "weiblich", "male": "männlich", "males": "männlich", "tranny": "trans", "trans": "trans", "malefemale": "paar", "femalemale": "paar", "group": "paar"}
_CB_GENDER = {"f": "weiblich", "m": "männlich", "t": "trans", "s": "trans", "c": "paar"}
_cam_cache = {}
_cam_cache_lock = threading.Lock()
_cam_pending = {}
_cam_list_pool = futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="AHCamList")
_CAM_LIST_WAIT = 6.0
# Stream discovery has its own budget; a page of 36 visible cams can start
# together without occupying the UI server's workers or the segment budget.
_CAM_PLAY_CONCURRENCY = 48
_cam_play_slots = threading.BoundedSemaphore(_CAM_PLAY_CONCURRENCY)
_cam_request = threading.local()
_cam_file_lock = threading.Lock()


def _cam_timeout(timeout):
    cancel = getattr(_cam_request, "cancel", None)
    if cancel is not None and cancel.is_set():
        raise ConnectionAbortedError("Cam request cancelled")
    connection = getattr(_cam_request, "connection", None)
    if connection is not None:
        import select
        try:
            if select.select([connection], [], [], 0)[0] and not connection.recv(1, socket.MSG_PEEK):
                raise ConnectionAbortedError("Cam request cancelled")
        except OSError as exc:
            raise ConnectionAbortedError("Cam request cancelled") from exc
    deadline = getattr(_cam_request, "deadline", None)
    if deadline is None:
        return timeout
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Cam connection deadline")
    return min(timeout, remaining)


def _cam_read(response, limit, timeout):
    if getattr(_cam_request, "deadline", None) is None:
        return response.read(limit)
    chunks = []
    remaining = limit
    while remaining > 0:
        wait = _cam_timeout(timeout)
        raw = getattr(getattr(response, "fp", None), "raw", None)
        sock = getattr(raw, "_sock", None)
        if sock is not None:
            sock.settimeout(wait)
        chunk = response.read1(min(65536, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _cam_open(url, headers, timeout, limit, jar=None):
    request = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)) if jar is not None else urllib.request.build_opener()
    try:
        response = opener.open(request, timeout=_cam_timeout(timeout))
    except urllib.error.HTTPError as exc:
        try:
            body = _cam_read(exc, min(limit, 4000), timeout)
        except Exception:
            body = b""
        finally:
            exc.close()
        return exc.code, body
    except Exception:
        return 0, b""
    try:
        return getattr(response, "status", 200) or 200, _cam_read(response, limit, timeout)
    except (OSError, TimeoutError):
        return 0, b""
    finally:
        response.close()


def _cam_age_ok(value):
    if value in (None, "", False):
        return True
    try:
        age = int(value)
    except (TypeError, ValueError):
        return True
    if age <= 0:
        return True
    return age >= 18


def _cam_subject(text):
    raw = str(text or "")
    if _CAM_CHILD.search(raw):
        return None
    text = re.sub(r"\s+", " ", raw).strip()
    if not text or "http" in text.lower() or "<" in text or ">" in text:
        return ""
    return text[:120]


def _cam_short(value, limit):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text or "http" in text.lower() or "<" in text or ">" in text or _CAM_CHILD.search(text):
        return ""
    return text[:limit]


def _cam_country(value):
    text = _cam_short(value, 32)
    if not re.fullmatch(r"[A-Za-z][A-Za-z .'-]{1,31}", text or ""):
        return ""
    return text


def _cam_langs(value):
    parts = value if isinstance(value, (list, tuple)) else re.split(r"[,/|]", str(value or ""))
    found = []
    for part in parts:
        text = _cam_short(part, 24)
        if len(text) < 2 or text.lower() in found:
            continue
        found.append(text)
        if len(found) >= 6:
            break
    return found


def _cam_number(value, limit):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    if number <= 0 or number > limit:
        return 0
    return number


def _cam_shown_age(value):
    if not _cam_age_ok(value):
        return 0
    try:
        age = int(value)
    except (TypeError, ValueError):
        return 0
    if age < 18 or age > 99:
        return 0
    return age


def _cam_badges(hd, *pairs):
    found = []
    if hd:
        found.append("HD")
    for label, value in pairs:
        if _cam_flag(value) and label not in found:
            found.append(label)
    return found[:6]


def _cam_details(room, source):
    if not isinstance(room, dict) or not isinstance(source, dict):
        return room
    from live_cam_profile import catalog_facts
    room["catalogFacts"] = catalog_facts(source)
    languages = _cam_langs(source.get("languages") or source.get("spoken_languages") or source.get("lang"))
    if languages:
        room["languages"] = languages
    followers = _cam_number(source.get("followers") if "followers" in source else source.get("num_followers"), 100_000_000)
    if source.get("followers", source.get("num_followers")) is not None:
        room["followers"] = followers
    seconds = _cam_number(source.get("seconds") if "seconds" in source else source.get("seconds_online"), 10_000_000)
    if source.get("seconds", source.get("seconds_online")) is not None:
        room["seconds"] = seconds
    country = _cam_country(source.get("country") or source.get("flag"))
    if country:
        room["country"] = country
    place = _cam_short(source.get("place") or source.get("location") or source.get("city"), 40)
    if place and place.lower() != country.lower():
        room["place"] = place
    age = _cam_shown_age(source.get("age"))
    if age:
        room["age"] = age
    badges = source.get("badges") if isinstance(source.get("badges"), list) else []
    badges = [str(item)[:16] for item in badges if str(item or "").strip()][:6]
    if badges:
        room["badges"] = badges
    return room


def _cam_tag_list(*values):
    found = []

    def add(value):
        text = re.sub(r"\s+", " ", str(value or "")).strip().lower().lstrip("#")
        text = re.sub(r"[^0-9a-zäöüß +._-]", "", text).strip()
        if len(text) < 2 or len(text) > 24 or text.isdigit() or "http" in text:
            return
        if _CAM_CHILD.search(text) or text in found:
            return
        found.append(text)

    def walk(value):
        if len(found) >= 12:
            return
        if isinstance(value, dict):
            for key in ("tag", "name", "label", "title"):
                if isinstance(value.get(key), str):
                    add(value.get(key))
            return
        if isinstance(value, (list, tuple)):
            for item in value[:24]:
                walk(item)
            return
        raw = str(value or "")
        for piece in re.findall(r"#([0-9A-Za-zÄÖÜäöüß_+-]{2,24})", raw):
            add(piece)
        if "," in raw or "|" in raw:
            for piece in re.split(r"[,|]", raw):
                add(piece)

    for value in values:
        walk(value)
        if len(found) >= 12:
            break
    return found


def _cam_collect_tags(source):
    if not isinstance(source, dict):
        return _cam_tag_list(source)
    blobs = []
    for key in ("tags", "tag", "tagsList", "hashtags", "hashTags", "categories"):
        if key in source:
            blobs.append(source.get(key))
    streams = source.get("streams")
    if isinstance(streams, list):
        blobs.append(streams)
    blobs.append(source.get("roomSubject") or source.get("subject") or source.get("room_subject") or "")
    return _cam_tag_list(*blobs)


def _cam_flag(value):
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "hd")
    return bool(value)


def _cam_image(url, referer):
    url = str(url or "")
    if not url.startswith("https://") or _is_video_url(url):
        return ""
    if referer:
        url = url + "|Referer=" + urllib.parse.quote(referer, safe="")
    return media_url(url)


def _cam_wm():
    with _cam_file_lock:
        if not os.path.isfile(CAM_PATH):
            return ""
        try:
            with open(CAM_PATH, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return ""
    value = str((data or {}).get("wm") or "").strip() if isinstance(data, dict) else ""
    return value if _CAM_KEY.fullmatch(value) else ""


def cam_key_has():
    return bool(_cam_wm())


def cam_key_set(raw):
    try:
        body = json.loads(raw.decode("utf-8") or "{}")
    except (ValueError, AttributeError):
        body = {}
    if not isinstance(body, dict):
        body = {}
    text = str(body.get("wm") or "").strip()
    if text and not _CAM_KEY.fullmatch(text):
        return {"ok": False, "has_key": cam_key_has(), "error": "Der Schlüssel hat ein unerwartetes Format."}
    # An empty box used to delete the saved key. Only Entfernen sends clear.
    if not text and body.get("clear") is not True:
        return {"ok": True, "has_key": cam_key_has()}
    with _cam_file_lock:
        try:
            if not text:
                if os.path.isfile(CAM_PATH):
                    os.remove(CAM_PATH)
            else:
                os.makedirs(PROFILE, exist_ok=True)
                temporary = CAM_PATH + ".tmp"
                with open(temporary, "w", encoding="utf-8") as handle:
                    json.dump({"wm": text}, handle, ensure_ascii=True)
                    handle.write("\n")
                os.replace(temporary, CAM_PATH)
        except OSError:
            return {"ok": False, "has_key": False, "error": "Der Schlüssel ließ sich nicht speichern."}
    with _cam_cache_lock:
        for key in list(_cam_cache):
            if key and key[0] == "chaturbate":
                _cam_cache.pop(key, None)
    return {"ok": True, "has_key": bool(text)}


def _cam_cached(key, loader):
    def snapshot(payload):
        return {**payload, "items": [dict(room) for room in payload.get("items") or []]}

    with _cam_cache_lock:
        hit = _cam_cache.get(key)
        if hit and time.monotonic() < hit[0]:
            return snapshot(hit[1])
        pending = _cam_pending.get(key)
        owner = pending is None
        if owner:
            pending = futures.Future()
            _cam_pending[key] = pending
    if not owner:
        try:
            return snapshot(pending.result(timeout=22))
        except futures.TimeoutError:
            return {"ok": False, "items": [], "error": "Die Raumliste wird noch geladen."}
    try:
        payload = loader()
        ttl = 20 if payload.get("ok") else 3
        if key[0] == "all" and payload.get("pending"):
            ttl = 2
        with _cam_cache_lock:
            _cam_cache[key] = (time.monotonic() + ttl, payload)
            if len(_cam_cache) > 24:
                for old in sorted(_cam_cache, key=lambda item: _cam_cache[item][0])[:8]:
                    _cam_cache.pop(old, None)
        pending.set_result(payload)
        return snapshot(payload)
    except Exception as exc:
        pending.set_exception(exc)
        raise
    finally:
        with _cam_cache_lock:
            _cam_pending.pop(key, None)


def _sc_image(path):
    path = str(path or "").split("?", 1)[0]
    if ".." in path or not path.startswith(("/previews/", "/avatars/")):
        return ""
    if not re.fullmatch(r"/[A-Za-z0-9_./~%-]{1,240}", path):
        return ""
    return _cam_image("https://static-cdn.strpst.com" + path, "https://stripchat.com/")


def _sc_list(tag, limit, offset):
    query = urllib.parse.urlencode({"limit": str(limit), "offset": str(offset), "primaryTag": tag, "sortBy": "stripScore"})
    headers = {
        "User-Agent": _CAM_UA,
        "Accept": "application/json",
        "Referer": "https://stripchat.com/" + tag,
        "Origin": "https://stripchat.com",
        "X-Requested-With": "XMLHttpRequest",
    }
    status, body = _cam_open("https://stripchat.com/api/front/v2/models?" + query, headers, 8, 800_000)
    if status != 200:
        return [], "Stripchat antwortet gerade nicht."
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return [], "Stripchat lieferte keine Liste."
    models = []
    for block in (data.get("blocks") or []) if isinstance(data, dict) else []:
        if isinstance(block, dict):
            models.extend(block.get("models") or [])
    return models, ""


def _sc_room(model, allow_offline=False):
    if not isinstance(model, dict):
        return None
    status = str(model.get("status") or "").lower()
    live = bool(model.get("isLive")) and status == "public"
    private = status in ("private", "p2p", "p2pvoice", "groupshow", "virtualprivate", "ticket")
    if not live and not allow_offline:
        return None
    name = str(model.get("username") or "")
    if not _CAM_NAME.fullmatch(name) or _CAM_CHILD.search(name):
        return None
    for key in ("age", "profileAge"):
        if key in model and not _cam_age_ok(model.get(key)):
            return None
    subject = _cam_subject(model.get("roomSubject") or model.get("subject") or "")
    if subject is None:
        return None
    gender = _SC_GENDER.get(str(model.get("broadcastGender") or model.get("gender") or "").strip().lower(), "")
    stream = str(model.get("streamName") or "")
    if not live or private or not _CAM_STREAM.fullmatch(stream):
        stream = ""
    try:
        viewers = int(model.get("viewersCount") or 0)
    except (TypeError, ValueError):
        viewers = 0
    hd = _cam_flag(model.get("isHd"))
    room = {
        "site": "stripchat",
        "name": name,
        "gender": gender,
        "viewers": max(0, viewers),
        "hd": hd,
        "subject": subject,
        "tags": _cam_collect_tags(model),
        "thumb": _sc_image(model.get("previewUrlThumbSmall") or model.get("avatarUrl") or ""),
        "portrait": _sc_image(model.get("avatarUrl") or ""),
        "stream": stream,
        "online": bool(live and not private),
        "show": "privat" if private else ("public" if live else "offline"),
    }
    return _cam_details(room, {
        **model,
        "country": model.get("country"),
        "badges": _cam_badges(hd, ("Neu", model.get("isNew")), ("VR", model.get("isVr")), ("Mobil", model.get("isMobile"))),
    })


def _sc_rooms(gender, offset):
    tags = _SC_TAGS.get(gender, _SC_TAGS["all"])
    per = 15 if len(tags) > 1 else 60
    tag_offset = 0 if len(tags) > 1 else offset
    items = []
    seen = set()
    errors = []
    batches = []
    if len(tags) == 1:
        batches.append(_sc_list(tags[0], per, tag_offset))
    else:
        with futures.ThreadPoolExecutor(max_workers=4) as pool:
            batches.extend(pool.map(lambda tag: _sc_list(tag, per, tag_offset), tags))
    for models, err in batches:
        if err:
            errors.append(err)
            continue
        taken = 0
        for model in models:
            if taken >= per:
                break
            room = _sc_room(model)
            if not room or room["name"].lower() in seen:
                continue
            seen.add(room["name"].lower())
            items.append(room)
            taken += 1
            if len(items) >= 60:
                break
        if len(items) >= 60:
            break
    if not items and errors:
        debug_log("server", "cam", "liste", {"site": "stripchat"})
        return {"ok": False, "site": "stripchat", "items": [], "error": errors[0]}
    return {"ok": True, "site": "stripchat", "items": items[:60], "paged": gender not in ("", "all")}


def _cam_client_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(2)
        sock.connect(("1.1.1.1", 80))
        return sock.getsockname()[0]
    except OSError:
        return ""
    finally:
        sock.close()


def _cb_error(status, text):
    if status == 0:
        return "Chaturbate hat nicht rechtzeitig geantwortet."
    try:
        err = json.loads(text)
    except ValueError:
        err = {}
    errors = err.get("errors") if isinstance(err, dict) else {}
    if not isinstance(errors, dict):
        errors = {}
    if "wm" in errors:
        return "Chaturbate lehnt den Schlüssel ab."
    if "client_ip" in errors:
        return "Chaturbate akzeptiert die lokale Adresse nicht."
    if "gender" in errors:
        return "Chaturbate kennt diese Gruppe gerade nicht."
    return "Chaturbate antwortet gerade nicht."


def _cb_fetch(gender, limit, offset, wm, ip):
    params = {"wm": wm, "format": "json", "limit": str(limit), "client_ip": ip}
    if offset:
        params["offset"] = str(offset)
    if gender in ("f", "m", "t", "s", "c"):
        params["gender"] = gender
    status, body = _cam_open(
        "https://chaturbate.com/api/public/affiliates/onlinerooms/?" + urllib.parse.urlencode(params),
        {"User-Agent": _CAM_UA, "Accept": "application/json"},
        10,
        800_000,
    )
    return status, body.decode("utf-8", "replace")


def _cb_room(row, allow_offline=False):
    if not isinstance(row, dict):
        return None
    show = str(row.get("current_show") or "").lower()
    public = show == "public"
    private = show in ("private", "group", "hidden", "away")
    if not public and not allow_offline:
        return None
    name = str(row.get("username") or "")
    if not _CAM_NAME.fullmatch(name) or _CAM_CHILD.search(name) or _CAM_CHILD.search(str(row.get("display_name") or "")):
        return None
    if not _cam_age_ok(row.get("age")) or not _cam_age_ok(row.get("display_age")):
        return None
    subject = _cam_subject(row.get("room_subject") or "")
    if subject is None:
        return None
    try:
        viewers = int(row.get("num_users") or 0)
    except (TypeError, ValueError):
        viewers = 0
    hd = _cam_flag(row.get("is_hd"))
    room = {
        "site": "chaturbate",
        "name": name,
        "gender": _CB_GENDER.get(str(row.get("gender") or "").lower(), ""),
        "viewers": max(0, viewers),
        "hd": hd,
        "subject": subject,
        "tags": _cam_collect_tags(row),
        "thumb": _cam_image(row.get("image_url_360x270") or row.get("image_url") or row.get("img") or "", "https://chaturbate.com/"),
        "stream": "",
        "online": public,
        "show": "privat" if private else ("public" if public else "offline"),
    }
    return _cam_details(room, {
        **row,
        "spoken_languages": row.get("spoken_languages"),
        "num_followers": row.get("num_followers"),
        "seconds_online": row.get("seconds_online"),
        "country": row.get("country"),
        "location": row.get("location"),
        "age": row.get("age"),
        "badges": _cam_badges(hd, ("Neu", row.get("is_new"))),
    })


def _cb_rooms(gender, offset):
    wm = _cam_wm()
    stored = bool(wm)
    if not wm:
        return {"ok": False, "need_key": True, "has_key": False, "site": "chaturbate", "items": [], "error": _CAM_KEY_HINT}
    ip = _cam_client_ip()
    if not ip:
        return {"ok": False, "has_key": stored, "site": "chaturbate", "items": [], "error": "Die eigene Adresse für Chaturbate ließ sich nicht ermitteln."}
    status, text = _cb_fetch(gender if gender != "all" else "", 60, offset, wm, ip)
    if gender == "t" and status == 400 and "gender" in text:
        status, text = _cb_fetch("s", 60, offset, wm, ip)
    if status != 200:
        debug_log("server", "cam", "liste", {"site": "chaturbate"})
        return {"ok": False, "has_key": stored, "site": "chaturbate", "items": [], "error": _cb_error(status, text)}
    try:
        data = json.loads(text)
    except ValueError:
        return {"ok": False, "has_key": stored, "site": "chaturbate", "items": [], "error": "Chaturbate lieferte keine Liste."}
    rows = data.get("results") if isinstance(data, dict) else data
    if isinstance(data, dict) and not isinstance(rows, list):
        rows = data.get("rooms") or []
    if not isinstance(rows, list):
        rows = []
    items = []
    seen = set()
    for row in rows:
        room = _cb_room(row)
        if not room or room["name"].lower() in seen:
            continue
        seen.add(room["name"].lower())
        items.append(room)
        if len(items) >= 60:
            break
    return {"ok": True, "has_key": True, "site": "chaturbate", "items": items, "paged": True}


_CAM_SITES = live_cam_providers.SITES
_CAM_ACCOUNT_SITES = live_cam_providers.ACCOUNT_SITES
_cam_public_sources = None


def _cam_extra_sources():
    global _cam_public_sources
    if _cam_public_sources is None:
        _cam_public_sources = live_cam_providers.PublicProviders(globals())
    return _cam_public_sources


def _cam_extra_rooms(site, gender, offset):
    return _cam_extra_sources().rooms(site, gender, offset)


def _cam_extra_play(site, name):
    return _cam_extra_sources().play(site, name)
_cam_lib_lock = threading.Lock()
_cam_lib_save_lock = threading.Lock()
_cam_models_epoch = 0
_cam_epoch_at = 0.0
_cam_models_service = None
_cam_library_sync_service = None
_cam_library_sync_lock = threading.Lock()

def _cam_library_sync():
    global _cam_library_sync_service
    with _cam_library_sync_lock:
        if _cam_library_sync_service is None:
            _cam_library_sync_service = live_cam_library_sync.LibrarySync(globals())
        return _cam_library_sync_service

_cam_biography_instance = None
_cam_biography_lock = threading.Lock()


def _cam_biography_service():
    global _cam_biography_instance
    with _cam_biography_lock:
        if _cam_biography_instance is None:
            _cam_biography_instance = live_cam_biography.BiographyService(globals())
        return _cam_biography_instance


_cam_models_service_lock = threading.Lock()

def _cam_models_hub():
    global _cam_models_service
    with _cam_models_service_lock:
        if _cam_models_service is None:
            _cam_models_service = live_cam_models.ModelsHub(globals())
        return _cam_models_service

_cam_lib_cache = None
_cam_lib_written = 0.0


def _cam_site(value):
    site = str(value or "").strip().lower()
    return site if site in _CAM_SITES else ""


def _cam_pair(site, name):
    site = _cam_site(site)
    name = str(name or "").strip()
    if not site or not _CAM_NAME.fullmatch(name) or _CAM_CHILD.search(name):
        return ""
    return site + ":" + name


def _cam_json_read(path):
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _cam_json_write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
    os.replace(temp, path)


def _cam_library_blank():
    return {"models": {}, "favs": [], "groups": [], "account": {}, "account_meta": {}}


def _cam_library_load():
    global _cam_lib_cache
    with _cam_lib_lock:
        if _cam_lib_cache is None:
            raw = _cam_json_read(CAM_LIBRARY)
            blank = _cam_library_blank()
            if isinstance(raw.get("models"), dict):
                blank["models"] = raw["models"]
            if isinstance(raw.get("favs"), list):
                blank["favs"] = [item for item in raw["favs"] if isinstance(item, str)][:60000]
            if isinstance(raw.get("groups"), list):
                blank["groups"] = raw["groups"][:40]
            if isinstance(raw.get("account"), dict):
                blank["account"] = raw["account"]
            if isinstance(raw.get("account_meta"), dict):
                blank["account_meta"] = raw["account_meta"]
            _cam_lib_cache = blank
        return _cam_lib_cache


def _cam_library_save(force=False):
    global _cam_lib_written, _cam_models_epoch, _cam_epoch_at
    from copy import deepcopy
    snapshot = None
    with _cam_lib_save_lock:
        with _cam_lib_lock:
            if _cam_lib_cache is None:
                return
            now = time.time()
            # Publishing every room touch rebuilt the whole catalog index and
            # stalled the Live page. The open view reads a fresh epoch at most
            # every 20 seconds; the file itself is written at most once a minute.
            if force or now - _cam_epoch_at >= 20:
                _cam_models_epoch += 1
                _cam_epoch_at = now
            if force or now - _cam_lib_written >= 60:
                models = _cam_lib_cache.get("models") or {}
                snapshot = {
                    "models": {key: dict(row) if isinstance(row, dict) else row for key, row in models.items()},
                    "favs": list(_cam_lib_cache.get("favs") or []),
                    "groups": deepcopy(_cam_lib_cache.get("groups") or []),
                    "account": deepcopy(_cam_lib_cache.get("account") or {}),
                    "account_meta": deepcopy(_cam_lib_cache.get("account_meta") or {}),
                }
                _cam_lib_written = now
        if snapshot is not None:
            _cam_json_write(CAM_LIBRARY, snapshot)


def _cam_viewers(value, previous):
    try:
        return max(0, min(int(value or 0), 1_000_000))
    except (TypeError, ValueError):
        try:
            return max(0, min(int(previous or 0), 1_000_000))
        except (TypeError, ValueError):
            return 0


def _cam_library_see(items):
    if not items:
        return
    library = _cam_library_load()
    added = False
    now = int(time.time())
    with _cam_lib_lock:
        models = library["models"]
        for item in items:
            if not isinstance(item, dict):
                continue
            key = _cam_pair(item.get("site"), item.get("name"))
            if not key:
                continue
            tags = [tag for tag in (item.get("tags") or []) if isinstance(tag, str)][:12]
            previous = models.get(key) if isinstance(models.get(key), dict) else {}
            if not previous:
                added = True
            models[key] = {
                **{k: v for k, v in previous.items() if k in ("coverAt", "coverSource", "coverError", "profileImages", "profileAt", "profileError", "enrichedAt", "bio", "displayName", "publicFacts", "publicLinks", "profileTags", "profileSource")},
                "site": key.split(":", 1)[0],
                "name": key.split(":", 1)[1],
                "gender": str(item.get("gender") or previous.get("gender") or "")[:20],
                "tags": tags or list(previous.get("tags") or [])[:12],
                "subject": str(item.get("subject") or previous.get("subject") or "")[:120],
                "thumb": str(item.get("thumb") or previous.get("thumb") or "")[:700],
                "portrait": str(item.get("portrait") or previous.get("portrait") or "")[:700],
                "hd": item.get("hd") if isinstance(item.get("hd"), bool) else previous.get("hd"),
                "viewers": _cam_viewers(item.get("viewers"), previous.get("viewers")) if item.get("viewers") is not None else None,
                "online": item.get("online") if isinstance(item.get("online"), bool) else None,
                "show": str(item.get("show") or "unknown")[:16],
                "stream": item.get("stream") if _CAM_STREAM.fullmatch(str(item.get("stream") or "")) else str(previous.get("stream") or ""),
                "languages": _cam_langs(item.get("languages") or previous.get("languages") or []),
                "followers": _cam_number(item["followers"], 100_000_000) if item.get("followers") is not None else (None if not previous.get("metadataVersion") and previous.get("followers")==0 else previous.get("followers")),
                "metadataVersion": 2,
                "seconds": _cam_number(item["seconds"], 10_000_000) if item.get("seconds") is not None else None,
                "country": _cam_country(item.get("country") or previous.get("country")),
                "place": _cam_short(item.get("place") or previous.get("place") or "", 40),
                "age": _cam_shown_age(item.get("age") or previous.get("age")),
                "badges": [str(badge)[:16] for badge in (item.get("badges") or previous.get("badges") or []) if str(badge or "").strip()][:6],
                "seen": now,
                "firstSeen": previous.get("firstSeen") or previous.get("seen") or now,
                "lastOnline": now if item.get("online") is True else previous.get("lastOnline"),
                "observations": int(previous.get("observations") or 0) + (1 if now-int(previous.get("seen") or 0)>=30 else 0),
                "appearances": int(previous.get("appearances") or 0) + (1 if item.get("online") is True and (previous.get("online") is not True or now-int(previous.get("seen") or 0)>120) else 0),
                "gaming": item.get("gaming") if isinstance(item.get("gaming"),bool) else previous.get("gaming"),
                "catalogFacts": item.get("catalogFacts") or previous.get("catalogFacts") or [],
                "personal": dict(previous.get("personal") or {}),
            }
        # The persistent library is an archive. Refreshes never evict old models.
    _cam_library_save(False)


def _cam_library_view(query):
    from live_cam_performance import studio_snapshots
    compact=(query or {}).get('part')=='studio' and (query or {}).get('compact')=='1'
    if compact:
        try:offset=max(0,min(60000,int((query or {}).get('offset') or 0)))
        except (ValueError,TypeError):offset=0
        token=(query or {}).get('snapshot')
        if token:
            page=studio_snapshots.page(token,offset,2000)
            if page is None:return {'ok':False,'error':'Der Listenstand ist abgelaufen. Bitte die Modellliste aktualisieren.'}
            _cam_attach_local(page['items']);return page
    library = _cam_library_load()
    part = str((query or {}).get("part") or "meta").strip().lower()
    site = _cam_site((query or {}).get("site"))
    gender = str((query or {}).get("gender") or "").strip().lower()
    tag = str((query or {}).get("tag") or "").strip().lower()[:24]
    text = str((query or {}).get("q") or "").strip().lower()[:40]
    group_id = str((query or {}).get("group") or "").strip()[:40]
    try:
        offset = max(0, min(60000, int((query or {}).get("offset") or 0)))
    except (TypeError, ValueError):
        offset = 0
    effective_groups = []
    if part != "studio" or offset == 0:
        hub = _cam_models_hub()
        with hub.lock:
            _, effective_groups = hub.records()
    with _cam_lib_lock:
        favs = [item for item in library.get("favs") or [] if isinstance(item, str)]
        account = library.get("account") if isinstance(library.get("account"), dict) else {}
        groups = [{k: json.loads(json.dumps(v)) for k, v in group.items() if k != 'account'} for group in effective_groups if not group.get('systemRole') or group.get('items')]
        models = library.get("models") if isinstance(library.get("models"), dict) else {}
        account_names = set()
        for names in account.values():
            if isinstance(names, list):
                account_names.update(item for item in names if isinstance(item, str))
        if part == "studio":
            models = dict(models)
            for key in account_names:
                if key not in models and ":" in key:
                    site_name, model_name = key.split(":", 1)
                    if _cam_pair(site_name, model_name) == key:
                        models[key] = {"site": site_name, "name": model_name, "personal": {}, "online": None, "seen": 0}
        rows = []
        for key, row in (() if part in ("meta", "groups") else models.items()):
            if not isinstance(row, dict):
                continue
            if part == "single" and key != _cam_pair((query or {}).get("site"), (query or {}).get("name")):
                continue
            if site and row.get("site") != site:
                continue
            if gender and gender not in ("", "all") and str(row.get("gender") or "") != {"f": "weiblich", "m": "männlich", "t": "trans", "c": "paar"}.get(gender, gender):
                continue
            if tag and tag not in (row.get("tags") or []):
                continue
            blob = (str(row.get("name") or "") + " " + str(row.get("subject") or "") + " " + " ".join(row.get("tags") or [])).lower()
            if text and text not in blob:
                continue
            if part == "favs" and key not in favs:
                continue
            if part == "account" and key not in account_names:
                continue
            if part == "group":
                wanted = []
                for group in groups:
                    if group["id"] == group_id:
                        wanted = group["items"]
                if key not in wanted:
                    continue
            public = dict(row)
            if compact:
                for field in ('bio','publicFacts','publicLinks','profileImages','catalogFacts','profileTags'):
                    public.pop(field,None)
            public["fav"] = key in favs
            public["accountFav"] = key in account_names
            public.pop("stream", None)
            stream = row.get("stream") if _CAM_STREAM.fullmatch(str(row.get("stream") or "")) else ""
            if stream:
                public["stream"] = stream
            rows.append(public)
    if part in ("meta", "groups"):
        rows = []
    rows.sort(key=lambda row: (-int(row.get("viewers") or 0), str(row.get("name") or "").lower()))
    accounts = _cam_account_public()
    if compact:
        data={'ok':True,'part':'studio','total':len(rows),'items':rows,'favs':favs,
              'groups':groups,'accounts':accounts,'count':len(models),'following_meta':dict(library.get('account_meta') or {})}
        token=studio_snapshots.put(data)
        page=studio_snapshots.page(token,offset,2000);_cam_attach_local(page['items']);return page
    shown = rows[offset:offset + (250 if part == "studio" else 60)]
    _cam_attach_local(shown)
    return {
        "ok": True,
        "part": part,
        "total": len(rows),
        "items": shown,
        "favs": favs,
        "groups": [{**{k: group[k] for k in ("id", "name", "description", "parent", "kind", "systemRole", "site", "revision", "archived", "cover") if k in group}, "count": len(group["items"]), **({"items": group["items"]} if part in ("studio", "single") else {})} for group in groups],
        "accounts": accounts,
        "count": len(models),
        **({"following_meta": dict(library.get("account_meta") or {})} if part == "studio" else {}),
    }


def _cam_library_post(raw):
    try:
        body = json.loads(raw.decode("utf-8") or "{}")
    except ValueError:
        return {"ok": False, "error": "Die Anfrage war unlesbar."}
    if not isinstance(body, dict):
        return {"ok": False, "error": "Die Anfrage war unlesbar."}
    op = str(body.get("op") or "")
    if op.startswith("group-"):
        hub = _cam_models_hub()
        try:
            with hub.lock:
                result = hub.group_service().legacy(body)
            return {**result, **result.get("group", {}), "groups": _cam_library_view({"part": "groups"}).get("groups", [])}
        except (ValueError, TypeError, KeyError, OSError) as error:
            return {"ok": False, "error": str(error)[:350]}
    library = _cam_library_load()
    if op in ("model-save", "model-delete"):
        key = _cam_pair(body.get("site"), body.get("name"))
        if not key:
            return {"ok": False, "error": "Unbekanntes Model."}
        with _cam_lib_lock:
            if op == "model-delete":
                library["models"].pop(key, None)
                library["favs"] = [item for item in library["favs"] if item != key]
                for group in library["groups"]:
                    group["items"] = [item for item in group.get("items") or [] if item != key]
            else:
                if key not in library["models"] and len(library["models"]) >= 60000:
                    return {"ok": False, "error": "Der persönliche Modelbestand ist voll."}
                row = library["models"].setdefault(key, {"site": key.split(":", 1)[0], "name": key.split(":", 1)[1], "online": None, "show": "unknown", "seen": 0})
                personal = row.setdefault("personal", {})
                if "expected_notes_revision" in body and body.get("expected_notes_revision") != personal.get("notesRevision", 0):
                    return {"ok": False, "conflict": True, "error": "Die Notizen wurden zwischenzeitlich in einem anderen Fenster geändert. Dein Entwurf bleibt erhalten.", "personal": dict(personal)}
                personal["saved"] = True
                if "notes" in body:
                    personal["notes"] = str(body["notes"])[:10000]
                if isinstance(body.get("tags"), list):
                    personal["tags"] = [str(tag)[:40] for tag in body["tags"][:100]]
                if "notes" in body or "tags" in body:
                    personal["notesRevision"] = personal.get("notesRevision", 0) + 1
                for field in ("bookmarked", "compare"):
                    if field in body and isinstance(body[field], bool):
                        personal[field] = body[field]
                for field, maximum in (("rating", 5), ("priority", 10)):
                    if field in body:
                        try:
                            personal[field] = max(0, min(maximum, int(body[field])))
                        except (TypeError, ValueError):
                            pass
                personal_reply = dict(personal)
        _cam_library_save(True)
        return {"ok": True, **({"personal": personal_reply} if op == "model-save" else {})}
    if op == "import-favs":
        with _cam_lib_lock:
            for item in body.get("items") or []:
                parts = item.split(":", 1) if isinstance(item, str) else []
                key = _cam_pair(parts[0], parts[1]) if len(parts) == 2 and _cam_pair(parts[0], parts[1]) == item else ""
                if key and key not in library["favs"] and len(library["favs"]) < 60000:
                    library["favs"].append(key)
        _cam_library_save(True)
        return {"ok": True, "favs": list(library["favs"])}
    if op == "fav":
        key = _cam_pair(body.get("site"), body.get("name"))
        if not key:
            return {"ok": False, "error": "Unbekanntes Model."}
        with _cam_lib_lock:
            if body.get("on"):
                if key not in library["favs"] and len(library["favs"]) < 60000:
                    library["favs"].append(key)
            elif key in library["favs"]:
                library["favs"].remove(key)
        _cam_library_save(True)
        return {"ok": True, "favs": list(library["favs"])}
    if op == "group-add":
        name = re.sub(r"\s+", " ", str(body.get("name") or "")).strip()[:40]
        if len(name) < 2:
            return {"ok": False, "error": "Der Gruppenname ist zu kurz."}
        with _cam_lib_lock:
            if len(library["groups"]) >= 40:
                return {"ok": False, "error": "Es sind schon 40 Cam-Gruppen da."}
            group_id = hashlib.sha256(os.urandom(16)).hexdigest()[:12]
            library["groups"].append({"id": group_id, "name": name, "items": []})
        _cam_library_save(True)
        return {"ok": True, "id": group_id}
    if op == "group-rename":
        name = re.sub(r"\s+", " ", str(body.get("name") or "")).strip()[:40]
        with _cam_lib_lock:
            for group in library["groups"]:
                if isinstance(group, dict) and group.get("id") == body.get("id") and len(name) >= 2:
                    group["name"] = name
        _cam_library_save(True)
        return {"ok": True}
    if op == "group-order":
        order = body.get("items")
        if not isinstance(order, list) or len(order) > 40 or any(not isinstance(value, str) for value in order):
            return {"ok": False, "error": "Ungültige Gruppenreihenfolge."}
        with _cam_lib_lock:
            positions = {value: index for index, value in enumerate(order)}
            library["groups"].sort(key=lambda group: positions.get(group.get("id"), len(order)))
        _cam_library_save(True)
        return {"ok": True}
    if op == "group-delete":
        with _cam_lib_lock:
            library["groups"] = [group for group in library["groups"] if not (isinstance(group, dict) and group.get("id") == body.get("id"))]
        _cam_library_save(True)
        return {"ok": True}
    if op == "group-item":
        key = _cam_pair(body.get("site"), body.get("name"))
        if not key:
            return {"ok": False, "error": "Unbekanntes Model."}
        with _cam_lib_lock:
            for group in library["groups"]:
                if not isinstance(group, dict) or group.get("id") != body.get("id"):
                    continue
                items = group.setdefault("items", [])
                if body.get("on"):
                    if key not in items and len(items) < 60000:
                        items.append(key)
                elif key in items:
                    items.remove(key)
        _cam_library_save(True)
        return {"ok": True}
    return {"ok": False, "error": "Diese Cam-Aktion fehlt."}


def _cam_single_profile(query):
    key = _cam_pair((query or {}).get("site"), (query or {}).get("name"))
    if not key:
        return {"ok": False, "error": "Unbekanntes Model."}
    site, name = key.split(":", 1)
    host = live_cam_providers.HOSTS[site]
    source = live_cam_providers.public_url(site, name)
    if site == "cam4":
        status, body = _cam_open("https://www.cam4.com/rest/v1.0/profile/" + urllib.parse.quote(name, safe="") + "/info", {"User-Agent":_CAM_UA,"Accept":"application/json"}, 10, 1_000_000)
        if status == 200:
            try:
                from live_cam_profile import cam4_profile
                info = json.loads(body)
                if not _cam_age_ok(info.get("age")):
                    return {"ok":False,"error":"Dieses öffentliche Profil ist nicht verfügbar."}
                return {"ok":True,"profile":cam4_profile(info,name,int(time.time()*1000))}
            except (ValueError,TypeError,AttributeError):
                pass
    status, body = _cam_open(source, {"User-Agent": _CAM_UA, "Accept": "text/html", "Referer": "https://" + host + "/"}, 15, 2 * 1024 * 1024 + 1, None if query.get("public_only") else _cam_jar(site)[0])
    if status != 200:
        return {"ok": False, "error": "Das öffentliche Profil ist derzeit nicht zugänglich (HTTP %s). Der gespeicherte Stand bleibt erhalten." % status}
    document = body.decode("utf-8", "replace")
    if _cam_blocked(document):
        return {"ok": False, "error": "Die offizielle Profilseite verlangt eine manuelle Freigabe oder Anmeldung. Bitte im offiziellen Raum öffnen; der gespeicherte Stand bleibt erhalten."}
    try:
        from live_cam_profile import parse_profile
        return {"ok": True, "profile": parse_profile(document, source, key, int(time.time() * 1000))}
    except ValueError as error:
        return {"ok": False, "error": str(error)}


def _cam_blocked(text):
    sample = (text or "").lower()
    title = ""
    match = re.search(r"<title>\s*([^<]{0,90})", sample)
    if match:
        title = re.sub(r"\s+", " ", match.group(1)).strip()
    if title.startswith("just a moment") or title.startswith("attention required"):
        return True
    if "cf-browser-verification" in sample or 'id="challenge-form"' in sample:
        return True
    # A normal login page loads captcha scripts next to the password field.
    if 'type="password"' in sample or "type='password'" in sample or 'name="password"' in sample:
        return False
    return "cf-challenge" in sample


def _cam_exchange(url, headers, data, timeout, limit, jar):
    request = urllib.request.Request(url, data=data, headers=headers)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    try:
        response = opener.open(request, timeout=_cam_timeout(timeout))
    except urllib.error.HTTPError as exc:
        try:
            body = _cam_read(exc, min(limit, 8000), timeout)
        except Exception:
            body = b""
        finally:
            exc.close()
        return exc.code, body
    except Exception:
        return 0, b""
    try:
        return getattr(response, "status", 200) or 200, _cam_read(response, limit, timeout)
    except (OSError, TimeoutError):
        return 0, b""
    finally:
        response.close()


_cam_session_lock = threading.RLock()


def _cam_sessions():
    return _cam_json_read(CAM_SESSION)


def _cam_session_store(site, user, jar):
    from live_cam_performance import resolver_cache
    resolver_cache.invalidate(site)
    with _cam_session_lock:
        cookies = []
        for cookie in jar:
            value = str(cookie.value or "")
            if not cookie.name or not value or len(value) > 8000 or len(cookies) >= 16:
                continue
            cookies.append({"name": str(cookie.name)[:80], "value": value, "domain": str(cookie.domain or "")[:120], "path": str(cookie.path or "/")[:80]})
        data = _cam_sessions()
        data[site] = {"user": str(user or "")[:80], "cookies": cookies, "at": int(time.time())}
        _cam_json_write(CAM_SESSION, data)
        resolver_cache.invalidate(site)


def _cam_session_drop(site):
    with _cam_session_lock:
        data = _cam_sessions()
        if site in data:
            data.pop(site, None)
            if data:
                _cam_json_write(CAM_SESSION, data)
            elif os.path.isfile(CAM_SESSION):
                os.remove(CAM_SESSION)


def _cam_jar(site):
    jar = http.cookiejar.CookieJar()
    row = _cam_sessions().get(site)
    user = ""
    if not isinstance(row, dict):
        return jar, user
    user = str(row.get("user") or "")[:80]
    for item in row.get("cookies") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        value = str(item.get("value") or "")
        domain = str(item.get("domain") or "")
        path = str(item.get("path") or "/") or "/"
        if not name or not value or len(value) > 8000:
            continue
        try:
            jar.set_cookie(http.cookiejar.Cookie(
                0, name[:80], value, None, False, domain[:120], bool(domain), domain.startswith("."),
                path[:80], True, False, None, True, None, None, {},
            ))
        except Exception:
            continue
    return jar, user


_cam_user_service = None
_cam_user_service_lock = threading.Lock()
def _cam_user_request_allowed(headers):
    try:
        host=urllib.parse.urlsplit('http://'+str(headers.get('Host') or ''))
        if host.hostname not in ('127.0.0.1','localhost','::1'):return False
        origin=headers.get('Origin')
        if origin:
            parsed=urllib.parse.urlsplit(origin)
            if parsed.scheme!='http' or parsed.netloc!=host.netloc:return False
        return headers.get('Sec-Fetch-Site') not in ('cross-site',)
    except ValueError:return False


def _cam_user_hub():
    global _cam_user_service
    with _cam_user_service_lock:
        if _cam_user_service is None:
            from live_cam_account import AccountHub
            _cam_user_service = AccountHub(globals())
    return _cam_user_service


def _cam_session_fingerprint(jar, user):
    import hashlib
    cookies=sorted((c.domain,c.name,c.value,c.path) for c in jar)
    return hashlib.sha256(json.dumps([user,cookies],sort_keys=True).encode()).hexdigest()


def _cam_session_commit(site, expected, user, jar):
    with _cam_session_lock:
        current, current_user=_cam_jar(site)
        if _cam_session_fingerprint(current,current_user)!=expected:
            raise ValueError('Die Website-Sitzung wurde inzwischen geändert. Der alte Abruf wurde verworfen; die neue Anmeldung bleibt erhalten.')
        _cam_session_store(site,user,jar)


def _cam_account_public():
    data = _cam_sessions()
    public = {}
    for site in _CAM_SITES:
        row = data.get(site) if isinstance(data.get(site), dict) else {}
        public[site] = {"on": bool(row.get("cookies")) if site in _CAM_ACCOUNT_SITES else False, "user": str(row.get("user") or "")[:80], "accountSupported": site in _CAM_ACCOUNT_SITES, "followingSupported": site in live_cam_providers.FOLLOWING_SITES}
    return public


def _cam_login_fields(body):
    site = _cam_site(body.get("site"))
    user = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    if not site or not re.fullmatch(r"[A-Za-z0-9._@+\-]{2,80}", user) or not password or len(password) > 200 or "\x00" in password:
        return "", "", ""
    return site, user, password


def _cam_put_cookie(jar, name, value, domain):
    jar.set_cookie(http.cookiejar.Cookie(
        0, name, value, None, False,
        domain, True, str(domain).startswith("."),
        "/", True, False, None, True, None, None, {},
    ))


def _cam_message(data):
    if not isinstance(data, dict):
        return ""
    parts = []
    for key in ("error", "message", "status"):
        value = data.get(key)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict):
            for sub in ("message", "code", "error"):
                if isinstance(value.get(sub), str):
                    parts.append(value[sub])
    nested = data.get("data")
    if isinstance(nested, dict) and nested is not data:
        for key in ("error", "message", "status"):
            value = nested.get(key)
            if isinstance(value, str):
                parts.append(value)
    text = re.sub(r"\s+", " ", " ".join(parts)).strip()
    return text[:180]


def _cam_paste_parts(raw):
    text = str(raw or "").strip()
    if not text or len(text) > 4000 or "\x00" in text:
        return []
    parts = []
    for chunk in re.split(r"[\r\n;]+", text):
        chunk = chunk.strip()
        if not chunk or len(parts) >= 8:
            continue
        if "=" in chunk:
            name, value = chunk.split("=", 1)
            name = name.strip()
            if not name or name.lower() == "cookie" or len(name) > 80:
                continue
            parts.append((name, value.strip().strip('"').strip("'")))
        else:
            parts.append(("", chunk.strip().strip('"').strip("'")))
    return parts


def _cam_pick_paste(raw, cookie_name, pattern):
    for name, value in _cam_paste_parts(raw):
        if name.lower() == cookie_name.lower() and re.fullmatch(pattern, value):
            return value
    # A bare base64 cookie can end in '='; that is padding, not a cookie name.
    text = str(raw or "").strip().strip('"').strip("'")
    if len(text) <= 4000 and re.fullmatch(pattern, text):
        return text
    return ""


def _cam_dicts(data, limit=100):
    found = []

    def walk(node, depth):
        if len(found) >= limit or depth > 6:
            return
        if isinstance(node, list):
            rows = [item for item in node if isinstance(item, dict) and (item.get("username") or item.get("display_name"))]
            if rows:
                found.extend(rows[: limit - len(found)])
                return
            for item in node[:30]:
                walk(item, depth + 1)
            return
        if isinstance(node, dict):
            for key in ("models", "rooms", "favorites", "items", "results", "blocks", "user"):
                if key in node:
                    walk(node[key], depth + 1)

    walk(data, 0)
    return found


def _sc_config(jar):
    headers = {"User-Agent": _CAM_UA, "Accept": "application/json", "Referer": "https://stripchat.com/"}
    status, body = _cam_exchange(
        "https://stripchat.com/api/front/v3/config/initial?requestPath=%2F&timezoneOffset=0",
        headers, None, 10, 400_000, jar,
    )
    text = body.decode("utf-8", "replace")
    if status != 200 or _cam_blocked(text):
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    initial = data.get("initial") if isinstance(data, dict) else None
    client = initial.get("client") if isinstance(initial, dict) else None
    return client if isinstance(client, dict) else None


def _sc_user_name(user):
    if not isinstance(user, dict) or user.get("isGuest") is True:
        return ""
    name = str(user.get("username") or user.get("login") or "")
    if not _CAM_NAME.fullmatch(name) or _CAM_CHILD.search(name):
        return ""
    return name


def _sc_who(jar):
    client = _sc_config(jar)
    if not isinstance(client, dict) or "user" not in client:
        return None
    return _sc_user_name(client.get("user"))


_SC_PASTE = r"[A-Za-z0-9._~+/-]{8,2000}"
_SC_COOKIE = "stripchat_com_sessionId"


def _cam_following_pages(jar, url, limit, headers, params):
    rows, seen = [], set()
    for page in range(50):
        query = dict(params, limit=str(limit), offset=str(page*limit))
        status, body = _cam_exchange(url+'?'+urllib.parse.urlencode(query), headers, None, 12, 800_000, jar)
        if status in (401,403):
            return rows, 'Die Website-Sitzung ist abgelaufen. Bitte neu anmelden.'
        if status != 200:
            return rows, 'Die Following-Liste konnte nicht vollständig gelesen werden.'
        try: data = json.loads(body.decode('utf-8','replace'))
        except ValueError: return rows, 'Die Following-Liste war nicht lesbar.'
        chunk = _cam_dicts(data, limit=limit+1)
        signature = tuple(str(r.get('username') or r.get('display_name') or '') for r in chunk)
        if chunk and signature in seen:
            return rows, 'Der Anbieter wiederholt dieselbe Following-Seite; der Bestand ist unvollständig.'
        seen.add(signature)
        if isinstance(data,dict) and data.get('error'):
            return rows, 'Der Anbieter hat die Kontoliste nicht bestätigt.'
        if not isinstance(data,(dict,list)):
            return rows, 'Der Anbieter hat keine bestätigte Kontoliste geliefert.'
        if not chunk and isinstance(data,dict) and not any(isinstance(data.get(key),list) for key in ('models','rooms','favorites','items','results','blocks')) and data.get('total_count')!=0:
            return rows, 'Der Anbieter hat eine leere Antwort ohne bestätigte Following-Liste geliefert.'
        rows.extend(chunk)
        total = data.get('total_count') if isinstance(data,dict) else None
        if len(chunk)<limit or isinstance(total,int) and (page+1)*limit>=total:
            return rows, ''
    return rows, 'Der Abruf hat die Seitengrenze erreicht; die Following-Liste ist unvollständig.'


def _sc_account_rooms(jar):
    who = _sc_who(jar)
    if who is None:return [], 'Stripchat gibt die Kontoliste gerade nicht her.'
    if not who:return [], 'Die Stripchat-Sitzung ist abgelaufen. Bitte neu anmelden.'
    headers={'User-Agent':_CAM_UA,'Accept':'application/json','Referer':'https://stripchat.com/favorites','Origin':'https://stripchat.com','X-Requested-With':'XMLHttpRequest'}
    rooms,seen,warnings=[],set(),[]
    for url,offline in [('https://stripchat.com/api/front/models/favorites',False),('https://stripchat.com/api/front/models/favorites/offline',True)]:
        rows,warning=_cam_following_pages(jar,url,60,headers,{'sortBy':'lastAdded'})
        if warning:warnings.append(warning)
        for model in rows:
            room=_sc_room(model,allow_offline=True)
            if not room or room['name'].lower() in seen:continue
            if offline:room.update(online=False,show='offline',stream='')
            seen.add(room['name'].lower());rooms.append(room)
    return rooms, ' '.join(dict.fromkeys(warnings))


def _sc_login(username, password, code=""):
    jar = http.cookiejar.CookieJar()
    client = _sc_config(jar)
    token = str(client.get("csrfToken") or "") if isinstance(client, dict) else ""
    if not re.fullmatch(r"[A-Za-z0-9._~+/-]{8,200}", token):
        return "", "Stripchat verlangt einen Browser-Check. Melde dich im normalen Browser an und übernimm unten den Cookie stripchat_com_sessionId."
    payload = {
        "loginOrEmail": username,
        "password": password,
        "remember": True,
        "csrfToken": token,
        "csrfTimestamp": str(client.get("csrfTimestamp") or ""),
        "csrfNotifyTimestamp": str(client.get("csrfNotifyTimestamp") or ""),
    }
    digits = str(code or "").strip()
    if re.fullmatch(r"\d{6}", digits):
        payload["tfaCode"] = digits
    headers = {
        "User-Agent": _CAM_UA,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://stripchat.com",
        "Referer": "https://stripchat.com/",
        "X-Requested-With": "XMLHttpRequest",
    }
    status, body = _cam_exchange(
        "https://stripchat.com/api/front/auth/login",
        headers, json.dumps(payload).encode("utf-8"), 10, 200_000, jar,
    )
    text = body.decode("utf-8", "replace")
    if _cam_blocked(text):
        return "", "Stripchat verlangt einen Browser-Check. Melde dich im normalen Browser an und übernimm unten den Cookie stripchat_com_sessionId."
    try:
        data = json.loads(text)
    except ValueError:
        data = {}
    message = _cam_message(data).lower()
    if "captcha" in message:
        return "", "Stripchat verlangt einen Browser-Check und hat den direkten Login nicht bestätigt. Melde dich auf der offiziellen Website an und übernimm unten den Sitzungscookie stripchat_com_sessionId. In das Cookie-Feld gehört kein Passwort."
    if "two-factor" in message or "zwei-faktor" in message or "2fa" in message:
        return "", "Stripchat will den Code aus der Authenticator-App. Trag die sechs Ziffern ins Feld Code ein, oder übernimm unten die Sitzung aus dem Browser."
    user = _sc_user_name(data.get("user") if isinstance(data, dict) else None)
    if not user and isinstance(data, dict) and isinstance(data.get("data"), dict):
        user = _sc_user_name(data["data"].get("user"))
    if status == 200 and user:
        confirmed = _sc_who(jar)
        if not confirmed or confirmed.lower() != user.lower() or not any(cookie.name == _SC_COOKIE and cookie.value for cookie in jar):
            return "", "Stripchat hat noch keine gültige Kontositzung bestätigt. Die bisherige Verbindung bleibt erhalten. Bitte die Browser-Sitzung übernehmen."
        _cam_session_store("stripchat", confirmed, jar)
        return confirmed, ""
    if any(word in message for word in ("invalid", "incorrect", "wrong password", "not found")):
        return "", "Stripchat hat das Passwort nicht angenommen."
    return "", "Stripchat hat die Anmeldung nicht angenommen. Wenn die Seite eine Prüfung zeigt, übernimm unten den Cookie stripchat_com_sessionId."


def _sc_session_take(raw):
    value = _cam_pick_paste(raw, _SC_COOKIE, _SC_PASTE)
    if not value:
        return "", "Die Sitzung ist nicht lesbar. Kopiere nur den Wert von stripchat_com_sessionId."
    jar = http.cookiejar.CookieJar()
    _cam_put_cookie(jar, _SC_COOKIE, value, ".stripchat.com")
    name = _sc_who(jar)
    if name is None:
        return "", "Stripchat gibt die Sitzung gerade nicht her. Versuch es gleich noch einmal."
    if not name:
        return "", "Stripchat hat diese Sitzung nicht angenommen. Melde dich im normalen Browser an und kopiere stripchat_com_sessionId neu."
    _cam_session_store("stripchat", name, jar)
    return name, ""


def _cb_login(username, password):
    jar = http.cookiejar.CookieJar()
    page = "https://chaturbate.com/auth/login/"
    headers = {"User-Agent": _CAM_UA, "Accept": "text/html", "Referer": "https://chaturbate.com/"}
    status, body = _cam_exchange(page, headers, None, 12, 400_000, jar)
    text = body.decode("utf-8", "replace")
    if status != 200 or _cam_blocked(text):
        return "", "Chaturbate verlangt einen Browser-Check. Die Anmeldung von hier klappt dann nicht."
    match = re.search(r'name="csrfmiddlewaretoken"\s+value="([^"]+)"', text)
    token = match.group(1) if match else ""
    if not token:
        for cookie in jar:
            if cookie.name == "csrftoken":
                token = cookie.value
    if not token:
        return "", "Chaturbate hat die Anmeldung nicht angenommen."
    form = urllib.parse.urlencode({
        "username": username,
        "password": password,
        "csrfmiddlewaretoken": token,
        "next": "/",
    }).encode("utf-8")
    headers = {
        "User-Agent": _CAM_UA,
        "Accept": "text/html",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://chaturbate.com",
        "Referer": page,
    }
    status, body = _cam_exchange(page, headers, form, 12, 200_000, jar)
    if _cam_blocked(body.decode("utf-8", "replace")):
        return "", "Chaturbate verlangt einen Browser-Check. Die Anmeldung von hier klappt dann nicht."
    if not any(cookie.name == "sessionid" for cookie in jar):
        return "", "Chaturbate hat das Passwort von hier nicht angenommen. Die Seite will eine Browser-Prüfung. Melde dich im normalen Browser an und übernimm unten nur die sessionid."
    _cam_session_store("chaturbate", username, jar)
    return username, ""


def _cb_session_value(raw):
    text = str(raw or "").strip()
    if not text or len(text) > 400:
        return ""
    match = re.search(r"(?:^|[;\s])sessionid=([A-Za-z0-9]{20,80})\b", text, re.I)
    if match:
        return match.group(1)
    text = text.strip().strip('"').strip("'")
    if re.fullmatch(r"[A-Za-z0-9]{20,80}", text):
        return text
    return ""


def _cb_set_session(jar, value):
    jar.set_cookie(http.cookiejar.Cookie(
        0, "sessionid", value, None, False,
        ".chaturbate.com", True, True,
        "/", True, False, None, True, None, None, {},
    ))


def _cb_logged_name(text):
    for match in re.finditer(r"logged_in_user\s*[:=]\s*JSON\.parse\(\s*'((?:\\'|[^']){0,20000})'", text or ""):
        raw = match.group(1)
        if raw in ("", "null", "false"):
            continue
        decoded = raw.replace("\\'", "'").replace('\\"', '"').replace("\\/", "/")
        try:
            data = json.loads(decoded)
        except ValueError:
            try:
                data = json.loads(bytes(raw, "utf-8").decode("unicode_escape"))
            except (ValueError, UnicodeError):
                data = None
        if not isinstance(data, dict):
            continue
        name = str(data.get("username") or "")
        if re.fullmatch(r"[A-Za-z0-9_]{2,40}", name) and not _CAM_CHILD.search(name):
            return name
    return ""


def _cb_who(jar):
    headers = {"User-Agent": _CAM_UA, "Accept": "text/html", "Referer": "https://chaturbate.com/"}
    status, body = _cam_exchange("https://chaturbate.com/", headers, None, 10, 500_000, jar)
    if status != 200:
        return ""
    return _cb_logged_name(body.decode("utf-8", "replace"))


def _cb_session_take(raw):
    value = _cb_session_value(raw)
    if not value:
        return "", "Die Sitzung ist nicht lesbar. Kopiere nur den Wert von sessionid."
    jar = http.cookiejar.CookieJar()
    _cb_set_session(jar, value)
    name = _cb_who(jar)
    if not name:
        return "", "Chaturbate hat diese Sitzung nicht angenommen. Melde dich im normalen Browser an und kopiere sessionid neu."
    _cam_session_store("chaturbate", name, jar)
    return name, ""


def _cb_account_rooms(jar):
    if not _cb_who(jar):return [], 'Die Chaturbate-Sitzung ist abgelaufen. Bitte neu anmelden.'
    headers={'User-Agent':_CAM_UA,'Accept':'application/json','Referer':'https://chaturbate.com/followed-cams/','X-Requested-With':'XMLHttpRequest'}
    rooms,seen,warnings=[],set(),[]
    for offline in (False,True):
        query={'follow':'true'}
        if offline:query['offline']='true'
        rows,warning=_cam_following_pages(jar,'https://chaturbate.com/api/ts/roomlist/room-list/',90,headers,query)
        if warning:warnings.append(warning)
        if rows and any('is_following' in row for row in rows):
            followed=[r for r in rows if r.get('is_following') is True]
            if not followed:
                warnings.append('Die Quelle hat keine gefolgten Models bestätigt; öffentliche Treffer werden nicht als Following übernommen.')
            rows=followed
        for row in rows:
            room=_cb_room(row,allow_offline=True)
            if not room or room['name'].lower() in seen:continue
            if offline:room.update(online=False,show='offline')
            seen.add(room['name'].lower());rooms.append(room)
    return rooms,' '.join(dict.fromkeys(warnings))


_BC_COOKIE = "bonga20120608"
_BC_PASTE = r"[A-Za-z0-9._~+/-]{8,2000}"
_BC_PASTE_HINT = "BongaCams lässt die Anmeldung von hier nicht zu. Die Seite verlangt eine Browser-Prüfung. Melde dich im normalen Browser an und übernimm unten nur den Cookie bonga20120608."


def _bc_page(jar):
    headers = {"User-Agent": _CAM_UA, "Accept": "text/html", "Referer": "https://bongacams.com/"}
    status, body = _cam_exchange("https://bongacams.com/", headers, None, 10, 120_000, jar)
    text = body.decode("utf-8", "replace")
    if status != 200 or _cam_blocked(text):
        return ""
    return text


def _bc_csrf(text):
    field = re.search(r'data-csrf_field="([A-Za-z0-9_-]{1,40})"', text or "")
    value = re.search(r'data-csrf_value="([^"]{8,200})"', text or "")
    return (field.group(1) if field else ""), (value.group(1) if value else "")


def _bc_named_user(text):
    # A guest page has no account username. Only an account object counts.
    for key in ("currentUser", "authUser", "member", "account", "userData"):
        match = re.search(
            r'"%s"\s*:\s*\{[^{}]{0,500}"username"\s*:\s*"([A-Za-z0-9_-]{2,40})"' % key,
            text or "",
        )
        if not match:
            continue
        name = match.group(1)
        if _CAM_NAME.fullmatch(name) and not _CAM_CHILD.search(name) and not name.lower().startswith("guest"):
            return name
    return ""


def _bc_sip_name(jar):
    for cookie in jar:
        if cookie.name != "sip":
            continue
        raw = urllib.parse.unquote(str(cookie.value or ""))
        name = ""
        if raw[:1] in ("{", "["):
            try:
                data = json.loads(raw)
            except ValueError:
                data = None
            if isinstance(data, dict):
                name = str(data.get("username") or data.get("login") or "")
        elif re.fullmatch(r"[A-Za-z0-9_-]{2,40}", raw):
            name = raw
        if _CAM_NAME.fullmatch(name) and not _CAM_CHILD.search(name) and not name.lower().startswith("guest"):
            return name
    return ""


def _bc_who(jar):
    text = _bc_page(jar)
    if not text:
        return None
    return _bc_named_user(text) or _bc_sip_name(jar)


def _bc_marked(model):
    if not isinstance(model, dict):
        return False
    for key in ("favorite", "is_favorite", "isFavorite", "fav", "followed", "is_followed"):
        if model.get(key) in (True, 1, "1"):
            return True
    return False


def _bc_names(models):
    names = []
    for model in models or []:
        if not isinstance(model, dict):
            continue
        name = str(model.get("username") or "").lower()
        if name:
            names.append(name)
    return names


def _bc_is_public_dump(fav_models, public_models):
    # favorite=1 without a session is the public catalog, not the account.
    if any(_bc_marked(model) for model in fav_models or [] if isinstance(model, dict)):
        return False
    fav = _bc_names(fav_models)
    public = _bc_names(public_models)
    if not fav or not public:
        return True
    return fav == public[:len(fav)]


def _bc_login(username, password):
    jar = http.cookiejar.CookieJar()
    page = _bc_page(jar)
    if not page:
        return "", "BongaCams verlangt einen Browser-Check. Die Anmeldung von hier klappt dann nicht."
    _field, token = _bc_csrf(page)
    form = urllib.parse.urlencode({
        "log_in[username]": username,
        "log_in[password]": password,
        "remember": "1",
        "headerForm": "1",
    }).encode("utf-8")
    headers = {
        "User-Agent": _CAM_UA,
        "Accept": "application/json, text/html",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://bongacams.com",
        "Referer": "https://bongacams.com/",
        "X-Requested-With": "XMLHttpRequest",
    }
    if token:
        headers["X-CSRF-TOKEN"] = token
    status, body = _cam_exchange("https://bongacams.com/login", headers, form, 10, 200_000, jar)
    text = body.decode("utf-8", "replace")
    if _cam_blocked(text):
        return "", _BC_PASTE_HINT
    try:
        data = json.loads(text)
    except ValueError:
        data = {}
    message = _cam_message(data).lower()
    if "captcha" in message or "method not allowed" in message:
        return "", _BC_PASTE_HINT
    if any(word in message for word in ("invalid", "incorrect", "wrong password")):
        return "", "BongaCams hat das Passwort nicht angenommen."
    ok = status == 200 and isinstance(data, dict) and str(data.get("status") or "").lower() in ("success", "ok")
    name = _bc_who(jar) if ok else ""
    if not name:
        return "", _BC_PASTE_HINT if not ok else "BongaCams hat das Konto nicht bestätigt. Übernimm unten den Cookie bonga20120608."
    _cam_session_store("bongacams", name, jar)
    return name, ""


def _bc_session_take(raw):
    value = _cam_pick_paste(raw, _BC_COOKIE, _BC_PASTE)
    if not value:
        return "", "Die Sitzung ist nicht lesbar. Kopiere nur den Wert von bonga20120608."
    jar = http.cookiejar.CookieJar()
    _cam_put_cookie(jar, _BC_COOKIE, value, ".bongacams.com")
    name = _bc_who(jar)
    if name is None:
        return "", "BongaCams gibt die Sitzung gerade nicht her. Versuch es gleich noch einmal."
    if not name:
        return "", "BongaCams hat diese Sitzung nicht angenommen. Melde dich im normalen Browser an und kopiere bonga20120608 neu."
    _cam_session_store("bongacams", name, jar)
    return name, ""


def _bc_account_rooms(jar):
    who = _bc_who(jar)
    if who is None:
        return [], "BongaCams gibt die Kontoliste gerade nicht her."
    if not who:
        return [], "Die BongaCams-Sitzung ist abgelaufen. Bitte neu anmelden."
    headers = {
        "User-Agent": _CAM_UA,
        "Accept": "application/json",
        "Referer": "https://bongacams.com/",
        "Origin": "https://bongacams.com",
        "X-Requested-With": "XMLHttpRequest",
    }
    status, body = _cam_exchange(
        "https://bongacams.com/tools/listing_v3.php?online_only=1&limit=60&offset=0&favorite=1",
        headers, None, 8, 800_000, jar,
    )
    if status in (401, 403):
        return [], "Die BongaCams-Sitzung ist abgelaufen. Bitte neu anmelden."
    if status != 200:
        return [], "BongaCams gibt die Kontoliste gerade nicht her."
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return [], "BongaCams gibt die Kontoliste gerade nicht her."
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        return [], "BongaCams gibt die Kontoliste gerade nicht her."
    if not models:
        return [], ""
    public, _err = _bc_fetch("", 60, 0)
    if _bc_is_public_dump(models, public):
        return [], "BongaCams gibt die Kontoliste gerade nicht her."
    rooms = []
    seen = set()
    for model in models:
        room = _bc_room(model, allow_offline=True)
        if not room or room["name"].lower() in seen:
            continue
        if not _bc_marked(model) and str(model.get("room") or "").lower() != "public":
            room["online"] = False
            room["show"] = "offline"
            room["stream"] = ""
        seen.add(room["name"].lower())
        rooms.append(room)
    return rooms, ""


_CS_COOKIE = "www_cs_session"
_CS_PASTE = r"(?:[A-Za-z0-9._~+/-]|%[A-Fa-f0-9]{2}){8,2000}={0,2}"
_CS_PASTE_HINT = "CamSoda verlangt eine Browser-Prüfung und hat die lokale Anmeldung nicht bestätigt. Das ist keine Bestätigung eines falschen Passworts. Bitte auf der offiziellen Website anmelden und die Browser-Sitzung übernehmen; in das Cookie-Feld gehört kein Passwort."


def _cs_api_error(status, text):
    if _cam_blocked(text):
        return _CS_PASTE_HINT
    if status == 0:
        return "CamSoda ist beim Anmeldeversuch nicht erreichbar gewesen. Bitte später erneut versuchen. Eine bestehende Verbindung bleibt erhalten."
    if status != 200:
        return "CamSoda hat den lokalen Zugriff mit HTTP %s abgewiesen. Die Anmeldung wurde nicht bestätigt; eine bestehende Verbindung bleibt erhalten." % status
    return ""


def _cs_config(jar):
    # The website's public site_config bootstrap sets site.csrf. Its API client
    # sends that value as X-CSRF-TOKEN, with the same cookie jar (checked 2026-10-18).
    headers = {"User-Agent": _CAM_UA, "Accept": "application/json", "Referer": "https://www.camsoda.com/"}
    status, body = _cam_exchange("https://www.camsoda.com/api/v1/site_config", headers, None, 10, 400_000, jar)
    text = body.decode("utf-8", "replace")
    error = _cs_api_error(status, text)
    if error:
        return "", error
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    token = data.get("csrf") if isinstance(data, dict) else None
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9._~+/=\-]{8,1024}", token):
        return "", "CamSoda hat die Anmeldevorbereitung nicht im erwarteten Format geliefert. Es wurde kein Passwort gesendet. Bitte die offizielle Browser-Anmeldung verwenden."
    return token, ""
_CS_FOLLOW_KEYS = ("favorites", "favorite", "following", "follows", "friends", "bookmarks")


def _cs_current(jar):
    headers = {
        "User-Agent": _CAM_UA,
        "Accept": "application/json",
        "Referer": "https://www.camsoda.com/",
        "Origin": "https://www.camsoda.com",
    }
    status, body = _cam_exchange("https://www.camsoda.com/api/v1/user/current", headers, None, 10, 400_000, jar)
    text = body.decode("utf-8", "replace")
    if _cam_blocked(text):
        return None, "block"
    if status != 200:
        return None, "down"
    try:
        data = json.loads(text)
    except ValueError:
        return None, "down"
    if not isinstance(data, dict):
        return None, "down"
    return data, ""


def _cs_who_from(data):
    # Current /user/current responses are consumed by the website through user;
    # they need not carry the older top-level status=true marker.
    if not isinstance(data, dict) or data.get("status", True) is not True or data.get("error"):
        return ""
    user = data.get("user")
    if not isinstance(user, dict):
        return ""
    name = str(user.get("username") or "")
    if name.lower().startswith("guest") or not _CAM_NAME.fullmatch(name) or _CAM_CHILD.search(name):
        return ""
    return name


def _cs_who(jar):
    data, flag = _cs_current(jar)
    if flag:
        return None
    return _cs_who_from(data)


def _cs_login(username, password):
    jar = http.cookiejar.CookieJar()
    csrf, error = _cs_config(jar)
    if error:
        return "", error
    form = urllib.parse.urlencode({"username": username, "password": password}).encode("utf-8")
    headers = {
        "User-Agent": _CAM_UA,
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://www.camsoda.com",
        "Referer": "https://www.camsoda.com/",
        "X-CSRF-TOKEN": csrf,
    }
    status, body = _cam_exchange("https://www.camsoda.com/api/v1/auth/login", headers, form, 10, 200_000, jar)
    text = body.decode("utf-8", "replace")
    error = _cs_api_error(status, text)
    if _cam_blocked(text):
        return "", error
    try:
        data = json.loads(text)
    except ValueError:
        data = {}
    message = _cam_message(data).lower()
    if "captcha" in message:
        return "", _CS_PASTE_HINT
    if "csrf" in message:
        return "", "CamSoda hat die Sitzungsprüfung abgelehnt. Bitte die Anmeldung auf der offiziellen Website abschließen; das Passwort wurde dadurch nicht als falsch bestätigt."
    if any(word in message for word in ("invalid credentials", "invalid_credentials", "invalid password", "invalid_password", "incorrect password", "wrong password")):
        return "", "CamSoda hat das Passwort nicht angenommen."
    if error:
        return "", error
    if status != 200 or not isinstance(data, dict) or data.get("error"):
        return "", "CamSoda hat die Anmeldung nicht bestätigt. Die Antwort der Anmeldeschnittstelle war nicht im erwarteten Format; bitte auf der offiziellen Website anmelden."
    name = _cs_who(jar)
    if name is None:
        return "", "CamSoda hat die Kontoprüfung nach der Anmeldung nicht freigegeben. Bitte die offizielle Browser-Anmeldung verwenden. Eine bestehende Verbindung bleibt erhalten."
    if not name or not any(cookie.name == _CS_COOKIE and cookie.value for cookie in jar):
        return "", "CamSoda hat keine gültige Kontositzung bestätigt. Bitte die offizielle Browser-Anmeldung verwenden. Eine bestehende Verbindung bleibt erhalten."
    _cam_session_store("camsoda", name, jar)
    return name, ""


def _cs_session_take(raw):
    value = _cam_pick_paste(raw, _CS_COOKIE, _CS_PASTE)
    if not value:
        return "", "Die Sitzung ist nicht lesbar. Kopiere nur den Wert von www_cs_session."
    jar = http.cookiejar.CookieJar()
    _cam_put_cookie(jar, _CS_COOKIE, value, ".camsoda.com")
    data, flag = _cs_current(jar)
    if flag == "block":
        return "", "CamSoda verlangt weiter einen Browser-Check. Die Sitzung wurde nicht gespeichert."
    if flag:
        return "", "CamSoda gibt die Sitzung gerade nicht her. Versuch es gleich noch einmal."
    name = _cs_who_from(data)
    if not name:
        return "", "CamSoda hat diese Sitzung nicht angenommen. Melde dich im normalen Browser an und kopiere www_cs_session neu."
    _cam_session_store("camsoda", name, jar)
    return name, ""


def _cs_follow_nodes(node, found, armed):
    if len(found) >= 120:
        return
    if isinstance(node, str):
        if armed:
            found.append(node)
        return
    if isinstance(node, list):
        if armed:
            for item in node[:120]:
                _cs_follow_nodes(item, found, True)
        return
    if not isinstance(node, dict):
        return
    if armed and (node.get("username") or node.get("name") or node.get("display_name")):
        found.append(node)
        return
    for key, value in node.items():
        if str(key).lower() in _CS_FOLLOW_KEYS:
            _cs_follow_nodes(value, found, True)


def _cs_follow_room(node):
    online = False
    show = "offline"
    thumb = ""
    subject = ""
    if isinstance(node, str):
        name = node
    elif isinstance(node, dict):
        name = str(node.get("username") or node.get("name") or node.get("display_name") or "")
        if not _cam_age_ok(node.get("age") if node.get("age") not in (None, "") else node.get("display_age")):
            return None
        subject = _cam_subject(node.get("subject") or node.get("topic") or "")
        if subject is None:
            return None
        chat = str(node.get("chatstatus") or node.get("chat_status") or "").lower()
        flag = node.get("online")
        if flag is None:
            flag = node.get("is_online")
        if flag is None:
            flag = node.get("isOnline")
        private = chat in ("private", "group", "ticket", "away")
        live = flag is True or flag == 1 or chat in ("online", "public")
        if private:
            online, show = False, "privat"
        elif live:
            online, show = True, "public"
        image = str(node.get("thumb") or node.get("image") or node.get("avatar") or "")
        if image.startswith("//"):
            image = "https:" + image
        if image.startswith("https://") and not _is_video_url(image):
            thumb = _cam_image(image, "https://www.camsoda.com/")
    else:
        return None
    if not _CAM_NAME.fullmatch(name) or _CAM_CHILD.search(name) or name.lower().startswith("guest"):
        return None
    return {
        "site": "camsoda",
        "name": name,
        "gender": "",
        "viewers": 0,
        "hd": False,
        "subject": subject or "",
        "tags": [],
        "thumb": thumb,
        "stream": "",
        "online": online,
        "show": show,
    }


def _cs_account_rooms(jar):
    data, flag = _cs_current(jar)
    if flag == "block":
        return [], "CamSoda verlangt einen Browser-Check. Die Kontoliste lässt sich so nicht lesen."
    if flag:
        return [], "CamSoda gibt die Kontoliste gerade nicht her."
    if not _cs_who_from(data):
        return [], "Die CamSoda-Sitzung ist abgelaufen. Bitte neu anmelden."
    found = []
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    _cs_follow_nodes(user, found, False)
    rooms = []
    seen = set()
    for node in found:
        room = _cs_follow_room(node)
        if not room or room["name"].lower() in seen:
            continue
        seen.add(room["name"].lower())
        rooms.append(room)
    return rooms, ""


def _cam_account_favs(site):
    if site not in live_cam_providers.FOLLOWING_SITES:
        return {"ok": False, "error": "Die Kontoanmeldung ist verfügbar. Die offizielle Following-Liste dieses Anbieters lässt sich hier noch nicht zuverlässig abrufen. Bitte auf der offiziellen Website öffnen."}
    jar, user = _cam_jar(site)
    if not user:
        return {"ok": False, "error": "Für diese Seite ist niemand angemeldet."}
    loaders = {
        "stripchat": _sc_account_rooms,
        "chaturbate": _cb_account_rooms,
        "bongacams": _bc_account_rooms,
        "camsoda": _cs_account_rooms,
    }
    rooms, error = loaders[site](jar)
    if error and not rooms:
        if "abgelaufen" in error:
            _cam_session_drop(site)
        return {"ok": False, "error": error, "user": user}
    library = _cam_library_load()
    if not error:
        with _cam_lib_lock:
            library["account"][site] = [_cam_pair(room.get("site"), room.get("name")) for room in rooms if _cam_pair(room.get("site"), room.get("name"))]
            library.setdefault("account_meta", {})[site] = {"at": int(time.time()), "user": user, "count": len(rooms)}
    _cam_library_see(rooms)
    _cam_library_save(True)
    return {"ok": True, "user": user, "items": rooms[:120], "partial": bool(error), "warning": error or ""}


def cam_account_post(raw):
    try:
        body = json.loads(raw.decode("utf-8") or "{}")
    except ValueError:
        return {"ok": False, "error": "Die Anfrage war unlesbar."}
    if not isinstance(body, dict):
        return {"ok": False, "error": "Die Anfrage war unlesbar."}
    op = str(body.get("op") or "")
    if op in ("login", "session", "favs") and _cam_site(body.get("site")) not in _CAM_ACCOUNT_SITES:
        return {"ok": False, "error": "Für diesen Anbieter ist noch keine geprüfte Konto- und Following-Anbindung verfügbar. Bitte die offizielle Website verwenden."}
    if op == "logout":
        site = _cam_site(body.get("site"))
        if not site:
            return {"ok": False, "error": "Diese Live-Seite fehlt."}
        _cam_session_drop(site)
        return {"ok": True, "accounts": _cam_account_public()}
    if op == "status":
        return {"ok": True, "accounts": _cam_account_public()}
    if op == "favs":
        site = _cam_site(body.get("site"))
        if not site:
            return {"ok": False, "error": "Diese Live-Seite fehlt."}
        return _cam_account_favs(site)
    if op == "session":
        site = _cam_site(body.get("site"))
        if site in ("cam4", "xlovecam"):
            from live_cam_account_providers import WebsiteAccounts
            saved, error = WebsiteAccounts(globals()).session_take(site, body.get("session"))
            if error:
                return {"ok": False, "error": error}
            return {"ok": True, "user": saved, "accounts": _cam_account_public()}
        takers = {
            "chaturbate": _cb_session_take,
            "stripchat": _sc_session_take,
            "bongacams": _bc_session_take,
            "camsoda": _cs_session_take,
        }
        if site not in takers:
            return {"ok": False, "error": "Diese Live-Seite fehlt."}
        saved, error = takers[site](body.get("session"))
        if error:
            return {"ok": False, "error": error}
        return {"ok": True, "user": saved, "accounts": _cam_account_public()}
    if op != "login":
        return {"ok": False, "error": "Diese Cam-Aktion fehlt."}
    site, user, password = _cam_login_fields(body)
    if not site:
        return {"ok": False, "error": "Name oder Passwort fehlt."}
    if site in ("cam4", "xlovecam"):
        from live_cam_account_providers import WebsiteAccounts
        saved, error = WebsiteAccounts(globals()).login(site, user, password)
    elif site == "stripchat":
        code = str(body.get("code") or "")
        if len(code) > 12 or "\x00" in code:
            code = ""
        saved, error = _sc_login(user, password, code)
    else:
        logins = {"chaturbate": _cb_login, "bongacams": _bc_login, "camsoda": _cs_login}
        saved, error = logins[site](user, password)
    if error:
        return {"ok": False, "error": error}
    return {"ok": True, "user": saved, "accounts": _cam_account_public()}


def _cam_attach_local(items):
    if not items:
        return
    library = _cam_library_load()
    with _cam_lib_lock:
        models = library.get("models") if isinstance(library.get("models"), dict) else {}
        favs = {item for item in library.get("favs") or [] if isinstance(item, str)}
        account_names = set()
        account = library.get("account") if isinstance(library.get("account"), dict) else {}
        for names in account.values():
            if isinstance(names, list):
                account_names.update(item for item in names if isinstance(item, str))
        group_counts = {}
        for group in library.get("groups") or []:
            if not isinstance(group, dict):
                continue
            for item in group.get("items") or []:
                if isinstance(item, str):
                    group_counts[item] = group_counts.get(item, 0) + 1
        for room in items:
            if not isinstance(room, dict):
                continue
            key = _cam_pair(room.get("site"), room.get("name"))
            local = {}
            if key and key in favs:
                local["fav"] = True
            if key and key in account_names:
                local["account"] = True
            groups = group_counts.get(key, 0) if key else 0
            if groups:
                local["groups"] = groups
            row = models.get(key) if key else None
            if isinstance(row, dict):
                seen = _cam_number(row.get("seen"), 4_000_000_000)
                if seen:
                    local["seen"] = seen
            if local:
                room["local"] = local


def _cam_all_rooms(gender, offset):
    def load_stripchat():
        used = 0 if gender in ("", "all") else offset
        return _cam_cached(("stripchat", gender or "all", used), lambda: _sc_rooms(gender, used))

    def load_chaturbate():
        return _cam_cached(("chaturbate", gender, offset), lambda: _cb_rooms(gender, offset))

    def load_bonga():
        return _cam_cached(("bongacams", gender or "all", offset), lambda: _bc_rooms(gender, offset))

    def load_camsoda():
        return _cam_cached(("camsoda", gender or "all", 0), lambda: _cs_rooms(gender))

    jobs = [load_stripchat, load_chaturbate, load_bonga]
    if offset == 0:
        jobs.append(load_camsoda)
    sites = ["stripchat", "chaturbate", "bongacams"] + (["camsoda"] if offset == 0 else [])
    jobs.append(lambda: _cam_cached(("cam4", gender or "all", offset), lambda: _cam_extra_rooms("cam4", gender, offset)))
    sites.append("cam4")
    if offset == 0:
        jobs.append(lambda: _cam_cached(("xlovecam", "all", 0), lambda: _cam_extra_rooms("xlovecam", gender, 0)))
        sites.append("xlovecam")
    tasks = {_cam_list_pool.submit(job): site for job, site in zip(jobs, sites)}
    pending = set(tasks)
    results = []
    deadline = time.monotonic() + _CAM_LIST_WAIT
    while pending and time.monotonic() < deadline:
        done, pending = futures.wait(pending, timeout=max(0, deadline - time.monotonic()), return_when=futures.FIRST_COMPLETED)
        for task in done:
            try:
                results.append(task.result())
            except Exception:
                results.append({"ok": False, "error": "Eine Live-Seite antwortet gerade nicht."})
        if any(result.get("ok") and result.get("items") for result in results):
            # Deliver useful rooms immediately; slower providers fill in on the next poll.
            ready, pending = futures.wait(pending, timeout=min(0.03, max(0, deadline - time.monotonic())))
            for task in ready:
                try:
                    results.append(task.result())
                except Exception:
                    results.append({"ok": False, "error": "Eine Live-Seite antwortet gerade nicht."})
            break
    items = []
    seen = set()
    notes = []
    if pending:
        notes.append("Weitere Anbieter werden noch geladen.")
    any_ok = False
    paged = False
    for payload in results:
        if not isinstance(payload, dict):
            continue
        if payload.get("need_key"):
            notes.append("Chaturbate braucht noch den Affiliate-Schlüssel in den Einstellungen.")
            continue
        if not payload.get("ok"):
            if payload.get("error"):
                notes.append(str(payload.get("error"))[:160])
            continue
        any_ok = True
        if payload.get("note"):
            notes.append(str(payload["note"])[:250])
        if payload.get("paged"):
            paged = True
        for room in payload.get("items") or []:
            if not isinstance(room, dict):
                continue
            key = (str(room.get("site") or ""), str(room.get("name") or "").lower())
            if key in seen:
                continue
            seen.add(key)
            items.append(room)
    items.sort(key=lambda room: (-int(room.get("viewers") or 0), str(room.get("name") or "").lower()))
    if not any_ok:
        return {"ok": False, "site": "all", "items": [], "paged": False, "pending": bool(pending), "pending_sites": [tasks[task] for task in pending], "error": notes[0] if notes else "Die Live-Seiten antworten gerade nicht."}
    return {"ok": True, "site": "all", "items": items[:540], "paged": paged, "pending": bool(pending), "pending_sites": [tasks[task] for task in pending], "note": " ".join(dict.fromkeys(notes))[:300]}


def cam_rooms(query):
    site = str((query or {}).get("site") or "").strip().lower()
    gender = str((query or {}).get("gender") or "").strip().lower()
    if gender not in ("", "all", "f", "m", "t", "c"):
        gender = ""
    try:
        offset = int((query or {}).get("offset") or 0)
    except (TypeError, ValueError):
        offset = 0
    offset = max(0, min(5000, offset))
    if site == "chaturbate":
        if not _cam_wm():
            payload = {"ok": False, "need_key": True, "has_key": False, "site": "chaturbate", "items": [], "error": _CAM_KEY_HINT}
        else:
            payload = _cam_cached(("chaturbate", gender, offset), lambda: _cb_rooms(gender, offset))
    elif site == "stripchat":
        used = 0 if gender in ("", "all") else offset
        payload = _cam_cached(("stripchat", gender or "all", used), lambda: _sc_rooms(gender, used))
    elif site == "bongacams":
        payload = _cam_cached(("bongacams", gender or "all", offset), lambda: _bc_rooms(gender, offset))
    elif site == "camsoda":
        payload = _cam_cached(("camsoda", gender or "all", 0), lambda: _cs_rooms(gender))
    elif site in ("cam4", "xlovecam"):
        used = offset if site == "cam4" else 0
        payload = _cam_cached((site, gender if site == "cam4" else "all", used), lambda: _cam_extra_rooms(site, gender, used))
    elif site == "all":
        payload = _cam_cached(("all", gender or "all", offset), lambda: _cam_all_rooms(gender, offset))
    else:
        payload = {"ok": False, "items": [], "error": "Diese Live-Seite fehlt."}
    if payload.get("ok"):
        _cam_attach_local(payload.get("items") or [])
        _cam_library_see(payload.get("items") or [])
    return payload


def _cam_playlist_ok(url, headers):
    status, body = _cam_open(url, headers, 8, 400)
    return status == 200 and body.lstrip().startswith(b"#EXTM3U")


def _cb_field(text, key):
    for pattern in (r'"%s"\s*:\s*"([^"\\]{0,180})"' % key, r'\\"%s\\"\s*:\s*\\"([^"\\]{0,180})\\"' % key):
        match = re.search(pattern, text)
        if match:
            return match.group(1).replace("\\/", "/").replace("\\u002F", "/").replace("\\u002f", "/")
    return ""


def _cb_https_playlist(raw):
    text = html.unescape(str(raw or "")).replace("\\/", "/").replace("\\u002F", "/").replace("\\u002f", "/")
    text = text.strip()
    if len(text) > 2000 or any(char in text for char in " \r\n\t\"'<>"):
        return ""
    path = text.split("?", 1)[0]
    if text.startswith("https://") and path.endswith(".m3u8"):
        return text
    return ""


def _cb_hls(text):
    match = re.search(r'hls_source\\?"\s*:\s*\\?"((?:[^"\\]|\\.){20,2000})', text or "")
    return _cb_https_playlist(match.group(1)) if match else ""


_CB_CLOSED = ("private", "hidden", "offline", "away", "group", "password protected")
_CB_PLAY_HOST = re.compile(r"(^|\.)(mmcdn\.com|highwebmedia\.com)$", re.I)


def _cb_csrf(jar):
    for cookie in jar:
        value = str(cookie.value or "")
        if cookie.name == "csrftoken" and re.fullmatch(r"[A-Za-z0-9]{8,128}", value):
            return value
    return ""


def _cb_put_csrf(jar):
    token = _cb_csrf(jar)
    if token:
        return token
    token = hashlib.sha256(os.urandom(16)).hexdigest()[:32]
    try:
        _cam_put_cookie(jar, "csrftoken", token, "chaturbate.com")
    except Exception:
        return ""
    return _cb_csrf(jar)


def _cb_edge_url(payload):
    if not isinstance(payload, dict):
        return "", ""
    room_status = str(payload.get("room_status") or "").strip().lower()[:32]
    if room_status in _CB_CLOSED or (room_status and room_status != "public"):
        return room_status, ""
    success = payload.get("success")
    if success in (False, 0, "0", "false"):
        return room_status, ""
    playlist = ""
    for key in ("url", "hls_source", "playlist_url"):
        playlist = _cb_https_playlist(payload.get(key))
        if playlist:
            break
    if room_status != "public" or not playlist:
        return room_status, ""
    if success not in (True, 1, "1", "true", None):
        return room_status, ""
    return room_status, playlist


def _cb_edge(name, jar):
    token = _cb_put_csrf(jar)
    if not token:
        return "", ""
    body = urllib.parse.urlencode({"room_slug": name, "bandwidth": "high"}).encode("ascii")
    headers = {
        "User-Agent": _CAM_UA,
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRFToken": token,
        "Referer": "https://chaturbate.com/%s/" % urllib.parse.quote(name),
        "Origin": "https://chaturbate.com",
    }
    status, raw = _cam_exchange("https://chaturbate.com/get_edge_hls_url_ajax/", headers, body, 6, 20_000, jar)
    if status != 200:
        return "", ""
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return "", ""
    return _cb_edge_url(payload)


def _cb_page_playlists(text):
    found = []
    first = _cb_hls(text)
    if first:
        found.append(first)
    pattern = r"https?:(?:\\?/|/){2}(?:[^\"'\\\s]|\\.){8,1600}\.m3u8(?:\?[^\"'\\\s]{0,300})?"
    for match in re.finditer(pattern, text or "", re.I):
        playlist = _cb_https_playlist(match.group(0))
        if not playlist or playlist in found:
            continue
        host = urllib.parse.urlparse(playlist).netloc.lower()
        if not _CB_PLAY_HOST.search(host):
            continue
        lowered = playlist.lower()
        if any(word in lowered for word in ("advert", "preroll", "/ads/", "vast")):
            continue
        found.append(playlist)
        if len(found) >= 4:
            break
    return found


def _cb_play(name):
    jar = http.cookiejar.CookieJar()
    # The playlist address works once. The player must be the first reader.
    edge_status, edge_url = _cb_edge(name, jar)
    if edge_status in _CB_CLOSED:
        return {"ok": False, "error": "Der Raum ist nicht öffentlich."}
    headers = {"User-Agent": _CAM_UA, "Accept": "text/html", "Accept-Language": "de,en;q=0.8", "Referer": "https://chaturbate.com/"}
    # The edge address is enough to start. The room page only checks status and age,
    # so a ready edge URL must not wait on the full document.
    page_timeout, page_limit = (3, 200_000) if edge_url else (6, 1_200_000)
    status, body = _cam_open("https://chaturbate.com/%s/" % urllib.parse.quote(name), headers, page_timeout, page_limit, jar)
    text = body.decode("utf-8", "replace") if status == 200 else ""
    if text:
        room_status = _cb_field(text, "room_status").lower()
        if room_status in _CB_CLOSED:
            return {"ok": False, "error": "Der Raum ist nicht öffentlich."}
        age = re.search(r'"age"\s*:\s*(\d{1,3})\b', text) or re.search(r'\\"age\\"\s*:\s*(\d{1,3})\b', text)
        if age and not _cam_age_ok(age.group(1)):
            return {"ok": False, "error": "Der Raum wird nicht geöffnet."}
        subject = _cb_field(text, "room_subject")
        if subject and _cam_subject(subject) is None:
            return {"ok": False, "error": "Der Raum wird nicht geöffnet."}
    candidates = []
    if edge_url:
        candidates.append(edge_url)
    for playlist in _cb_page_playlists(text):
        if playlist not in candidates:
            candidates.append(playlist)
    if not candidates:
        if status != 200:
            return {"ok": False, "error": "Der Chaturbate-Raum antwortet nicht."}
        if _cam_blocked(text):
            return {"ok": False, "error": "Chaturbate prüft den Browser gerade."}
        return {"ok": False, "error": "Dieser Raum nennt keinen öffentlichen Stream."}
    parts = []
    for cookie in jar:
        value = str(cookie.value or "")
        if cookie.name and value and "\r" not in value and "\n" not in value:
            parts.append(cookie.name + "=" + value)
    pack = {"Referer": "https://chaturbate.com/", "Origin": "https://chaturbate.com", "User-Agent": _CAM_UA}
    cookie_text = "; ".join(parts)[:3500]
    if cookie_text:
        pack["Cookie"] = cookie_text
    path = _cam_pack(candidates[0], pack)
    return {"ok": True, "title": name, "path": path, "sources": [{"label": "Live", "path": path}], "facts": {"site": "Chaturbate"}}


def _sc_media_ok(text, playlist_url, headers):
    if "EXT-X-MOUFLON-ADVERT" in text or "#EXT-X-ENDLIST" in text or "#EXTINF:" not in text:
        return False
    live = _live_playlist(text, playlist_url)
    if not live or "EXT-X-MOUFLON" in live:
        return False
    peek = dict(headers)
    peek["Range"] = "bytes=0-15"
    for line in live.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ".m3u8" in stripped.split("?", 1)[0].lower():
            continue
        absolute = urllib.parse.urljoin(playlist_url, stripped)
        parsed = urllib.parse.urlparse(absolute)
        if parsed.scheme != "https" or "doppiocdn" not in parsed.netloc.lower() or ".." in parsed.path:
            continue
        status, body = _cam_open(absolute, peek, 8, 32)
        if status not in (200, 206):
            return False
        return (
            body.startswith(b"\x47")
            or b"ftyp" in body[:16]
            or b"moof" in body[:16]
            or b"sidx" in body[:16]
            or b"styp" in body[:16]
        )
    return False


def _sc_play(name, stream):
    stream = str(stream or "")
    if not _CAM_STREAM.fullmatch(stream):
        return {"ok": False, "error": "Bitte den Raum noch einmal aus der Liste öffnen."}
    master = "https://edge-hls.doppiocdn.com/hls/%s/master/%s_auto.m3u8" % (stream, stream)
    pack = {"Referer": "https://stripchat.com/", "Origin": "https://stripchat.com", "User-Agent": _CAM_UA}
    status, body = _cam_open(master, pack, 8, 100_000)
    text = body.decode("utf-8", "replace")
    if status != 200 or not text.lstrip().startswith("#EXTM3U"):
        return {"ok": False, "error": "Dieser Raum startet gerade nicht."}
    pending = None
    best = ""
    best_height = -1
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#EXT-X-STREAM-INF"):
            pending = None if "blur" in stripped.lower() else stripped
            continue
        if pending is None or not stripped or stripped.startswith("#"):
            continue
        if "blur" in stripped.lower():
            pending = None
            continue
        height = 0
        found = re.search(r"RESOLUTION=\d+x(\d+)", pending)
        if found:
            height = int(found.group(1))
        if height >= best_height:
            best_height = height
            best = urllib.parse.urljoin(master, stripped)
        pending = None
    keys = _mouflon_keys()
    psch, pkey = _mouflon_pkey(text, master, keys)
    if not pkey or pkey not in keys:
        keys = _mouflon_keys(True)
        psch, pkey = _mouflon_pkey(text, master, keys)
    if not best or not pkey:
        return {"ok": False, "error": "Dieser Raum startet gerade nicht."}
    signed = best + ("&" if "?" in best else "?") + "psch=%s&pkey=%s" % (urllib.parse.quote(psch), urllib.parse.quote(pkey))
    status, body = _cam_open(signed, pack, 8, 100_000)
    media = body.decode("utf-8", "replace")
    if status != 200 or not _sc_media_ok(media, signed, pack):
        return {"ok": False, "error": "Stripchat liefert beim Öffnen nur einen kurzen Werbeclip. Der Live-Stream ist verschlüsselt und hat keinen normalen Link. Die Werbung wird nicht abgespielt."}
    path = _cam_pack(master, pack)
    return {"ok": True, "title": name, "path": path, "sources": [{"label": "Live", "path": path}], "facts": {"site": "Stripchat"}}


_BC_TABS = {"f": "female", "m": "male", "c": "couples", "t": "transsexual"}
_BC_GENDER = {
    "female": "weiblich",
    "male": "männlich",
    "transsexual": "trans",
    "trans": "trans",
    "couple": "paar",
    "couples": "paar",
    "couple_f_m": "paar",
    "couple_t_t": "paar",
}
_CS_GENDER = {"f": "weiblich", "m": "männlich", "t": "trans", "c": "paar", "female": "weiblich", "male": "männlich"}


def _bc_gender(value):
    text = str(value or "").strip().lower()
    if text in _BC_GENDER:
        return _BC_GENDER[text]
    if text.startswith("couple"):
        return "paar"
    return ""


def _bc_thumb(value):
    url = str(value or "").strip()
    if url.startswith("//"):
        url = "https:" + url
    if "{ext}" in url:
        url = url.replace("{ext}", "jpg")
    if "{" in url or "}" in url or not url.startswith("https://") or _is_video_url(url):
        return ""
    return _cam_image(url, "https://bongacams.com/")


def _bc_room(model, allow_offline=False):
    if not isinstance(model, dict):
        return None
    public = str(model.get("room") or "").lower() == "public"
    if not public and not allow_offline:
        return None
    name = str(model.get("username") or "")
    if not _CAM_NAME.fullmatch(name) or _CAM_CHILD.search(name) or _CAM_CHILD.search(str(model.get("display_name") or "")):
        return None
    esid = str(model.get("esid") or "")
    if not _CAM_STREAM.fullmatch(esid):
        esid = ""
    try:
        viewers = int(model.get("viewers") or 0)
    except (TypeError, ValueError):
        viewers = 0
    quality = str(model.get("vq") or "").lower()
    hd = "1080" in quality or "1280" in quality or quality.startswith("hd")
    room = {
        "site": "bongacams",
        "name": name,
        "gender": _bc_gender(model.get("gender")),
        "viewers": max(0, viewers),
        "hd": hd,
        "subject": _cam_subject(model.get("room_subject") or model.get("subject") or "") or "",
        "tags": _cam_collect_tags(model),
        "thumb": _bc_thumb(model.get("thumb_image") or model.get("profile_image") or model.get("avatar")),
        "stream": esid if public else "",
        "online": public,
        "show": "public" if public else "offline",
    }
    return _cam_details(room, {
        **model,
        "lang": model.get("lang"),
        "flag": model.get("flag"),
        "badges": _cam_badges(hd, ("Top", model.get("is_top"))),
    })


def _bc_fetch(tab, limit, offset):
    params = {"online_only": "1", "offset": str(offset), "limit": str(limit)}
    if tab:
        params["livetab"] = tab
    headers = {
        "User-Agent": _CAM_UA,
        "Accept": "application/json",
        "Referer": "https://bongacams.com/",
        "Origin": "https://bongacams.com",
        "X-Requested-With": "XMLHttpRequest",
    }
    status, body = _cam_open("https://bongacams.com/tools/listing_v3.php?" + urllib.parse.urlencode(params), headers, 10, 800_000)
    if status != 200:
        return [], "BongaCams antwortet gerade nicht."
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return [], "BongaCams lieferte keine Liste."
    if not isinstance(data, dict):
        return [], "BongaCams lieferte keine Liste."
    models = data.get("models")
    return models if isinstance(models, list) else [], ""


def _bc_take(models, limit, seen):
    items = []
    for model in models:
        if len(items) >= limit:
            break
        room = _bc_room(model)
        if not room or room["name"].lower() in seen:
            continue
        seen.add(room["name"].lower())
        items.append(room)
    return items


def _bc_rooms(gender, offset):
    if gender in ("", "all"):
        seen = set()
        items = []
        errors = []
        with futures.ThreadPoolExecutor(max_workers=4) as pool:
            batches = list(pool.map(lambda tab: _bc_fetch(tab, 20, 0), ("female", "male", "couples", "transsexual")))
        for models, err in batches:
            if err:
                errors.append(err)
                continue
            items.extend(_bc_take(models, 15, seen))
            if len(items) >= 60:
                break
        if not items and errors:
            debug_log("server", "cam", "liste", {"site": "bongacams"})
            return {"ok": False, "site": "bongacams", "items": [], "error": errors[0]}
        return {"ok": True, "site": "bongacams", "items": items[:60], "paged": False}
    models, err = _bc_fetch(_BC_TABS.get(gender, ""), 60, offset)
    if err:
        debug_log("server", "cam", "liste", {"site": "bongacams"})
        return {"ok": False, "site": "bongacams", "items": [], "error": err}
    return {"ok": True, "site": "bongacams", "items": _bc_take(models, 60, set()), "paged": True}


def _bc_play(name, stream):
    stream = str(stream or "")
    if not _CAM_STREAM.fullmatch(stream):
        return {"ok": False, "error": "Bitte den Raum noch einmal aus der Liste öffnen."}
    playlist = "https://%s.bcvcdn.com/hls/stream_%s/playlist.m3u8" % (stream, name)
    pack = {"Referer": "https://bongacams.com/", "Origin": "https://bongacams.com", "User-Agent": _CAM_UA}
    status, body = _cam_open(playlist, pack, 8, 20_000)
    text = body.decode("utf-8", "replace")
    if status != 200 or not text.lstrip().startswith("#EXTM3U") or "EXT-X-MOUFLON-ADVERT" in text:
        return {"ok": False, "error": "Dieser Raum startet gerade nicht."}
    if "#EXT-X-ENDLIST" in text and "#EXT-X-STREAM-INF" not in text:
        return {"ok": False, "error": "Dieser Raum startet gerade nicht."}
    path = _cam_pack(playlist, pack)
    return {"ok": True, "title": name, "path": path, "sources": [{"label": "Live", "path": path}], "facts": {"site": "BongaCams"}}


def _cs_tpl(row):
    tpl = row.get("tpl") if isinstance(row, dict) else None
    if isinstance(tpl, dict):
        return {str(key): value for key, value in tpl.items()}
    if isinstance(tpl, list):
        return {str(index): value for index, value in enumerate(tpl)}
    return {}


def _cs_room(row):
    tpl = _cs_tpl(row)
    name = ""
    gender = ""
    subject = ""
    image = ""
    viewers = 0
    for key in sorted(tpl, key=lambda item: int(item) if str(item).isdigit() else 999):
        value = tpl.get(key)
        if isinstance(value, str) and not name and _CAM_NAME.fullmatch(value):
            name = value
        elif value in ("f", "m", "t", "c", "female", "male"):
            gender = str(value)
        elif key == "4" and isinstance(value, int):
            viewers = value
        elif isinstance(value, str) and not image and (value.startswith("https://") or value.startswith("//")):
            image = "https:" + value if value.startswith("//") else value
        elif isinstance(value, str) and not subject and " " in value:
            subject = value
    if not name or _CAM_CHILD.search(name):
        return None
    subject = _cam_subject(subject)
    if subject is None:
        return None
    if not image.startswith("https://") or _is_video_url(image):
        image = ""
    return {
        "site": "camsoda",
        "name": name,
        "gender": _CS_GENDER.get(gender, ""),
        "viewers": max(0, min(viewers, 1_000_000)),
        "hd": False,
        "subject": subject,
        "tags": _cam_tag_list(subject, *[value for value in tpl.values() if isinstance(value, str) and value.count(",") >= 2 and "http" not in value.lower()]),
        "thumb": _cam_image(image, "https://www.camsoda.com/") if image else "",
        "stream": "",
        "online": True,
        "show": "public",
        "_g": gender[:1],
    }


def _cs_rooms(gender):
    headers = {
        "User-Agent": _CAM_UA,
        "Accept": "application/json",
        "Referer": "https://www.camsoda.com/",
        "Origin": "https://www.camsoda.com",
    }
    status, body = _cam_open("https://www.camsoda.com/api/v1/browse/online?gender=f&page=1", headers, 10, 800_000)
    if status != 200:
        debug_log("server", "cam", "liste", {"site": "camsoda"})
        return {"ok": False, "site": "camsoda", "items": [], "error": "CamSoda antwortet gerade nicht."}
    text = body.decode("utf-8", "replace")
    start = text.find("[", text.find('"results"'))
    if start < 0:
        return {"ok": False, "site": "camsoda", "items": [], "error": "CamSoda lieferte keine Liste."}
    want = {"f": "f", "m": "m", "t": "t", "c": "c"}.get(gender, "")
    items = []
    seen = set()
    pos = start + 1
    decoder = json.JSONDecoder()
    while len(items) < 60 and pos < len(text):
        while pos < len(text) and text[pos] in " \r\n\t,":
            pos += 1
        if pos >= len(text) or text[pos] == "]":
            break
        try:
            obj, end = decoder.raw_decode(text[pos:])
        except ValueError:
            break
        pos += end
        room = _cs_room(obj)
        if not room or room["name"].lower() in seen:
            continue
        if want and room.get("_g") != want:
            continue
        seen.add(room["name"].lower())
        room.pop("_g", None)
        items.append(room)
    if want and not items:
        return {"ok": False, "site": "camsoda", "items": [], "paged": False, "error": "CamSoda gibt diese Gruppe in der öffentlichen Liste gerade nicht her."}
    return {"ok": True, "site": "camsoda", "items": items, "paged": False}


def _cs_server_ok(value):
    return bool(re.fullmatch(r"[A-Za-z0-9.-]{3,80}(?:/[A-Za-z0-9._~-]{1,40})?", value))


def _cs_play(name):
    guest = "guest_%05d" % ((int(time.time() * 1000) + len(name)) % 90000 + 10000)
    headers = {
        "User-Agent": _CAM_UA,
        "Accept": "application/json",
        "Referer": "https://www.camsoda.com/" + name,
        "Origin": "https://www.camsoda.com",
    }
    status, body = _cam_open(
        "https://www.camsoda.com/api/v1/video/vtoken/%s?username=%s" % (urllib.parse.quote(name), guest),
        headers,
        8,
        80_000,
    )
    if status != 200:
        return {"ok": False, "error": "Der CamSoda-Raum antwortet nicht."}
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return {"ok": False, "error": "Der CamSoda-Raum antwortet nicht."}
    if not isinstance(data, dict):
        return {"ok": False, "error": "Der CamSoda-Raum antwortet nicht."}
    if data.get("private_servers"):
        return {"ok": False, "error": "Der Raum ist nicht öffentlich."}
    stream = str(data.get("stream_name") or "")
    servers = data.get("edge_servers") if isinstance(data.get("edge_servers"), list) else []
    token = str(data.get("token") or "")
    if not servers or not re.fullmatch(r"[A-Za-z0-9_./:-]{2,80}", stream) or ".." in stream:
        return {"ok": False, "error": "Dieser Raum nennt keinen öffentlichen Stream."}
    if not re.fullmatch(r"[A-Za-z0-9._~+/=-]{8,400}", token):
        return {"ok": False, "error": "Dieser Raum nennt keinen öffentlichen Stream."}
    server = str(servers[0] or "")
    if not _cs_server_ok(server):
        return {"ok": False, "error": "Dieser Raum startet gerade nicht."}
    playlist = "https://%s/%s_v1/index.m3u8?token=%s" % (server, stream, urllib.parse.quote(token, safe=""))
    pack = {"Referer": "https://www.camsoda.com/", "Origin": "https://www.camsoda.com", "User-Agent": _CAM_UA}
    status, body = _cam_open(playlist, pack, 8, 30_000)
    text = body.decode("utf-8", "replace")
    if status != 200 or not text.lstrip().startswith("#EXTM3U") or "EXT-X-MOUFLON-ADVERT" in text or "#EXT-X-ENDLIST" in text:
        return {"ok": False, "error": "Dieser Raum startet gerade nicht."}
    path = _cam_pack(playlist, pack)
    return {"ok": True, "title": name, "path": path, "sources": [{"label": "Live", "path": path}], "facts": {"site": "CamSoda"}}


def cam_play(query, connection=None):
    from live_cam_performance import resolver_cache
    site=str((query or {}).get('site') or '').strip().lower()
    name=str((query or {}).get('name') or '').strip()
    if not _CAM_NAME.fullmatch(name) or _CAM_CHILD.search(name):
        return {'ok':False,'error':'Unbekannter Raum.'}
    # Chaturbate can issue a different, one-use media address per connection.
    if site=='chaturbate':return _cam_play_uncached(query,connection)
    key=(site,name,str((query or {}).get('stream') or ''))
    return resolver_cache.resolve(key,lambda:_cam_play_uncached(query,connection),fresh=(query or {}).get('fresh')=='1')


def _cam_play_uncached(query, connection=None):
    site = str((query or {}).get("site") or "").strip().lower()
    name = str((query or {}).get("name") or "").strip()
    if not _CAM_NAME.fullmatch(name) or _CAM_CHILD.search(name):
        return {"ok": False, "error": "Unbekannter Raum."}
    if not _cam_play_slots.acquire(timeout=3):
        return {"ok": False, "error": "Mehrere Räume werden gerade verbunden. Bitte gleich erneut versuchen."}
    started = time.monotonic()
    _cam_request.deadline = started + 18
    _cam_request.connection = connection
    try:
        if site == "stripchat":
            payload = _sc_play(name, (query or {}).get("stream") or "")
        elif site == "chaturbate":
            payload = _cb_play(name)
        elif site == "bongacams":
            payload = _bc_play(name, (query or {}).get("stream") or "")
        elif site == "camsoda":
            payload = _cs_play(name)
        elif site in ("cam4", "xlovecam"):
            payload = _cam_extra_play(site, name)
        else:
            payload = {"ok": False, "error": "Diese Live-Seite fehlt."}
    except (OSError, TimeoutError, ValueError):
        payload = {"ok": False, "error": "Der Raum hat nicht rechtzeitig geantwortet. Erneut verbinden ist möglich."}
    finally:
        _cam_request.deadline = None
        _cam_request.connection = None
        _cam_play_slots.release()
    debug_log("server", "cam", "verbunden" if payload.get("ok") else "raum", {"site": site, "ms": int((time.monotonic() - started) * 1000)})
    return payload


_library_media = media_library.MediaService(run_plugin)
_star_finder_service = None
_star_service_lock = threading.Lock()


def _star_service():
    global _star_finder_service
    with _star_service_lock:
        if _star_finder_service is None:
            _star_finder_service = star_finder.StarFinder(sys.modules[__name__])
        return _star_finder_service


def _star_jobs_payload():
    data = av_sync_status()
    runtime = _star_runtime_hub()
    for job in data.get("jobs") or []:
        ident = job["id"]
        job["paused"] = runtime.paused(ident)
        job["checkpoint"] = (_job_cursor_get({"texts":"library"}.get(ident,ident)) or {}).get("checkpoint")
        if job["paused"]:
            job["running"] = False
            job["what"] = "Pausiert · gespeicherter Fortschritt bleibt erhalten"
            job["eta"] = None
        if ident == "names" and _babe_run.get("name_errors"):
            job["note"] = (job.get("note") or "")+" · "+str(_babe_run["name_errors"])+" Quellenabrufe offen"
        if ident == "names" and _babe_run.get("sitemap_error"):
            job["note"] = (job.get("note") or "")+" · "+_babe_run["sitemap_error"]
        if ident == "lang":
            state = data.get("lang") or {}
            job["succeeded"] = int(state.get("ready") or 0)
            job["failed"] = int(state.get("failed") or 0)
            job["skipped"] = int(state.get("skipped") or 0)
    service=_star_service()
    service.boxes.start()
    service.library.start()
    data.setdefault('jobs',[]).append(service.boxes.job())
    data['jobs'].extend(service.library.jobs())
    return {**data,**runtime.public(),"overview":service.overview(),"available_sources":service.sources.catalog()}


def _star_control(body):
    service = _star_service()
    operation = body.get("op")
    if operation == 'box-config':
        try:return service.boxes.configure(body)
        except star_runtime.SourceError as error:
            from star_stashbox import STATUS
            return {'ok':False,'error':STATUS.get(error.reason,'Quellverbindung fehlgeschlagen. Bitte später erneut prüfen.')}
    if operation == 'box-enqueue':
        ident,name=service._identity(body)
        if not ident:raise ValueError('Das Profil fehlt.')
        service.boxes.enqueue(ident,name,bool(body.get('force')))
        return {'ok':True,'pending':True}
    if operation == 'box-confirm':return service.boxes.confirm(body)
    if operation == "profile": return service.refresh(body)
    if operation == "profile-full": return service.full_refresh(body)
    if operation == "images": return service.more_images(body)
    if operation == "note":
        ident,name = service._identity(body)
        if not ident: raise ValueError("Das Profil fehlt.")
        with service.runtime.store.lock:
            old = service.runtime.store.cached("notes",ident) or {"revision":0}
            if int(body.get("revision") or 0)!=int(old.get("revision") or 0):
                return {"ok":False,"conflict":True,"note":old,"error":"Die Notiz wurde in einem anderen Fenster geändert. Dein Entwurf bleibt erhalten."}
            row = {"text":str(body.get("text") or "")[:20000],"revision":int(old.get("revision") or 0)+1,"at":time.time()}
            service.runtime.store.cache("notes",ident,row,10**12)
        return {"ok":True,"note":row}
    if operation == "discover":
        name = str(body.get("name") or "").strip()[:100]
        if len(name)<3: raise ValueError("Bitte mindestens drei Zeichen eingeben.")
        service.runtime.submit("discover:"+name.casefold(),lambda:_av_lookup_query(name,star_index()))
        return {"ok":True,"pending":True}
    result = service.runtime.control(body)
    if operation=='run' and body.get('job') in ('scenes','all'):service.boxes.run_now()
    if operation=='run' and body.get('job') in ('catalogs','enrichment','all'):service.library.run_now(body.get('job'))
    if operation in ("run","resume"): _av_wake.set()
    return result


_multitube_service = None
_multitube_service_lock = threading.Lock()


def _multitube_resolver():
    global _multitube_service
    with _multitube_service_lock:
        if _multitube_service is None:
            from multitube_backend import Resolver
            _multitube_service = Resolver(ADDON, PROFILE)
        return _multitube_service


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def _cors(self):
        origin = self.headers.get("Origin") or ""
        if origin.startswith("http://127.0.0.1:") or origin.startswith("http://localhost:"):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Range, Content-Type")
            self.send_header("Access-Control-Expose-Headers", "Content-Length, Content-Range, Accept-Ranges")

    def _send(self, code, body, content_type="text/html; charset=utf-8", cache_seconds=0):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        headers = {}
        if code == 200 and self.command == "GET":
            from ui_performance import encoded_response
            path = urllib.parse.urlsplit(self.path).path
            code, data, headers = encoded_response(path, data, content_type, self.headers.get("Accept-Encoding", ""), self.headers.get("If-None-Match", ""))
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        if code != 304:
            self.send_header("Content-Length", str(len(data)))
        for name, value in headers.items():
            self.send_header(name, value)
        if "Cache-Control" in headers:
            pass
        elif cache_seconds > 0:
            self.send_header("Cache-Control", "public, max-age=%s" % int(cache_seconds))
        elif cache_seconds < 0:
            self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/api/multitube/resolve", "/api/multitube/link"):
            if not _cam_user_request_allowed(self.headers):
                self._send(403, json.dumps({"ok": False, "error": "Multitube ist nur über die lokale Oberfläche erreichbar."}), "application/json", -1)
                return
            query = dict(urllib.parse.parse_qsl(parsed.query))
            try:
                from multitube_backend import query_from_url
                payload = {"ok": True, "query": query_from_url(query.get("url", ""), ADDON)} if parsed.path.endswith("/link") else _multitube_resolver().resolve(query.get("query", ""), query.get("requestId", ""), query.get("fresh") == "1")
            except ValueError as error:
                payload = {"ok": False, "error": str(error)}
            except Exception:
                payload = {"ok": False, "error": "Das Video konnte nicht aufgelöst werden. Vorhandene Videos bleiben erhalten."}
            try:
                self._send(200, json.dumps(payload), "application/json; charset=utf-8", -1)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                pass
            return
        if parsed.path == "/api/design-asset":
            try:
                name = dict(urllib.parse.parse_qsl(parsed.query)).get("file", "")
                path = settings_design.asset_path(PROFILE, name)
                mime = {"png":"image/png","jpg":"image/jpeg","gif":"image/gif","webp":"image/webp","woff":"font/woff","woff2":"font/woff2","ttf":"font/ttf","otf":"font/otf"}[path.suffix[1:]]
                self._send(200, path.read_bytes(), mime, 31536000)
            except (ValueError, OSError, KeyError):
                self._send(404, "Designdatei fehlt", "text/plain; charset=utf-8", -1)
            return
        note_ui(parsed.path)
        if parsed.path.startswith("/api/star-finder/"):
            query = dict(urllib.parse.parse_qsl(parsed.query,keep_blank_values=True))
            try:
                service = _star_service()
                if parsed.path == "/api/star-finder/thumb":
                    self._send(200,service.thumbnail(query.get("token","")),"image/webp",86400)
                    return
                if parsed.path == "/api/star-finder/catalog": payload = service.catalog(query)
                elif parsed.path == "/api/star-finder/profile": payload = service.get_profile(query)
                elif parsed.path == "/api/star-finder/images": payload = service.images(query)
                elif parsed.path == "/api/star-finder/content": payload = service.boxes.content(query)
                elif parsed.path == "/api/star-finder/jobs": payload = _star_jobs_payload()
                else: self._send(404,"Unbekannter Star-Finder-Bereich.","text/plain");return
                self._send(200,json.dumps(payload),"application/json; charset=utf-8",-1)
            except (ValueError, OSError) as error:
                self._send(400,json.dumps({"ok":False,"error":str(error)[:200]}),"application/json; charset=utf-8",-1)
            return
        if parsed.path == "/api/media/resolve":
            query = dict(urllib.parse.parse_qsl(parsed.query))
            try:
                payload = _library_media.resolve(query.get("query", ""))
                if payload.get("ok"):
                    for key in ("src", "download"):
                        payload[key] = "http://127.0.0.1:%d%s" % (MEDIA_PORT, payload[key])
            except Exception:
                payload = {"ok": False, "error": "Die Mediendatei konnte nicht geöffnet werden. Bitte erneut versuchen."}
            self._send(200, json.dumps(payload), "application/json; charset=utf-8", -1)
            return
        if parsed.path in ("/static/ui_i18n.js", "/static/ui_messages.js"):
            with open(os.path.join(ROOT, "static", parsed.path.rsplit("/", 1)[-1]), encoding="utf-8") as handle:
                self._send(200, handle.read(), "text/javascript; charset=utf-8", -1)
            return
        if parsed.path == "/static/camclient-script.ttf":
            with open(os.path.join(ROOT, "static", "camclient-script.ttf"), "rb") as handle:
                self._send(200, handle.read(), "font/ttf", 86400)
            return
        if parsed.path in ("/static/star_finder.js", "/static/star_finder.css"):
            filename = os.path.join(ROOT,"static",parsed.path.rsplit("/",1)[-1])
            with open(filename,encoding="utf-8") as handle:
                self._send(200,handle.read(),"text/css; charset=utf-8" if filename.endswith(".css") else "text/javascript; charset=utf-8",-1)
            return
        if parsed.path in ("/api/media/file", "/api/download-file"):
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:%d%s" % (MEDIA_PORT, self.path))
            self.send_header("Content-Length", "0")
            self._cors()
            self.end_headers()
            return
        if parsed.path == "/api/health":
            self._send(200, json.dumps({"ok": True, "pid": os.getpid()}), "application/json; charset=utf-8", -1)
            return
        if parsed.path in ("/api/image", "/api/stream"):
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:%d%s" % (MEDIA_PORT, self.path))
            self.send_header("Content-Length", "0")
            self._cors()
            self.end_headers()
            return
        if parsed.path in ("/static/chaturbate_tutorial.js", "/static/tutorials/chaturbate-tools.png", "/static/tutorials/chaturbate-settings.png"):
            filename = os.path.join(ROOT, parsed.path.lstrip("/"))
            with open(filename, "rb") as handle:
                self._send(200, handle.read(), "image/png" if filename.endswith(".png") else "text/javascript; charset=utf-8", -1)
            return
        if parsed.path in ("/static/adult-client-logo.jpg", "/static/adult-client-logo.png"):
            filename = parsed.path.rsplit("/", 1)[-1]
            with open(os.path.join(ROOT, "static", filename), "rb") as handle:
                self._send(200, handle.read(), "image/png" if filename.endswith(".png") else "image/jpeg", -1)
            return
        if parsed.path in ("/", "/index.html"):
            page = os.path.join(ROOT, "static", "app.html")
            with open(page, "r", encoding="utf-8") as handle:
                self._send(200, handle.read())
            return
        if parsed.path in ("/static/offline_videos.js", "/static/offline_videos.css", "/static/hls.min.js", "/static/brand_gold.css", "/static/live_cam_domain.js", "/static/live_cam_store.js", "/static/live_cam_studio.js", "/static/live_cam_studio.css", "/static/live_cam_single_domain.js", "/static/live_cam_single.js", "/static/live_cam_single.css", "/static/live_cam_gallery.js", "/static/live_cam_media_domain.js", "/static/live_cam_media_browser.js", "/static/live_cam_media.js", "/static/live_cam_notifications.js", "/static/live_cam_notifications.css", "/static/live_cam_gallery.css", "/static/live_cam_user.js", "/static/live_cam_user.css", "/static/live_cam_analytics.js", "/static/live_cam_statistics.js", "/static/live_cam_statistics_domain.js", "/static/live_cam_statistics_recorder.js", "/static/live_cam_statistics.css", "/static/live_cam_groups.js", "/static/live_cam_remembered.js", "/static/live_cam_following.js", "/static/live_cam_following.css", "/static/live_cam_discover.js", "/static/live_cam_discover_domain.js", "/static/live_cam_discover.css", "/static/live_cam_groups.css", "/static/live_cam_groups_domain.js", "/static/live_cam_models.js", "/static/live_cam_models.css", "/static/live_cam_models_domain.js", "/static/media_library.js", "/static/media_library.css", "/static/multitube.css", "/static/multitube_domain.js", "/static/multitube_store.js", "/static/multitube.js", "/static/settings_studio.css", "/static/settings_studio.js", "/static/settings_domain.js", "/static/settings_schema.json", "/static/tube_profile.css", "/static/tube_profile_domain.js", "/static/tube_profile.js", "/static/tube_consumption.js", "/static/tube_player.js", "/static/tube_insights_domain.js"):
            filename = os.path.join(ROOT, "static", parsed.path.rsplit("/", 1)[-1])
            with open(filename, "r", encoding="utf-8") as handle:
                self._send(200, handle.read(), "text/css; charset=utf-8" if filename.endswith(".css") else "application/json; charset=utf-8" if filename.endswith(".json") else "text/javascript; charset=utf-8", -1)
            return
        if parsed.path == "/api/browse":
            started = time.time()
            query = dict(urllib.parse.parse_qsl(parsed.query))
            fresh = query.pop("fresh", None)
            depth = query.pop("depth", None)
            encoded = urllib.parse.urlencode(query)
            mode = query.get("mode")
            if mode in ("32", "offline-play"):
                self._send(200, json.dumps(_download_library.browse(query)), "application/json; charset=utf-8", -1)
                return
            cacheable = mode not in ("4", "6", "21")
            key = cache_key("v19-quality|" + encoded + "|cv=" + website_cache_version(query.get("website")) + "|depth=" + str(depth or ""))
            ttl = 30 * 24 * 3600 if mode == "60" and query.get("action") not in ("filmography_batch",) else LIST_TTL
            if cacheable and not fresh:
                cached = read_list_cache(key, ttl)
                if cached and _signed_media_stale(cached):
                    cached = None
                if cached:
                    items = cached.get("items") or []
                    debug_log("server", "browse", "cache", {"mode": mode, "n": len(items), "ms": int((time.time() - started) * 1000)})
                    self._send(200, json.dumps(cached), "application/json; charset=utf-8")
                    return
            payload = run_plugin(encoded, depth, priority=True)
            if payload.get("busy"):
                debug_log("server", "browse", "busy", {"mode": mode, "ms": int((time.time() - started) * 1000)})
                self._send(200, json.dumps(payload), "application/json; charset=utf-8")
                return
            if query.get("mode") in ("2", "4", "5") or (query.get("url") or "") in ("", "BOOTSTRAP"):
                enrich_tube_media(payload, query)
            if cacheable:
                write_list_cache(key, payload)
            payload["cached"] = False
            debug_log("server", "browse", "live", {
                "mode": mode,
                "n": len(payload.get("items") or []),
                "ms": int((time.time() - started) * 1000),
                "err": bool(payload.get("error")),
            })
            self._send(200, json.dumps(payload), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/hover-clip":
            query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
            self._send(200, json.dumps(hover_clip(query.get("url") or "")), "application/json; charset=utf-8", -1)
            return
        if parsed.path == "/api/tube-search":
            query = dict(urllib.parse.parse_qsl(parsed.query))
            payload = tube_search_payload(query.get("q") or "", query.get("page") or "1", query.get("per") or "", query.get("fresh") == "1")
            self._send(200, json.dumps(payload), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/catalog":
            self._send(200, json.dumps(catalog_payload()), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/terms":
            query = dict(urllib.parse.parse_qsl(parsed.query))
            self._send(200, json.dumps(site_terms(query.get("website", ""), query.get("q", ""))), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/site-preview":
            name = str(dict(urllib.parse.parse_qsl(parsed.query)).get("website") or "")
            if name in media_library.LIVE_SITES or not any(site.get("id") == name for site in _catalog_sites()):
                self._send(400, json.dumps({"ok": False, "items": [], "error": "Unbekannter Tube-Anbieter."}), "application/json; charset=utf-8", -1)
                return
            self._send(200, json.dumps(_site_previews.get(name)), "application/json; charset=utf-8", -1)
            return
        if parsed.path == "/api/site":
            query = dict(urllib.parse.parse_qsl(parsed.query))
            self._send(200, json.dumps(site_meta(query.get("website", ""))), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/page-sorts":
            query = dict(urllib.parse.parse_qsl(parsed.query))
            self._send(200, json.dumps(page_sorts(query.get("website", ""), query.get("url", ""))), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/film-facts":
            query = dict(urllib.parse.parse_qsl(parsed.query))
            self._send(200, json.dumps(film_facts(query.get("title", ""))), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/tube-profile":
            if not _cam_user_request_allowed(self.headers):
                self._send(403, '{"ok":false}', "application/json", -1)
                return
            store = _tube_consumption()
            if dict(urllib.parse.parse_qsl(parsed.query)).get("status") == "1":
                result = {"recording": store.enabled()}
            else:
                result = store.payload(_tube_model_lookup, read_ui().get("events", []))
            self._send(200, json.dumps(result), "application/json; charset=utf-8", -1)
            return
        if parsed.path == "/api/ui":
            self._send(200, json.dumps(read_ui()), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/models":
            self._send(200, json.dumps(model_sync_status()), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/stars":
            query = dict(urllib.parse.parse_qsl(parsed.query))
            self._send(200, json.dumps(star_catalog(query)), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/star-faces":
            query = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)
            self._send(200, json.dumps(star_faces(query.get("name") or [])), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/cam-key":
            self._send(200, json.dumps({"ok": True, "has_key": cam_key_has()}), "application/json; charset=utf-8", -1)
            return
        if parsed.path == "/api/cam-library":
            query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
            self._send(200, json.dumps(_cam_library_view(query)), "application/json; charset=utf-8", -1)
            return
        if parsed.path == "/api/cam-user":
            if not _cam_user_request_allowed(self.headers):
                self._send(403, json.dumps({"ok":False,"error":"Kontozugriff nur über die lokale Oberfläche."}), "application/json", -1)
                return
            self._send(200, json.dumps(_cam_user_hub().public()), "application/json; charset=utf-8", -1)
            return
        if parsed.path == "/api/cam-group-artwork":
            query = dict(urllib.parse.parse_qsl(parsed.query))
            key = query.get("key", "")
            if not re.fullmatch(r"[a-f0-9]{64}\.(?:webp|svg)", key):
                self._send(404, "Gruppenbild nicht gefunden.", cache_seconds=-1)
                return
            try:
                with open(os.path.join(PROFILE, "cam_group_artwork", key), "rb") as image:
                    self._send(200, image.read(), "image/svg+xml" if key.endswith(".svg") else "image/webp", 86400)
            except OSError:
                self._send(404, "Gruppenbild nicht gefunden.", cache_seconds=-1)
            return
        if parsed.path == "/api/cam-model-cover":
            query = dict(urllib.parse.parse_qsl(parsed.query))
            try:
                data = _cam_library_sync().read_cover(query.get("site"), query.get("name"))
                self._send(200, data, "image/jpeg", 3600)
            except (OSError, ValueError):
                self._send(404, "Modelcover wird noch ergänzt.", cache_seconds=-1)
            return
        if parsed.path == "/api/cam-profile":
            query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
            self._send(200, json.dumps(_cam_single_profile(query)), "application/json; charset=utf-8", -1)
            return
        if parsed.path == "/api/cam-account":
            self._send(200, json.dumps({"ok": True, "accounts": _cam_account_public()}), "application/json; charset=utf-8", -1)
            return
        if parsed.path == "/api/cam-rooms":
            query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
            self._send(200, json.dumps(cam_rooms(query)), "application/json; charset=utf-8", -1)
            return
        if parsed.path == "/api/cam-play":
            query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
            payload = cam_play(query, self.connection)
            try:
                self._send(200, json.dumps(payload), "application/json; charset=utf-8", -1)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                pass
            return
        if parsed.path == "/api/star":
            query = dict(urllib.parse.parse_qsl(parsed.query))
            self._send(200, json.dumps(star_profile(
                query.get("id") or "",
                query.get("name") or "",
                (query.get("enrich") or "") in ("1", "true", "ja"),
            )), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/star-images":
            query = dict(urllib.parse.parse_qsl(parsed.query))
            self._send(200, json.dumps(star_image_slice(
                query.get("id") or "",
                query.get("name") or "",
                query.get("from") or "0",
            )), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/star-sync":
            self._send(200, json.dumps(av_sync_status()), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/star-lang":
            query = dict(urllib.parse.parse_qsl(parsed.query))
            self._send(200, json.dumps(star_lang_payload(
                query.get("id") or "",
                query.get("name") or "",
                (query.get("fresh") or "") in ("1", "true", "ja"),
            )), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/star-lang-batch":
            self._send(200, json.dumps(_star_lang_batch_public()), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/offline":
            self._send(200, json.dumps(offline_report()), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/tools":
            self._send(200, json.dumps(tools_status()), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/stars-trending":
            self._send(200, json.dumps(star_trending()), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/star-cover":
            query = dict(urllib.parse.parse_qsl(parsed.query))
            path = _star_cover_file(query.get("file") or "")
            if not path:
                self._send(404, "Bild fehlt")
                return
            mime = {"jpg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}.get(path.rsplit(".", 1)[-1], "application/octet-stream")
            with open(path, "rb") as handle:
                self._send(200, handle.read(), mime, cache_seconds=3600)
            return
        if parsed.path == "/api/download-options":
            self._send(200, json.dumps(download_options(parsed.query)), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/download-storage":
            self._send(200, json.dumps(_download_library.storage(dict(urllib.parse.parse_qsl(parsed.query)).get("fresh")=="1")), "application/json; charset=utf-8", -1)
            return
        if parsed.path == "/api/downloads":
            self._send(200, json.dumps(download_jobs_public()), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/stats":
            self._send(200, json.dumps(library_facts()), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/prefs":
            self._send(200, json.dumps(read_prefs()), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/brand-image":
            query = dict(urllib.parse.parse_qsl(parsed.query))
            path = _brand_path(query.get("file") or "")
            if not path:
                self._send(404, "Bild fehlt")
                return
            mime = {"jpg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}.get(path.rsplit(".", 1)[-1], "application/octet-stream")
            with open(path, "rb") as handle:
                self._send(200, handle.read(), mime, cache_seconds=7 * 24 * 3600)
            return
        if parsed.path == "/api/group-logo":
            query = dict(urllib.parse.parse_qsl(parsed.query))
            path = _group_logo_path(query.get("file") or "")
            if not path:
                self._send(404, "Logo fehlt")
                return
            mime = {"jpg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}.get(path.rsplit(".", 1)[-1], "application/octet-stream")
            with open(path, "rb") as handle:
                self._send(200, handle.read(), mime)
            return
        if parsed.path == "/api/image":
            self._proxy_image(parsed.query)
            return
        if parsed.path == "/api/stream":
            self._proxy_stream(parsed.query)
            return
        if parsed.path == "/logos/" or parsed.path.startswith("/logos/"):
            rel = urllib.parse.unquote(parsed.path[len("/logos/"):])
            self._send_file(os.path.join(ADDON, "resources", "logos", rel))
            return
        if parsed.path == "/file":
            query = dict(urllib.parse.parse_qsl(parsed.query))
            self._send_file(query.get("path", ""))
            return
        self._send(404, "Nicht gefunden")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/multitube/cancel":
            if not _cam_user_request_allowed(self.headers):
                self._send(403, '{"ok":false}', "application/json", -1)
                return
            try:
                length = int(self.headers.get("Content-Length") or "0")
                if length < 0 or length > 1000:
                    self.close_connection = True
                    self._send(413, '{"ok":false}', "application/json", -1)
                    return
                body = json.loads(self.rfile.read(length) or b'{}')
                result = _multitube_resolver().cancel(str(body.get("requestId") or ""))
            except (ValueError, AttributeError):
                result = {"ok": False}
            self._send(200, json.dumps(result), "application/json", -1)
            return
        if parsed.path == "/api/design-asset":
            if not _cam_user_request_allowed(self.headers):
                self._send(403, '{"ok":false}', "application/json", -1)
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0 or length > 11_000_000:
                    self.close_connection = True
                    raise ValueError("Bild höchstens 8 MB, Schrift höchstens 4 MB.")
                body = json.loads(self.rfile.read(length))
                result = settings_design.save_asset(PROFILE, body.get("kind"), body.get("data"), body.get("expected", ""))
                self._send(200, json.dumps(result), "application/json; charset=utf-8", -1)
            except (ValueError, AttributeError) as error:
                self._send(400, json.dumps({"ok": False, "error": str(error)}), "application/json; charset=utf-8", -1)
            except OSError:
                self._send(500, '{"ok":false,"error":"Die Datei konnte nicht gespeichert werden."}', "application/json", -1)
            return
        if parsed.path == "/api/tube-profile":
            if not _cam_user_request_allowed(self.headers):
                self._send(403, '{"ok":false}', "application/json", -1)
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length < 0 or length > 450000:
                    self.close_connection = True
                    self._send(413, '{"ok":false}', "application/json", -1)
                    return
                result = _tube_consumption().write(json.loads(self.rfile.read(length) or b'{}'))
                self._send(200, json.dumps(result), "application/json; charset=utf-8", -1)
            except (ValueError, TypeError, AttributeError) as error:
                self._send(400, json.dumps({"ok":False,"error":str(error)[:200]}), "application/json", -1)
            except (OSError, tube_consumption.sqlite3.Error):
                self._send(500, '{"ok":false,"error":"Zeitmessung konnte nicht gespeichert werden."}', "application/json", -1)
            return
        note_ui(parsed.path)
        if parsed.path == "/api/restart":
            self._send(200, json.dumps(schedule_restart()), "application/json; charset=utf-8", -1)
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        if parsed.path == "/api/group-logo":
            limit = 2_200_000
        elif parsed.path == "/api/star-cover":
            limit = 12_000_000
        elif parsed.path == "/api/cam-key":
            limit = 4000
        elif parsed.path == "/api/cam-library":
            limit = 8000
        elif parsed.path == "/api/cam-models":
            limit = 16_000_000
        elif parsed.path in ("/api/cam-account", "/api/cam-user"):
            limit = 12000
        else:
            limit = 6_000_000
        if length < 0 or length > limit:
            self.close_connection = True
            self._send(413, "zu gross")
            return
        raw = self.rfile.read(length) if length else b""
        if parsed.path == "/api/star-finder/control":
            if not _cam_user_request_allowed(self.headers):
                self._send(403,'{"ok":false,"error":"Quellenverwaltung nur über die lokale Oberfläche."}',"application/json",-1)
                return
            try:
                body = json.loads(raw or b"{}")
                if not isinstance(body,dict): raise ValueError("Ungültige Anfrage.")
                result = _star_control(body)
                self._send(200,json.dumps(result),"application/json; charset=utf-8",-1)
            except (ValueError,TypeError) as error:
                self._send(400,json.dumps({"ok":False,"error":str(error)[:200]}),"application/json; charset=utf-8",-1)
            return
        if parsed.path == "/api/group-logo":
            self._save_group_logo(raw)
            return
        if parsed.path == "/api/brand-image":
            self._save_brand_image(raw)
            return
        if parsed.path == "/api/star-cover":
            self._save_star_cover(raw)
            return
        if parsed.path == "/api/cam-key":
            self._send(200, json.dumps(cam_key_set(raw)), "application/json; charset=utf-8", -1)
            return
        if parsed.path == "/api/cam-models":
            if not _cam_user_request_allowed(self.headers):
                self._send(403, json.dumps({"ok":False,"error":"Modeldaten nur über die lokale Oberfläche."}), "application/json", -1)
                return
            try:
                result = _cam_models_hub().handle(raw)
            except (ValueError, OSError) as error:
                result = {"ok":False,"error":str(error)}
            self._send(200, json.dumps(result), "application/json; charset=utf-8", -1)
            return
        if parsed.path == "/api/cam-library":
            self._send(200, json.dumps(_cam_library_post(raw)), "application/json; charset=utf-8", -1)
            return
        if parsed.path == "/api/cam-user":
            if not _cam_user_request_allowed(self.headers):
                self._send(403, json.dumps({"ok":False,"error":"Kontozugriff nur über die lokale Oberfläche."}), "application/json", -1)
                return
            _cam_request.deadline=time.monotonic()+85
            _cam_request.connection=self.connection
            try:
                result=_cam_user_hub().handle(raw)
            finally:
                _cam_request.deadline=None
                _cam_request.connection=None
                _cam_request.cancel=None
            self._send(200, json.dumps(result), "application/json; charset=utf-8", -1)
            return
        if parsed.path == "/api/cam-account":
            _cam_request.deadline=time.monotonic()+22
            _cam_request.connection=self.connection
            try:result=cam_account_post(raw)
            finally:
                _cam_request.deadline=None
                _cam_request.connection=None
            self._send(200, json.dumps(result), "application/json; charset=utf-8", -1)
            return
        if parsed.path == "/api/download":
            self._start_download(raw)
            return
        if parsed.path == "/api/download-open-folder":
            if not _cam_user_request_allowed(self.headers):
                self._send(403,json.dumps({"ok":False,"error":"Ordner bitte über die lokale Oberfläche öffnen."}),"application/json; charset=utf-8")
                return
            try:
                values=json.loads(raw.decode('utf-8'))
                result=_download_library.reveal(values.get('path',''))
                self._send(200,json.dumps(result),'application/json; charset=utf-8')
            except (OSError,ValueError,AttributeError) as error:
                self._send(400,json.dumps({'ok':False,'error':str(error)}),'application/json; charset=utf-8')
            return
        if parsed.path == "/api/download-cancel":
            self._download_action(raw, "cancel")
            return
        if parsed.path == "/api/download-forget":
            self._download_action(raw, "forget")
            return
        if parsed.path == "/api/download-show":
            self._download_action(raw, "show")
            return
        if parsed.path == "/api/download-resume":
            self._download_action(raw, "resume")
            return
        if parsed.path == "/api/tools":
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except ValueError:
                body = {}
            self._send(200, json.dumps(tools_apply(body if isinstance(body, dict) else {})), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/offline":
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except ValueError:
                body = {}
            self._send(200, json.dumps(offline_apply(body if isinstance(body, dict) else {})), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/star-lang-batch":
            self._send(200, json.dumps(star_lang_batch_start()), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/star-sync":
            self._send(200, json.dumps(av_sync_kick()), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/log":
            if length > 100000:
                self._send(413, "zu gross")
                return
            try:
                incoming = json.loads(raw.decode("utf-8") or "{}")
            except ValueError:
                incoming = {}
            events = incoming.get("events") if isinstance(incoming, dict) else None
            if not isinstance(events, list):
                events = [incoming] if isinstance(incoming, dict) else []
            for event in events[:40]:
                if not isinstance(event, dict):
                    continue
                debug_log("ui", event.get("kind") or "event", event.get("msg") or "", event.get("detail"))
            self._send(200, '{"ok":true}', "application/json")
            return
        if parsed.path == "/api/stop":
            xbmc.Player().stop()
            self._send(200, '{"ok":true}', "application/json")
            return
        if parsed.path == "/api/prefs":
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except ValueError:
                data = {}
            self._send(200, json.dumps(write_prefs(data)), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/ui":
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except ValueError:
                data = {}
            try:
                result = write_ui(data)
                self._send(200, json.dumps(result), "application/json; charset=utf-8", -1)
            except settings_design.Conflict as error:
                self._send(409, json.dumps({"ok": False, "error": str(error)}), "application/json; charset=utf-8", -1)
            except ValueError as error:
                self._send(400, json.dumps({"ok": False, "error": str(error)}), "application/json; charset=utf-8", -1)
            return
        if parsed.path == "/api/site-sort":
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except ValueError:
                data = {}
            self._send(200, json.dumps(apply_site_sort(data.get("website", ""), data.get("index", 0), data.get("url") or "")), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/site-period":
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except ValueError:
                data = {}
            self._send(200, json.dumps(apply_site_period(data.get("website", ""), data.get("index", 0), data.get("url") or "")), "application/json; charset=utf-8")
            return
        self._send(404, "Nicht gefunden")

    def _save_group_logo(self, raw):
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            self._send(400, "ungueltig")
            return
        try:
            blob = base64.b64decode(payload.get("data") or "", validate=False)
        except Exception:
            self._send(400, "ungueltig")
            return
        try:
            name = save_group_logo(str(payload.get("id") or ""), blob)
        except ValueError as exc:
            self._send(413 if str(exc) == "size" else 400, "zu gross" if str(exc) == "size" else "kein bild")
            return
        debug_log("server", "group-logo", "gespeichert", {"file": name, "bytes": len(blob)})
        self._send(200, json.dumps({"logo": name}), "application/json; charset=utf-8")

    def _save_brand_image(self, raw):
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            self._send(400, "ungueltig")
            return
        slot = str(payload.get("slot") or "")
        if payload.get("clear"):
            try:
                clear_brand_image(slot)
            except ValueError:
                self._send(400, "ungueltig")
                return
            debug_log("server", "brand", "entfernt", {"slot": slot})
            self._send(200, json.dumps({"ok": True, "slot": slot}), "application/json; charset=utf-8")
            return
        try:
            blob = base64.b64decode(payload.get("data") or "", validate=False)
        except Exception:
            self._send(400, "ungueltig")
            return
        try:
            name = save_brand_image(slot, blob)
        except ValueError as exc:
            self._send(413 if str(exc) == "size" else 400, "zu gross" if str(exc) == "size" else "kein bild")
            return
        stamp = int(time.time())
        debug_log("server", "brand", "gespeichert", {"file": name, "bytes": len(blob)})
        self._send(200, json.dumps({"file": name, "stamp": stamp, "slot": slot}), "application/json; charset=utf-8")

    def _save_star_cover(self, raw):
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            self._send(400, "ungueltig")
            return
        star_id = str(payload.get("id") or "")
        name = str(payload.get("name") or "")
        try:
            if payload.get("clear"):
                thumb = _star_cover_clear(star_id, name)
                self._send(200, json.dumps({"ok": True, "cover": False, "thumb": thumb, "clear": True}), "application/json; charset=utf-8")
                return
            if payload.get("data"):
                blob = base64.b64decode(payload.get("data") or "", validate=False)
            elif payload.get("image_token"):
                blob = _star_service().cover_bytes(str(payload["image_token"]))
            elif payload.get("url"):
                blob = _star_cover_fetch(payload.get("url"))
            else:
                raise ValueError("url")
            thumb = _star_cover_store(star_id, name, blob)
        except ValueError as exc:
            code = str(exc)
            if code == "age":
                self._send(403, json.dumps({"error": "age", "message": "Für dieses Profil wird kein Cover gespeichert."}), "application/json; charset=utf-8")
                return
            if code == "size":
                self._send(413, json.dumps({"error": "size", "message": "Das Bild ist zu groß. Höchstens 8 MB."}), "application/json; charset=utf-8")
                return
            self._send(400, json.dumps({"error": code, "message": "Das Bild konnte nicht übernommen werden."}), "application/json; charset=utf-8")
            return
        except Exception:
            self._send(502, json.dumps({"error": "fetch", "message": "Das Bild konnte nicht geladen werden."}), "application/json; charset=utf-8")
            return
        self._send(200, json.dumps({"ok": True, "cover": True, "thumb": thumb}), "application/json; charset=utf-8")

    def _start_download(self, raw):
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        result = start_download(
            payload.get("title") or "",
            payload.get("path") or "",
            payload.get("label") or "",
            payload.get("kind") or "",
            payload.get("folder") or "",
        )
        self._send(200 if result.get("ok") else 400, json.dumps(result), "application/json; charset=utf-8")

    def _download_action(self, raw, action):
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        job_id = payload.get("id") or ""
        if action == "cancel":
            result = cancel_download(job_id)
        elif action == "forget":
            result = forget_download(job_id)
        elif action == "resume":
            result = resume_download(job_id)
        else:
            result = reveal_download(job_id)
        self._send(200, json.dumps(result), "application/json; charset=utf-8")

    def _send_file(self, path):
        root = os.path.abspath(os.path.join(ADDON, "resources", "logos"))
        real = os.path.abspath(path)
        allowed = real == root or real.startswith(root + os.sep) or real.startswith(os.path.abspath(PROFILE) + os.sep)
        if not allowed or not os.path.isfile(real):
            self._send(404, "Datei fehlt")
            return
        mime = mimetypes.guess_type(real)[0] or "application/octet-stream"
        with open(real, "rb") as handle:
            self._send(200, handle.read(), mime, cache_seconds=7 * 24 * 3600)

    def _proxy_image(self, query):
        params = dict(urllib.parse.parse_qsl(query))
        url = params.get("url") or ""
        if not url.startswith(("http://", "https://")) or _is_video_url(url):
            self._send(404, "Bild nicht erreichbar")
            return
        fresh = params.get("live") == "1" and _cam_fresh_ok(url)
        try:
            data, mime = load_image(url, fresh=fresh)
            self._send(200, data, mime, cache_seconds=-1 if fresh else 7 * 24 * 3600)
        except Exception:
            self._send(404, "Bild nicht erreichbar")

    def _proxy_stream(self, query):
        params = dict(urllib.parse.parse_qsl(query))
        live_cam = params.get("cam") == "1"
        url, extra = split_kodi_url(params.get("url") or "")
        if not url.startswith(("http://", "https://")):
            self._send(400, "Ungültige Streamadresse")
            return
        if not _stream_slots.acquire(timeout=0.2):
            debug_log("server", "stream", "zu viele gleichzeitig", {"url": _stream_log_url(url)})
            self._send(429, "Zu viele Streams gleichzeitig")
            return
        response = None
        try:
            agent = (params.get("User-Agent") or extra.get("User-Agent") or "Mozilla/5.0").replace("\r", "").replace("\n", "")[:200]
            headers = {"User-Agent": agent or "Mozilla/5.0"}
            for key in ("Referer", "Origin", "Cookie"):
                if params.get(key):
                    headers[key] = params[key]
                elif extra.get(key):
                    headers[key] = extra[key]
            if self.headers.get("Range"):
                headers["Range"] = self.headers.get("Range")
            req = urllib.request.Request(url, headers=headers)
            try:
                if live_cam:
                    from live_cam_http import open_cam_media
                    response = open_cam_media(url, headers, timeout=15)
                else:
                    response = urllib.request.urlopen(req, timeout=15)
            except Exception as exc:
                debug_log("server", "stream", "start fehlgeschlagen", {"url": _stream_log_url(url), "err": re.sub(r"https?://\S+", "", str(exc))[:160]})
                self._send(502, str(exc))
                if isinstance(exc, urllib.error.HTTPError):
                    exc.close()
                return
            mime = response.headers.get("Content-Type", "application/octet-stream").split(";")[0]
            playlist = "mpegurl" in mime.lower() or response.geturl().split("?", 1)[0].lower().endswith(".m3u8")
            if playlist:
                body = response.read(2_000_000)
                text = body.decode("utf-8", "replace")
                playlist_url = response.geturl()
                live = _live_playlist(text, playlist_url)
                if live is None:
                    self._send(502, "Dieser Stream ist nur Werbung.")
                    return
                forwarded = {key: headers[key] for key in ("Referer", "Origin", "Cookie", "User-Agent") if key in headers}
                if live_cam:
                    forwarded["cam"] = "1"
                text = rewrite_playlist(live, playlist_url, forwarded)
                self._send(200, text, "application/vnd.apple.mpegurl")
                return
            status = getattr(response, "status", 200) or 200
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Accept-Ranges", "bytes")
            for key in ("Content-Length", "Content-Range"):
                if response.headers.get(key):
                    self.send_header(key, response.headers.get(key))
            self._cors()
            self.end_headers()
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)
        except Exception:
            pass
        finally:
            if response is not None:
                response.close()
            _stream_slots.release()


class MediaHandler(Handler):
    """Bilder und Streams. Eigener Port, damit sie die Oberfläche nicht blockieren."""

    def do_GET(self):
        self.connection.settimeout(20)
        parsed = urllib.parse.urlparse(self.path)
        note_ui(parsed.path)
        if parsed.path == "/api/image":
            self._proxy_image(parsed.query)
            return
        if parsed.path == "/api/stream":
            self.connection.settimeout(120)
            self._proxy_stream(parsed.query)
            return
        if parsed.path == "/api/download-file":
            _download_library.serve(self, parsed.query)
            return
        if parsed.path == "/api/media/file":
            _library_media.serve(self, parsed.query)
            return
        if parsed.path in ("/api/group-logo", "/api/brand-image", "/api/star-cover", "/api/cam-play"):
            Handler.do_GET(self)
            return
        self._send(404, "Nicht gefunden")

    def do_HEAD(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/download-file":
            _download_library.serve(self, parsed.query, head=True)
            return
        if parsed.path == "/api/media/file":
            _library_media.serve(self, parsed.query, head=True)
            return
        self._send(405, "Nicht unterstützt")

    def do_POST(self):
        self._send(404, "Nicht gefunden")


def _peek_lane(request):
    """Keep bootstrap assets and small navigation reads independent of slow media."""
    from time import monotonic, sleep
    chunk = b""
    deadline = monotonic() + 0.05
    try:
        request.settimeout(0.05)
        while monotonic() < deadline:
            chunk = request.recv(1024, socket.MSG_PEEK)
            if not chunk or len(chunk.split(b" ", 2)) >= 3:
                break
            # TCP can deliver the method before the path. Do not classify that
            # partial request as background work and reject valid navigation.
            sleep(0.001)
    except OSError:
        pass
    finally:
        try:
            request.settimeout(None)
        except OSError:
            pass
    line = chunk.split(b"\r\n", 1)[0] if chunk else b""
    parts = line.split(b" ")
    path = parts[1].split(b"?", 1)[0] if len(parts) > 1 else b""
    if path in (b"/api/restart", b"/api/health"): return "control"
    if path in (b"/", b"/index.html", b"/api/catalog", b"/api/ui", b"/api/prefs", b"/api/site") or path.startswith(b"/static/"):
        return "interactive"
    return "normal"


def _listen_ports():
    return [PORT, MEDIA_PORT] + list(MULTI_PORTS)


def _ports_free(ports):
    held = []
    try:
        for port in ports:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                sock.close()
                return False
            held.append(sock)
        return True
    finally:
        for sock in held:
            try:
                sock.close()
            except OSError:
                pass


def _wait_until_ports_free(ports, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if _ports_free(ports):
            return True
        time.sleep(0.2)
    return False


_restart_lock = threading.Lock()
_restart_started = False


def schedule_restart():
    global _restart_started
    with _restart_lock:
        if _restart_started:
            return {"ok": True, "pid": os.getpid(), "already": True}
        _restart_started = True
    threading.Thread(target=_restart_process, name="ah-restart", daemon=True).start()
    return {"ok": True, "pid": os.getpid()}


def _restart_process():
    time.sleep(0.35)
    try:
        with _tube_lock:
            for job in _tube_jobs.values():
                job["stop"] = True
    except Exception:
        pass
    if _cam_library_sync_service is not None:
        _cam_library_sync_service.stop.set()
        _cam_library_save(True)
    if _star_store is not None:
        with _star_extra_lock:
            _star_extra_save(force=True)
    debug_log("server", "neustart", "prozess", {"pid": os.getpid()})
    args = [sys.executable, os.path.join(ROOT, "portable_entry.py"), "--no-browser", "--wait-free"]
    kwargs = {
        "cwd": ROOT,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(args, **kwargs)
    except OSError as exc:
        debug_log("server", "neustart", "fehler", {"err": str(exc)[:200]})
        return
    os._exit(0)


class BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler, workers):
        super().__init__(address, handler)
        self._workers = threading.BoundedSemaphore(workers)
        self._control = threading.BoundedSemaphore(2)
        self._interactive = threading.BoundedSemaphore(8)

    def process_request(self, request, client_address):
        lane = _peek_lane(request)
        gate = self._control if lane == "control" else self._interactive if lane == "interactive" else self._workers
        acquired = gate.acquire(blocking=False)
        if not acquired and lane == "interactive":
            gate = self._workers
            acquired = gate.acquire(blocking=False)
        if not acquired:
            try:
                request.settimeout(0.2)
                request.sendall(b"HTTP/1.0 429 Busy\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            except Exception:
                pass
            try:
                request.close()
            except Exception:
                pass
            return
        thread = threading.Thread(target=self._run, args=(request, client_address, gate), daemon=True)
        thread.start()

    def _run(self, request, client_address, gate):
        try:
            self.finish_request(request, client_address)
            self.shutdown_request(request)
        except Exception:
            self.handle_error(request, client_address)
            try:
                self.shutdown_request(request)
            except Exception:
                pass
        finally:
            gate.release()


def main():
    if not os.path.isfile(os.path.join(ADDON, "default.py")):
        print("Addon nicht gefunden:", ADDON)
        return 1
    if "--wait-free" in sys.argv and not _wait_until_ports_free(_listen_ports(), 12):
        debug_log("server", "neustart", "ports belegt")
        print("Ports belegt")
        return 1
    addon_main()
    enable_library_menus()
    ThreadingHTTPServer.allow_reuse_address = False
    media_ports = [MEDIA_PORT] + MULTI_PORTS
    for media_port in media_ports:
        media = BoundedHTTPServer(("127.0.0.1", media_port), MediaHandler, 24)
        threading.Thread(target=media.serve_forever, name="AHMedia-%s" % media_port, daemon=True).start()
    api = BoundedHTTPServer(("127.0.0.1", PORT), Handler, 16)
    url = "http://127.0.0.1:%s/" % PORT
    print("Adult Client by emberhost:", url)
    print("Medien:", " ".join("http://127.0.0.1:%s/" % media_port for media_port in media_ports))
    debug_log("server", "start", url, {"media": media_ports})
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)
    threading.Thread(target=_extra_flush_loop, name="star-extra-flush", daemon=True).start()
    star_lang_batch_start()
    av_sync_start()
    babe_sync_start()
    _star_service().boxes.start()
    _star_service().library.start()
    try:
        api.serve_forever()
    finally:
        if _cam_library_sync_service is not None:
            _cam_library_sync_service.close()


if __name__ == "__main__":
    raise SystemExit(main() or 0)
