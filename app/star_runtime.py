"""Bounded Star Finder work, persistent controls and public-source HTTP cache."""
from __future__ import annotations

import concurrent.futures
from contextlib import contextmanager
import copy
import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import weakref

JOBS = ("lang", "texts", "names", "more", "analvids", "scenes", "catalogs", "enrichment")
JOB_LABELS = {"lang":"Deutsche Texte", "texts":"Profile & Biografien", "names":"Neue Profile entdecken", "more":"Zusätzliche Fakten & Bilder", "analvids":"AnalVids-Katalog"}
DEFAULTS = {"paused":False,"speed":"balanced","interval":24,"prefetch":24,"jobs":{},"requests":{}}
PERFORMANCE = {
    'eco':dict(http=2,profiles=2,enrichment=1,scenes=1,translations=1,gap=1.5),
    'balanced':dict(http=4,profiles=2,enrichment=1,scenes=1,translations=1,gap=.55),
    'fast':dict(http=6,profiles=2,enrichment=2,scenes=2,translations=2,gap=.3),
    'turbo':dict(http=12,profiles=4,enrichment=4,scenes=3,translations=4,gap=.3),
    'maximum':dict(http=20,profiles=8,enrichment=6,scenes=4,translations=6,gap=.3),
}


class SourceError(Exception):
    def __init__(self, reason, retry_at=0):
        super().__init__(reason)
        self.reason = reason
        self.retry_at = retry_at


