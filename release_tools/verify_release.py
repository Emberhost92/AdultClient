"""Verify final archives and absence of publisher credentials without printing keys."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

BASE=Path(__file__).resolve().parent.parent
ROOT=BASE/'distribution'/'AdultClient-0.3.0-beta.1'


def digest(path):
    with path.open('rb') as handle:return hashlib.file_digest(handle,'sha256').hexdigest()


def verify():
    manifest=json.loads((ROOT.parent/'program-update.json').read_text())
    program=ROOT.parent/manifest['file']
    assert program.stat().st_size==manifest['bytes']
    assert digest(program)==manifest['sha256']
    sys.path.insert(0,str(BASE/'AdultHideoutWeb'))
    from star_stashbox import Credentials
    secrets=[row.get('key','').encode() for row in Credentials(BASE/'AdultHideoutWeb'/'profile').read().values() if isinstance(row,dict) and row.get('key')]
    secrets=[secret for secret in secrets if len(secret)>12]
    archives=[program,ROOT.parent/(ROOT.name+'-Windows-Komplett.zip')]
    for archive in archives:
        with zipfile.ZipFile(archive) as z:
            assert z.testzip() is None
            for item in z.infolist():
                parts=Path(item.filename).parts[1:]
                assert parts and parts[0]!='userdata' and '.auth' not in parts and 'node_modules' not in parts
                if archive==program:assert parts[0]!='data'
                if item.file_size<20_000_000:
                    content=z.read(item)
                    assert not any(secret in content for secret in secrets),'Publisher credential found in archive'
            if archive==program:
                assert sum(item.file_size for item in z.infolist())==manifest['unpacked_bytes']
                prefix=ROOT.name+'/'
                for file in ('update_engine.py','portable_support.py','portable_entry.py','export_models.py'):
                    assert z.read(prefix+'app/'+file)==(BASE/'release_tools'/file).read_bytes()
                assert z.read(prefix+'app/static/portable.js')==(BASE/'release_tools'/'portable.js').read_bytes()
    data=json.loads((ROOT/'data'/'star-data.sqlite3.json').read_text())
    assert digest(ROOT/'data'/'star-data.sqlite3.gz')==data['sha256']
    sums=[]
    for file in [*archives,ROOT.parent/'program-update.json',ROOT/'data'/'star-data.sqlite3.gz',ROOT/'data'/'star-data.sqlite3.json']:
        sums.append(digest(file)+'  '+file.relative_to(ROOT.parent).as_posix())
    (ROOT.parent/'SHA256SUMS-0.3.0.txt').write_text('\n'.join(sums)+'\n',encoding='utf-8')
    print(json.dumps({'passed':True,'archives':[{'file':p.name,'bytes':p.stat().st_size} for p in archives],
                      'program_manifest':True,'source_files_match':True,'no_userdata_or_publisher_keys':True,'model_package_hash':True}))


if __name__=='__main__':verify()
