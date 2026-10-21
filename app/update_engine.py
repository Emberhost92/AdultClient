"""Independent release discovery, verified staging and Windows portable replacement.

Only public GitHub releases are used. No publisher token is shipped to clients.
The worker runs from a private runtime copy, so the installed runtime is not locked.
"""
from contextlib import closing
from datetime import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

MANAGED = {'app', 'runtime', 'addon', 'MediaScraper', 'licenses', 'build-source',
           'AdultClient.exe', 'release.json', 'BITTE-LESEN.md'}
MAX_PROGRAM = 512 * 1024**2
MAX_UNPACKED = 2 * 1024**3


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    os.replace(temp, path)


def read(path, fallback=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return fallback


def version(value):
    """SemVer precedence; build metadata is intentionally ignored."""
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?', str(value))
    if not match:
        raise ValueError('Ungültige Programmversion: ' + str(value)[:60])
    pre = match[4]
    parts = tuple((0, int(x)) if x.isdigit() else (1, x) for x in pre.split('.')) if pre else ()
    return (int(match[1]), int(match[2]), int(match[3]), pre is None, parts)


def timestamp(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError):
        return 0


def github_asset(url, repo):
    p = urllib.parse.urlsplit(url)
    prefix = '/' + repo.lower() + '/releases/download/'
    if p.scheme != 'https' or p.netloc.lower() != 'github.com' or not p.path.lower().startswith(prefix) or p.username or p.query or p.fragment:
        raise ValueError('Updateadresse gehört nicht zum gewählten GitHub-Projekt.')
    return url


def remote_json(url, limit=1024*1024):
    request = urllib.request.Request(url, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'AdultClient-Updater'})
    with urllib.request.urlopen(request, timeout=20) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Updatebeschreibung ist zu groß.')
    return json.loads(data)


def validate_manifest(manifest, kind):
    if manifest.get('format') != 1:
        raise ValueError('Dieses Updateformat wird noch nicht unterstützt.')
    if not re.fullmatch('[0-9a-f]{64}', str(manifest.get('sha256', ''))):
        raise ValueError('Prüfsumme fehlt im Updatepaket.')
    cap = MAX_PROGRAM if kind == 'program' else 2 * 1024**3
    for key, maximum in [('bytes', cap), ('unpacked_bytes', 8 * 1024**3 if kind == 'data' else MAX_UNPACKED)]:
        if type(manifest.get(key)) is not int or not 0 < manifest[key] <= maximum:
            raise ValueError('Ungültige Paketgröße: ' + key)
    if kind == 'program':
        version(manifest.get('version'))
    elif not timestamp(manifest.get('created')) or manifest.get('personal_data') is not False:
        raise ValueError('Ungültiges öffentliches Modelldatenpaket.')
    return manifest


def download(url, path, manifest, progress):
    if shutil.disk_usage(path.parent).free < manifest['bytes'] + manifest['unpacked_bytes'] + 64 * 1024**2:
        raise ValueError('Nicht genügend freier Speicher für Download und Entpacken.')
    digest = hashlib.sha256()
    count = 0
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'AdultClient-Updater'})
        with urllib.request.urlopen(request, timeout=30) as response, path.open('wb') as out:
            while chunk := response.read(1024*1024):
                count += len(chunk)
                if count > manifest['bytes']:
                    raise ValueError('Download ist größer als angekündigt.')
                out.write(chunk)
                digest.update(chunk)
                progress(count, manifest['bytes'])
        if count != manifest['bytes'] or digest.hexdigest() != manifest['sha256']:
            raise ValueError('Download unvollständig oder Prüfsumme falsch.')
    except Exception:
        path.unlink(missing_ok=True)
        raise


