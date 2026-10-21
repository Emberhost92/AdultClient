"""Separate portable runtime entry; never uses the publisher's installed addon/profile."""
import ctypes
import gzip
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT/'app'
PROFILE = Path(os.environ.get('AC_TEST_PROFILE') or ROOT/'userdata')


def ports_free(port):
    sockets=[]
    try:
        for number in range(port,port+22):
            s=socket.socket();s.bind(('127.0.0.1',number));sockets.append(s)
        return True
    except OSError:return False
    finally:
        for s in sockets:s.close()


def run():
    PROFILE.mkdir(parents=True,exist_ok=True)
    lock = ctypes.windll.kernel32.CreateMutexW(None, False, 'Local\\AdultClient-'+hashlib.sha256(str(ROOT).encode()).hexdigest()[:20])
    if ctypes.windll.kernel32.GetLastError()==183:
        if '--wait-free' in sys.argv:
            for _ in range(30):
                ctypes.windll.kernel32.CloseHandle(lock)
                time.sleep(.5)
                lock=ctypes.windll.kernel32.CreateMutexW(None,False,'Local\\AdultClient-'+hashlib.sha256(str(ROOT).encode()).hexdigest()[:20])
                if ctypes.windll.kernel32.GetLastError()!=183:break
            else:return
        else:
            try:
                p=json.loads((PROFILE/'instance.json').read_text());webbrowser.open(p['url'])
            except (OSError,ValueError):pass
            return
    log=(PROFILE/'startup.log').open('a',encoding='utf-8',buffering=1)
    sys.stdout=sys.stderr=log
    for name in ('AH_STASHDB_KEY','AH_FANSDB_KEY','AH_TPDB_KEY'):os.environ.pop(name,None)
    os.environ['AH_ADDON']=str(ROOT/'addon')
    os.environ['AH_PROFILE']=str(PROFILE)
    port=next((p for p in range(18765,19200,25) if ports_free(p)),None)
    if port is None:raise RuntimeError('Kein freier lokaler Port gefunden.')
    os.environ['AH_PORT']=str(port);os.environ['AH_MEDIA_PORT']=str(port+1)
    settings=PROFILE/'settings.json'
    if not settings.exists():settings.write_text(json.dumps({'offline_images':'false'}),encoding='utf-8')
    ui=PROFILE/'web_ui.json'
    if not ui.exists():ui.write_text(json.dumps({'offline':{'images':False}}),encoding='utf-8')
    sys.path.insert(0,str(APP))
    from portable_support import merge_pending
    try:
        # This is a one-start flag. A later normal restart must apply queued data.
        skip_data = os.environ.pop('AC_SKIP_DATA_UPDATE', None)
        if not skip_data:merge_pending(PROFILE)
    except Exception as error:
        pending=PROFILE/'updates'/'pending.sqlite3'
        if pending.exists():os.replace(pending,PROFILE/'updates'/'rejected.sqlite3')
        (PROFILE/'update-error.txt').write_text('Datenupdate nicht übernommen; bisherige Daten bleiben erhalten.\n'+str(error),encoding='utf-8')
    seed=ROOT/'data'/'star-data.sqlite3.gz'
    target=PROFILE/'star_data.sqlite3'
    if not target.exists() and seed.exists():
        manifest=json.loads(seed.with_suffix('.json').read_text(encoding='utf-8'))
        with seed.open('rb') as f:
            if hashlib.file_digest(f,'sha256').hexdigest()!=manifest['sha256']:raise ValueError('Modelldatenpaket ist beschädigt.')
        temp=target.with_suffix('.tmp')
        with gzip.open(seed,'rb') as inp,temp.open('wb') as out:
            while chunk:=inp.read(1024*1024):out.write(chunk)
        os.replace(temp,target)
        (PROFILE/'model-package.json').write_text(json.dumps(manifest),encoding='utf-8')
    if not target.exists():
        from star_store import StarStore
        initial=StarStore(str(PROFILE))
        initial.save_settings({'paused':True,'speed':'eco','interval':24,'prefetch':12,'jobs':{},'requests':{}})
        initial.close()
    sys.path.insert(0,str(APP))
    import server
    import portable_support
    portable_support.install(server, ROOT, PROFILE)
    url='http://127.0.0.1:'+str(port)
    (PROFILE/'instance.json').write_text(json.dumps({'url':url,'pid':os.getpid(),'root':str(ROOT)}),encoding='utf-8')
    sys.argv=[str(APP/'server.py'),'--no-browser']
    import threading
    def open_ready():
        for _ in range(120):
            try:
                urllib.request.urlopen(url+'/api/health',timeout=2).close()
                (PROFILE/'startup.ready').write_text(url,encoding='utf-8')
                if not os.environ.get('AC_TEST_NO_BROWSER'):webbrowser.open(url)
                return
            except OSError:time.sleep(1)
    threading.Thread(target=open_ready,daemon=True).start()
    server.main()


if __name__=='__main__':
    try:run()
    except Exception:
        import traceback
        PROFILE.mkdir(parents=True,exist_ok=True)
        (PROFILE/'startup-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        ctypes.windll.user32.MessageBoxW(0,'Start fehlgeschlagen. Details: '+str(PROFILE/'startup-error.txt'),'Adult Client',16)
