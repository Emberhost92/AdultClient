"""Reusable upstream connections for explicitly marked live-cam media only."""

import http.client
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


class _CamResponse:
    def __init__(self, transport, key, connection, response, url):
        self._transport = transport
        self._key = key
        self._connection = connection
        self._response = response
        self._broken = False
        self.headers = response.headers
        self.status = response.status
        self.url = url

    def geturl(self):
        return self.url

    def read(self, size=-1):
        try:
            return self._response.read(size)
        except Exception:
            self._broken = True
            raise

    def close(self):
        connection, self._connection = self._connection, None
        if connection is None:
            return
        reusable = not self._broken and not self._response.will_close and self._response.isclosed()
        self._response.close()
        if reusable:
            self._transport.release(self._key, connection)
        else:
            connection.close()


class CamMediaTransport:
    def __init__(self, use_system_proxy=True):
        self._idle = {}
        self._lock = threading.Lock()
        self._use_system_proxy = use_system_proxy
        self._proxy_at = 0.0
        self._has_proxy = False
        self._tls_context = None

    def _proxy_enabled(self):
        if not self._use_system_proxy:
            return False
        now = time.monotonic()
        if now - self._proxy_at > 60 or not self._proxy_at:
            # Preserve the existing Windows/environment proxy configuration.
            proxies = urllib.request.getproxies()
            self._has_proxy = bool(proxies.get("http") or proxies.get("https"))
            self._proxy_at = now
        return self._has_proxy

    def take(self, key, timeout):
        with self._lock:
            entries = self._idle.get(key, [])
            while entries:
                at, connection = entries.pop()
                if time.monotonic() - at <= 20:
                    connection.timeout = timeout
                    if connection.sock is not None:
                        connection.sock.settimeout(timeout)
                    return connection, True
                connection.close()
            self._idle.pop(key, None)
        scheme, host, port = key
        if scheme == "https":
            return http.client.HTTPSConnection(host, port, timeout=timeout, context=self.tls_context()), False
        return http.client.HTTPConnection(host, port, timeout=timeout), False

    def tls_context(self):
        with self._lock:
            if self._tls_context is None:
                context = ssl.create_default_context()
                # Windows' Python roots can lag behind the browser's roots.
                # Add the installed Mozilla CA bundle, retaining verification.
                try:
                    import certifi
                except ImportError:
                    pass
                else:
                    context.load_verify_locations(cafile=certifi.where())
                self._tls_context = context
            return self._tls_context

    def release(self, key, connection):
        with self._lock:
            now = time.monotonic()
            for old_key in list(self._idle):
                kept = []
                for at, old in self._idle[old_key]:
                    if now - at <= 20:
                        kept.append((at, old))
                    else:
                        old.close()
                if kept:
                    self._idle[old_key] = kept
                else:
                    del self._idle[old_key]
            entries = self._idle.setdefault(key, [])
            # Keep the connections from a full page's segment wave. A four-
            # connection host cache discards most of a 36-cam wave and repeats
            # their TLS handshakes on the very next segment.
            if len(entries) >= 48 or sum(map(len, self._idle.values())) >= 64:
                connection.close()
                return
            entries.append((now, connection))

    def close(self):
        with self._lock:
            for entries in self._idle.values():
                for _at, connection in entries:
                    connection.close()
            self._idle.clear()

    def open(self, url, headers, timeout=15):
        if self._proxy_enabled():
            return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout, context=self.tls_context())
        deadline = time.monotonic() + timeout
        for redirect in range(6):
            parsed = urllib.parse.urlsplit(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Invalid cam media URL")
            key = (parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
            target = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
            for attempt in range(2):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Cam media timeout")
                connection, reused = self.take(key, remaining)
                try:
                    connection.request("GET", target, headers=headers)
                    response = connection.getresponse()
                    break
                except (OSError, http.client.HTTPException):
                    connection.close()
                    if not reused or attempt:
                        raise
            wrapped = _CamResponse(self, key, connection, response, url)
            if response.status in (301, 302, 303, 307, 308) and response.headers.get("Location"):
                next_url = urllib.parse.urljoin(url, response.headers["Location"])
                wrapped.close()
                if urllib.parse.urlsplit(next_url).netloc != parsed.netloc:
                    headers = {name: value for name, value in headers.items() if name.lower() not in ("cookie", "authorization")}
                url = next_url
                continue
            if response.status >= 400:
                wrapped.close()
                raise urllib.error.HTTPError(url, response.status, response.reason, response.headers, None)
            return wrapped
        raise urllib.error.URLError("Too many cam media redirects")


_transport = CamMediaTransport()


def open_cam_media(url, headers, timeout=15):
    return _transport.open(url, headers, timeout)
