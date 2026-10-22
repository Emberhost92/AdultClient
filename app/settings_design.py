"""Shared-schema design validation and immutable local design assets."""
import base64
import hashlib
import io
import json
import math
from pathlib import Path
import re
import struct
import threading
import urllib.parse

SCHEMA = json.loads((Path(__file__).parent / 'static' / 'settings_schema.json').read_text(encoding='utf-8'))
ASSET = re.compile(r'^[a-f0-9]{64}\.(png|jpg|gif|webp|woff2?|ttf|otf)$')
IMAGE = re.compile(r'^[a-f0-9]{64}\.(png|jpg|gif|webp)$')
FONT = re.compile(r'^[a-f0-9]{64}\.(woff2?|ttf|otf)$')
LOCK = threading.RLock()


class Conflict(ValueError):
    pass


def record(value):
    return value if isinstance(value, dict) else {}


def url(value):
    try:
        parsed = urllib.parse.urlsplit(str(value or ''))
        return str(value)[:2000] if parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username and not parsed.password else ''
    except ValueError:
        return ''


def clean_value(value, rule):
    default = rule['default']
    kind = rule['type']
    if value is None:
        return default
    if kind == 'boolean':
        return value if isinstance(value, bool) else default
    if kind == 'number':
        try:
            number = float(value)
            return round(max(rule['min'], min(rule['max'], number)), 2) if math.isfinite(number) else default
        except (ValueError, TypeError):
            return default
    if kind == 'color':
        return value.lower() if isinstance(value, str) and re.fullmatch(r'#[a-fA-F0-9]{6}', value) else default
    if kind == 'text':
        return value.strip()[:rule['max']] if isinstance(value, str) else default
    if kind == 'url':
        return url(value)
    if kind == 'image':
        return value if isinstance(value, str) and IMAGE.fullmatch(value) else ''
    if kind == 'enum':
        return str(value) if str(value) in rule['values'] else default
    if kind == 'font':
        return value if isinstance(value, str) and (value in SCHEMA['fonts'] or value.startswith('asset:') and FONT.fullmatch(value[6:])) else default
    return default


def background(raw):
    raw = record(raw)
    return {key: clean_value(raw.get(key), rule) for key, rule in SCHEMA['background'].items()}


def appearance(raw):
    raw = record(raw)
    out = {}
    for key, default in SCHEMA['appearance'].items():
        value = raw.get(key)
        if isinstance(default, list):
            out[key] = [v for v in value if isinstance(v,str) and v in SCHEMA["menus"] and v != "settings"] if isinstance(value,list) else []
        elif isinstance(default, dict):
            out[key] = {k:v.strip()[:40] for k,v in record(value).items() if k in SCHEMA["menus"] and k != "settings" and isinstance(v,str)}
        elif isinstance(default, bool):
            out[key] = value if isinstance(value, bool) else default
        elif isinstance(default, (int, float)):
            out[key] = clean_value(value, {'type': 'number', 'default': default, 'min': 0, 'max': 1000})
        elif default.startswith('#'):
            out[key] = clean_value(value, {'type': 'color', 'default': default})
        elif key == 'photo':
            out[key] = url(value)
        else:
            out[key] = value if isinstance(value, str) and len(value) <= 80 else default
    return out


