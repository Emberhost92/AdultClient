"""Portable-only settings, data package checks and opt-in resumable image storage."""
import gzip
from contextlib import closing
import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from update_engine import Updates, save


def write_json(path, data):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');os.replace(temp,path)


def merge_pending(profile):
    """Only before the server opens SQLite. Personal tables and metadata stay intact."""
    pending=profile/'updates'/'pending.sqlite3'
    if not pending.exists():return
    target=profile/'star_data.sqlite3'
    from export_models import TABLES, CACHES, decode
    with closing(sqlite3.connect(pending)) as source, source:
        if source.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('Modelldaten sind beschädigt.')
    if not target.exists():
        os.replace(pending,target)
        manifest=profile/'updates'/'pending.json'
        if manifest.exists():os.replace(manifest,profile/'model-package.json')
        return
    with closing(sqlite3.connect(target)) as dest, dest:
        with closing(sqlite3.connect(profile/'updates'/'before-update.sqlite3')) as backup, backup:dest.backup(backup)
        dest.execute('ATTACH DATABASE ? AS incoming',(str(pending),))
        with dest:
            for table in TABLES:
                if table=='metadata':continue
                columns=[r[1] for r in dest.execute('PRAGMA main.table_info('+table+')')]
                incoming=[r[1] for r in dest.execute('PRAGMA incoming.table_info('+table+')')]
                if not columns or incoming!=columns:raise ValueError('Unpassendes Datenpaket: '+table)
                for row in dest.execute('SELECT * FROM incoming.'+table):
                    if table=='records':
                        if row[0] not in ('profiles','lang','people'):continue
                        old=dest.execute('SELECT payload FROM main.records WHERE bucket=? AND key=?',row[:2]).fetchone()
                        if old and float(decode(old[0]).get('at') or 0)>float(decode(row[2]).get('at') or 0):continue
                    if table=='cache' and row[0] not in CACHES:continue
                    dest.execute('INSERT OR REPLACE INTO main.'+table+' VALUES('+','.join('?' for _ in row)+')',row)
            dest.execute("DELETE FROM cache WHERE kind IN ('ui-source-cards','filter-projection')")
    pending.unlink()
    manifest=profile/'updates'/'pending.json'
    if manifest.exists():os.replace(manifest,profile/'model-package.json')


