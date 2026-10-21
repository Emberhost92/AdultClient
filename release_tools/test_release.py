import gzip
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import io
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from export_models import clean, export, encode
from portable_support import merge_pending, Portable


def fixture(path):
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript('''
        CREATE TABLE records(bucket TEXT,key TEXT,payload TEXT,PRIMARY KEY(bucket,key));
        CREATE TABLE metadata(key TEXT PRIMARY KEY,payload TEXT);
        CREATE TABLE cache(kind TEXT,key TEXT,payload TEXT,expires REAL,PRIMARY KEY(kind,key));
        CREATE TABLE source_catalog(source TEXT,entity TEXT,profile TEXT,name TEXT,payload TEXT,first_seen REAL,checked REAL,seen_run TEXT,PRIMARY KEY(source,entity));
        CREATE TABLE source_gallery(profile TEXT,source TEXT,entity TEXT,url TEXT,payload TEXT,PRIMARY KEY(profile,source,entity,url));
        CREATE TABLE source_links(url TEXT,profile TEXT,PRIMARY KEY(url,profile));
        CREATE TABLE box_scenes(source TEXT,profile TEXT,id TEXT,payload TEXT,run TEXT,PRIMARY KEY(source,profile,id));
        CREATE TABLE private_history(url TEXT);
        ''')
        db.execute('INSERT INTO records VALUES(?,?,?)',('profiles','model',encode({'ok':True,'at':1,'name':'Public Model','bio':'Public biography','images':['https://example.org/image.jpg|Cookie=secret-cookie&Referer=https%3A%2F%2Fexample.org'],'nested':{'ApiKey':'private-key','fact':'Public fact'},'local_path':'C:\\private\\photo.jpg'})))
        db.execute('INSERT INTO records VALUES(?,?,?)',('notes','model',encode({'text':'private-note'})))
        db.execute('INSERT INTO cache VALUES(?,?,?,?)',('http','request',encode({'Cookie':'private-cookie'}),1e12))
        db.execute('INSERT INTO cache VALUES(?,?,?,?)',('sources','model',encode({'sources':{'test':{'ok':True,'facts':['public']}}},True),1e12))
        db.execute('INSERT INTO metadata VALUES(?,?)',('state',encode({'covers':{'model':'private-cover'},'trends':['private-trend']})))
        db.execute('INSERT INTO private_history VALUES(?)',('private-visit',))


