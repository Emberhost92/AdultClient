"""Browser playback for videos in explicitly configured download folders."""
import functools
import hashlib
import shutil
import math
import mimetypes
import os
import re
import urllib.parse

VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.webm', '.mov', '.ts', '.m4v')


@functools.lru_cache(maxsize=128)
def ts_duration(path, size, modified):
    """Read only the ends of a transport stream, using its 90 kHz PES clock."""
    timestamps = []
    with open(path, 'rb') as handle:
        for offset in (0, max(0, size - 1024 * 1024)):
            handle.seek(offset - offset % 188)
            data = handle.read(1024 * 1024)
            for at in range(0, len(data)-188+1, 188):
                packet = data[at:at+188]
                if packet[0] != 0x47 or not packet[1] & 0x40:
                    continue
                control = (packet[3] >> 4) & 3
                start = 5 + packet[4] if control == 3 else 4 if control == 1 else 188
                pes = packet[start:]
                if len(pes) < 14 or pes[:3] != b'\x00\x00\x01' or not 0xe0 <= pes[3] <= 0xef or not pes[7] & 0x80:
                    continue
                p = pes[9:14]
                timestamps.append(((p[0] & 14) << 29) | (p[1] << 22) | ((p[2] & 254) << 14) | (p[3] << 7) | (p[4] >> 1))
    if not timestamps:
        return 1.0
    first = timestamps[0]
    seconds = max((stamp-first) % (1 << 33) for stamp in timestamps if (stamp-first) % (1 << 33) < 90_000*86400) / 90_000
    return max(1.0, seconds + 0.1)


