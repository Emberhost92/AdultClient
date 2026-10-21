"""Export only public model records. Never copy a user's profile directory."""
import argparse
import gzip
import hashlib
import json
import re
import sqlite3
import time
import urllib.parse
import zlib
from pathlib import Path

TABLES = ('records', 'metadata', 'cache', 'box_scenes', 'source_catalog', 'source_gallery', 'source_links')
CACHES = {'sources', 'source-coverage', 'box-features', 'box-summary', 'box-state', 'metadata-features', 'translation'}
PRIVATE = re.compile(r'^(?:api[_-]?key|authorization|password|cookie[s]?|access[_-]?token|refresh[_-]?token|headers|notes?|favorites?|favourites?|history|downloads?|credentials|session[s]?|local_path|cover[s]?|bookmark[s]?)$', re.I)
EMPTY_STATE = {'version': 1, 'trends': [], 'covers': {}, 'sync': {}}


def clean(value, secrets=()):
    if isinstance(value, dict):
        return {k: clean(v, secrets) for k, v in value.items() if not PRIVATE.fullmatch(k)}
    if isinstance(value, list):
        return [clean(v, secrets) for v in value]
    if not isinstance(value, str):
        return value
    if re.search(r'(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/]|file://|/Users/|/home/)', value):
        return ''
    if value.startswith(('http://', 'https://')):
        url, _, header = value.partition('|')
        p = urllib.parse.urlsplit(url)
        if p.username or p.password or p.hostname in ('localhost', '127.0.0.1', '::1'):
            return ''
        query = [(k,v) for k,v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
                 if not PRIVATE.fullmatch(k) and k.lower() not in ('token', 'signature', 'sig', 'auth')]
        url = urllib.parse.urlunsplit((p.scheme,p.netloc,p.path,urllib.parse.urlencode(query),p.fragment))
        # Public referer/agent headers can be necessary for images; never export cookies.
        safe = [(k,v) for k,v in urllib.parse.parse_qsl(header) if k.lower() in ('referer','user-agent','origin')]
        value = url + ('|' + urllib.parse.urlencode(safe) if safe else '')
    if any(s and s in value for s in secrets):
        return ''
    return value


def decode(raw):
    return json.loads(zlib.decompress(raw[4:]) if isinstance(raw, bytes) and raw.startswith(b'AHZ1') else raw)


def encode(value, compressed=False):
    raw = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    return b'AHZ1'+zlib.compress(raw.encode(), 6) if compressed else raw


def export(source, target, secrets=()):
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target or target.exists():
        raise ValueError('Exportziel muss neu und von der Quelldatenbank getrennt sein.')
    target.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(source.as_uri()+'?mode=ro', uri=True, timeout=60)
    dst = sqlite3.connect(target)
    counts = {}
    try:
        # One read transaction gives a consistent snapshot while the private app runs.
        src.execute('BEGIN')
        dst.execute('PRAGMA journal_mode=OFF')
        dst.execute('PRAGMA synchronous=OFF')
        for table, sql in src.execute("SELECT name,sql FROM sqlite_master WHERE type='table'"):
            if table not in TABLES:
                continue
            dst.execute(sql)
            cols = [r[1] for r in src.execute('PRAGMA table_info('+table+')')]
            count = 0
            for row in src.execute('SELECT * FROM '+table):
                row = list(row)
                if table == 'records' and row[cols.index('bucket')] not in ('profiles','lang','people'):
                    continue
                if table == 'metadata':
                    continue
                if table == 'cache' and row[cols.index('kind')] not in CACHES:
                    continue
                for i, col in enumerate(cols):
                    if col == 'payload':
                        raw = row[i]
                        row[i] = encode(clean(decode(raw), secrets), isinstance(raw,bytes))
                    elif isinstance(row[i],str):
                        row[i] = clean(row[i], secrets)
                dst.execute('INSERT INTO '+table+' VALUES('+','.join('?' for _ in row)+')', row)
                count += 1
            counts[table] = count
            print(table, count, flush=True)
        dst.execute("INSERT INTO metadata VALUES('state',?)", (encode(EMPTY_STATE),))
        dst.execute("INSERT INTO metadata VALUES('settings',?)", (encode({'paused':True,'speed':'eco','interval':24,'prefetch':12,'jobs':{},'requests':{}}),))
        for _, sql in src.execute("SELECT name,sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL AND tbl_name IN ("+','.join('?' for _ in TABLES)+')', TABLES):
            dst.execute(sql)
        dst.commit()
        assert dst.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    finally:
        dst.close()
        src.close()
    packed = target.with_suffix('.sqlite3.gz')
    with target.open('rb') as inp, packed.open('wb') as output:
        with gzip.GzipFile(filename='', mode='wb', fileobj=output, mtime=0, compresslevel=6) as out:
            while chunk := inp.read(1024*1024): out.write(chunk)
    with packed.open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    manifest = {'format':1,'created':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'file':packed.name,
                'sha256':digest,'bytes':packed.stat().st_size,'unpacked_bytes':target.stat().st_size,'tables':counts,
                'images':'remote-urls-only','personal_data':False}
    packed.with_suffix('.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return manifest


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('target')
    a=p.parse_args();print(json.dumps(export(a.source,a.target)))
