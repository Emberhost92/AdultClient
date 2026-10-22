"""Reproducible local portable build. No GitHub upload and no private profile copy."""
import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile

HERE=Path(__file__).resolve().parent
WORKSPACE=HERE.parent
APP=WORKSPACE/'AdultHideoutWeb'
VERSION='0.3.12-beta.1'


def copy_tree(source,target):
    shutil.copytree(source,target,ignore=shutil.ignore_patterns('__pycache__','node_modules','*.pyc','.auth','.git','*.log','*.bak'),dirs_exist_ok=True)


def build(output,include_models=True):
    output=Path(output).resolve()
    if output.exists():raise ValueError('Ausgabeordner existiert bereits. Für einen neuen Build neuen Ordner wählen.')
    output.mkdir(parents=True)
    for folder in ('app','runtime','addon','data','licenses','MediaScraper'):(output/folder).mkdir()
    for source in APP.glob('*.py'):shutil.copy2(source,output/'app'/source.name)
    copy_tree(APP/'shim',output/'app'/'shim');copy_tree(APP/'static',output/'app'/'static')
    for name in ('portable_entry.py','portable_support.py','update_engine.py','export_models.py'):shutil.copy2(HERE/name,output/'app'/name)
    shutil.copy2(HERE/'portable.js',output/'app'/'static'/'portable.js')
    shutil.copy2(WORKSPACE/'MediaScraper'/'models.py',output/'MediaScraper'/'models.py')
    # All sources required to recreate this binary distribution are included.
    copy_tree(HERE,output/'build-source')
    for name in ('README.md','STAR_FINDER.md','MEDIA_LIBRARY.md','MULTICAM.md'):
        shutil.copy2(APP/name,output/'app'/name)
    installed=Path(os.environ['APPDATA'])/'Kodi'/'addons'/'plugin.video.adulthideout'
    for source in installed.rglob('*'):
        if not source.is_file() or '__pycache__' in source.parts or source.suffix in ('.pyc','.log'):continue
        rel=source.relative_to(installed)
        # Only addon code, public catalogue data and shipped UI assets, no user data.
        if source.suffix.lower() not in ('.py','.xml','.txt','.md','.json','.gz','.png','.jpg','.jpeg','.svg','.webp','.po'):continue
        target=output/'addon'/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    # CPython runtime without site-packages, docs, headers, tests, installers or Tk.
    base=Path(sys.base_prefix)
    for name in ('python.exe','pythonw.exe','python3.dll','python314.dll','vcruntime140.dll','vcruntime140_1.dll','LICENSE.txt'):
        shutil.copy2(base/name,output/'runtime'/name)
    copy_tree(base/'DLLs',output/'runtime'/'DLLs')
    with zipfile.ZipFile(output/'runtime'/'python314.zip','w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for source in (base/'Lib').rglob('*'):
            rel=source.relative_to(base/'Lib')
            if any(part in ('site-packages','__pycache__','test','tests','idlelib','tkinter','turtledemo','ensurepip','venv') for part in rel.parts):continue
            if source.is_file() and source.suffix=='.py':z.write(source,rel.as_posix())
    (output/'runtime'/'python314._pth').write_text('python314.zip\n.\nDLLs\nLib/site-packages\n../app\n../addon\nimport site\n',encoding='utf-8')
    packages=output/'runtime'/'Lib'/'site-packages';packages.mkdir(parents=True)
    for distribution in ('requests','urllib3','certifi','charset-normalizer','idna','beautifulsoup4','soupsieve','typing-extensions','pillow'):
        dist=importlib.metadata.distribution(distribution)
        for rel in dist.files or []:
            if '..' in rel.parts or '__pycache__' in rel.parts or rel.suffix=='.pyc':continue
            source=Path(dist.locate_file(rel));target=packages/rel
            if source.is_file():target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    # The installed application remains untouched: only this copy receives release paths/UI.
    source=output/'app'/'star_models_sources.py'
    content=source.read_text(encoding='utf-8').replace('self.script.parent / ".auth" / "models"','Path(__import__("os").environ["AH_PROFILE"]) / "source_sessions"')
    source.write_text(content,encoding='utf-8')
    source=output/'app'/'server.py'
    content=source.read_text(encoding='utf-8').replace('os.path.abspath(__file__), "--no-browser", "--wait-free"','os.path.join(ROOT, "portable_entry.py"), "--no-browser", "--wait-free"')
    source.write_text(content,encoding='utf-8')
    source=output/'app'/'static'/'app.html'
    source.write_text(source.read_text(encoding='utf-8').replace('</body>','<script src="/static/portable.js"></script>\n</body>'),encoding='utf-8')
    source=output/'app'/'static'/'settings_studio.js'
    source.write_text(source.read_text(encoding='utf-8').replace('["tools", "Speicher & Extras",','["updates", "Updates & Modellbilder", "Programm, Datenpakete und Offline-Bilder"],\n    ["tools", "Speicher & Extras",'),encoding='utf-8')
    compiler=Path(os.environ['WINDIR'])/'Microsoft.NET'/'Framework64'/'v4.0.30319'/'csc.exe'
    subprocess.run([str(compiler),'/nologo','/target:winexe','/reference:System.Windows.Forms.dll','/out:'+str(output/'AdultClient.exe'),str(HERE/'Launcher.cs')],check=True)
    config={'version':VERSION,'repository':'Emberhost92/AdultClient','channel':'beta','data_asset':'star-data.sqlite3.gz'}
    (output/'release.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
    shutil.copy2(installed/'LICENSE.txt',output/'licenses'/'AdultHideout-GPL-2.0.txt')
    shutil.copy2(base/'LICENSE.txt',output/'licenses'/'Python.txt')
    shutil.copy2(HERE/'README.md',output/'BITTE-LESEN.md')
    if include_models:
        sys.path.insert(0,str(APP))
        from star_stashbox import Credentials
        # Only used in memory for redaction. Keys are never printed or packaged.
        secrets=[row.get('key','') for row in Credentials(APP/'profile').read().values() if isinstance(row,dict)]
        secrets.extend(os.environ.get(name,'') for name in ('AH_STASHDB_KEY','AH_FANSDB_KEY','AH_TPDB_KEY'))
        from export_models import export
        manifest=export(APP/'profile'/'star_data.sqlite3',output/'data'/'star-data.sqlite3',secrets)
        (output/'data'/'star-data.sqlite3').unlink()
        print('MODELS',json.dumps(manifest),flush=True)
    print('BUILD',str(output),flush=True)
    return output


def archive(output,complete=False):
    target=output.parent/(output.name+('-Windows-Komplett.zip' if complete else '-Windows.zip'))
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for source in output.rglob('*'):
            rel=source.relative_to(output)
            if not source.is_file() or rel.parts[0]=='userdata' or '__pycache__' in rel.parts or 'node_modules' in rel.parts:continue
            if rel.parts[0]=='data':
                if not complete or source.name not in ('star-data.sqlite3.gz','star-data.sqlite3.json'):continue
            z.write(source,output.name+'/'+rel.as_posix(),compress_type=zipfile.ZIP_STORED if source.suffix=='.gz' else zipfile.ZIP_DEFLATED)
    print('APP_ZIP',target.stat().st_size,str(target),flush=True)
    if not complete:
        with target.open('rb') as handle:digest=hashlib.file_digest(handle,'sha256').hexdigest()
        with zipfile.ZipFile(target) as z:unpacked=sum(i.file_size for i in z.infolist())
        manifest={'format':1,'version':json.loads((output/'release.json').read_text())['version'],
                  'file':target.name,'bytes':target.stat().st_size,'unpacked_bytes':unpacked,'sha256':digest}
        (output.parent/'program-update.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    return target


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output');p.add_argument('--without-models',action='store_true');p.add_argument('--archive-only',action='store_true');p.add_argument('--complete',action='store_true')
    a=p.parse_args()
    if a.archive_only:archive(Path(a.output).resolve(),a.complete)
    else:
        output=build(a.output,not a.without_models);archive(output)
        if not a.without_models:archive(output,True)
