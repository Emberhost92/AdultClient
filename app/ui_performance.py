"""Bounded local UI work; expensive filesystem totals never hold up navigation."""
import gzip
import hashlib
import os
import threading
import time


class DirectorySummary:
    def __init__(self, ttl=60):
        self.ttl = ttl
        self.lock = threading.Lock()
        self.rows = {}

    def get(self, path):
        key = os.path.abspath(path)
        with self.lock:
            row = self.rows.setdefault(key, {"files": None, "bytes": None, "at": 0, "running": False})
            if not row["running"] and (not row["at"] or time.monotonic()-row["at"] >= self.ttl):
                row["running"] = True
                threading.Thread(target=self._scan, args=(key,row), name="ui-directory-summary", daemon=True).start()
            return dict(row)

    def invalidate(self):
        with self.lock:
            self.rows.clear()

    def _scan(self, key, row):
        files = size = 0
        try:
            pending = [key]
            while pending:
                directory = pending.pop()
                try:
                    with os.scandir(directory) as entries:
                        for entry in entries:
                            if entry.is_dir(follow_symlinks=False):
                                pending.append(entry.path)
                            elif entry.is_file(follow_symlinks=False):
                                try:
                                    size += entry.stat(follow_symlinks=False).st_size
                                    files += 1
                                except OSError:
                                    pass
                except FileNotFoundError:
                    continue
            with self.lock:
                if self.rows.get(key) is row:row.update(files=files, bytes=size, at=time.monotonic(), error=False)
        except OSError:
            with self.lock:
                if self.rows.get(key) is row:row.update(at=time.monotonic(), error=True)
        finally:
            with self.lock:
                if self.rows.get(key) is row:row["running"] = False


def encoded_response(path, data, content_type, accept_encoding="", etag_header=""):
    """Revalidate UI assets on every load; compress text only when negotiated."""
    headers = {}
    asset = path.startswith("/static/") or path in ("/", "/index.html")
    text = content_type.startswith("text/") or content_type.split(';')[0] in ("application/json", "application/javascript")
    if text and len(data) >= 1024:
        headers["Vary"] = "Accept-Encoding"
        accepts = {}
        for part in accept_encoding.lower().split(','):
            bits = part.strip().split(';')
            try:
                accepts[bits[0]] = next((float(v.strip()[2:]) for v in bits[1:] if v.strip().startswith('q=')), 1)
            except ValueError:
                accepts[bits[0]] = 0
        if accepts.get('gzip', accepts.get('*', 0)) > 0:
            compressed = gzip.compress(data, compresslevel=3, mtime=0)
            if len(compressed) < len(data):
                data = compressed
                headers["Content-Encoding"] = "gzip"
    if asset:
        # Strong validators identify the actual representation, including its
        # coding. Vary is required on a 304 as well as on the corresponding 200.
        tag = '"'+hashlib.sha256(data).hexdigest()+'"'
        headers.update({"ETag": tag, "Cache-Control": "no-cache"})
        if any(value.strip().removeprefix('W/') in (tag, '*') for value in etag_header.split(',')):
            return 304, b"", headers
    return 200, data, headers


directory_summary = DirectorySummary()
