"""Launch the built EXE with an isolated synthetic catalogue and test the real UI."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import sys
import time
import urllib.request

BASE=Path(__file__).resolve().parent.parent
ROOT=BASE/('distribution/AdultClient-'+(sys.argv[1] if len(sys.argv)>1 else '0.3.10-beta.1'))
with tempfile.TemporaryDirectory(prefix='ac-live-catalog-') as folder:
    profile=Path(folder)
    sites=('stripchat','chaturbate','bongacams','camsoda','cam4','xlovecam')
    now=int(time.time())
    models={}
    for i in range(6000):
        site=sites[i%6];name=f'Demo_{i:05}'
        models[site+':'+name]={'site':site,'name':name,'seen':now,'online':True,'show':'public',
                                  'viewers':6000-i,'tags':['test'],'personal':{},'gender':'weiblich'}
    (profile/'cam_library.json').write_text(json.dumps({'models':models,'groups':[],'favs':[],'account':{}}))
    (profile/'update-settings.json').write_text('{"automatic":false,"beta":true}')
    env=dict(os.environ,AC_TEST_PROFILE=str(profile),AC_TEST_NO_BROWSER='1')
    child=subprocess.Popen([str(ROOT/'AdultClient.exe')],env=env,creationflags=subprocess.CREATE_NO_WINDOW)
    url=None
    try:
        for _ in range(60):
            try:
                url=json.loads((profile/'instance.json').read_text())['url']
                urllib.request.urlopen(url+'/api/health',timeout=2).close()
                break
            except Exception:time.sleep(.5)
        else:raise RuntimeError('Portable EXE did not start')
        for test in sys.argv[2:] or ['test_live_catalog_speed.cjs']:
            subprocess.run(['C:/Program Files/nodejs/node.exe',str(BASE/'release_tools/i18n_tools'/test),url,'portable'],check=True)
    finally:
        if url:
            try:urllib.request.urlopen(urllib.request.Request(url+'/api/distribution',data=b'{"op":"shutdown"}',headers={'Origin':url,'Content-Type':'application/json'}),timeout=10).close()
            except Exception:pass
        # The EXE hands off to the server process and exits; wait for its shutdown.
        for _ in range(30):
            try:
                urllib.request.urlopen(url+'/api/health',timeout=.5).close()
            except Exception:break
            time.sleep(.5)
        child.wait(timeout=10)