class ReleaseTests(unittest.TestCase):
    def test_export_includes_public_models_but_excludes_all_personal_tables_and_http(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);src=p/'private.sqlite3';fixture(src)
            manifest=export(src,p/'public.sqlite3',('secret-cookie','private-key'))
            with closing(sqlite3.connect(p/'public.sqlite3')) as db, db:
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                self.assertFalse(db.execute("SELECT 1 FROM records WHERE bucket='notes'").fetchone())
                self.assertFalse(db.execute("SELECT 1 FROM cache WHERE kind='http'").fetchone())
                self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='private_history'").fetchone())
                text=db.execute("SELECT payload FROM records WHERE bucket='profiles'").fetchone()[0]
                self.assertIn('Public biography',text);self.assertIn('Public fact',text)
                self.assertNotIn('private',text);self.assertNotIn('secret-cookie',text)
                state=json.loads(db.execute("SELECT payload FROM metadata WHERE key='state'").fetchone()[0]);self.assertEqual(state['covers'],{})
                self.assertTrue(json.loads(db.execute("SELECT payload FROM metadata WHERE key='settings'").fetchone()[0])['paused'])
            packed=p/'public.sqlite3.gz'
            with packed.open('rb') as f:self.assertEqual(hashlib.file_digest(f,'sha256').hexdigest(),manifest['sha256'])
            self.assertEqual(gzip.decompress(packed.read_bytes()),(p/'public.sqlite3').read_bytes())
            with closing(sqlite3.connect(src)) as db, db:self.assertEqual(db.execute('SELECT count(*) FROM private_history').fetchone()[0],1)

    def test_data_update_preserves_notes_covers_history_and_newer_local_research(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);src=p/'publisher.sqlite3';fixture(src)
            (p/'updates').mkdir();export(src,p/'updates'/'pending.sqlite3')
            target=p/'star_data.sqlite3';fixture(target)
            with closing(sqlite3.connect(target)) as db, db:
                db.execute("UPDATE records SET payload=? WHERE bucket='profiles'",(encode({'at':999,'bio':'Newer research'}),))
            merge_pending(p)
            self.assertTrue((p/'updates'/'before-update.sqlite3').exists())
            self.assertFalse((p/'updates'/'pending.sqlite3').exists())
            with closing(sqlite3.connect(target)) as db, db:
                self.assertIn('Newer research',db.execute("SELECT payload FROM records WHERE bucket='profiles'").fetchone()[0])
                self.assertIn('private-note',db.execute("SELECT payload FROM records WHERE bucket='notes'").fetchone()[0])
                self.assertIn('private-cover',db.execute("SELECT payload FROM metadata WHERE key='state'").fetchone()[0])
                self.assertEqual(db.execute('SELECT count(*) FROM private_history').fetchone()[0],1)

    def test_public_image_headers_survive_but_authentication_does_not(self):
        url='https://example.org/a.jpg|Cookie=private&Authorization=private&Referer=https%3A%2F%2Fexample.org%2F'
        result=clean(url)
        self.assertIn('Referer=',result);self.assertNotIn('Cookie',result);self.assertNotIn('Authorization',result)
        self.assertEqual(clean('https://user:password@example.org/a.jpg'),'')

    def test_no_github_request_without_repository(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'release.json').write_text('{"version":"test","repository":""}')
            controller=Portable(None,p,p)
            with patch('urllib.request.urlopen') as request:
                with self.assertRaisesRegex(ValueError,'kein Veröffentlichungs'):controller.check_updates()
                request.assert_not_called()

    def test_opt_in_images_are_verified_reused_offline_and_not_downloaded_twice(self):
        from PIL import Image
        image=io.BytesIO();Image.new('RGB',(4,4),'gold').save(image,'PNG');raw=image.getvalue()
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'release.json').write_text('{"version":"test","repository":""}')
            app=SimpleNamespace(split_kodi_url=lambda url:(url,{}))
            controller=Portable(app,p,p)
            controller.image_urls=lambda:iter(['https://example.org/image.png']*2)
            with patch('urllib.request.urlopen',return_value=io.BytesIO(raw)) as request:
                controller.download_images();self.assertEqual(request.call_count,1)
            self.assertEqual(controller.cached_image('https://example.org/image.png'),(raw,'image/png'))
            self.assertEqual(controller.status()['images']['stored'],1)
            with patch('urllib.request.urlopen') as request:
                controller.download_images();request.assert_not_called()
            controller.stop.set()
            controller.image_urls=lambda:iter(['https://example.org/another.png'])
            with patch('urllib.request.urlopen') as request:
                controller.download_images();request.assert_not_called()

    def test_bad_update_rolls_back_public_data_and_keeps_private_data(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);fixture(p/'star_data.sqlite3');(p/'updates').mkdir()
            fixture(p/'updates'/'pending.sqlite3')
            with closing(sqlite3.connect(p/'updates'/'pending.sqlite3')) as db, db:
                db.execute('ALTER TABLE source_gallery ADD COLUMN wrong TEXT')
                db.execute("UPDATE records SET payload=? WHERE bucket='profiles'",(encode({'at':10000,'bio':'Must roll back'}),))
            with self.assertRaisesRegex(ValueError,'Unpassendes'):merge_pending(p)
            with closing(sqlite3.connect(p/'star_data.sqlite3')) as db, db:
                self.assertIn('Public biography',db.execute("SELECT payload FROM records WHERE bucket='profiles'").fetchone()[0])
                self.assertIn('private-note',db.execute("SELECT payload FROM records WHERE bucket='notes'").fetchone()[0])


if __name__=='__main__':unittest.main()