class Portable(Updates):
    def __init__(self, app, root, profile):
        self.app,self.root,self.profile=app,root,profile
        self.config=json.loads((root/'release.json').read_text(encoding='utf-8'))
        self.stop=threading.Event();self.guard=threading.Lock();self.running=False
        self.task={'running':False,'done':0,'failed':0,'bytes':0,'message':'Bilder werden nur bei Bedarf geladen.'}
        self.latest=None;self.update_task={'running':False,'message':''}
        self.image_dir=profile/'offline-model-images'
        self.image_db=profile/'offline-model-images.sqlite3'
        with closing(sqlite3.connect(self.image_db)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS images(key TEXT PRIMARY KEY,url TEXT,status TEXT,bytes INTEGER,mime TEXT)')
        self.init_updates()

    def status(self):
        with closing(sqlite3.connect(self.image_db)) as db, db:
            done,size=db.execute("SELECT count(*),coalesce(sum(bytes),0) FROM images WHERE status='done'").fetchone()
        return {**self.update_status(),'ok':True,'version':self.config['version'],'repository':self.config.get('repository',''),
                'package':json.loads((self.profile/'model-package.json').read_text()) if (self.profile/'model-package.json').exists() else None,
                'images':{**self.task,'stored':done,'stored_bytes':size},'latest':self.latest,'update':self.update_task,
                'pending':(self.profile/'updates'/'pending.sqlite3').exists(),
                'update_error':(self.profile/'update-error.txt').read_text(encoding='utf-8') if (self.profile/'update-error.txt').exists() else ''}

    def cached_image(self,url):
        key=hashlib.sha256(url.split('|',1)[0].encode()).hexdigest()
        path=self.image_dir/key
        if not path.exists():return None
        with closing(sqlite3.connect(self.image_db)) as db, db:row=db.execute("SELECT mime FROM images WHERE key=? AND status='done'",(key,)).fetchone()
        return (path.read_bytes(),row[0]) if row else None

    def image_urls(self):
        # Union deduplicates remote addresses; a separate read-only connection avoids the UI lock.
        source=(self.profile/'star_data.sqlite3').as_uri()+'?mode=ro'
        with closing(sqlite3.connect(source,uri=True)) as db, db:
            for (url,) in db.execute('SELECT DISTINCT url FROM source_gallery ORDER BY url'):yield url
            for (payload,) in db.execute("SELECT payload FROM records WHERE bucket IN ('profiles','people')"):
                row=json.loads(payload)
                for url in row.get('images') or []:
                    if isinstance(url,str):yield url
                if row.get('thumb'):yield row['thumb']
            from export_models import decode
            for (payload,) in db.execute("SELECT payload FROM cache WHERE kind='sources'"):
                for row in (decode(payload).get('sources') or {}).values():
                    for image in row.get('images') or []:
                        if isinstance(image,dict) and image.get('url'):yield image['url']
            for (payload,) in db.execute('SELECT payload FROM source_catalog'):
                for image in decode(payload).get('images') or []:
                    if isinstance(image,dict) and image.get('url'):yield image['url']
        import gzip
        path=self.root/'addon'/'resources'/'data'/'star_index.json.gz'
        if path.exists():
            with gzip.open(path,'rt',encoding='utf-8') as f:
                for row in json.load(f).get('performers',[]):
                    if row.get('thumb'):yield row['thumb']

    def download_images(self):
        from PIL import Image
        try:
            self.image_dir.mkdir(parents=True,exist_ok=True)
            with closing(sqlite3.connect(self.image_db)) as db, db:
                for raw_url in self.image_urls():
                    if self.stop.is_set():break
                    url,headers=self.app.split_kodi_url(raw_url)
                    p=urllib.parse.urlsplit(url)
                    if p.scheme!='https' or not p.hostname or p.username:continue
                    try:
                        if ipaddress.ip_address(p.hostname).is_private:continue
                    except ValueError:
                        if p.hostname.lower()=='localhost':continue
                    key=hashlib.sha256(url.encode()).hexdigest()
                    if db.execute("SELECT 1 FROM images WHERE key=? AND status='done'",(key,)).fetchone():continue
                    path=self.image_dir/key;temp=path.with_suffix('.part')
                    try:
                        safe={'User-Agent':'Mozilla/5.0','Referer':p.scheme+'://'+p.netloc+'/'}
                        safe.update({k:v for k,v in headers.items() if k.lower() in ('user-agent','referer','origin')})
                        with urllib.request.urlopen(urllib.request.Request(url,headers=safe),timeout=15) as response:
                            data=response.read(40_000_001)
                        if len(data)>40_000_000:raise ValueError('Bild größer als 40 MB')
                        with Image.open(io.BytesIO(data)) as img:
                            img.verify();mime=Image.MIME.get(img.format,'image/jpeg')
                        temp.write_bytes(data);os.replace(temp,path)
                        db.execute('INSERT OR REPLACE INTO images VALUES(?,?,?,?,?)',(key,url,'done',len(data),mime));db.commit()
                        self.task['done']+=1;self.task['bytes']+=len(data)
                    except Exception:
                        temp.unlink(missing_ok=True);self.task['failed']+=1
                    self.task['message']='Lädt Modellbilder; kann jederzeit pausiert werden.'
                    self.stop.wait(.25)
            self.task['message']='Pausiert. Gespeicherte Bilder bleiben erhalten.' if self.stop.is_set() else 'Bildlauf abgeschlossen. Nicht erreichbare Bilder können erneut versucht werden.'
        except Exception as e:self.task['message']='Bildlauf angehalten: '+str(e)[:180]
        finally:self.running=False;self.task['running']=False

    def action(self,body):
        op=body.get('op')
        if op=='images-start':
            with self.guard:
                if not self.running:
                    self.stop.clear();self.running=True;self.task['running']=True
                    threading.Thread(target=self.download_images,daemon=True).start()
        elif op=='images-stop':self.stop.set()
        elif op=='check':return self.check_updates()
        elif op in ('data-update','program-update'):self.prepare('data' if op=='data-update' else 'program')
        elif op in ('restart','install-program'):self.restart(op=='install-program')
        elif op=='update-settings':
            for key in ('automatic','beta'):
                if key in body:
                    if type(body[key]) is not bool:raise ValueError('Ungültige Updateeinstellung.')
                    self.preferences[key]=body[key]
            save(self.profile/'update-settings.json',self.preferences)
            self.available={'program':None,'data':None}
            self.check_state['checked']=0
        elif op=='shutdown':
            self.stop.set()
            self.updater_stop.set()
            with self.app._star_extra_lock:self.app._star_extra_save(force=True)
            threading.Timer(1,lambda:os._exit(0)).start()
        else:raise ValueError('Unbekannte Aktion.')
        return self.status()


def install(app,root,profile):
    controller=Portable(app,root,profile)
    controller.start_update_checks()
    original_get=app.Handler.do_GET;original_post=app.Handler.do_POST
    def get(handler):
        path=urllib.parse.urlsplit(handler.path).path
        if path=='/api/distribution':
            handler._send(200,json.dumps(controller.status()),'application/json; charset=utf-8',-1);return
        if path=='/static/portable.js':
            handler._send(200,(root/'app'/'static'/'portable.js').read_text(encoding='utf-8'),'text/javascript; charset=utf-8',-1);return
        return original_get(handler)
    def post(handler):
        if urllib.parse.urlsplit(handler.path).path!='/api/distribution':return original_post(handler)
        if not app._cam_user_request_allowed(handler.headers):handler._send(403,'{}','application/json',-1);return
        try:
            n=int(handler.headers.get('Content-Length','0'))
            if not 0<n<=2048:raise ValueError('Ungültige Anfrage.')
            result=controller.action(json.loads(handler.rfile.read(n)))
        except Exception as e:result={'ok':False,'error':str(e)[:200]}
        handler._send(200,json.dumps(result),'application/json; charset=utf-8',-1)
    app.Handler.do_GET=get;app.Handler.do_POST=post
    original_image=app.load_image
    def load_image(url,fresh=False):
        return (None if fresh else controller.cached_image(url)) or original_image(url,fresh=fresh)
    app.load_image=load_image
    # Model thumbnail requests use the same original offline image, without extra downloads.
    from star_finder import StarFinder
    original_thumb=StarFinder.thumbnail
    def thumb(service,token):
        row=service.thumb_tokens.get(token)
        cached=controller.cached_image(row['url']) if row else None
        if not cached:return original_thumb(service,token)
        from PIL import Image,ImageOps
        with Image.open(io.BytesIO(cached[0])) as image:
            image=ImageOps.exif_transpose(image);image.thumbnail((480,640));out=io.BytesIO();image.convert('RGB').save(out,'WEBP',quality=78);return out.getvalue()
    StarFinder.thumbnail=thumb