def extract_program(packed, target, manifest):
    """Validate the entire ZIP before extracting; never accept userdata or data."""
    with zipfile.ZipFile(packed) as archive:
        entries = []
        seen = set()
        total = 0
        prefixes = set()
        for item in archive.infolist():
            name = item.filename
            parts = PurePosixPath(name).parts
            if not parts or name.startswith('/') or '\\' in name or any(x in ('.', '..') or ':' in x or x.rstrip(' .') != x for x in parts):
                raise ValueError('Unsicherer Pfad im Programmupdate.')
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Verknüpfungen im Programmupdate sind nicht erlaubt.')
            prefixes.add(parts[0])
            entries.append((item, parts))
        strip = len(prefixes) == 1 and next(iter(prefixes)) not in MANAGED
        for item, parts in entries:
            parts = parts[1:] if strip else parts
            if not parts:
                continue
            if parts[0] not in MANAGED or any(re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', x) for x in parts):
                raise ValueError('Nicht erlaubte Datei im Programmupdate.')
            key = '/'.join(parts).lower()
            if key in seen:
                raise ValueError('Doppelter Dateiname im Programmupdate.')
            seen.add(key)
            total += item.file_size
            if total > manifest['unpacked_bytes'] or len(seen) > 50000:
                raise ValueError('Entpacktes Programm ist größer als angekündigt.')
        if total != manifest['unpacked_bytes']:
            raise ValueError('Unvollständige Programmbeschreibung.')
        for item, parts in entries:
            parts = parts[1:] if strip else parts
            if not parts:
                continue
            output = target.joinpath(*parts)
            if item.is_dir():
                output.mkdir(parents=True, exist_ok=True)
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as inp, output.open('wb') as out:
                    shutil.copyfileobj(inp, out)
    required = ['AdultClient.exe', 'runtime/pythonw.exe', 'app/portable_entry.py', 'app/update_engine.py', 'release.json']
    if any(not (target / item).is_file() for item in required):
        raise ValueError('Im Programmupdate fehlen notwendige Dateien.')
    config = read(target / 'release.json', {})
    if config.get('version') != manifest['version']:
        raise ValueError('Programmversion und Updatebeschreibung stimmen nicht überein.')


class Updates:
    def init_updates(self):
        self.updater_stop = threading.Event()
        self.update_guard = threading.Lock()
        self.check_guard = threading.Lock()
        self.update_task = {'running': False, 'message': '', 'kind': '', 'phase': '', 'done': 0, 'total': 0}
        self.latest = None
        self.available = {'program': None, 'data': None}
        self.check_state = {'running': False, 'checked': 0, 'error': ''}
        self.preferences = read(self.profile/'update-settings.json', {'automatic': True, 'beta': True})
        cached = read(self.profile/'updates'/'discovery.json', {})
        if cached.get('repository') == self.config.get('repository') and cached.get('beta') == self.preferences.get('beta'):
            self.available = cached.get('available', self.available)
            self.check_state['checked'] = cached.get('checked', 0)
        self.program_pending = read(self.profile/'updates'/'program-ready.json')
        self.refresh_available()

    def refresh_available(self):
        current = read(self.profile/'model-package.json', {})
        for kind, candidate in self.available.items():
            if not candidate:
                continue
            try:
                manifest = candidate['manifest']
                candidate['available'] = (version(manifest['version']) > version(self.config['version'])) if kind == 'program' else (manifest['sha256'] != current.get('sha256') and timestamp(manifest['created']) > timestamp(current.get('created')))
            except (KeyError, ValueError):
                candidate['available'] = False

    def update_status(self):
        self.refresh_available()
        self.program_pending = read(self.profile/'updates'/'program-ready.json')
        if self.program_pending and version(self.program_pending['manifest']['version']) <= version(self.config['version']):
            self.program_pending = None
        return {'available': self.available, 'check': self.check_state, 'preferences': self.preferences,
                'program_pending': bool(self.program_pending), 'install_result': read(self.profile/'updates'/'install-result.json')}

    def discover(self):
        repo = self.config.get('repository', '')
        if not repo:
            raise ValueError('Noch kein Veröffentlichungs-Repository eingerichtet. Es wurde nichts hochgeladen.')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
            raise ValueError('Ungültiges Repository.')
        # Releases are independent: a data-only release must not hide the program release.
        candidates = {'program': None, 'data': None}
        for page in range(1, 6):
            releases = remote_json('https://api.github.com/repos/' + repo + '/releases?per_page=100&page=' + str(page), 4*1024*1024)
            for release in releases:
                if release.get('draft') or (release.get('prerelease') and not self.preferences.get('beta')):
                    continue
                assets = {a['name']: a for a in release.get('assets', [])}
                for kind, filename in [('program', 'program-update.json'), ('data', 'star-data.sqlite3.json')]:
                    if filename not in assets:
                        continue
                    url = github_asset(assets[filename]['browser_download_url'], repo)
                    manifest = validate_manifest(remote_json(url), kind)
                    asset = manifest.get('file')
                    if asset not in assets:
                        raise ValueError('Die veröffentlichte Paketdatei fehlt: ' + str(asset))
                    package = assets[asset]
                    if package.get('size') != manifest['bytes']:
                        raise ValueError('Veröffentlichte Paketgröße stimmt nicht überein.')
                    digest = package.get('digest')
                    if digest and digest != 'sha256:' + manifest['sha256']:
                        raise ValueError('GitHub-Prüfsumme stimmt nicht mit dem Paket überein.')
                    candidate = {'manifest': manifest, 'download': github_asset(package['browser_download_url'], repo),
                                 'notes': str(release.get('body') or '')[:12000], 'url': release.get('html_url', ''), 'version': manifest.get('version', manifest.get('created'))}
                    previous = candidates[kind]
                    key = version(manifest['version']) if kind == 'program' else timestamp(manifest['created'])
                    old = (version(previous['manifest']['version']) if kind == 'program' else timestamp(previous['manifest']['created'])) if previous else None
                    if old is None or key > old:
                        candidates[kind] = candidate
            if len(releases) < 100:
                break
        self.available = candidates
        self.check_state['checked'] = time.time()
        self.refresh_available()
        save(self.profile/'updates'/'discovery.json', {'repository': repo, 'beta': self.preferences.get('beta'), 'checked': self.check_state['checked'], 'available': candidates})

    def check_updates(self):
        if not self.config.get('repository'):
            raise ValueError('Noch kein Veröffentlichungs-Repository eingerichtet. Es wurde nichts hochgeladen.')
        if not self.check_guard.acquire(blocking=False):
            return self.status()
        self.check_state.update(running=True, error='')
        def work():
            try:
                self.discover()
            except urllib.error.HTTPError as error:
                self.check_state['error'] = ('Noch keine öffentliche Veröffentlichung erreichbar.' if error.code == 404 else 'GitHub ist vorübergehend nicht erreichbar. Bitte später erneut versuchen.')
                self.check_state['checked'] = time.time()
            except Exception as error:
                self.check_state['error'] = str(error)[:180]
                self.check_state['checked'] = time.time()
            finally:
                self.check_state['running'] = False
                self.check_guard.release()
        threading.Thread(target=work, daemon=True).start()
        return self.status()

    def start_update_checks(self):
        def loop():
            # Never block startup, playback or navigation on a remote request.
            while not self.updater_stop.wait(15):
                if self.preferences.get('automatic') and self.config.get('repository') and time.time() - self.check_state['checked'] >= 86400:
                    self.check_updates()
        threading.Thread(target=loop, daemon=True).start()

    def progress(self, done, total):
        self.update_task.update(done=done, total=total)

    def prepare(self, kind):
        self.refresh_available()
        candidate = self.available.get(kind)
        if not candidate or not candidate.get('available'):
            raise ValueError('Für diesen Bereich ist kein neueres Update verfügbar.')
        if not self.update_guard.acquire(blocking=False):
            raise ValueError('Bitte zuerst den laufenden Download abschließen lassen.')
        self.update_task = {'running': True, 'kind': kind, 'phase': 'download', 'done': 0, 'total': candidate['manifest']['bytes'], 'message': ''}
        def work():
            folder = self.profile/'updates'
            folder.mkdir(exist_ok=True)
            packed = folder/(kind + '-download.part')
            temp = folder/('program-staging' if kind == 'program' else 'pending.part')
            try:
                manifest = candidate['manifest']
                database = self.profile/'star_data.sqlite3'
                database_size = database.stat().st_size if database.exists() else 0
                # Reserve room for a transaction-safe backup and possible SQLite WAL growth.
                required = manifest['bytes'] + manifest['unpacked_bytes'] + 2*database_size + 64*1024**2
                if shutil.disk_usage(folder).free < required:
                    raise ValueError('Nicht genügend freier Speicher für Download und Entpacken.')
                download(github_asset(candidate['download'], self.config['repository']), packed, manifest, self.progress)
                self.update_task['phase'] = 'verify'
                if kind == 'program':
                    (folder/'program-ready.json').unlink(missing_ok=True)
                    self.program_pending = None
                    # Remove only our staging directory under this profile, never installation/user files.
                    if temp.exists():
                        shutil.rmtree(temp)
                    temp.mkdir()
                    extract_program(packed, temp, manifest)
                    if read(temp/'release.json', {}).get('repository') != self.config.get('repository'):
                        raise ValueError('Das Update würde die Veröffentlichungsquelle ändern.')
                    self.program_pending = {'manifest': manifest}
                    save(folder/'program-ready.json', self.program_pending)
                else:
                    count = 0
                    with gzip.open(packed, 'rb') as inp, temp.open('wb') as out:
                        while chunk := inp.read(1024*1024):
                            count += len(chunk)
                            if count > manifest['unpacked_bytes']:
                                raise ValueError('Datenpaket ist zu groß.')
                            out.write(chunk)
                    if count != manifest['unpacked_bytes']:
                        raise ValueError('Unvollständiges Datenpaket.')
                    with closing(sqlite3.connect(temp)) as db:
                        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                            raise ValueError('Datenpaket beschädigt.')
                    os.replace(temp, folder/'pending.sqlite3')
                    save(folder/'pending.json', manifest)
                self.update_task.update(phase='ready', message='')
            except Exception as error:
                self.update_task.update(phase='error', message=str(error)[:180])
                if temp.is_file():
                    temp.unlink(missing_ok=True)
            finally:
                packed.unlink(missing_ok=True)
                self.update_task['running'] = False
                self.update_guard.release()
        threading.Thread(target=work, daemon=True).start()

    def restart(self, install_program=False):
        if self.update_task['running']:
            raise ValueError('Bitte den laufenden Download zuerst abschließen lassen.')
        if install_program and not self.program_pending:
            raise ValueError('Zuerst das Programmupdate herunterladen.')
        folder = self.profile/'updates'
        folder.mkdir(exist_ok=True)
        if not self.update_guard.acquire(blocking=False):
            raise ValueError('Ein Update wird bereits vorbereitet.')
        try:
            helper = folder/'helper-runtime'
            if helper.exists():
                shutil.rmtree(helper)
            shutil.copytree(self.root/'runtime', helper, ignore=shutil.ignore_patterns('Lib', '__pycache__'))
            # The worker uses only stdlib. Its interpreter must not import the app being replaced.
            (helper/'python314._pth').write_text('python314.zip\n.\nDLLs\n', encoding='utf-8')
            shutil.copy2(Path(__file__), helper/'update_engine.py')
            plan = {'root': str(self.root), 'profile': str(self.profile), 'pid': os.getpid(), 'install_program': install_program}
            save(folder/'install-plan.json', plan)
            with self.app._star_extra_lock:
                self.app._star_extra_save(force=True)
            subprocess.Popen([str(helper/'pythonw.exe'), str(helper/'update_engine.py'), '--apply', str(folder/'install-plan.json')], cwd=str(helper), creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.stop.set()
            self.updater_stop.set()
            self.update_task.update(phase='restarting', message='')
            threading.Timer(1, lambda: os._exit(0)).start()
        except Exception:
            self.update_guard.release()
            raise


def wait_pid(pid, timeout):
    if os.name != 'nt':
        return True
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x100000, False, pid)
    if not handle:
        return True
    try:
        return kernel.WaitForSingleObject(handle, int(timeout*1000)) == 0
    finally:
        kernel.CloseHandle(handle)


def swap(root, staged, backup, journal):
    # Keep the bootstrap EXE stable: even a power loss between directory renames
    # must leave an entry point which can invoke the recovery worker.
    names = sorted(p.name for p in staged.iterdir() if p.name != 'AdultClient.exe' or not (root/p.name).exists())
    if not names or any(n not in MANAGED for n in names):
        raise ValueError('Ungültiges vorbereitetes Programmupdate.')
    backup.mkdir()
    save(journal, {'names': names})
    for name in names:
        dest = root/name
        if dest.exists():
            os.replace(dest, backup/name)
        os.replace(staged/name, dest)
    return names


def rollback(root, staged, backup, journal):
    for name in reversed(read(journal, {}).get('names', [])):
        original = backup/name
        dest = root/name
        # If staged still exists and no backup, this entry was never touched.
        changed = original.exists() or not (staged/name).exists()
        if changed and dest.exists():
            if dest.is_dir():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        if original.exists():
            os.replace(original, dest)
    journal.unlink(missing_ok=True)


def launch(root, profile, skip_data=False):
    env = os.environ.copy()
    env['AC_TEST_PROFILE'] = str(profile)
    env.pop('AC_SKIP_DATA_UPDATE', None)
    if skip_data:
        env['AC_SKIP_DATA_UPDATE'] = '1'
    for key in ('AH_PROFILE', 'AH_ADDON', 'AH_PORT', 'AH_MEDIA_PORT'):
        env.pop(key, None)
    return subprocess.Popen([str(root/'runtime'/'pythonw.exe'), str(root/'app'/'portable_entry.py'), '--wait-free'], cwd=str(root), env=env, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def healthy(process, root, profile, expected, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        if (profile/'startup-error.txt').exists():
            return False
        instance = read(profile/'instance.json', {})
        if instance.get('pid') == process.pid and (profile/'startup.ready').exists():
            try:
                url = instance['url']
                parsed = urllib.parse.urlsplit(url)
                if parsed.hostname == '127.0.0.1' and parsed.scheme == 'http':
                    with urllib.request.urlopen(url+'/api/distribution', timeout=2) as response:
                        state = json.load(response)
                    if state.get('version') == expected:
                        return True
            except (OSError, ValueError):
                pass
        time.sleep(.5)
    return False


def apply(plan):
    root, profile = Path(plan['root']).resolve(), Path(plan['profile']).resolve()
    folder = profile/'updates'
    staged, backup, journal = folder/'program-staging', folder/'program-backup', folder/'install-journal.json'
    changed = False
    stopped = False
    database_backup = None
    process = None
    try:
        if not wait_pid(int(plan['pid']), 45):
            raise ValueError('Das laufende Programm wurde nicht rechtzeitig beendet. Es wurden keine Dateien ersetzt.')
        stopped = True
        if plan['install_program']:
            if journal.exists():
                raise ValueError('Eine frühere Installation muss zuerst wiederhergestellt werden.')
            if backup.exists():
                shutil.rmtree(backup)
            manifest = read(folder/'program-ready.json', {})['manifest']
            if read(staged/'release.json', {}).get('version') != manifest['version']:
                raise ValueError('Vorbereitetes Programmupdate fehlt oder ist beschädigt.')
            if (profile/'star_data.sqlite3').exists():
                database_backup = folder/'before-program.sqlite3'
                database_backup.unlink(missing_ok=True)
                with closing(sqlite3.connect(profile/'star_data.sqlite3')) as source, closing(sqlite3.connect(database_backup)) as target:
                    source.backup(target)
            changed = True
            swap(root, staged, backup, journal)
            expected = manifest['version']
        else:
            expected = read(root/'release.json')['version']
        (profile/'startup.ready').unlink(missing_ok=True)
        (profile/'startup-error.txt').unlink(missing_ok=True)
        process = launch(root, profile, skip_data=plan['install_program'])
        if not healthy(process, root, profile, expected, timeout=180 if plan['install_program'] else 3600):
            raise ValueError('Die neue Version konnte nicht erfolgreich gestartet werden.')
        save(folder/'install-result.json', {'ok': True, 'version': expected, 'at': time.time()})
        if changed:
            (folder/'program-ready.json').unlink(missing_ok=True)
            journal.unlink(missing_ok=True)
    except Exception as error:
        if process and process.poll() is None:
            process.kill()
            process.wait(timeout=15)
        if changed and journal.exists():
            rollback(root, staged, backup, journal)
            if database_backup:
                for suffix in ('-wal', '-shm'):
                    (profile/('star_data.sqlite3'+suffix)).unlink(missing_ok=True)
                shutil.copy2(database_backup, profile/'star_data.sqlite3')
            (folder/'program-ready.json').unlink(missing_ok=True)
            # The failed program must not leave a data migration queued for the old program.
            save(folder/'install-result.json', {'ok': False, 'error': str(error)[:200], 'at': time.time()})
            launch(root, profile, skip_data=True)
        else:
            save(folder/'install-result.json', {'ok': False, 'error': str(error)[:200], 'at': time.time()})
            if stopped:
                launch(root, profile, skip_data=True)


def installer_lock(root):
    """The OS releases this lock on crash/power loss; recovery never races an installer."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateMutexW(None, True, 'Local\\AdultClient-Update-' + hashlib.sha256(str(root).encode()).hexdigest()[:20])
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(handle)
        return None
    return handle


def recover(plan):
    root, profile = Path(plan['root']), Path(plan['profile'])
    folder = profile/'updates'
    journal = folder/'install-journal.json'
    if journal.exists():
        rollback(root, folder/'program-staging', folder/'program-backup', journal)
        database_backup = folder/'before-program.sqlite3'
        if database_backup.exists():
            for suffix in ('-wal', '-shm'):
                (profile/('star_data.sqlite3'+suffix)).unlink(missing_ok=True)
            shutil.copy2(database_backup, profile/'star_data.sqlite3')
        (folder/'program-ready.json').unlink(missing_ok=True)
        save(folder/'install-result.json', {'ok': False, 'error': 'Die unterbrochene Installation wurde wiederhergestellt.', 'at': time.time()})
    launch(root, profile, skip_data=True)


if __name__ == '__main__' and len(sys.argv) == 3 and sys.argv[1] in ('--apply', '--recover'):
    plan = read(Path(sys.argv[2]))
    if plan:
        handle = installer_lock(Path(plan['root']).resolve())
        if handle:
            (apply if sys.argv[1] == '--apply' else recover)(plan)
