"""Short-lived, bounded live discovery reuse and stable compact studio pages."""
import copy
import threading
import time
import uuid


class ResolverCache:
    def __init__(self, ttl=10, maximum=128):
        self.ttl=ttl;self.maximum=maximum;self.lock=threading.RLock()
        self.rows={};self.pending={};self.versions={}

    def invalidate(self,site):
        with self.lock:
            self.versions[site]=self.versions.get(site,0)+1
            self.rows={k:v for k,v in self.rows.items() if k[0]!=site}

    def resolve(self,key,fetch,fresh=False):
        with self.lock:
            version=self.versions.get(key[0],0);token=(*key,version)
            now=time.monotonic()
            self.rows={k:v for k,v in self.rows.items() if now-v[0]<self.ttl}
            if not fresh and token in self.rows:return copy.deepcopy(self.rows[token][1])
            pending=self.pending.get(token)
            if pending is None:
                pending=threading.Event();self.pending[token]=pending;owner=True
            else:owner=False
        if not owner:
            if not pending.wait(20):return {'ok':False,'error':'Die Streamprüfung dauert noch an. Bitte erneut prüfen.'}
            with self.lock:
                row=self.rows.get(token)
                if row and time.monotonic()-row[0]<self.ttl:return copy.deepcopy(row[1])
            # A failed or cancelled lookup must not start an immediate retry wave.
            return {'ok':False,'error':'Der Raum konnte nicht bestätigt werden. Bitte erneut prüfen.'}
        try:
            result=fetch()
            if result.get('ok') and result.get('path'):
                with self.lock:
                    if self.versions.get(key[0],0)==version:
                        if len(self.rows)>=self.maximum:self.rows.pop(next(iter(self.rows)))
                        self.rows[token]=(time.monotonic(),copy.deepcopy(result))
            return result
        finally:
            with self.lock:self.pending.pop(token,None);pending.set()


class StudioSnapshots:
    def __init__(self,ttl=90,maximum=3):
        self.lock=threading.Lock();self.rows={};self.ttl=ttl;self.maximum=maximum

    def put(self,data):
        with self.lock:
            now=time.monotonic();self.rows={k:v for k,v in self.rows.items() if now-v[0]<self.ttl}
            if len(self.rows)>=self.maximum:self.rows.pop(next(iter(self.rows)))
            key=uuid.uuid4().hex;self.rows[key]=(now,data);return key

    def page(self,key,offset,limit):
        with self.lock:
            row=self.rows.get(key)
            if not row or time.monotonic()-row[0]>=self.ttl:
                self.rows.pop(key,None);return None
            data=row[1]
            # Callers enrich only the requested rows, never mutate the snapshot.
            return {**data,'items':[dict(item) for item in data['items'][offset:offset+limit]],'snapshot':key}


resolver_cache=ResolverCache()
studio_snapshots=StudioSnapshots()
