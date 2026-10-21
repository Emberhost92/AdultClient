"""Explicit source publication dates, preserving precision and timezone."""
from datetime import datetime
from html.parser import HTMLParser
import json
import re
from urllib.parse import urljoin, urlsplit


def valid_upload_date(value):
    if not isinstance(value, str):
        return ''
    value = value.strip()
    if len(value) < 10 or len(value) > 40 or value[4:5] != '-' or value[7:8] != '-':
        return ''
    try:
        datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return ''
    return value


def upload_date(text, video=None):
    video = video or {}
    for key in ('uploadDate', 'datePublished'):
        value = valid_upload_date(video.get(key))
        if value:
            return value

    class Dates(HTMLParser):
        value = ''

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            key = (attrs.get('itemprop') or attrs.get('property') or attrs.get('name') or '').lower()
            if key in ('uploaddate', 'datepublished', 'video:release_date', 'video:upload_date'):
                value = valid_upload_date(attrs.get('content') or attrs.get('datetime'))
                if value and not self.value:
                    self.value = value

    parser = Dates()
    parser.feed(text or '')
    return parser.value


DETAIL_FIELDS = ('title', 'description', 'sourceUrl', 'uploader', 'uploaderUrl',
                 'publisher', 'videoId', 'comments', 'likes', 'dislikes',
                 'rating', 'languages', 'sourceQuality', 'width', 'height',
                 'bitrate', 'fileSize', 'modifiedDate')


def plain(value, limit=4000):
    class Text(HTMLParser):
        def __init__(self): super().__init__(); self.parts = []
        def handle_data(self, data): self.parts.append(data)
    parser = Text(); parser.feed(str('' if value is None else value))
    return re.sub(r'\s+', ' ', ' '.join(parser.parts)).strip()[:limit]


def clean_details(raw):
    if not isinstance(raw, dict): return {}
    result = {}
    for key in DETAIL_FIELDS:
        value = raw.get(key)
        if value is None or isinstance(value, (dict, list, bool)): continue
        value = plain(value, 4000 if key == 'description' else 1000)
        if not value: continue
        if key.endswith('Url') and urlsplit(value).scheme not in ('https', 'http'): continue
        if key == 'modifiedDate' and not valid_upload_date(value): continue
        result[key] = value
    return result


def video_details(text, page, video=None):
    """Read current-video fields only; never expose stream tokens or site config."""
    video = video or {}
    name = lambda node: plain(node.get('name')) if isinstance(node, dict) else plain(node)
    author = video.get('author') or video.get('creator') or {}
    if isinstance(author, list): author = next(iter(author), {})
    identifier = video.get('identifier') or ''
    if isinstance(identifier, dict): identifier = identifier.get('value') or identifier.get('name') or ''
    language = video.get('inLanguage') or ''
    if isinstance(language, list): language = ', '.join(name(v) for v in language)
    result = {'title': video.get('name'), 'description': video.get('description'),
              'sourceUrl': page, 'uploader': name(author),
              'uploaderUrl': author.get('url', '') if isinstance(author, dict) else '',
              'publisher': name(video.get('publisher') or video.get('productionCompany')),
              'videoId': identifier, 'languages': name(language),
              'bitrate': video.get('bitrate'), 'fileSize': video.get('contentSize'),
              'modifiedDate': valid_upload_date(video.get('dateModified'))}
    for key in ('width', 'height'):
        value = video.get(key)
        result[key] = value.get('value') if isinstance(value, dict) else value
    stats = video.get('interactionStatistic') or []
    if isinstance(stats, dict): stats = [stats]
    for stat in stats if isinstance(stats, list) else []:
        if not isinstance(stat, dict): continue
        kind = stat.get('interactionType') or ''
        if isinstance(kind, dict): kind = kind.get('@type', '')
        for action, key in (('CommentAction', 'comments'), ('DislikeAction', 'dislikes'), ('LikeAction', 'likes')):
            if str(kind).rstrip('/').split('/')[-1] == action:
                result[key] = stat.get('userInteractionCount')
    rating = video.get('aggregateRating') or {}
    if isinstance(rating, dict) and rating.get('ratingValue') is not None:
        result['rating'] = str(rating['ratingValue']) + (' / '+str(rating['bestRating']) if rating.get('bestRating') else '')

    class PageInfo(HTMLParser):
        def __init__(self): super().__init__(); self.capture = []; self.values = {}
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'link' and 'canonical' in attrs.get('rel', '').split():
                result['sourceUrl'] = urljoin(page, attrs.get('href', ''))
            classes = attrs.get('class', '').split()
            key = 'rating' if 'rating-good-perc' in classes else 'sourceQuality' if 'video-hd-mark' in classes else None
            if key in self.values: key = None
            self.capture.append((tag, key))
            if key: self.values[key] = []
        def handle_endtag(self, tag):
            for index in range(len(self.capture)-1, -1, -1):
                if self.capture[index][0] == tag: del self.capture[index:]; break
        def handle_data(self, data):
            for key in {key for _, key in self.capture if key}: self.values[key].append(data)
    parser = PageInfo(); parser.feed(text or '')
    # These explicit video classes belong to the XVideos/XNXX current-video header.
    host = (urlsplit(page).hostname or '').lower()
    if any(host == site or host.endswith('.'+site) for site in ('xvideos.com', 'xnxx.com')):
        for key, values in parser.values.items(): result[key] = ''.join(values).strip()
        match = re.search(r'window\.xv\.conf\s*=\s*', text or '')
        if match:
            try: config, _ = json.JSONDecoder().raw_decode(text[match.end():])
            except ValueError: config = {}
            if isinstance(config, dict):
                current = config.get('data') if isinstance(config.get('data'), dict) else config
                encoded = str(current.get('encoded_id_video') or '')
                if encoded and encoded in urlsplit(page).path:
                    result.update(videoId=current.get('id_video') or encoded,
                                  uploader=current.get('uploader') or result.get('uploader'),
                                  uploaderUrl=urljoin(page, current['uploader_url']) if current.get('uploader_url') else result.get('uploaderUrl'))
                    dynamic = config.get('dyn') if isinstance(config.get('dyn'), dict) else {}
                    data = current.get('vmdata') or dynamic.get('vmdata') or {}
                    if isinstance(data, dict) and type(data.get('pub_comments')) is int:
                        result['comments'] = data['pub_comments']
    return clean_details(result)
