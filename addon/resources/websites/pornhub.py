#!/usr/bin/env python

import os
import re
import sys
import json
import html
import time
import urllib.parse
import urllib.request
import urllib.error
from http.cookiejar import CookieJar

import requests

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin

from resources.lib.base_website import BaseWebsite
from resources.lib.lookup_info import choose_and_open, extract_html_items

class PornhubWebsite(BaseWebsite):
    supports_uploader_lookup = True
    uploader_lookup_patterns = ((
        r'videoUploaderBlock[\s\S]{0,800}?usernameWrap[\s\S]{0,300}?<a[^>]+href="([^"]+)"[^>]*>([^<]+)',
        1,
        2,
    ),)
    config = {
        "name": "pornhub",
        "base_url": "https://www.pornhub.com",
        "api_base": "https://www.pornhub.com/webmasters",
    }

    def __init__(self, addon_handle):
        super().__init__(
            name=self.config["name"],
            base_url=self.config["base_url"],
            search_url="https://www.pornhub.com/video/search?search={}",
            addon_handle=addon_handle
        )
        
        self.label = 'Pornhub'
        self.cookie_jar = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )
        urllib.request.install_opener(self.opener)
        self._set_age_cookie()
        self.playlist_session = requests.Session()
        self.playlist_session.headers.update(self.get_headers(self.base_url + '/playlists'))
        self.playlist_session.cookies.update({
            'age_verified': '1',
            'accessAgeDisclaimerPH': '1',
            'accessAgeDisclaimerUK': '1',
            'accessPH': '1',
            'platform': 'pc',
        })

        self.sorting_options = ["Newest", "Most Viewed", "Top Rated"]
        self.sorting_paths = {
            "Newest": "newest",
            "Most Viewed": "mostviewed",
            "Top Rated": "rating"
        }
        
        self.period_options = ["All Time", "This Month", "This Week"]
        self.period_paths = {"All Time": "alltime", "This Month": "monthly", "This Week": "weekly"}
        
        self.pornstar_sort_options = ["Most Popular", "Most Viewed", "Top Trending", "Most Subscribed", "Alphabetical", "No. Of Videos", "Random"]
        self.pornstar_sort_paths = {
            "Most Popular": "", "Most Viewed": "mv", "Top Trending": "t", 
            "Most Subscribed": "ms", "Alphabetical": "a", "No. Of Videos": "nv", "Random": "r"
        }

    def get_start_url_and_label(self):
        addon = xbmcaddon.Addon()
        selected_sort_name = addon.getSetting('pornhub_sort_by') or "Newest"
        sort_param = self.sorting_paths.get(selected_sort_name, 'newest')
        start_url = f"{self.base_url}/video?o={sort_param}"
        label = f"{self.label} [COLOR yellow]{selected_sort_name}[/COLOR]"
        return start_url, label

    def _set_age_cookie(self):
        for name, value in (
            ('age_verified', '1'),
            ('accessAgeDisclaimerPH', '1'),
            ('accessAgeDisclaimerUK', '1'),
            ('accessPH', '1'),
            ('platform', 'pc'),
        ):
            self.cookie_jar.set_cookie(self._create_cookie(name, value, '.pornhub.com'))

    def _extract_flashvars(self, content):
        """Extract Pornhub's flashvars object with brace balancing."""
        for marker in (r'var\s+flashvars_\d+\s*=', r'var\s+flashvars\s*=', r'flashvars\s*='):
            for match in re.finditer(marker, content, re.DOTALL):
                start = content.find('{', match.end())
                if start == -1:
                    continue

                depth = 0
                quote = None
                escape = False
                for idx in range(start, len(content)):
                    ch = content[idx]
                    if escape:
                        escape = False
                        continue
                    if ch == '\\':
                        escape = True
                        continue
                    if quote:
                        if ch == quote:
                            quote = None
                        continue
                    if ch in ('"', "'"):
                        quote = ch
                        continue
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            raw = content[start:idx + 1]
                            try:
                                data = json.loads(raw)
                                if data and data.get('mediaDefinitions'):
                                    self.logger.info(f"Pornhub: Successfully extracted flashvars with marker: {marker}")
                                    return data
                            except Exception as exc:
                                self.logger.warning(f"Pornhub: flashvars JSON parse failed: {exc}")
                            break
        return None

    def _warmup_session(self, referer=None):
        try:
            self._set_age_cookie()
            req = urllib.request.Request(
                self.base_url,
                headers=self.get_headers(referer or self.base_url)
            )
            with self.opener.open(req, timeout=8) as resp:
                resp.read(2048)
            return True
        except Exception as exc:
            self.logger.warning(f"Pornhub: session warmup failed: {exc}")
            return False

    def _prime_stream_url(self, stream_url, referer, headers, attempts=3):
        """Prime DNS/CDN access before handing the HLS URL to Kodi."""
        clean_url = stream_url.split("|", 1)[0]
        request_headers = {
            "User-Agent": headers.get("User-Agent", self.get_headers().get("User-Agent")),
            "Referer": headers.get("Referer", referer),
            "Origin": headers.get("Origin", self.base_url.rstrip("/")),
        }
        cookie = headers.get("Cookie")
        if cookie:
            request_headers["Cookie"] = cookie

        for attempt in range(attempts):
            try:
                req = urllib.request.Request(clean_url, headers=request_headers)
                with self.opener.open(req, timeout=8) as resp:
                    sample = resp.read(512)
                if sample:
                    return True
            except Exception as exc:
                self.logger.warning(
                    f"Pornhub: stream preflight failed on attempt {attempt + 1}: {exc}"
                )
                time.sleep(0.5 * (attempt + 1))
        return False

    def _create_cookie(self, name, value, domain):
        from http.cookiejar import Cookie
        return Cookie(
            version=0, name=name, value=value, port=None, port_specified=False,
            domain=domain, domain_specified=True, domain_initial_dot=domain.startswith('.'),
            path='/', path_specified=True, secure=False, expires=None, discard=True,
            comment=None, comment_url=None, rest={'HttpOnly': None}, rfc2109=False
        )

    def get_headers(self, referer=None):
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7',
        }
        if referer: headers['Referer'] = referer
        return headers

    def make_request(self, url, referer=None, is_api=False):
        last_error = None
        for attempt in range(3):
            try:
                if attempt:
                    time.sleep(0.8 * attempt)
                    self._set_age_cookie()

                headers = self.get_headers(referer)
                if is_api:
                    headers['Accept'] = 'application/json, text/plain, */*'
                    headers['X-Requested-With'] = 'XMLHttpRequest'
                
                req = urllib.request.Request(url, headers=headers)
                with self.opener.open(req, timeout=15) as resp:
                    return resp.read().decode('utf-8', errors='ignore')
            except urllib.error.HTTPError as e:
                last_error = e
                self.logger.warning(f"Pornhub request failed for {url} on attempt {attempt + 1}: HTTP {e.code}")
                if e.code not in (403, 429, 503):
                    break
            except Exception as e:
                last_error = e
                self.logger.warning(f"Pornhub request failed for {url} on attempt {attempt + 1}: {e}")
                break

        if last_error:
            self.logger.warning(f"Pornhub request exhausted for {url}: {last_error}")
        if hasattr(self, 'notify_error'):
            self.notify_error("Failed to load data.")
        return None
    
    def process_content(self, url):
        params = {}
        if len(sys.argv) > 2 and sys.argv[2]:
            params = dict(urllib.parse.parse_qsl(sys.argv[2][1:]))
        action = params.get('action')
        if action == "show_related":
            self.process_related_videos(url)
            return

        if not url or url == "BOOTSTRAP": url = self.base_url

        parsed_url = urllib.parse.urlparse(url)
        path = parsed_url.path

        if path.rstrip('/') == '/playlists':
            self.process_public_playlists(url)
        elif re.match(r'^/playlist/\d+/?$', path):
            self.process_public_playlist(url)
        elif '/pornstar/' in path or '/model/' in path or '/channels/' in path or '/channel/' in path or '/users/' in path:
            self._list_profile_videos(url)
        elif '/pornstars' in path:
            self.process_pornstars(url)
        elif '/categories' in path:
            self.process_categories()
        else:
            if hasattr(self, 'add_dir'):
                self.add_dir('[COLOR blue]Search[/COLOR]', '', 5, self.icons['search'], name_param=self.name)
                self.add_dir('Categories', f"{self.base_url}/categories", 2, self.icons['categories'])
                self.add_dir(self.addon.getLocalizedString(30963) or 'Public Playlists', f"{self.base_url}/playlists", 2, self.icons['default'])
                
                pornstars_url = f"{self.base_url}/pornstars"
                self.add_dir(
                    'Pornstars', 
                    pornstars_url, 
                    2, 
                    self.icons['pornstars'], 
                    context_menu=[
                        ('Sort by', f'RunPlugin({sys.argv[0]}?mode=7&action=select_pornstar_sort&website={self.name}&original_url={urllib.parse.quote_plus(pornstars_url)})')
                    ]
                )
            
            self.process_video_list(url)

        if hasattr(self, 'end_directory'):
            self.end_directory()

    def _thumb_with_headers(self, thumb, referer=None):
        thumb = html.unescape(thumb or '').replace('\\/', '/')
        if not thumb or thumb.startswith('data:'):
            return self.icon
        if thumb.startswith('//'):
            thumb = 'https:' + thumb
        if '|' not in thumb:
            thumb += '|User-Agent={}&Referer={}'.format(
                urllib.parse.quote(self.get_headers().get('User-Agent', 'Mozilla/5.0')),
                urllib.parse.quote(referer or (self.base_url + '/')),
            )
        return thumb

    def _playlist_cards(self, content):
        cards = []
        seen = set()
        pattern = r'<li\s+id="playlist_(\d+)"\s+class="full-width">(.*?)(?=<li\s+id="playlist_|</ul>)'
        for match in re.finditer(pattern, content or '', re.IGNORECASE | re.DOTALL):
            playlist_id, block = match.group(1), match.group(2)
            if playlist_id in seen:
                continue
            title_match = re.search(
                r'data-label="playlist_title"[\s\S]{0,300}?title="([^"]+)"', block, re.IGNORECASE
            )
            if not title_match:
                continue
            thumb_match = re.search(r'<img[^>]+(?:data-image|data-src|data-thumb_url)="(https?://[^"]+)"', block, re.IGNORECASE)
            count_match = re.search(r'<span\s+class="number"><span>([^<]+)</span>\s*videos', block, re.IGNORECASE)
            uploader_match = re.search(r'class="usernameLink"[^>]*>([^<]+)</a>', block, re.IGNORECASE)
            seen.add(playlist_id)
            cards.append({
                'id': playlist_id,
                'title': html.unescape(title_match.group(1)).strip(),
                'thumb': html.unescape(thumb_match.group(1)) if thumb_match else self.icon,
                'count': html.unescape(count_match.group(1)).strip() if count_match else '',
                'uploader': html.unescape(uploader_match.group(1)).strip() if uploader_match else '',
            })
        return cards

    def _playlist_request(self, url, referer=None, ajax=False):
        headers = self.get_headers(referer or (self.base_url + '/playlists'))
        if ajax:
            headers['Accept'] = 'application/json, text/plain, */*'
            headers['X-Requested-With'] = 'XMLHttpRequest'
        candidates = [url]
        parsed = urllib.parse.urlparse(url)
        if parsed.netloc == 'www.pornhub.com':
            candidates.append(parsed._replace(netloc='www.pornhub.org').geturl())
        for candidate in candidates:
            try:
                response = self.playlist_session.get(candidate, headers=headers, timeout=15)
                if response.status_code == 200 and response.text:
                    return response.text
                self.logger.warning('Pornhub playlist HTTP %s for %s', response.status_code, candidate)
            except requests.RequestException as exc:
                self.logger.warning('Pornhub playlist request failed for %s: %s', candidate, exc)
        return ''

    def process_public_playlists(self, url):
        content = self._playlist_request(url, referer=self.base_url + '/playlists')
        if not content:
            return
        cards = self._playlist_cards(content)
        for card in cards:
            label = card['title']
            if card['count']:
                label += ' [COLOR lime]({} videos)[/COLOR]'.format(card['count'])
            playlist_url = '{}/playlist/{}'.format(self.base_url, card['id'])
            plot = 'Public PornHub playlist'
            if card['uploader']:
                plot += '\nCreated by: {}'.format(card['uploader'])
            self.add_dir(
                label, playlist_url, 2,
                self._thumb_with_headers(card['thumb'], url), self.fanart,
                info_labels={'title': card['title'], 'plot': plot},
            )
        next_match = re.search(r'<link\s+rel="next"\s+href="([^"]+)"', content, re.IGNORECASE)
        if not next_match:
            next_match = re.search(r'<li\s+class="page_next">[\s\S]*?<a[^>]+href="([^"]+)"', content, re.IGNORECASE)
        if next_match:
            self.add_dir('[COLOR blue]Next Page >>>>[/COLOR]', urllib.parse.urljoin(url, html.unescape(next_match.group(1))), 2, self.icons['default'])

    def _playlist_page_data(self, playlist_url):
        parsed = urllib.parse.urlparse(playlist_url)
        params = urllib.parse.parse_qs(parsed.query)
        try:
            page = max(1, int(params.get('page', ['1'])[0]))
        except (ValueError, TypeError):
            page = 1
        clean_url = parsed._replace(query='').geturl()
        content = self._playlist_request(clean_url, referer=self.base_url + '/playlists')
        if not content:
            return '', [], 0
        meta_match = re.search(r'PLAYLIST_VIEW\s*=\s*(\{.*?\})\s*;', content, re.DOTALL)
        meta = {}
        if meta_match:
            try:
                meta = json.loads(meta_match.group(1))
            except (ValueError, TypeError):
                pass
        total = int(meta.get('video_count') or 0)
        title = html.unescape(str(meta.get('title') or 'Public Playlist'))
        page_content = content
        if page > 1:
            lazy_match = re.search(r'lazyloadUrl\s*=\s*"([^"]+)"', content)
            if not lazy_match:
                return title, [], total
            chunk_url = urllib.parse.urljoin(clean_url, html.unescape(lazy_match.group(1)))
            separator = '&' if '?' in chunk_url else '?'
            page_content = self._playlist_request(chunk_url + separator + 'page={}'.format(page), referer=clean_url, ajax=True)
        else:
            list_match = re.search(r'<ul[^>]+id="videoPlaylist"[^>]*>(.*?)</ul>', content, re.IGNORECASE | re.DOTALL)
            page_content = list_match.group(1) if list_match else ''
        return title, self._playlist_video_cards(page_content, clean_url), total

    def _playlist_video_cards(self, content, referer):
        videos = []
        seen = set()
        chunks = re.split(r'(?=<li\b[^>]*class="[^"]*videoBox)', content or '', flags=re.IGNORECASE)
        for block in chunks:
            key_match = re.search(r'data-video-vkey="([^"]+)"', block, re.IGNORECASE)
            if not key_match:
                key_match = re.search(r'href="[^"]*viewkey=([^"&]+)', block, re.IGNORECASE)
            if not key_match or key_match.group(1) in seen:
                continue
            viewkey = html.unescape(key_match.group(1))
            title_match = re.search(r'href="[^"]*viewkey=[^"]+"\s+title="([^"]+)"', block, re.IGNORECASE)
            thumb_match = re.search(r'<img[^>]+(?:data-image|data-src|data-thumb_url)="(https?://[^"]+)"', block, re.IGNORECASE)
            duration_match = re.search(r'<var\s+class="duration">([^<]+)</var>', block, re.IGNORECASE)
            if not title_match:
                continue
            seen.add(viewkey)
            videos.append({
                'viewkey': viewkey,
                'title': html.unescape(title_match.group(1)).strip(),
                'thumb': self._thumb_with_headers(thumb_match.group(1) if thumb_match else '', referer),
                'duration': duration_match.group(1).strip() if duration_match else '',
            })
        return videos

    def process_public_playlist(self, url):
        title, videos, total = self._playlist_page_data(url)
        if not videos:
            self.notify_error(self.addon.getLocalizedString(30965) or 'No public playlist videos found')
            return
        play_label = self.addon.getLocalizedString(30964) or 'Play this playlist page'
        self.add_dir('[COLOR green]{}[/COLOR]'.format(play_label), url, 7, self.icons['default'], action='play_public_playlist')
        for video in videos:
            label = video['title']
            if video['duration']:
                label += ' [COLOR lime]({})[/COLOR]'.format(video['duration'])
            video_url = '{}/view_video.php?viewkey={}'.format(self.base_url, video['viewkey'])
            self.add_link(label, video_url, 4, video['thumb'], self.fanart,
                          info_labels={'title': video['title'], 'duration': video['duration'], 'plot': title})
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        page = max(1, int(params.get('page', ['1'])[0]))
        page_size = 36 if page == 1 else 40
        consumed = 36 + max(0, page - 1) * 40
        if len(videos) >= page_size and (not total or consumed < total):
            params['page'] = [str(page + 1)]
            next_url = parsed._replace(query=urllib.parse.urlencode(params, doseq=True)).geturl()
            self.add_dir('[COLOR blue]Next Page >>>>[/COLOR]', next_url, 2, self.icons['default'])

    def play_public_playlist(self, original_url=None):
        _title, videos, _total = self._playlist_page_data(original_url or '')
        if not videos:
            self.notify_error(self.addon.getLocalizedString(30965) or 'No public playlist videos found')
            return
        playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
        playlist.clear()
        for video in videos:
            target = '{}?mode=4&website={}&url={}&name={}&thumbnail={}'.format(
                sys.argv[0], self.name,
                urllib.parse.quote_plus('{}/view_video.php?viewkey={}'.format(self.base_url, video['viewkey'])),
                urllib.parse.quote_plus(video['title']),
                urllib.parse.quote_plus(video['thumb']),
            )
            item = xbmcgui.ListItem(video['title'])
            item.setArt({'thumb': video['thumb'], 'icon': video['thumb'], 'fanart': self.fanart})
            item.setProperty('IsPlayable', 'true')
            playlist.add(target, item)
        xbmc.Player().play(playlist)

    def _profile_owner(self, html_content, url):
        parsed = urllib.parse.urlparse(url)
        path = re.sub(r"/videos.*$", "", parsed.path).rstrip("/")
        owner_url = urllib.parse.urlunparse(parsed._replace(path=path or "/", query="", fragment=""))
        title = ""
        head = (html_content or "")[:30000]
        match = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', head, re.I)
        if not match:
            match = re.search(r'<meta[^>]+content="([^"]+)"[^>]+property="og:title"', head, re.I)
        if not match:
            match = re.search(r"<title>([^<]{2,140})</title>", head, re.I)
        if match:
            title = html.unescape(match.group(1))
            title = re.split(r"\s+channel\b|\s+on Pornhub", title, flags=re.I)[0].strip()
        if not title:
            title = path.rstrip("/").split("/")[-1].replace("-", " ")
        return title, owner_url

    def _profile_block(self, page):
        for marker in (
            'id="showAllChanelVideos"',
            'id="videosTab"',
            'id="pornstarVideos"',
            'id="moreData"',
            'class="videos row-5-thumbs',
        ):
            start = page.find(marker)
            if start < 0:
                continue
            end = page.find('class="pagination', start)
            if end < 0:
                end = page.find("relatedChannels", start)
            if end < 0:
                end = start + 500000
            return page[start:end]
        return ""

    def _profile_cards(self, block):
        cards = []
        seen = set()
        for chunk in (block or "").split("<li ")[1:]:
            key_match = re.search(r'data-video-vkey="([a-z0-9]+)"', chunk[:1200], re.I)
            if not key_match:
                key_match = re.search(r'viewkey=([a-z0-9]+)', chunk[:1200], re.I)
            if not key_match or key_match.group(1) in seen:
                continue
            viewkey = key_match.group(1)
            title = ""
            for anchor in re.findall(r"<a\b[^>]*>", chunk[:6000], re.I):
                if viewkey not in anchor:
                    continue
                title_match = re.search(r'title="([^"]+)"', anchor)
                if title_match:
                    title = html.unescape(title_match.group(1)).strip()
                    break
            if not title or title.lower() in ("verified", "hd", "premium"):
                alt_match = re.search(r'alt="([^"]{3,180})"', chunk[:8000], re.I)
                if alt_match:
                    title = html.unescape(alt_match.group(1)).strip()
            if not title or title.lower() in ("verified", "hd", "premium"):
                continue
            seen.add(viewkey)
            clip_match = re.search(r'data-mediabook="(https?://[^"]+)"', chunk[:8000], re.I)
            thumb_match = re.search(r'(?:data-mediumthumb|data-thumb_url|data-image)="(https?://[^"]+)"', chunk[:8000], re.I)
            duration_match = re.search(r'class="duration">([^<]+)', chunk[:8000], re.I)
            user_match = re.search(
                r'href="([^"]*(?:/channels/|/channel/|/model/|/pornstar/|/users/)[^"#]*)"[^>]*>([^<]{2,80})</a>',
                chunk[:8000], re.I,
            )
            cards.append({
                "viewkey": viewkey,
                "title": title,
                "clip": html.unescape(clip_match.group(1)) if clip_match else "",
                "thumb": html.unescape(thumb_match.group(1)) if thumb_match else "",
                "duration": duration_match.group(1).strip() if duration_match else "",
                "uploader": html.unescape(user_match.group(2)).strip() if user_match else "",
                "uploader_url": urllib.parse.urljoin(self.base_url + "/", html.unescape(user_match.group(1))) if user_match else "",
            })
        return cards

    def _best_video_block(self, page):
        best = ""
        best_count = 0
        for marker in (
            'id="videoCategory"',
            'id="videoSearchResult"',
            'id="showAllChanelVideos"',
            'id="videosTab"',
            'id="pornstarVideos"',
            'id="moreData"',
            'class="videos search-video-thumbs',
            'class="videos row-5-thumbs',
            'class="videoUList',
        ):
            start = 0
            while True:
                start = (page or "").find(marker, start)
                if start < 0:
                    break
                end = page.find('class="pagination', start)
                if end < 0:
                    end = start + 500000
                block = page[start:end]
                count = block.count("data-mediabook")
                if count > best_count:
                    best = block
                    best_count = count
                start += len(marker)
        return best

    def _category_ids(self):
        shared = getattr(PornhubWebsite, "_shared_cat_ids", None)
        if shared:
            return shared
        path = os.path.join(os.environ.get("AH_PROFILE") or "", "cache", "pornhub_category_ids.json")
        try:
            if path and os.path.isfile(path) and time.time() - os.path.getmtime(path) < 7 * 86400:
                stored = json.load(open(path, encoding="utf-8"))
                if isinstance(stored, dict) and stored:
                    PornhubWebsite._shared_cat_ids = stored
                    return stored
        except (OSError, ValueError):
            pass
        page = self.make_request(self.base_url + "/categories", referer=self.base_url) or ""
        ids = {}
        for match in re.finditer(r'href="/video\?c=(\d+)[^"]*"[\s\S]{0,400}?alt="([^"]+)"', page, re.I):
            slug = html.unescape(match.group(2)).strip().lower().replace(" ", "-")
            ids.setdefault(slug, match.group(1))
        if ids:
            PornhubWebsite._shared_cat_ids = ids
            try:
                if path:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "w", encoding="utf-8") as handle:
                        json.dump(ids, handle, ensure_ascii=False)
            except OSError:
                pass
        return ids

    def _listing_page_url(self, current_url):
        html_order = {"newest": "mr", "mostviewed": "mv", "rating": "tr"}
        parsed = urllib.parse.urlparse(current_url)
        params = urllib.parse.parse_qs(parsed.query)
        order = params.get("o", [""])[0]
        page = params.get("page", [""])[0]
        query = {}
        if order in html_order:
            query["o"] = html_order[order]
        elif order in ("mr", "mv", "tr", "ht"):
            query["o"] = order
        if page and page != "1":
            query["page"] = page
        cid_param = (params.get("c") or [""])[0]
        if str(cid_param).isdigit():
            query["c"] = cid_param
            return self.base_url + "/video?" + urllib.parse.urlencode(query)
        slug = (params.get("category_slug") or params.get("category") or [""])[0].lower()
        if slug:
            cid = self._category_ids().get(slug)
            if not cid:
                return ""
            query["c"] = cid
            return self.base_url + "/video?" + urllib.parse.urlencode(query)
        if parsed.path.rstrip("/") in ("", "/video"):
            tail = ("?" + urllib.parse.urlencode(query)) if query else ""
            return self.base_url + "/video" + tail
        if order in html_order:
            params["o"] = [html_order[order]]
            return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(params, doseq=True)))
        return current_url

    def _emit_html_cards(self, cards, page_url, page):
        referer = self.base_url + "/"
        for card in cards:
            title = card["title"]
            label = title
            if card.get("duration"):
                label += " [COLOR lime](%s)[/COLOR]" % card["duration"]
            video_url = "{}/view_video.php?viewkey={}".format(self.base_url, card["viewkey"])
            thumb = card.get("thumb") or ""
            self.add_link(
                label, video_url, 4,
                self._thumb_with_headers(thumb) if thumb else self.icon,
                self.fanart,
                info_labels={"plot": title},
                uploader_name=card.get("uploader") or None,
                uploader_url=card.get("uploader_url") or None,
                preview=[thumb] if thumb else None,
                clip=card.get("clip") or None,
                referer=referer,
            )
        next_match = re.search(r'class="page_next"[\s\S]{0,800}?href="([^"]+)"', page or "", re.I)
        if not next_match:
            next_match = re.search(r'rel="next"[^>]*href="([^"]+)"', page or "", re.I)
        if next_match and hasattr(self, "add_dir"):
            next_url = urllib.parse.urljoin(page_url, html.unescape(next_match.group(1)))
            self.add_dir("[COLOR blue]Next Page >>>>[/COLOR]", next_url, 2, self.icons["default"])

    def _mediabooks(self, page_url):
        page = self.make_request(page_url, referer=self.base_url) or ""
        return {card["viewkey"]: card["clip"] for card in self._profile_cards(page) if card.get("clip")}

    def _list_profile_videos(self, url):
        parsed = urllib.parse.urlparse(url)
        candidates = [url]
        if not re.search(r"/(videos|uploads)/?$", parsed.path):
            candidates.insert(0, parsed._replace(path=parsed.path.rstrip("/") + "/videos").geturl())
        page = ""
        block = ""
        for candidate in candidates:
            page = self.make_request(candidate, referer=self.base_url) or ""
            block = self._profile_block(page)
            if block and "viewkey" in block:
                url = candidate
                break
        cards = self._profile_cards(block)
        if not cards:
            return False
        owner_name, owner_url = self._profile_owner(page, url)
        slug = owner_url.rstrip("/").split("/")[-1].replace("-", "").lower()
        names = []
        for card in cards:
            prefix = re.split(r"\s[-–]\s", card["title"], maxsplit=1)[0].strip()
            if prefix and prefix.lower().replace(" ", "") == slug and " " in prefix:
                names.append(prefix)
        display_owner = max(set(names), key=names.count) if names else owner_name
        total_match = re.search(r">([\d][\d,\.]*)\s*<br\s*/?>\s*<span>\s*VIDEOS\s*</span>", page, re.I)
        if total_match:
            xbmcplugin.setPluginCategory(self.addon_handle, "%s Videos im Kanal" % total_match.group(1))
        referer = self.base_url + "/"
        for card in cards:
            title = card["title"]
            label = title
            if card["duration"]:
                label += " [COLOR lime](%s)[/COLOR]" % card["duration"]
            video_url = "{}/view_video.php?viewkey={}".format(self.base_url, card["viewkey"])
            thumb = card["thumb"] or self.icon
            self.add_link(
                label, video_url, 4, self._thumb_with_headers(thumb), self.fanart,
                info_labels={"plot": title},
                uploader_name=display_owner,
                uploader_url=owner_url,
                preview=[thumb] if card["thumb"] else None,
                clip=card["clip"] or None,
                referer=referer,
            )
        next_match = re.search(r'class="page_next"[\s\S]{0,400}?href="([^"]+)"', page, re.I)
        if next_match and hasattr(self, "add_dir"):
            next_url = urllib.parse.urljoin(url, html.unescape(next_match.group(1)))
            if urllib.parse.urlparse(next_url).path.rstrip("/") == urllib.parse.urlparse(url).path.rstrip("/"):
                self.add_dir("[COLOR blue]Next Page >>>>[/COLOR]", next_url, 2, self.icons["default"])
        return True

    def process_video_list(self, current_url):
        list_url = self._listing_page_url(current_url)
        html_page = ""
        html_cards = []
        if list_url:
            try:
                html_page = self.make_request(list_url, referer=self.base_url) or ""
                block = self._best_video_block(html_page) or self._profile_block(html_page) or html_page
                html_cards = self._profile_cards(block)
            except Exception:
                html_cards = []
        clipped = [card for card in html_cards if card.get("clip")]
        if len(clipped) >= 8 and hasattr(self, "add_link"):
            self._emit_html_cards(html_cards, list_url, html_page)
            return
        parsed = urllib.parse.urlparse(current_url)
        params = urllib.parse.parse_qs(parsed.query)
        api_params = {'page': params.get('page', ['1'])[0]}
        
        if '/pornstar/' in parsed.path:
            pornstar_name = parsed.path.split('/pornstar/')[-1].split('/')[0]
            api_params['search'] = pornstar_name.replace('-', ' ')
        elif '/model/' in parsed.path:
            model_name = parsed.path.split('/model/')[-1].split('/')[0]
            api_params['search'] = model_name.replace('-', ' ')
        elif 'search' in params:
            api_params['search'] = params['search'][0]
        elif 'category' in params:
            api_params['category'] = params['category'][0]
        elif 'category_slug' in params:
            api_params['category'] = params['category_slug'][0]
        
        api_params['ordering'] = params.get('o', [self.sorting_paths['Newest']])[0]
        
        if api_params['ordering'] in ['mostviewed', 'rating']:
            api_params['period'] = params.get('p', ['alltime'])[0]
        
        api_url = f"{self.config['api_base']}/search?{urllib.parse.urlencode(api_params, doseq=True)}"
        content = self.make_request(api_url, referer=current_url, is_api=True)
        if not content: return

        try: data = json.loads(content)
        except json.JSONDecodeError: return

        videos = data.get('videos', [])
        books = {card["viewkey"]: card["clip"] for card in html_cards if card.get("clip")}
        
        context_menu = [
            ('Sort by', f'RunPlugin({sys.argv[0]}?mode=7&action=select_sort&website={self.name}&original_url={urllib.parse.quote_plus(current_url)})'),
            ('Select Period', f'RunPlugin({sys.argv[0]}?mode=7&action=select_period&website={self.name}&original_url={urllib.parse.quote_plus(current_url)})')
        ]
        
        for vid in videos:
            title = html.unescape(vid.get('title', ''))
            vid_id, thumb, duration = vid.get('video_id'), vid.get('default_thumb'), vid.get('duration')
            if all((title, vid_id, thumb, duration)) and hasattr(self, 'add_link'):
                if thumb:
                    thumb = thumb.replace("&amp;", "&")
                    if "|" not in thumb:
                        thumb += "|User-Agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0.0.0&Referer=https://www.pornhub.com/"
                
                video_url = f"{self.base_url}/view_video.php?viewkey={vid_id}"
                video_context_menu = [
                    ('Explore similar', f'RunPlugin({sys.argv[0]}?mode=7&action=explore_similar&website={self.name}&original_url={urllib.parse.quote_plus(video_url)})')
                ] + context_menu

                label = f"{title} [COLOR lime]({duration})[/COLOR]"
                frames = []
                for entry in (vid.get("thumbs") or []):
                    src = entry.get("src") if isinstance(entry, dict) else ""
                    if src:
                        frames.append(html.unescape(src).replace("\\/", "/"))
                details = []
                if duration:
                    details.append(str(duration))
                if vid.get("views"):
                    details.append("%s Aufrufe" % vid.get("views"))
                if vid.get("rating"):
                    try:
                        details.append("%s%%" % int(round(float(vid.get("rating")))))
                    except (TypeError, ValueError):
                        details.append("%s%%" % vid.get("rating"))
                if vid.get("publish_date"):
                    details.append(str(vid.get("publish_date"))[:10])
                stars = [entry.get("pornstar_name") for entry in (vid.get("pornstars") or []) if isinstance(entry, dict) and entry.get("pornstar_name")]
                uploader_name = stars[0] if stars else ""
                uploader_url = ""
                if uploader_name:
                    uploader_url = self.base_url + "/pornstar/" + urllib.parse.quote(uploader_name.lower().replace(" ", "-"))
                self.add_link(
                    label, video_url, 4, thumb, self.fanart, video_context_menu,
                    info_labels={"plot": " · ".join(details)},
                    preview=frames,
                    clip=books.get(str(vid_id)) or None,
                    referer=self.base_url + "/",
                    uploader_name=uploader_name,
                    uploader_url=uploader_url,
                )

        if len(videos) > 0 and hasattr(self, 'add_dir'):
            next_params = params.copy()
            current_page = int(api_params.get('page', '1'))
            next_params['page'] = [str(current_page + 1)]
            next_url = parsed._replace(query=urllib.parse.urlencode(next_params, doseq=True)).geturl()
            self.add_dir('[COLOR blue]Next Page >>>>[/COLOR]', next_url, 2, self.icons['default'])

    def process_categories(self):
        api_url = f"{self.config['api_base']}/categories"
        content = self.make_request(api_url, referer=self.config['base_url'], is_api=True)
        if not content: return
        
        try:
            data = json.loads(content)
            for cat in data.get('categories', []):
                name = cat.get('category')
                if name and hasattr(self, 'add_dir'):
                    slug = name.lower().replace(' ', '-')
                    kodi_url = f"{self.base_url}/video?category_slug={slug}"
                    self.add_dir(name, kodi_url, 2, self.icons['categories'])
        except json.JSONDecodeError:
            pass

    def process_pornstars(self, current_url):
        content = self.make_request(current_url, referer=self.base_url, is_api=False)
        if not content: return

        pornstar_context_menu = [
            ('Sort by', f'RunPlugin({sys.argv[0]}?mode=7&action=select_pornstar_sort&website={self.name}&original_url={urllib.parse.quote_plus(current_url)})')
        ]

        try:
            items = content.split('<li class="')
            for item in items[1:]:
                if 'performerCard' not in item: continue
                try:
                    url_part = item.split('<a href="')[1].split('"')[0]
                    full_url = urllib.parse.urljoin(self.base_url, html.unescape(url_part))
                    img_block = item.split('<img')[1]
                    thumb = html.unescape(img_block.split('data-thumb_url="')[1].split('"')[0])
                    if thumb:
                        thumb = thumb.replace("&amp;", "&")
                        if "|" not in thumb:
                            thumb += "|User-Agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0.0.0&Referer=https://www.pornhub.com/"
                            
                    name = html.unescape(img_block.split('alt="')[1].split('"')[0])
                    if hasattr(self, 'add_dir'):
                        self.add_dir(name, full_url, 2, thumb, self.fanart, context_menu=pornstar_context_menu)
                except IndexError:
                    continue
            
            if '<li class="page_next">' in content and hasattr(self, 'add_dir'):
                next_page_url_part = content.split('<li class="page_next">')[1].split('href="')[1].split('"')[0]
                next_page_url = urllib.parse.urljoin(self.base_url, html.unescape(next_page_url_part))
                self.add_dir('[COLOR blue]Next Page >>>>[/COLOR]', next_page_url, 2, self.icons['default'])
        except Exception:
            if hasattr(self, 'notify_error'): self.notify_error("An error occurred while parsing the page.")

    def _playback_candidates(self, media, referer, headers):
        found = []
        remote_mp4 = ""
        for stream in media or []:
            raw = stream.get("videoUrl") or ""
            if not isinstance(raw, str):
                continue
            stream_url = html.unescape(raw).replace("\\/", "/")
            if not stream_url.startswith("http"):
                continue
            fmt = (stream.get("format") or "").lower()
            if fmt == "mp4" and "get_media" in stream_url:
                remote_mp4 = stream_url
                continue
            if fmt != "hls":
                continue
            try:
                quality = int(str(stream.get("quality") or "0"))
            except (TypeError, ValueError):
                quality = 0
            found.append((quality, stream_url, "hls"))
        if remote_mp4:
            try:
                req = urllib.request.Request(remote_mp4, headers={
                    "User-Agent": headers.get("User-Agent") or self.get_headers().get("User-Agent"),
                    "Referer": referer,
                    "Origin": headers.get("Origin") or self.base_url.rstrip("/"),
                })
                with urllib.request.urlopen(req, timeout=8) as resp:
                    payload = json.loads(resp.read().decode("utf-8", "replace"))
                for item in payload if isinstance(payload, list) else []:
                    stream_url = item.get("videoUrl") or ""
                    if not str(stream_url).startswith("http"):
                        continue
                    try:
                        quality = int(item.get("quality") or item.get("height") or 0)
                    except (TypeError, ValueError):
                        quality = 0
                    found.append((quality, stream_url, "mp4"))
            except Exception as exc:
                self.logger.warning("Pornhub: get_media failed: %s", exc)
        found.sort(key=lambda item: (item[0], 1 if item[2] == "mp4" else 0))
        return found

    def _video_facts(self, html_content):
        page = html_content or ""
        start = page.find("video-detailed-info")
        chunk = page[start:start + 120000] if start >= 0 else ""
        for marker in ("relatedVideos", 'id="relatedVideos', "video-actions-tabs", "more-videos"):
            cut = chunk.find(marker)
            if cut > 800:
                chunk = chunk[:cut]
                break
        facts = {"views": "", "when": "", "about": "", "stars": [], "categories": [], "tags": []}
        rating_at = page.find('class="ratingInfo"')
        if rating_at >= 0:
            views_src = page[rating_at:rating_at + 700]
            views = re.search(r'class="count"[^>]*>([^<]+)', views_src)
            if views:
                facts["views"] = html.unescape(views.group(1)).strip()
            when = re.search(r'class="videoInfo"[^>]*>([^<]+)', views_src)
            if when:
                facts["when"] = html.unescape(when.group(1)).strip()
        if not chunk:
            return facts
        seen = set()
        for href, inner in re.findall(r'href="(/(?:pornstar|model)/[^"#]+)"[^>]*>(.*?)</a>', chunk, re.I | re.S):
            name = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", inner))).strip()
            if not name or len(name) > 60 or href in seen:
                continue
            seen.add(href)
            facts["stars"].append({"name": name, "url": urllib.parse.urljoin(self.base_url + "/", href)})
        for match in re.finditer(r'<a\b([^>]*data-label="(category|tag)"[^>]*)>(.*?)</a>', chunk, re.I | re.S):
            href = re.search(r'href="([^"]+)"', match.group(1), re.I)
            name = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", match.group(3)))).strip()
            kind = match.group(2).lower()
            if not href or not name or len(name) > 60 or name.lower() in seen:
                continue
            seen.add(name.lower())
            bucket = "categories" if kind == "category" else "tags"
            facts[bucket].append({"name": name, "url": urllib.parse.urljoin(self.base_url + "/", html.unescape(href.group(1)))})
        facts["stars"] = facts["stars"][:12]
        facts["categories"] = facts["categories"][:24]
        facts["tags"] = facts["tags"][:40]
        return facts

    def play_video(self, url):
        self.logger.info(f"Pornhub: play_video for {url}")
        
        # Ensure age disclaimer cookies are present
        data = None
        self._set_age_cookie()
        # Direct fetch without initial homepage warmup to avoid geo-block/consent cookies (returns 403)

        for attempt in range(2):
            content = self.make_request(url, referer=self.base_url if attempt == 0 else url)
            if content:
                data = self._extract_flashvars(content)
                if data:
                    break
            if attempt == 0:
                self.logger.warning("Pornhub: first video-page request had no playable flashvars; retrying after warmup.")
                self._warmup_session(referer=url)
        
        if data:
            media = data.get('mediaDefinitions', [])
            ua = self.get_headers()['User-Agent']
            headers = {
                'User-Agent': ua,
                'Referer': url,
                'Origin': self.base_url.rstrip('/'),
                'Cookie': "; ".join([f"{c.name}={c.value}" for c in self.cookie_jar])
            }
            header_str = urllib.parse.urlencode(headers)
            candidates = self._playback_candidates(media, url, headers)
            chosen = None
            kept = []
            for quality, stream_url, fmt in reversed(candidates):
                item = (quality, stream_url, fmt)
                if chosen is None:
                    if not self._prime_stream_url(stream_url, url, headers, attempts=1):
                        self.logger.warning("Pornhub: skip dead stream %s %s", quality, fmt)
                        continue
                    chosen = item
                    kept.append(item)
                    continue
                if quality < chosen[0]:
                    kept.append(item)
            if chosen:
                kept.sort(key=lambda item: (item[0], 1 if item == chosen else 0))
                quality, stream_url, fmt = kept[-1]
                kodi_url = stream_url if "|" in stream_url else stream_url + "|" + header_str
                self.logger.info("Pornhub: Playback resolved to %s %s", quality, fmt)
                li = xbmcgui.ListItem(path=kodi_url)
                li.setProperty('IsPlayable', 'true')
                packed = [{
                    "label": "%s %s" % (item[0] or "", item[2]),
                    "path": item[1] + "|" + header_str,
                } for item in kept]
                li.setProperty("web_sources", json.dumps(packed))
                li.setProperty("web_facts", json.dumps(self._video_facts(content), ensure_ascii=False)[:20000])
                if fmt == "hls":
                    li.setProperty('inputstream', 'inputstream.adaptive')
                    li.setProperty('inputstream.adaptive.manifest_type', 'hls')
                    li.setProperty('inputstream.adaptive.stream_headers', header_str)
                    li.setProperty('inputstream.adaptive.manifest_headers', header_str)
                    li.setMimeType('application/vnd.apple.mpegurl')
                else:
                    li.setMimeType('video/mp4')
                xbmcplugin.setResolvedUrl(self.addon_handle, True, li)
                return
        
        self.logger.error(f"Pornhub: No playable streams found in flashvars for {url}")
        if hasattr(self, 'notify_error'): self.notify_error("No playable stream found.")
        xbmcplugin.setResolvedUrl(self.addon_handle, False, xbmcgui.ListItem(path=url))

    def search(self, query):
        if not query: return
        url = f"{self.base_url}/video/search?search={urllib.parse.quote_plus(query)}&o=newest"
        self.process_content(url)

    def select_sort(self, original_url):
        dialog = xbmcgui.Dialog()
        idx = dialog.select("Sort by", self.sorting_options)
        if idx == -1: return

        sort_key = self.sorting_options[idx]
        sort_val = self.sorting_paths[sort_key]
        
        addon = xbmcaddon.Addon()
        addon.setSetting('pornhub_sort_by', sort_key)
        
        parsed_url = urllib.parse.urlparse(original_url)
        params = urllib.parse.parse_qs(parsed_url.query)
        params['o'] = [sort_val]
        params.pop('page', None)
        
        new_query = urllib.parse.urlencode(params, doseq=True)
        new_url = parsed_url._replace(query=new_query).geturl()
        
        xbmc.executebuiltin(f"Container.Update({sys.argv[0]}?mode=2&website={self.name}&url={urllib.parse.quote_plus(new_url)})")

    def select_period(self, original_url):
        dialog = xbmcgui.Dialog()
        idx = dialog.select("Select Period", self.period_options)
        if idx == -1: return

        period_key = self.period_options[idx]
        period_val = self.period_paths[period_key]
        parsed_url = urllib.parse.urlparse(original_url)
        params = urllib.parse.parse_qs(parsed_url.query)
        params['p'] = [period_val]
        params.pop('page', None)
        new_query = urllib.parse.urlencode(params, doseq=True)
        new_url = parsed_url._replace(query=new_query).geturl()
        xbmc.executebuiltin(f"Container.Update({sys.argv[0]}?mode=2&website={self.name}&url={urllib.parse.quote_plus(new_url)})")

    def select_pornstar_sort(self, original_url):
        dialog = xbmcgui.Dialog()
        idx = dialog.select("Sort Pornstars by", self.pornstar_sort_options)
        if idx == -1: return

        base_pornstar_url = f"{self.base_url}/pornstars"
        parsed_url = urllib.parse.urlparse(base_pornstar_url)
        params = {}
        sort_key = self.pornstar_sort_options[idx]
        sort_val = self.pornstar_sort_paths.get(sort_key)
        if sort_val: params['o'] = [sort_val]
        new_query = urllib.parse.urlencode(params, doseq=True)
        new_url = parsed_url._replace(query=new_query).geturl()
        xbmc.executebuiltin(f"Container.Update({sys.argv[0]}?mode=2&website={self.name}&url={urllib.parse.quote_plus(new_url)})")

    def process_related_videos(self, url):
        if hasattr(self, 'add_dir'):
            self.add_dir('[COLOR blue]Search[/COLOR]', '', 5, self.icons['search'], name_param=self.name)
        
        content = self.make_request(url, referer=self.base_url)
        if not content:
            self.logger.warning("Pornhub: failed to fetch related video page.")
            if hasattr(self, 'end_directory'): self.end_directory()
            return

        context_menu = [
            ('Sort by', f'RunPlugin({sys.argv[0]}?mode=7&action=select_sort&website={self.name}&original_url={urllib.parse.quote_plus(url)})'),
            ('Select Period', f'RunPlugin({sys.argv[0]}?mode=7&action=select_period&website={self.name}&original_url={urllib.parse.quote_plus(url)})')
        ]

        # Try parsing the relatedVideos JavaScript array for 100% true related videos
        js_match = re.search(r'relatedVideos\s*=\s*(\[.*?\])\s*;', content, re.DOTALL)
        if not js_match:
            js_match = re.search(r'var\s+relatedVideos\s*=\s*(\[.*?\])', content, re.DOTALL)

        if js_match:
            try:
                data = json.loads(js_match.group(1))
                # Extract all global URLs to map high-quality CDN thumbnails dynamically
                all_urls = re.findall(r'(https?://[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/[^"\s\'>]+)', content)
                url_map = {}
                for u in all_urls:
                    if "phncdn" in u or "phncdn.com" in u or "/videos/" in u:
                        m_path = re.search(r'/\d{6}/\d{2}/\d+/', u)
                        if m_path:
                            path_key = m_path.group(0)
                            # Prioritize images (.jpg, .jpeg, .png, .webp, or /plain/) over preview video webm/mp4
                            is_image = any(ext in u.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp', '/plain/']) and '.webm' not in u.lower()
                            if is_image or path_key not in url_map:
                                url_map[path_key] = u

                found_any = False
                for item in data:
                    fields = item.get("fields")
                    if not fields:
                        continue
                    vkey = fields.get("vkey")
                    if not vkey:
                        continue
                    
                    title = html.unescape(fields.get("title", "Related Video"))
                    title = re.sub(r'<[^>]+>', '', title).strip()
                    duration_sec = fields.get("duration", 0)
                    media_path = fields.get("media_path", "")

                    # Map thumbnail from our global URL map
                    thumb = ""
                    if media_path:
                        thumb = url_map.get(media_path, "")
                        if not thumb:
                            # Generic lookup by ID
                            video_id_str = media_path.strip("/").split("/")[-1]
                            # Try to find an image first
                            for u in all_urls:
                                if video_id_str in u and any(ext in u.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp', '/plain/']) and '.webm' not in u.lower():
                                    thumb = u
                                    break
                            if not thumb:
                                for u in all_urls:
                                    if video_id_str in u:
                                        thumb = u
                                        break
                    if not thumb:
                        thumb = self.fanart

                    if thumb and "|" not in thumb:
                        thumb = thumb.replace("&amp;", "&")
                        thumb += "|User-Agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0.0.0&Referer=https://www.pornhub.com/"

                    duration_str = ""
                    if duration_sec > 0:
                        mins = duration_sec // 60
                        secs = duration_sec % 60
                        duration_str = f"{mins}:{secs:02d}"

                    video_url = f"{self.base_url}/view_video.php?viewkey={vkey}"
                    video_context_menu = [
                        ('Explore similar', f'RunPlugin({sys.argv[0]}?mode=7&action=explore_similar&website={self.name}&original_url={urllib.parse.quote_plus(video_url)})'),
                    ] + context_menu

                    label = title
                    if duration_str:
                        label += f" [COLOR lime]({duration_str})[/COLOR]"

                    self.add_link(label, video_url, 4, thumb, self.fanart, video_context_menu)
                    found_any = True

                if found_any:
                    if hasattr(self, 'end_directory'): self.end_directory()
                    return
            except Exception as e:
                self.logger.warning(f"Pornhub: failed to parse JS relatedVideos: {e}")

        # Fallback to HTML matching if JavaScript parsing is unavailable
        related_matches = re.findall(r'<li\b[^>]*class="[^"]*(?:videoBox|ph-thumbnail)[^"]*"[^>]*>(.*?)</li>', content, re.DOTALL)
        if not related_matches:
            related_matches = re.findall(r'<div\b[^>]*class="[^"]*(?:videoBox|ph-thumbnail)[^"]*"[^>]*>(.*?)</div>', content, re.DOTALL)

        found_any = False
        for chunk in related_matches:
            v_match = re.search(r'href="[^"]*viewkey=([^"&]+)"', chunk)
            if not v_match:
                continue
            viewkey = v_match.group(1)
            
            t_match = re.search(r'title="([^"]+)"', chunk) or re.search(r'<span class="title">[^<]*<a[^>]*>([^<]+)</a>', chunk, re.DOTALL)
            img_match = re.search(r'<img[^>]+src="([^"]+)"', chunk) or re.search(r'data-src="([^"]+)"', chunk)
            dur_match = re.search(r'<var class="duration">([^<]+)</var>', chunk)

            title = html.unescape(t_match.group(1).strip()) if t_match else 'Untitled Video'
            title = re.sub(r'<[^>]+>', '', title).strip()
            img = img_match.group(1) if img_match else ''
            duration = dur_match.group(1).strip() if dur_match else ''

            if img:
                img = img.replace("&amp;", "&")
                if "|" not in img:
                    img += "|User-Agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0.0.0&Referer=https://www.pornhub.com/"

            video_url = f"{self.base_url}/view_video.php?viewkey={viewkey}"
            
            video_context_menu = [
                ('Explore similar', f'RunPlugin({sys.argv[0]}?mode=7&action=explore_similar&website={self.name}&original_url={urllib.parse.quote_plus(video_url)})'),
            ] + context_menu

            label = title
            if duration:
                label += f" [COLOR lime]({duration})[/COLOR]"
                
            self.add_link(label, video_url, 4, img, self.fanart, video_context_menu)
            found_any = True

        if not found_any:
            self.logger.warning("Pornhub: no related videos found on video page.")
            
        if hasattr(self, 'end_directory'):
            self.end_directory()

    def explore_similar(self, original_url=None):
        if not original_url:
            self.notify_info("No video URL available")
            return

        html_content = self.make_request(original_url)
        if not html_content:
            self.notify_error("Could not load video info")
            return

        pornstars_chunk = ""
        categories_chunk = ""
        tags_chunk = ""

        # Extract pornstars wrapper
        pornstars_match = re.search(r'<div[^>]+class="[^"]*pornstarsWrapper[^"]*"[^>]*>(.*?)</div>', html_content, re.DOTALL)
        if pornstars_match:
            pornstars_chunk = pornstars_match.group(1)

        # Extract categories wrapper
        categories_match = re.search(r'<div[^>]+class="[^"]*categoriesWrapper[^"]*"[^>]*>(.*?)</div>', html_content, re.DOTALL)
        if categories_match:
            categories_chunk = categories_match.group(1)

        # Extract tags wrapper
        tags_match = re.search(r'<div[^>]+class="[^"]*tagsWrapper[^"]*"[^>]*>(.*?)</div>', html_content, re.DOTALL)
        if tags_match:
            tags_chunk = tags_match.group(1)

        pornstar_items = []
        if pornstars_chunk:
            patterns = [
                ("Pornstar", r'href="(/pornstar/[^"]+)"[^>]*>([^<]+)', 2),
                ("Model", r'href="(/model/[^"]+)"[^>]*>([^<]+)', 2),
            ]
            pornstar_items = extract_html_items(pornstars_chunk, self.base_url, patterns)

        category_items = []
        if categories_chunk:
            patterns = [
                ("Category", r'href="(/categories/[^"]+)"[^>]*>([^<]+)', 2),
            ]
            category_items = extract_html_items(categories_chunk, self.base_url, patterns)
            for item in category_items:
                parsed = urllib.parse.urlparse(item["url"])
                slug = parsed.path.rstrip("/").split("/")[-1]
                item["url"] = f"{self.base_url}/video?category_slug={slug}"

        tag_items = []
        if tags_chunk:
            patterns = [
                ("Tag", r'href="(/video/search\?search=[^"]+)"[^>]*>([^<]+)', 2),
                ("Tag", r'href="(/search\?search=[^"]+)"[^>]*>([^<]+)', 2),
            ]
            tag_items = extract_html_items(tags_chunk, self.base_url, patterns)

        items = pornstar_items + category_items + tag_items

        if not items:
            # Fallback to global matching if wrapper blocks are not found or are empty
            patterns = [
                ("Pornstar", r'href="(/pornstar/[^"]+)"[^>]*>([^<]+)', 2),
                ("Model", r'href="(/model/[^"]+)"[^>]*>([^<]+)', 2),
                ("Category", r'href="(/categories/[^"]+)"[^>]*>([^<]+)', 2),
                ("Tag", r'href="(/video/search\?search=[^"]+)"[^>]*>([^<]+)', 2),
                ("Tag", r'href="(/search\?search=[^"]+)"[^>]*>([^<]+)', 2),
            ]
            items = extract_html_items(html_content, self.base_url, patterns)
            for item in items:
                if item["group"] == "Category":
                    parsed = urllib.parse.urlparse(item["url"])
                    slug = parsed.path.rstrip("/").split("/")[-1]
                    item["url"] = f"{self.base_url}/video?category_slug={slug}"
        
        if items:
            lang = xbmc.getLanguage(0).lower()
            if "german" in lang or "deutsch" in lang:
                group = "Wiedergabe"
                label = "[COLOR lime]>>> Show similar videos <<<[/COLOR]"
            elif "spanish" in lang or "español" in lang or "espanol" in lang:
                group = "Reproducción"
                label = "[COLOR lime]>>> Mostrar videos similares <<<[/COLOR]"
            elif "french" in lang or "français" in lang or "francais" in lang:
                group = "Lecture"
                label = "[COLOR lime]>>> Afficher les vidéos similaires <<<[/COLOR]"
            else:
                group = "Playback"
                label = "[COLOR lime]>>> Show Similar Videos <<<[/COLOR]"
            items.insert(0, {
                "group": group,
                "label": label,
                "url": original_url,
                "mode": 2,
                "action": "show_related"
            })
            
        if not choose_and_open(items, self.config["name"], "Explore similar"):
            self.logger.info("[pornhub] No lookup target selected for {}".format(original_url))
