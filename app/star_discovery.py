"""Incremental sitemap discovery with durable per-URL completion and retries."""
from __future__ import annotations
import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET


def valid_sitemap(path):
    try:
        tag=''
        for _,node in ET.iterparse(path,events=('end',)):
            tag=node.tag.rsplit('}',1)[-1]
            node.clear()
        return tag in ('urlset','sitemapindex')
    except (OSError,ET.ParseError):return False


def sitemap_sources(app,runtime):
    """Discover published profile maps; keep the last known list on source failure."""
    saved=runtime.store.cached('sitemap-sources','babepedia') or {}
    sources=list(saved.get('urls') or app._BABE_SITEMAPS)
    try:
        response=runtime.request('https://www.babepedia.com/sitemap.xml',ttl=runtime.interval(),limit=500000,cooldown_host=False)
        root=ET.fromstring(response['body'])
        found=[]
        for node in root.iter():
            if node.tag.rsplit('}',1)[-1]!='loc':continue
            url=(node.text or '').strip();parsed=urllib.parse.urlsplit(url)
            if parsed.scheme=='https' and parsed.hostname in ('www.babepedia.com','babepedia.com') and re.fullmatch(r'/sitemapmain\d+\.xml',parsed.path):found.append(url)
        if found:
            sources=list(dict.fromkeys(sources+found))
            runtime.store.cache('sitemap-sources','babepedia',{'urls':sources,'at':response.get('at')},10**12)
        app._babe_run['sitemap_error']=''
    except Exception:
        app._babe_run['sitemap_error']='Der Sitemap-Index antwortet nicht; die bekannten Profillisten bleiben erhalten.'
    return sources


class DiscoveryQueue:
    def __init__(self, store):
        self.store=store
        with store.lock,store.db:
            store.db.executescript("""
              CREATE TABLE IF NOT EXISTS discovery(url TEXT PRIMARY KEY,source TEXT NOT NULL,lastmod TEXT,
                state TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,
                next_at REAL NOT NULL DEFAULT 0,updated REAL NOT NULL DEFAULT 0,error TEXT NOT NULL DEFAULT '');
              CREATE INDEX IF NOT EXISTS discovery_ready ON discovery(state,next_at,updated);
            """)
            # The process owns this queue. Interrupted claims are retried;
            # completed URLs never depend on a shifting numeric XML offset.
            store.db.execute("UPDATE discovery SET state='pending' WHERE state='running'")

    def seed(self,path,source,known=lambda url:False):
        stat=os.stat(path);fingerprint=str(stat.st_mtime_ns)+':'+str(stat.st_size)
        cached=self.store.cached('sitemap-manifest',source)
        if cached and cached.get('fingerprint')==fingerprint:
            return 0
        entries=[]
        # Parse and validate the whole input before changing the queue, so a
        # truncated download cannot masquerade as a completed source snapshot.
        for _,node in ET.iterparse(path,events=('end',)):
            if node.tag.rsplit('}',1)[-1]!='url':
                continue
            fields={child.tag.rsplit('}',1)[-1]:(child.text or '').strip() for child in node}
            url=fields.get('loc','');parsed=urllib.parse.urlsplit(url)
            if parsed.scheme=='https' and parsed.hostname in ('babepedia.com','www.babepedia.com') and parsed.path.startswith('/babe/'):
                entries.append((url,source,fields.get('lastmod',''),bool(known(url))))
            node.clear()
        added=0
        with self.store.lock,self.store.db:
            for url,source,lastmod,is_known in entries:
                old=self.store.db.execute('SELECT lastmod FROM discovery WHERE url=?',(url,)).fetchone()
                if not old:
                    self.store.db.execute('INSERT INTO discovery(url,source,lastmod,state,updated) VALUES(?,?,?,?,?)',(url,source,lastmod,'done' if is_known else 'pending',time.time()))
                    added+=not is_known
                elif lastmod and old[0]!=lastmod:
                    self.store.db.execute("UPDATE discovery SET lastmod=?,state='pending',attempts=0,next_at=0,error='' WHERE url=?",(lastmod,url))
            self.store.cache('sitemap-manifest',source,{'fingerprint':fingerprint},10**12)
        return added

    def claim(self):
        with self.store.lock,self.store.db:
            row=self.store.db.execute("SELECT url FROM discovery WHERE state IN ('pending','error') AND next_at<=? ORDER BY attempts,updated DESC LIMIT 1",(time.time(),)).fetchone()
            if not row:
                return None
            self.store.db.execute("UPDATE discovery SET state='running' WHERE url=?",row)
            return row[0]

    def complete(self,url,error=''):
        with self.store.lock,self.store.db:
            row=self.store.db.execute('SELECT attempts FROM discovery WHERE url=?',(url,)).fetchone()
            if not row:
                return
            attempts=row[0]+1 if error else 0
            retry=time.time()+(7*86400 if error=='missing' else min(86400,300*2**min(attempts,8))) if error else 0
            self.store.db.execute('UPDATE discovery SET state=?,attempts=?,next_at=?,updated=?,error=? WHERE url=?',('error' if error else 'done',attempts,retry,time.time(),error,url))

    def status(self):
        with self.store.lock:
            rows=dict(self.store.db.execute('SELECT state,count(*) FROM discovery GROUP BY state'))
            retry=self.store.db.execute("SELECT min(next_at) FROM discovery WHERE state='error'").fetchone()[0]
        return {'total':sum(rows.values()),'done':rows.get('done',0),'pending':rows.get('pending',0),'active':rows.get('running',0),'failed':rows.get('error',0),'retry_at':retry or 0}


