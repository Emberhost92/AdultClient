"""Real Windows process/update tests in disposable copies, never the working app."""
import json
from contextlib import closing
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request

from update_engine import extract_program, read, save, wait_pid, swap

BASE=Path(__file__).resolve().parent.parent
RELEASE=BASE/'distribution'/'AdultClient-0.3.0-beta.1'
MANIFEST=read(BASE/'distribution'/'program-update.json')
ZIP=BASE/'distribution'/MANIFEST['file']


def api(url,body=None):
    request=urllib.request.Request(url+'/api/distribution',data=json.dumps(body).encode() if body else None,
        headers={'Content-Type':'application/json','Origin':url})
    with urllib.request.urlopen(request,timeout=30) as response:
        result=json.load(response)
    if not result.get('ok'):raise AssertionError(result)
    return result


def await_state(profile, predicate, timeout=120):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        instance=read(profile/'instance.json',{})
        try:
            state=api(instance['url'])
            if predicate(state):return instance,state
        except (OSError,KeyError,ValueError):pass
        time.sleep(.3)
    raise AssertionError('Timed out: '+str(read(profile/'updates'/'install-result.json'))+' '+str(read(profile/'instance.json')))


def queue_data(profile):
    incoming=profile/'incoming.sqlite3'
    with closing(sqlite3.connect(profile/'star_data.sqlite3')) as db,closing(sqlite3.connect(incoming)) as dest,dest:
        db.backup(dest)
        dest.execute("INSERT OR REPLACE INTO records VALUES(?,?,?)",('profiles','update-test',json.dumps({'at':9999999999,'name':'Update Fixture'})))
    from export_models import export
    export(incoming,profile/'updates'/'pending.sqlite3')
    (profile/'updates'/'pending.sqlite3.json').replace(profile/'updates'/'pending.json')


def run_case(parent, name, bad=False, data_only=False, interrupted=False):
    root=parent/name
    shutil.copytree(RELEASE,root,ignore=shutil.ignore_patterns('data','userdata','build-source','__pycache__'))
    config=read(root/'release.json');config['version']='0.3.0-beta.1';save(root/'release.json',config)
    profile=root/'userdata';profile.mkdir()
    save(profile/'update-settings.json',{'automatic':False,'beta':True})
    (profile/'private-cookie.txt').write_text('PRIVATE-SENTINEL')
    save(profile/'cam.json',{'wm':'TEST-PRIVATE-CODE'})
    (profile/'downloads').mkdir();(profile/'downloads'/'keep.mp4').write_bytes(b'PERSONAL-DOWNLOAD')
    if not data_only:
        staged=profile/'updates'/'program-staging';staged.mkdir(parents=True)
        extract_program(ZIP,staged,MANIFEST)
        if bad and not interrupted:
            (staged/'app'/'server.py').write_text('import os,sqlite3\ndb=sqlite3.connect(os.path.join(os.environ["AH_PROFILE"],"star_data.sqlite3"))\ndb.execute("UPDATE records SET payload=? WHERE bucket=\'notes\'",("BROKEN-MIGRATION",))\ndb.commit()\ndb.close()\nraise RuntimeError("intentional startup failure after schema/data migration")\n')
        save(profile/'updates'/'program-ready.json',{'manifest':MANIFEST})
    env=os.environ.copy();env.update(AC_TEST_PROFILE=str(profile),AC_TEST_NO_BROWSER='1')
    process=subprocess.Popen([str(root/'runtime'/'pythonw.exe'),str(root/'app'/'portable_entry.py')],env=env,cwd=root)
    try:
        instance,state=await_state(profile,lambda s:s['version']=='0.3.0-beta.1')
        with closing(sqlite3.connect(profile/'star_data.sqlite3')) as db,db:
            db.execute("INSERT OR REPLACE INTO records VALUES(?,?,?)",('notes','update-test',json.dumps({'text':'KEEP-MY-NOTE'})))
        if data_only or not bad:queue_data(profile)
        started=time.monotonic()
        if interrupted:
            api(instance['url'],{'op':'shutdown'});assert wait_pid(instance['pid'],15)
            folder=profile/'updates';helper=folder/'helper-runtime'
            shutil.copytree(root/'runtime',helper,ignore=shutil.ignore_patterns('Lib','__pycache__'))
            (helper/'python314._pth').write_text('python314.zip\n.\nDLLs\n')
            shutil.copy2(BASE/'release_tools'/'update_engine.py',helper/'update_engine.py')
            save(folder/'install-plan.json',{'root':str(root),'profile':str(profile),'pid':instance['pid'],'install_program':True})
            swap(root,folder/'program-staging',folder/'program-backup',folder/'install-journal.json')
            # Simulate power loss before the worker could confirm startup, then use the EXE.
            subprocess.Popen([str(root/'AdultClient.exe')],env=env,cwd=root)
        else:
            api(instance['url'],{'op':'restart' if data_only else 'install-program'})
        expected='0.3.0-beta.1' if bad or data_only else MANIFEST['version']
        instance,state=await_state(profile,lambda s:s['version']==expected and s.get('install_result') is not None,180)
        result=state['install_result']
        assert result['ok'] is not bad,result
        if not bad and not data_only:
            # A program update does not silently install an already queued data update.
            assert (profile/'updates'/'pending.sqlite3').exists()
            assert not state['program_pending']
            with closing(sqlite3.connect(profile/'star_data.sqlite3')) as db:
                assert db.execute("SELECT payload FROM records WHERE bucket='profiles' AND key='update-test'").fetchone() is None
            previous_at=result['at']
            api(instance['url'],{'op':'restart'})
            instance,state=await_state(profile,lambda s:s['version']==expected and s.get('install_result',{}).get('at',0)>previous_at,180)
            assert not state['pending']
        assert (profile/'private-cookie.txt').read_text()=='PRIVATE-SENTINEL'
        assert read(profile/'cam.json')['wm']=='TEST-PRIVATE-CODE'
        assert (profile/'downloads'/'keep.mp4').read_bytes()==b'PERSONAL-DOWNLOAD'
        with closing(sqlite3.connect(profile/'star_data.sqlite3')) as db,db:
            assert 'KEEP-MY-NOTE' in db.execute("SELECT payload FROM records WHERE bucket='notes' AND key='update-test'").fetchone()[0]
            if data_only or not bad:assert 'Update Fixture' in db.execute("SELECT payload FROM records WHERE bucket='profiles' AND key='update-test'").fetchone()[0]
        if data_only:assert not (profile/'updates'/'pending.sqlite3').exists()
        print(json.dumps({'case':name,'passed':True,'seconds':round(time.monotonic()-started,2),'version':state['version'],'result':result}),flush=True)
    finally:
        current=read(profile/'instance.json',{})
        if current.get('url'):
            try:api(current['url'],{'op':'shutdown'})
            except OSError:pass
        if current.get('pid'):wait_pid(current['pid'],15)
        if process.poll() is None:
            process.terminate();process.wait(timeout=15)
        time.sleep(1)


if __name__=='__main__':
    if os.name!='nt':raise SystemExit('Windows only')
    with tempfile.TemporaryDirectory(prefix='ac-update-test-',dir=BASE/'distribution') as folder:
        for name,bad,data_only,interrupted in [('program-success',False,False,False),('program-rollback',True,False,False),('data-only',False,True,False),('interrupted-recovery',True,False,True)]:
            if '--program-only' in sys.argv and name!='program-success':continue
            run_case(Path(folder),name,bad,data_only,interrupted)

