"""Regression tests for independent releases, verification and safe replacement."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch, Mock
import zipfile

from portable_support import Portable
from update_engine import version, extract_program, download, swap, rollback, save
from test_release import fixture


def wait(controller):
    deadline = time.monotonic()+5
    while controller.update_task['running'] or controller.check_state['running']:
        if time.monotonic()>deadline:
            raise AssertionError('Background task did not finish')
        time.sleep(.01)


class UpdateTests(unittest.TestCase):
    def setup_controller(self, folder):
        p=Path(folder)
        save(p/'release.json',{'version':'0.3.0-beta.1','repository':'Emberhost92/AdultClient'})
        return Portable(None,p,p)

    def manifest(self, **kw):
        return {'format':1,'version':'0.4.0','bytes':3,'unpacked_bytes':3,'sha256':hashlib.sha256(b'abc').hexdigest(),'file':'app.zip',**kw}

    def test_semver_no_lexical_downgrades_and_beta_precedence(self):
        self.assertGreater(version('1.10.0'),version('1.9.9'))
        self.assertGreater(version('1.0.0'),version('1.0.0-beta.99'))
        self.assertGreater(version('1.0.0-beta.10'),version('1.0.0-beta.9'))
        self.assertLess(version('1.0.0-alpha'),version('1.0.0-beta'))
        self.assertEqual(version('v1.0.0+one'),version('1.0.0+two'))

    def test_independent_program_and_data_releases_and_beta_channel(self):
        with tempfile.TemporaryDirectory() as folder:
            c=self.setup_controller(folder)
            program=self.manifest()
            beta=self.manifest(version='0.5.0-beta.2',file='beta.zip')
            data=self.manifest(file='data.gz',created='2026-10-21T16:00:00Z',personal_data=False)
            def release(label, manifest, prerelease=False):
                filename='star-data.sqlite3.json' if label=='data' else 'program-update.json'
                prefix='https://github.com/Emberhost92/AdultClient/releases/download/'+label+'/'
                return {'draft':False,'prerelease':prerelease,'assets':[
                    {'name':filename,'browser_download_url':prefix+filename},
                    {'name':manifest['file'],'browser_download_url':prefix+manifest['file'],'size':manifest['bytes'],'digest':'sha256:'+manifest['sha256']}],'body':label}
            releases=[release('data',data),release('stable',program),release('beta',beta,True)]
            def remote(url,*args):
                if 'api.github.com' in url:return releases
                return data if '/data/' in url else beta if '/beta/' in url else program
            with patch('update_engine.remote_json',side_effect=remote):
                c.discover()
                self.assertEqual(c.available['program']['version'],'0.5.0-beta.2')
                self.assertEqual(c.available['data']['version'],'0.4.0')
                self.assertTrue(c.available['data']['available'])
                c.preferences['beta']=False;c.discover()
                self.assertEqual(c.available['program']['version'],'0.4.0')
            save(Path(folder)/'model-package.json',data)
            c.refresh_available();self.assertFalse(c.available['data']['available'])
            c.config['version']='0.9.0';c.refresh_available();self.assertFalse(c.available['program']['available'])

    def test_cached_checks_do_not_require_network_for_ui_status(self):
        with tempfile.TemporaryDirectory() as folder:
            c=self.setup_controller(folder)
            with patch('urllib.request.urlopen') as network:
                for _ in range(3):c.status()
                network.assert_not_called()
            c.action({'op':'update-settings','automatic':False,'beta':False})
            restarted=Portable(None,Path(folder),Path(folder))
            self.assertFalse(restarted.preferences['automatic'])

    def test_discovery_failure_is_background_and_preserves_installed_version(self):
        with tempfile.TemporaryDirectory() as folder:
            c=self.setup_controller(folder)
            with patch('update_engine.remote_json',side_effect=OSError('offline')):
                c.check_updates();wait(c)
            self.assertEqual(c.check_state['error'],'offline')
            self.assertEqual(c.config['version'],'0.3.0-beta.1')

    def test_bad_hash_removes_partial_download(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'part'
            with patch('urllib.request.urlopen',return_value=io.BytesIO(b'bad')):
                with self.assertRaisesRegex(ValueError,'Prüfsumme'):
                    download('https://example.org/a',path,self.manifest(),lambda *_:None)
            self.assertFalse(path.exists())

    def test_data_download_is_verified_and_does_not_touch_installed_data(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);c=self.setup_controller(folder)
            fixture(p/'incoming.sqlite3');fixture(p/'star_data.sqlite3')
            before=(p/'star_data.sqlite3').read_bytes()
            raw=gzip.compress((p/'incoming.sqlite3').read_bytes())
            manifest=self.manifest(bytes=len(raw),unpacked_bytes=len(before),sha256=hashlib.sha256(raw).hexdigest(),created='2026-10-21T16:00:00Z',personal_data=False)
            c.available['data']={'manifest':manifest,'download':'https://github.com/Emberhost92/AdultClient/releases/download/data/data.gz'}
            with patch('urllib.request.urlopen',return_value=io.BytesIO(raw)):
                c.prepare('data');wait(c)
            self.assertEqual(c.update_task['phase'],'ready')
            self.assertEqual((p/'star_data.sqlite3').read_bytes(),before)
            self.assertTrue((p/'updates'/'pending.sqlite3').exists())

    def test_zip_rejects_private_data_traversal_and_duplicate_case(self):
        for names in [('pkg/userdata/notes','pkg/app/a'),('pkg/../escape','pkg/app/a'),('pkg/app/A','pkg/app/a'),('pkg/app/CON.txt',)]:
            with self.subTest(names=names),tempfile.TemporaryDirectory() as folder:
                p=Path(folder);packed=p/'app.zip'
                with zipfile.ZipFile(packed,'w') as z:
                    for name in names:z.writestr(name,b'x')
                with self.assertRaises(ValueError):extract_program(packed,p/'staged',self.manifest(unpacked_bytes=len(names)))
                self.assertFalse((p/'escape').exists())

    def test_transaction_rollback_restores_program_and_never_touches_userdata(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);root=p/'root';staged=p/'staged';root.mkdir();staged.mkdir()
            (root/'app').mkdir();(root/'app'/'version').write_text('old')
            (staged/'app').mkdir();(staged/'app'/'version').write_text('new')
            (root/'userdata').mkdir();(root/'userdata'/'notes').write_text('private')
            swap(root,staged,p/'backup',p/'journal.json')
            self.assertEqual((root/'app'/'version').read_text(),'new')
            rollback(root,staged,p/'backup',p/'journal.json')
            self.assertEqual((root/'app'/'version').read_text(),'old')
            self.assertEqual((root/'userdata'/'notes').read_text(),'private')

    def test_second_transfer_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            c=self.setup_controller(folder)
            c.available['program']={'manifest':self.manifest()}
            c.update_guard.acquire()
            with self.assertRaisesRegex(ValueError,'laufenden Download'):c.prepare('program')

    def test_automatic_checks_are_daily_and_survive_paused_images(self):
        with tempfile.TemporaryDirectory() as folder:
            c=self.setup_controller(folder)
            c.stop.set()  # Pausing images must not disable the update scheduler.
            with patch('update_engine.threading.Thread') as thread:
                c.start_update_checks()
                loop=thread.call_args.kwargs['target']
            c.updater_stop=Mock()
            c.updater_stop.wait.side_effect=[False,False,True]
            c.check_updates=Mock(side_effect=lambda:c.check_state.update(checked=time.time()))
            loop();c.check_updates.assert_called_once()
            c.preferences['automatic']=False;c.check_state['checked']=0
            c.updater_stop.wait.side_effect=[False,True]
            loop();c.check_updates.assert_called_once()


if __name__=='__main__':unittest.main()