class DownloadLibrary:
    def __init__(self, folders, media_origin=""):
        self.folders = folders
        self.media_origin = media_origin

    def roots(self):
        roots = []
        for folder in self.folders():
            if not folder:
                continue
            path = os.path.realpath(folder)
            if os.path.isdir(path) and os.path.normcase(path) not in {os.path.normcase(p) for p in roots}:
                roots.append(path)
        return roots

    def authorize(self, path):
        real = os.path.realpath(path)
        for root in self.roots():
            try:
                if os.path.commonpath((os.path.normcase(real), os.path.normcase(root))) == os.path.normcase(root):
                    return real
            except ValueError:
                pass
        raise ValueError('Diese Datei liegt nicht in einem eingerichteten Download- oder Offline-Ordner.')

    def storage(self, fresh=False):
        from ui_performance import directory_summary
        if fresh:directory_summary.invalidate()
        rows=[];drives={};unique=[]
        for path in self.roots():
            amount=directory_summary.get(path)
            try:
                disk=shutil.disk_usage(path)
                drive=os.path.splitdrive(path)[0] or os.path.sep
                drives[drive]=dict(path=drive,total=disk.total,used=disk.used,free=disk.free)
            except OSError:
                drive=''
            rows.append(dict(path=path,bytes=amount['bytes'],files=amount['files'],pending=amount['running'],drive=drive))
        for row in sorted(rows,key=lambda r:len(r['path'])):
            if not any(os.path.commonpath((os.path.normcase(row['path']),os.path.normcase(p)))==os.path.normcase(p) for p in unique if os.path.splitdrive(p)[0]==os.path.splitdrive(row['path'])[0]):
                unique.append(row['path'])
        return dict(ok=True,folders=rows,drives=list(drives.values()),bytes=None if any(r['bytes'] is None for r in rows if r['path'] in unique) else sum(r['bytes'] or 0 for r in rows if r['path'] in unique),pending=any(r['pending'] for r in rows))

    def reveal(self, path):
        path=self.authorize(path)
        folder=path if os.path.isdir(path) else os.path.dirname(path) if os.path.isfile(path) else ''
        if not folder:raise ValueError('Der Ordner ist nicht mehr vorhanden.')
        os.startfile(folder)
        return dict(ok=True)

    def source(self, path):
        return self.media_origin+'/api/download-file?'+urllib.parse.urlencode({'path':path})+('&playlist=1' if path.lower().endswith('.ts') else '')

    def browse(self, params):
        result = dict(items=[], resolved=None, error='', category='Offline-Videos', notifications=[], redirect='', pages=1, cached=False)
        try:
            roots = self.roots()
            path = params.get('path', '')
            if params.get('mode') == 'offline-play':
                path = self.authorize(path)
                if not os.path.isfile(path) or not path.lower().endswith(VIDEO_EXTENSIONS):
                    raise ValueError('Die gespeicherte Videodatei fehlt.')
                query = urllib.parse.urlencode({'path': path})
                ts = path.lower().endswith('.ts')
                result['resolved'] = dict(path=self.source(path),
                    title=os.path.splitext(os.path.basename(path))[0], mime='application/vnd.apple.mpegurl' if ts else mimetypes.guess_type(path)[0] or 'video/mp4')
                return result
            if not path and len(roots) == 1:
                path = roots[0]
            entries = []
            if path:
                path = self.authorize(path)
                with os.scandir(path) as listing:
                    for entry in listing:
                        if entry.is_dir() or entry.is_file() and entry.name.lower().endswith(VIDEO_EXTENSIONS):
                            try:
                                entries.append((self.authorize(entry.path), entry.is_dir()))
                            except ValueError:
                                continue
            else:
                entries = [(root, True) for root in roots]
            for name, folder in sorted(entries, key=lambda pair: os.path.basename(pair[0]).casefold()):
                title = os.path.basename(name) if folder else os.path.splitext(os.path.basename(name))[0]
                stat=os.stat(name)
                key=hashlib.sha256((name+':'+str(stat.st_size)+':'+str(stat.st_mtime_ns)).encode()).hexdigest()
                result['items'].append(dict(title=title or name, url='plugin://plugin.video.adulthideout/?'+urllib.parse.urlencode(
                    {'mode': '32' if folder else 'offline-play', 'path': name}), folder=folder, playable=not folder,
                    role='folder' if folder else 'video', offline=True, offlinePath=name, sizeBytes=None if folder else stat.st_size, previewKey=key, previewSrc='' if folder else self.source(name), previewMime='application/vnd.apple.mpegurl' if name.lower().endswith('.ts') else mimetypes.guess_type(name)[0] or 'video/mp4', thumb='', plot=name, context=[], media={'version':1,'kind':'folder' if folder else 'video'}))
            if not entries:
                result['category'] = 'Noch keine Offline-Videos. Starte auf einer Tube-Videokarte einen Download und wähle einen Ordner.'
        except (OSError, ValueError) as error:
            result['error'] = str(error)
            result['category'] = str(error)
        return result

    def serve(self, handler, query, head=False):
        params = dict(urllib.parse.parse_qsl(query))
        try:
            path = self.authorize(params.get('path', ''))
            if not os.path.isfile(path) or not path.lower().endswith(VIDEO_EXTENSIONS):
                raise ValueError('Videodatei fehlt.')
            size = os.path.getsize(path)
            if params.get('playlist') == '1' and path.lower().endswith('.ts'):
                duration = ts_duration(path, size, os.stat(path).st_mtime_ns)
                src = '/api/download-file?' + urllib.parse.urlencode({'path':path})
                text = '#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-PLAYLIST-TYPE:VOD\n#EXT-X-TARGETDURATION:%d\n#EXTINF:%.3f,\n%s\n#EXT-X-ENDLIST\n' % (math.ceil(duration), duration, src)
                handler._send(200, text, 'application/vnd.apple.mpegurl', -1)
                return
            start, end, partial = 0, size-1, False
            value = handler.headers.get('Range', '')
            if value:
                match = re.fullmatch(r'bytes=(\d*)-(\d*)', value)
                if not match or not any(match.groups()):
                    start = size
                elif not match[1]:
                    start = max(0, size-int(match[2]))
                else:
                    start = int(match[1]); end = min(end, int(match[2])) if match[2] else end
                if start >= size or end < start:
                    handler.send_response(416); handler.send_header('Content-Range', 'bytes */%d' % size)
                    handler.send_header('Content-Length', '0'); handler._cors(); handler.end_headers(); return
                partial = True
            handler.send_response(206 if partial else 200)
            handler.send_header('Content-Type', 'video/mp2t' if path.lower().endswith('.ts') else mimetypes.guess_type(path)[0] or 'application/octet-stream')
            handler.send_header('Content-Length', str(max(0,end-start+1)))
            handler.send_header('Accept-Ranges', 'bytes')
            handler.send_header('Cache-Control', 'private, no-store')
            if partial: handler.send_header('Content-Range', 'bytes %d-%d/%d' % (start,end,size))
            handler._cors(); handler.end_headers()
            if not head:
                with open(path, 'rb') as handle:
                    handle.seek(start); remaining=end-start+1
                    while remaining > 0:
                        chunk=handle.read(min(256*1024,remaining))
                        if not chunk: break
                        handler.wfile.write(chunk); remaining-=len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            return
        except (OSError, ValueError):
            handler._send(404, 'Gespeichertes Video nicht verfügbar.', 'text/plain; charset=utf-8')
