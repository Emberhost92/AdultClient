"""Incremental, transactional Star Finder persistence. Standard library only."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import threading
import time
import zlib


class Records(dict):
    """Keep the legacy in-memory interface, recording changed/deleted keys."""
    def __init__(self, rows=()):
        super().__init__(rows)
        self.changed = set()
        self.deleted = set()
        self.reset = False

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.changed.add(key)
        self.deleted.discard(key)

    def __delitem__(self, key):
        super().__delitem__(key)
        self.changed.discard(key)
        self.deleted.add(key)

    def pop(self, key, *default):
        if key not in self:
            return super().pop(key, *default)
        value = self[key]
        del self[key]
        return value

    def clear(self):
        super().clear()
        self.changed.clear()
        self.deleted.clear()
        self.reset = True

    def update(self, values=(), **kwargs):
        for key, value in dict(values, **kwargs).items():
            self[key] = value

    def setdefault(self, key, default=None):
        if key not in self:
            self[key] = default
        return self[key]


class StarStore:
    def __init__(self, profile):
        self.path = os.path.join(profile, "star_data.sqlite3")
        self.legacy = os.path.join(profile, "star_extra.json")
        self.lock = threading.RLock()
        self.state = None
        self.people = Records()
        self.meta_stamp = ""
        self.last_write_rows = 0
        self.cache_written = 0
        self.last_trim = 0
        os.makedirs(profile, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=20, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA busy_timeout=20000")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS records(bucket TEXT NOT NULL, key TEXT NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY(bucket,key));
          CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS cache(kind TEXT NOT NULL,key TEXT NOT NULL,payload TEXT NOT NULL,expires REAL NOT NULL,
            PRIMARY KEY(kind,key));
          CREATE INDEX IF NOT EXISTS cache_expiry ON cache(kind,expires);
          CREATE INDEX IF NOT EXISTS cache_expiry_all ON cache(expires);
        """)
        self.db.commit()

    @staticmethod
    def encode(value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def load(self):
        with self.lock:
            if self.state is not None:
                return self.state
            marker = self.db.execute("SELECT payload FROM metadata WHERE key='state'").fetchone()
            if marker:
                state = json.loads(marker[0])
                for bucket in ("profiles", "lang"):
                    state[bucket] = Records((key, json.loads(raw)) for key, raw in self.db.execute(
                        "SELECT key,payload FROM records WHERE bucket=?", (bucket,)))
                legacy_people = state.get("people")
                self.people = Records((key,json.loads(raw)) for key,raw in self.db.execute("SELECT key,payload FROM records WHERE bucket='people'"))
                if isinstance(legacy_people,list):
                    self.people.update((str(row["id"]),row) for row in legacy_people if isinstance(row,dict) and row.get("id"))
                state["people"] = list(self.people.values())
                self.state = state
                self.meta_stamp = self.encode({key: value for key, value in state.items() if key not in ("profiles", "lang", "people")})
                if isinstance(legacy_people,list):
                    self.meta_stamp = ""
                    self.flush()
                return state
            state = {"version":1,"trends":[],"profiles":{},"covers":{},"lang":{},"people":[],"sync":{}}
            if os.path.isfile(self.legacy):
                # Invalid input is an explicit startup error, never an empty import
                # that would silently replace the user's existing collection.
                with open(self.legacy, encoding="utf-8") as handle:
                    loaded = json.load(handle)
                if not isinstance(loaded, dict):
                    raise ValueError("Die bestehende Profildatei ist ungültig und wurde nicht verändert.")
                for key, default in state.items():
                    if isinstance(loaded.get(key), type(default)):
                        state[key] = loaded[key]
                state.update({key:value for key,value in loaded.items() if key not in state})
                backup = self.legacy + ".before-sqlite.bak"
                if not os.path.exists(backup):
                    shutil.copy2(self.legacy, backup)
            for bucket in ("profiles", "lang"):
                state[bucket] = Records(state[bucket])
                state[bucket].changed.update(state[bucket])
            self.state = state
            self.people.update((str(row["id"]),row) for row in state["people"] if isinstance(row,dict) and row.get("id"))
            self.flush()
            return state

    def flush(self, records_only=False):
        with self.lock:
            if self.state is None:
                return
            pending = []
            for bucket in ("profiles", "lang"):
                rows = self.state[bucket]
                if not isinstance(rows, Records):
                    rows = Records(rows)
                    rows.reset = True
                    rows.changed.update(rows)
                    self.state[bucket] = rows
                pending.append((bucket, rows))
            pending.append(("people", self.people))
            metadata = None if records_only else self.encode({key:value for key,value in self.state.items() if key not in ("profiles", "lang", "people")})
            written = 0
            # Dirty flags are cleared only after COMMIT. A disk failure leaves
            # both the last durable transaction and the retryable changes intact.
            with self.db:
                for bucket, rows in pending:
                    if rows.reset:
                        self.db.execute("DELETE FROM records WHERE bucket=?", (bucket,))
                    self.db.executemany("DELETE FROM records WHERE bucket=? AND key=?", ((bucket, str(key)) for key in rows.deleted))
                    updates = [(bucket, str(key), self.encode(rows[key])) for key in rows.changed if key in rows]
                    self.db.executemany("INSERT INTO records VALUES(?,?,?) ON CONFLICT(bucket,key) DO UPDATE SET payload=excluded.payload", updates)
                    written += len(updates) + len(rows.deleted)
                if metadata is not None and metadata != self.meta_stamp:
                    self.db.execute("INSERT INTO metadata VALUES('state',?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload", (metadata,))
            for _, rows in pending:
                rows.changed.clear()
                rows.deleted.clear()
                rows.reset = False
            if metadata is not None:
                self.meta_stamp = metadata
            self.last_write_rows = written

    @property
    def dirty(self):
        if self.state is None:
            return False
        return bool(self.people.changed or self.people.deleted) or any(not isinstance(self.state.get(bucket), Records) or self.state[bucket].changed or self.state[bucket].deleted or self.state[bucket].reset for bucket in ("profiles", "lang"))

    def put_person(self, row):
        self.people[str(row["id"])] = row

    def remove_people(self, keys):
        for key in keys:
            self.people.pop(str(key),None)

    def cached(self, kind, key):
        with self.lock:
            row = self.db.execute("SELECT payload FROM cache WHERE kind=? AND key=? AND expires>?", (kind, key, time.time())).fetchone()
        if not row:
            return None
        payload = row[0]
        if isinstance(payload,bytes) and payload.startswith(b"AHZ1"):
            payload = zlib.decompress(payload[4:])
        return json.loads(payload)

    def read_rows(self, query, parameters=()):
        """A WAL snapshot for large projections without holding the writer lock."""
        from pathlib import Path
        connection = sqlite3.connect(Path(self.path).resolve().as_uri()+"?mode=ro", uri=True, timeout=5)
        try:
            return connection.execute(query, parameters).fetchall()
        finally:
            connection.close()

    def cache(self, kind, key, payload, seconds):
        payload = self.encode(payload)
        if len(payload)>1024:
            payload = sqlite3.Binary(b"AHZ1"+zlib.compress(payload.encode(),3))
        with self.lock, self.db:
            self.db.execute("INSERT INTO cache VALUES(?,?,?,?) ON CONFLICT(kind,key) DO UPDATE SET payload=excluded.payload,expires=excluded.expires",
                            (kind, key, payload, time.time()+seconds))
            self.cache_written += len(payload)
            if self.cache_written>2_000_000 or time.monotonic()-self.last_trim>60:
                self.db.execute("DELETE FROM cache WHERE expires<?",(time.time(),))
                while self.db.execute("SELECT coalesce(sum(length(payload)),0) FROM cache WHERE kind='http'").fetchone()[0]>256*1024*1024:
                    self.db.execute("DELETE FROM cache WHERE kind='http' AND key IN (SELECT key FROM cache WHERE kind='http' ORDER BY expires LIMIT 100)")
                self.cache_written = 0
                self.last_trim = time.monotonic()

    def settings(self):
        with self.lock:
            row = self.db.execute("SELECT payload FROM metadata WHERE key='settings'").fetchone()
        return json.loads(row[0]) if row else {}

    def discard_cache(self, kind, key):
        with self.lock,self.db:
            self.db.execute("DELETE FROM cache WHERE kind=? AND key=?",(kind,key))

    def save_settings(self, settings):
        with self.lock, self.db:
            self.db.execute("INSERT INTO metadata VALUES('settings',?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload", (self.encode(settings),))

    def close(self):
        with self.lock:
            self.flush()
            self.db.close()


def resume_position(work, saved):
    """A stable identity survives insertions; an unverified numeric offset does not."""
    key = str(saved.get("key") or saved.get("id") or "")
    if key:
        for index, (ident, _) in enumerate(work):
            if str(ident) == key:
                return index + 1
        return 0
    if int(saved.get("total") or 0) == len(work):
        return max(0, min(len(work), int(saved.get("index") or 0)))
    return 0


def text_key(text, language="de"):
    return hashlib.sha256((language+"\0"+text).encode()).hexdigest()


def utf8_chunks(text, limit=450):
    current = ""
    size = 0
    for char in text:
        length = len(char.encode("utf-8"))
        if current and size+length>limit:
            yield current
            current = ""
            size = 0
        current += char
        size += length
    if current:
        yield current