def clean_design(raw=None, profiles=True):
    raw = record(raw)
    if raw.get('version', 1) != 1:
        raise ValueError('Diese Designversion wird noch nicht unterstützt. Vorhandene Daten bleiben erhalten.')
    out = {'version': 1}
    for path, rule in SCHEMA['fields'].items():
        source, target = raw, out
        parts = path.split('.')
        for key in parts[:-1]:
            source = record(source.get(key))
            target = target.setdefault(key, {})
        target[parts[-1]] = clean_value(source.get(parts[-1]), rule)
    if out['brand']['logo'] == 'c2cfefa1e3e32392f84cc37a80a29f68578996779285d13a8a067d4864090279.jpg':
        out['brand']['logo'] = ''
        out['brand']['background'] = 'transparent'
    for key in ('name', 'title'):
        if out['brand'][key] in ('AdultHideout', 'Adult Hideout'):
            out['brand'][key] = 'Adult Client'
    backgrounds = record(raw.get('backgrounds'))
    out['backgrounds'] = {'all': background(backgrounds.get('all')), 'pages': {}}
    for key, value in record(backgrounds.get('pages')).items():
        if key in SCHEMA['menus'] + ['browse', 'watch']:
            out['backgrounds']['pages'][key] = background(value)
    out['fonts'] = [{'file': f['file'], 'name': f['name'][:80]} for f in (raw.get('fonts') if isinstance(raw.get('fonts'), list) else []) if isinstance(f, dict) and isinstance(f.get('name'), str) and FONT.fullmatch(str(f.get('file', '')))][:12]
    out['siteLogos'] = dict([(key, value) for key, value in record(raw.get('siteLogos')).items() if re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', key) and isinstance(value, str) and IMAGE.fullmatch(value)][:600])
    out['menuIcons'] = {key: {'symbol': str(record(v).get('symbol') or '')[:8], 'image': str(record(v).get('image') or '') if IMAGE.fullmatch(str(record(v).get('image') or '')) else ''} for key, v in record(raw.get('menuIcons')).items() if key in SCHEMA['menus']}
    out['menuOrder'] = list(dict.fromkeys(k for k in (raw.get('menuOrder') if isinstance(raw.get('menuOrder'), list) else []) if isinstance(k, str) and k in SCHEMA['menus'] and k != 'settings'))
    out['profiles'] = []
    if profiles:
        for index, p in enumerate((raw.get('profiles') if isinstance(raw.get('profiles'), list) else [])[:24]):
            if isinstance(p, dict) and isinstance(p.get('name'), str) and p['name'].strip():
                out['profiles'].append({'id': str(p.get('id') or 'profile-' + str(index))[:100], 'name': p['name'].strip()[:80], 'design': clean_design(p.get('design'), False), 'appearance': appearance(p.get('appearance'))})
    return out


def asset_path(profile, name):
    if not isinstance(name, str) or not ASSET.fullmatch(name):
        raise ValueError('Ungültige Designdatei.')
    return Path(profile) / 'design_assets' / name


def image_extension(blob):
    from PIL import Image
    try:
        with Image.open(io.BytesIO(blob)) as image:
            if image.width * image.height > 32_000_000 or max(image.size) > 16000:
                raise ValueError('Das Bild hat zu viele Bildpunkte. Höchstens 32 Megapixel.')
            extension = {'PNG': 'png', 'JPEG': 'jpg', 'WEBP': 'webp', 'GIF': 'gif'}.get(image.format)
            image.verify()
        if not extension:
            raise ValueError('Bitte PNG, JPG, GIF oder WebP verwenden.')
        return extension
    except (OSError, SyntaxError, Image.DecompressionBombError) as error:
        raise ValueError('Das Bild ist beschädigt oder wird nicht unterstützt.') from error


def font_extension(blob):
    if len(blob) < 48:
        raise ValueError('Die Schriftdatei ist beschädigt.')
    signature = blob[:4]
    if signature in (b'wOFF', b'wOF2'):
        size = struct.unpack_from('>I', blob, 8)[0]
        tables = struct.unpack_from('>H', blob, 12)[0]
        if size != len(blob) or not 1 <= tables <= 256:
            raise ValueError('Die Schriftdatei ist beschädigt.')
        return 'woff' if signature == b'wOFF' else 'woff2'
    if signature in (b'\x00\x01\x00\x00', b'OTTO', b'true'):
        count = struct.unpack_from('>H', blob, 4)[0]
        if not 1 <= count <= 256 or 12 + count * 16 > len(blob):
            raise ValueError('Die Schriftdatei ist beschädigt.')
        for offset in range(12, 12 + count * 16, 16):
            start, length = struct.unpack_from('>II', blob, offset + 8)
            if start + length > len(blob):
                raise ValueError('Die Schriftdatei ist unvollständig.')
        return 'otf' if signature == b'OTTO' else 'ttf'
    raise ValueError('Bitte eine WOFF2-, WOFF-, TTF- oder OTF-Schriftdatei wählen.')


def save_asset(profile, kind, encoded, expected=''):
    if kind not in ('image', 'font') or not isinstance(encoded, str):
        raise ValueError('Ungültige Designdatei.')
    limit = 8_000_000 if kind == 'image' else 4_000_000
    if len(encoded) > (limit * 4 // 3 + 8):
        raise ValueError('Bild höchstens 8 MB, Schrift höchstens 4 MB.')
    try:
        blob = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError('Die Datei konnte nicht gelesen werden.') from error
    if not blob or len(blob) > limit:
        raise ValueError('Bild höchstens 8 MB, Schrift höchstens 4 MB.')
    extension = image_extension(blob) if kind == 'image' else font_extension(blob)
    name = hashlib.sha256(blob).hexdigest() + '.' + extension
    if expected and expected != name:
        raise ValueError('Die Designdatei passt nicht zur Sicherung.')
    target = asset_path(profile, name)
    with LOCK:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            if sum(p.stat().st_size for p in target.parent.iterdir() if p.is_file()) + len(blob) > 128_000_000:
                raise ValueError('Der lokale Designspeicher ist voll (128 MB).')
            temporary = target.with_suffix('.tmp')
            try:
                temporary.write_bytes(blob)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
    return {'ok': True, 'file': name, 'bytes': len(blob)}
