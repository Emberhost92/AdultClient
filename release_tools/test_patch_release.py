"""Verify the published patch through the real public updater, without private data."""
import hashlib
import json
from pathlib import Path
import tempfile
import time
import urllib.request

from portable_support import Portable

BASE = Path(__file__).resolve().parent.parent
VERSION = '0.3.1-beta.1'
REPO = 'Emberhost92/AdultClient'


def run():
    request = urllib.request.Request('https://api.github.com/repos/'+REPO+'/releases/tags/v'+VERSION,
                                     headers={'User-Agent': 'AdultClient-Release-Check'})
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    assets = {item['name']: item for item in release['assets']}
    assert not release['draft'] and release['prerelease']
    for name in ('AdultClient-'+VERSION+'-Windows.zip', 'AdultClient-'+VERSION+'-Windows-Komplett.zip',
                 'program-update.json', 'SHA256SUMS-'+VERSION+'.txt'):
        file = BASE/'distribution'/name
        with file.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        assert assets[name]['state'] == 'uploaded' and assets[name]['size'] == file.stat().st_size
        assert assets[name]['digest'] == 'sha256:'+digest, name
    with tempfile.TemporaryDirectory(prefix='ac-patch-check-', dir=BASE/'distribution') as folder:
        root = Path(folder)
        (root/'release.json').write_text(json.dumps({'version': '0.3.0-beta.1', 'repository': REPO, 'channel': 'beta'}))
        profile = root/'userdata'
        profile.mkdir()
        (profile/'update-settings.json').write_text(json.dumps({'automatic': False, 'beta': True}))
        updater = Portable(None, root, profile)
        updater.discover()
        assert updater.available['program']['available']
        assert updater.available['program']['manifest']['version'] == VERSION
        assert updater.available['data']['manifest']['created'] == '2026-10-21T10:59:20Z'
        updater.prepare('program')
        end = time.monotonic()+300
        while updater.update_task['running']:
            if time.monotonic() > end:
                raise TimeoutError('Program download timed out')
            time.sleep(.5)
        assert updater.update_task['phase'] == 'ready', updater.update_task
        staged = profile/'updates'/'program-staging'
        assert (staged/'app'/'static'/'chaturbate_tutorial.js').is_file()
        assert (staged/'app'/'static'/'tutorials'/'chaturbate-tools.png').is_file()
        assert (staged/'app'/'static'/'tutorials'/'chaturbate-settings.png').is_file()
        assert not (profile/'updates'/'pending.sqlite3').exists(), 'Program download must not download model data'
        updater.config['version'] = VERSION
        updater.refresh_available()
        assert not updater.available['program']['available']
        report = {'passed': True, 'version': VERSION, 'public_assets_hash_verified': 4,
                  'update_from_0_3_0_discovered': True, 'real_program_download_verified_and_staged': True,
                  'tutorial_files_present': True, 'model_data_not_downloaded': True,
                  'current_version_not_offered_again': True, 'release': release['html_url']}
        (BASE/'distribution'/'ONLINE-UPDATE-CHECK-0.3.1.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report), flush=True)


if __name__ == '__main__':
    run()