class StarRuntime:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.config = copy.deepcopy(DEFAULTS)
        saved = store.settings()
        self.config.update({key:value for key,value in saved.items() if key in DEFAULTS})
        if self.config.get("speed") not in PERFORMANCE:
            self.config["speed"] = "balanced"
        for key,allowed in (("interval",(6,12,24,48,168)),("prefetch",(12,24,48,96))):
            if self.config.get(key) not in allowed:self.config[key]=DEFAULTS[key]
        for key in ("jobs","requests"):
            if not isinstance(self.config.get(key),dict):self.config[key]={}
        self.config["jobs"]={key:bool(value) for key,value in self.config["jobs"].items() if key in JOBS}
        self.config["requests"]={key:float(value) for key,value in self.config["requests"].items() if key in JOBS and isinstance(value,(int,float))}
        self.active = 0
        self.pending = {}
        self.consumed = dict(self.config["requests"])
        self.hosts = {}
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="star-profile")
        self.priority_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="star-profile-now")
        self.worker_active = {}
        self.local = threading.local()
        self.key_locks = weakref.WeakValueDictionary()

    def key_lock(self, key):
        with self.lock:
            lock = self.key_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self.key_locks[key] = lock
            return lock

    def public(self):
        with self.lock:
            return {"settings":copy.deepcopy(self.config), "active":self.active,
                    "performance":dict(PERFORMANCE[self.config['speed']]),"workers_active":dict(self.worker_active),
                    "pending":len(self.pending), "sources":[{"host":host,"requests":row["requests"],
                      "cached":row["cached"],"error":row.get("error", ""),"retry_at":row.get("cool", 0)} for host,row in self.hosts.items()]}

    def control(self, body):
        with self.condition:
            operation = body.get("op")
            job = body.get("job")
            if operation in ("pause", "resume"):
                if job == "all":
                    self.config["paused"] = operation == "pause"
                elif job in JOBS:
                    self.config["jobs"][job] = operation == "pause"
                else:
                    raise ValueError("Unbekannter Lauf.")
            elif operation == "run":
                targets = JOBS if job == "all" else (job,)
                if any(target not in JOBS for target in targets):
                    raise ValueError("Unbekannter Lauf.")
                for target in targets:
                    self.config["requests"][target] = time.time()
                    self.config["jobs"][target] = False
                # A scheduled check must not silently cancel the global pause.
            elif operation == "settings":
                for key, allowed in (("speed",tuple(PERFORMANCE)),("interval",(6,12,24,48,168)),("prefetch",(12,24,48,96))):
                    if key in body:
                        if body[key] not in allowed:
                            raise ValueError("Ungültige Einstellung: "+key)
                        self.config[key] = body[key]
            else:
                raise ValueError("Unbekannte Aktion.")
            self.store.save_settings(self.config)
            self.condition.notify_all()
        return {"ok":True, **self.public()}

    def paused(self, job):
        return bool(self.config["paused"] or self.config["jobs"].get(job))

    @staticmethod
    def thread_job():
        name = threading.current_thread().name
        if name.startswith(("star-lang", "star-text-lang", "star-text-backfill")): return "lang"
        if name.startswith("star-more"): return "more"
        if name.startswith("star-names"): return "names"
        if name.startswith("star-text"): return "texts"
        if "analvids" in name: return "analvids"
        if name.startswith("star-box"): return "scenes"
        if name.startswith('star-catalogs'):return 'catalogs'
        if name.startswith('star-enrichment'):return 'enrichment'
        if name.startswith('star-profile'):return 'enrichment'
        if name.startswith('star-filter'):return 'enrichment'
        return ""

    def wait(self, job=None):
        job = job or self.thread_job()
        with self.condition:
            while job and self.paused(job):
                self.condition.wait(1)

    def due(self, job, next_at):
        self.wait(job)
        with self.lock:
            token = self.config["requests"].get(job, 0)
            if token > self.consumed.get(job, 0):
                self.consumed[job] = token
                return 0
        return next_at

    def interval(self):
        return int(self.config["interval"])*3600

    def limit(self, lane):
        return PERFORMANCE[self.config['speed']][lane]

    def wait_worker(self, lane, index, job, stop=None):
        with self.condition:
            while self.paused(job) or index >= self.limit(lane):
                if stop is not None and stop.is_set():return False
                self.condition.wait(.5)
            return stop is None or not stop.is_set()

    @contextmanager
    def work_slot(self, lane, job):
        with self.condition:
            while self.paused(job) or self.worker_active.get(lane,0)>=self.limit(lane):
                self.condition.wait(.5)
            self.worker_active[lane]=self.worker_active.get(lane,0)+1
        try:yield
        finally:
            with self.condition:
                self.worker_active[lane]-=1
                self.condition.notify_all()

    @contextmanager
    def fresh_requests(self):
        previous=getattr(self.local,'fresh',False)
        self.local.fresh=True
        try:yield
        finally:self.local.fresh=previous

    def submit(self, key, fn, priority=False):
        with self.lock:
            existing = self.pending.get(key)
            if existing:
                return existing
            if len(self.pending) >= 200:
                return None
            def work():
                if priority:
                    self.wait('enrichment')
                    return fn()
                with self.work_slot('profiles','enrichment'):
                    return fn()
            future = (self.priority_pool if priority else self.pool).submit(work)
            self.pending[key] = future
            future.add_done_callback(lambda done:self._finished(key, done))
            return future

    def _finished(self, key, future):
        with self.lock:
            if self.pending.get(key) is future:
                self.pending.pop(key, None)

    def request(self, url, headers=None, ttl=86400, limit=3_000_000, timeout=12, cooldown_host=True, data=None):
        self.wait()
        with self.key_lock("http:"+self.http_key(url,headers,data)):
            self.wait()
            return self._request(url,headers,ttl,limit,timeout,cooldown_host,data)

    @staticmethod
    def http_key(url,headers=None,data=None):
        auth=str((headers or {}).get("Authorization", ""))+str((headers or {}).get("ApiKey", ""))
        return hashlib.sha256((url+"\0"+auth).encode()+(data or b"")).hexdigest()

    def _request(self, url, headers=None, ttl=86400, limit=3_000_000, timeout=12, cooldown_host=True, data=None):
        self.local.observed_at = None
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
            raise SourceError("invalid")
        host = parsed.hostname.lower()
        key = self.http_key(url,headers,data)
        cached = self.store.cached("http", key) if ttl and not getattr(self.local,'fresh',False) else None
        with self.lock:
            state = self.hosts.setdefault(host, {"requests":0,"cached":0,"next":0,"cool":0,"error":""})
            if cached:
                state["cached"] += 1
                self.local.observed_at = cached.get("at")
                return cached
            failure = self.store.cached("http-error",key)
            if failure:
                state["error"] = failure["reason"]
                if failure.get("host_cool"):state["cool"] = max(state["cool"],failure["retry_at"])
                raise SourceError(failure["reason"],failure["retry_at"])
            if state["cool"] > time.time():
                raise SourceError(state["error"] or "rate-limit", state["cool"])
        # Separate source slots from Kodi routing and UI requests. The limit is
        # adjustable, but a single source is never hammered in a tight loop.
        with self.condition:
            job = self.thread_job()
            while (job and self.paused(job)) or self.active >= self.limit('http') or state["next"] > time.monotonic():
                if state['cool']>time.time():raise SourceError(state['error'] or 'rate-limit',state['cool'])
                self.condition.wait(.25)
            if state['cool']>time.time():raise SourceError(state['error'] or 'rate-limit',state['cool'])
            self.active += 1
            gap = self.limit('gap')
            state["next"] = time.monotonic()+gap
        try:
            request = urllib.request.Request(url, data=data, headers={"User-Agent":"AdultHideoutWeb/StarFinder (local personal metadata client)","Accept":"application/json,text/html;q=0.9,*/*;q=0.5",**(headers or {})})
            # API credentials must never follow a redirect to another recipient.
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self,*args,**kwargs):return None
            open_request=urllib.request.build_opener(NoRedirect()).open if data is not None else urllib.request.urlopen
            with open_request(request, timeout=timeout) as response:
                raw = response.read(limit+1)
                if len(raw)>limit:
                    raise SourceError("too-large")
                result = {"body":raw.decode("utf-8","replace"),"url":response.geturl(),"type":response.headers.get("Content-Type", ""),"at":time.time()}
            with self.lock:
                state["requests"] += 1
                state["error"] = ""
            if ttl:
                self.store.cache("http",key,result,ttl)
            self.local.observed_at = result["at"]
            return result
        except urllib.error.HTTPError as error:
            status = error.code
            try:
                delay = min(86400,max(60,int(error.headers.get("Retry-After") or 300)))
            except ValueError:
                delay = 300
            error.close()
            reason = "missing" if status==404 else "rate-limit" if status==429 else "blocked" if status in (401,403) else "http"
            with self.lock:
                state["error"] = reason
                if status in (429,503): state["cool"] = time.time()+delay
                elif status in (401,403) and cooldown_host: state["cool"] = time.time()+1800
            if status in (401,403,404,429,503):
                retry = time.time()+(86400 if status==404 else 1800 if status in (401,403) else max(60,state["cool"]-time.time()))
                self.store.cache("http-error",key,{"reason":reason,"retry_at":retry,"host_cool":status in (429,503) or status in (401,403) and cooldown_host},retry-time.time())
            raise SourceError(reason,state["cool"]) from None
        except (OSError, ValueError):
            with self.lock:
                state["error"] = "timeout"
            raise SourceError("timeout") from None
        finally:
            with self.condition:
                self.active -= 1
                self.condition.notify_all()

    def json(self, url, headers=None, ttl=86400):
        response = self.request(url,headers,ttl)
        try:
            payload = json.loads(response["body"])
            if isinstance(payload,dict) and payload.get("error"):
                # Wikimedia maxlag and similar API errors are HTTP 200 responses.
                # They must never remain in the successful one-day response cache.
                key=hashlib.sha256((url+"\0"+str((headers or {}).get("Authorization", ""))).encode()).hexdigest()
                self.store.discard_cache("http",key)
                error=payload["error"] if isinstance(payload["error"],dict) else {}
                reason="rate-limit" if error.get("code") in ("maxlag","ratelimited","readonly") else "source-error"
                retry=time.time()+60
                with self.lock:
                    state=self.hosts[urllib.parse.urlsplit(url).hostname.lower()]
                    state["error"]=reason;state["cool"]=retry
                raise SourceError(reason,retry)
            if isinstance(payload,dict):
                payload["_observed_at"] = response["at"]
            return payload
        except (ValueError, TypeError):
            key=hashlib.sha256((url+"\0"+str((headers or {}).get("Authorization", ""))).encode()).hexdigest()
            self.store.discard_cache("http",key)
            raise SourceError("invalid-json") from None

    def close(self):
        self.priority_pool.shutdown(wait=True)
        self.pool.shutdown(wait=True)