def run(app):
    runtime=app._star_runtime_hub()
    queue=DiscoveryQueue(runtime.store)
    saved=app._job_cursor_get('names')
    next_at=float(saved.get('next') or 0)
    pool=app.futures.ThreadPoolExecutor(max_workers=4,thread_name_prefix='star-names')
    known_names=set()

    def known(url):
        name=urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit('/',1)[-1]).replace('_',' ').casefold()
        return name in known_names

    def work(url):
        try:
            app._babe_take_loc(url)
            name=urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit('/',1)[-1]).replace('_',' ')
            index=app.star_index();pos=index['by_name'].get(name.casefold())
            key=index['cards'][pos]['id'] if pos is not None else 'bp:'+urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit('/',1)[-1])
            rec=app._star_extra_get(key) or {}
            error=rec.get('reason') if rec.get('reason') in ('timeout','http','blocked','rate-limit','redirect','missing') else ''
            with app._star_extra_lock:
                app._star_extra_save(force=True)
            queue.complete(url,error)
        except Exception:
            queue.complete(url,'source')

    while True:
        next_at=runtime.due('names',next_at)
        if next_at>time.time():
            with app._babe_guard:
                app._babe_pos['next']=next_at;app._babe_run['names']=False
            with runtime.condition:runtime.condition.wait(min(5,next_at-time.time()))
            continue
        try:
            index=app.star_index();known_names=set(index['by_name'])
            with app._star_extra_lock:
                known_names.update(str(row.get('name') or '').casefold() for row in app._star_extra_load()['people'] if isinstance(row,dict))
            app._BABE_SITEMAPS=tuple(sitemap_sources(app,runtime))
            for i,source in enumerate(app._BABE_SITEMAPS):
                runtime.wait('names')
                path=app._babe_sitemap(i)
                queue.seed(path,source,known)
            inflight=[]
            while True:
                runtime.wait('names')
                url=queue.claim()
                if not url:
                    app._star_drain(inflight)
                    break
                with app._babe_guard:
                    app._babe_run['names']=True;app._babe_run['name_current']=urllib.parse.unquote(url.rsplit('/',1)[-1]).replace('_',' ')
                inflight.append(pool.submit(work,url))
                if len(inflight)>=4:
                    inflight.pop(0).result()
                status=queue.status()
                with app._babe_guard:
                    app._babe_pos.update(seen=status['done']+status['failed'],locs=status['total'],next=0)
            status=queue.status();next_at=time.time()+runtime.interval()
            if status['retry_at']:
                next_at=min(next_at,max(time.time()+30,status['retry_at']))
            with app._babe_guard:
                app._babe_pos.update(seen=status['done']+status['failed'],locs=status['total'],next=next_at)
                app._babe_run.update(names=False,name_current='',name_errors=status['failed'])
            app._job_cursor_put('names',{'next':next_at,'seen':status['done'],'locs':status['total'],'done':not status['pending'],'checkpoint':time.time()},force=True)
        except Exception:
            app.debug_log('server','star','Die Namensquelle antwortet nicht; gespeicherte Aufgaben bleiben erhalten.')
            next_at=time.time()+600
            with app._babe_guard:
                app._babe_run['names']=False
                app._babe_pos['next']=next_at
