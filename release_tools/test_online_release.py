"""Live public release checks using the real portable updater, with an isolated profile."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import urllib.request

from portable_support import Portable, merge_pending

BASE=Path(__file__).resolve().parent.parent
REPO='Emberhost92/AdultClient'


def remote(url):
    request=urllib.request.Request(url,headers={'User-Agent':'AdultClient-Release-Verification','Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)


def wait(controller):
    deadline=time.monotonic()+1800
    previous=None
    while controller.update_task['running']:
        task=controller.update_task
        percent=int(100*task['done']/max(1,task['total']))//10*10
        status=(task['kind'],task['phase'],percent)
        if status!=previous:
            print(json.dumps({'kind':status[0],'phase':status[1],'percent':status[2]}),flush=True)
            previous=status
        if time.monotonic()>deadline:raise TimeoutError('Public update download timed out')
        time.sleep(.5)
    assert controller.update_task['phase']=='ready',controller.update_task


def run():
    releases=remote('https://api.github.com/repos/'+REPO+'/releases?per_page=100')
    assert {r['tag_name'] for r in releases}>={'v0.3.0-beta.1','data-2026-10-21'}
    files={a['name']:a for r in releases for a in r['assets']}
    expected=[BASE/'distribution'/'AdultClient-0.3.0-beta.1-Windows.zip',
              BASE/'distribution'/'AdultClient-0.3.0-beta.1-Windows-Komplett.zip',
              BASE/'distribution'/'program-update.json',BASE/'distribution'/'SHA256SUMS-0.3.0.txt',
              BASE/'distribution'/'AdultClient-0.3.0-beta.1'/'data'/'star-data.sqlite3.gz',
              BASE/'distribution'/'AdultClient-0.3.0-beta.1'/'data'/'star-data.sqlite3.json']
    for path in expected:
        asset=files[path.name]
        assert asset['state']=='uploaded' and asset['size']==path.stat().st_size
        with path.open('rb') as stream:checksum=hashlib.file_digest(stream,'sha256').hexdigest()
        assert asset.get('digest')=='sha256:'+checksum,{'asset':path.name,'digest_verified':False}
    print(json.dumps({'public_assets':len(expected),'all_github_hashes_match':True}),flush=True)
    with tempfile.TemporaryDirectory(prefix='ac-online-update-',dir=BASE/'distribution') as folder:
        p=Path(folder)
        (p/'release.json').write_text(json.dumps({'version':'0.2.9','repository':REPO}),encoding='utf-8')
        controller=Portable(None,p,p)
        controller.discover()
        assert controller.available['program']['available'] and controller.available['data']['available']
        assert controller.available['program']['manifest']['version']=='0.3.0-beta.1'
        for kind in ('program','data'):
            controller.prepare(kind);wait(controller)
        assert controller.status()['program_pending'] and controller.status()['pending']
        merge_pending(p)
        assert not controller.status()['pending'] and controller.status()['package']
        with closing(sqlite3.connect(p/'star_data.sqlite3')) as db:
            assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
            profiles=db.execute("SELECT count(*) FROM records WHERE bucket='profiles'").fetchone()[0]
            assert profiles>0
        controller.config['version']='0.3.0-beta.1'
        controller.refresh_available()
        assert not controller.available['program']['available'] and not controller.available['data']['available']
        controller.preferences['beta']=False
        controller.discover()
        assert controller.available['program'] is None
        assert controller.available['data'] is not None
        report={'passed':True,'repository':REPO,'public_assets_verified':len(expected),
                'program_download_and_extraction':True,'model_data_download_and_sqlite_check':True,
                'model_data_applied':True,'current_version_not_offered_again':True,'stable_data_independent_of_beta_program':True,
                'model_profiles':profiles}
        (BASE/'distribution'/'ONLINE-UPDATE-CHECK.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report),flush=True)


if __name__=='__main__':run()
