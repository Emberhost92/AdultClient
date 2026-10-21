"""CAM4 and XloveCam account adapters using their published website requests.

The transport and session persistence are supplied by the local server. Passwords
remain request-local. Public profile data never proves an authenticated account.

Website contracts checked 2026-10-18 against www.cam4.com's UserService.js
(/rest/v2.0/login and /rest/v2.0/login/user), and www.xlovecam.com/en/login/
plus its published common.js and WebAuthnys password encoder. These are website
interfaces, not promises of a stable third-party API.
"""
import base64
import http.cookiejar
import json
import re
import secrets
import urllib.parse


class WebsiteAccounts:
    COOKIES = {
        'cam4': ('JSESSIONID', 'cam4_SESSION_ID', 'INGRESSCOOKIE'),
        'xlovecam': ('PHPSESSID',),
    }
    LABELS = {'cam4': 'CAM4', 'xlovecam': 'XloveCam'}

    def __init__(self, backend):
        self.b = backend

    def request(self, site, path, jar, data=None, form=False):
        base = 'https://www.' + site + '.com'
        headers = {'User-Agent': self.b['_CAM_UA'], 'Accept': 'application/json,text/html',
                   'Referer': base + ('/en/login/' if site == 'xlovecam' else '/login'),
                   'Origin': base, 'X-Requested-With': 'XMLHttpRequest'}
        if data is not None:
            headers['Content-Type'] = ('application/x-www-form-urlencoded' if form else 'application/json')
            data = (urllib.parse.urlencode(data) if form else json.dumps(data)).encode('utf-8')
        status, raw = self.b['_cam_exchange'](base + path, headers, data, 12, 1_500_000, jar)
        document = raw.decode('utf-8', 'replace')
        if self.b['_cam_blocked'](document):
            return status, None
        try:
            value = json.loads(document)
        except ValueError:
            value = document
        return status, value

    @staticmethod
    def account_name(value):
        return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.@+\-]{2,80}', value) else ''

    @staticmethod
    def app_data(document):
        if not isinstance(document, str):
            return {}
        match = re.search(r'<script\b[^>]*\bid=[\"\']app-data[\"\'][^>]*>(.*?)</script>', document, re.S | re.I)
        try:
            data = json.loads(match[1]) if match else {}
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def xlove_page(self, jar):
        status, document = self.request('xlovecam', '/en/login/', jar)
        data = self.app_data(document) if status == 200 else {}
        config = data.get('Config')
        token = config.get('csrfProtectionToken') if isinstance(config, dict) else None
        return data, token if isinstance(token, str) and 1 <= len(token) <= 256 else ''

    def who(self, site, jar):
        if site == 'cam4':
            status, value = self.request(site, '/rest/v2.0/login/user', jar)
            if status != 200 or not isinstance(value, dict):
                return ''
            user_id = value.get('userId')
            if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
                return ''
            return self.account_name(value.get('username'))
        page, token = self.xlove_page(jar)
        if not token:
            return ''
        fields = {'csrfProtectionToken': token}
        page_user = page.get('user')
        auth = page_user.get('authPayload') if isinstance(page_user, dict) else None
        if isinstance(auth, str) and 0 < len(auth) <= 8000:
            fields['authPayload'] = auth
        status, value = self.request(site, '/en/user/info/', jar, fields, form=True)
        content = value.get('content') if isinstance(value, dict) else None
        user = content.get('userInfo') if isinstance(content, dict) else None
        if status != 200 or not isinstance(user, dict) or user.get('isAuth') not in (1, True):
            return ''
        return self.account_name(user.get('nickname'))

    def hint(self, site):
        return (self.LABELS[site] + ' hat die Anmeldung nicht bestätigt. Bitte Name und Passwort prüfen. '
                'Falls ein Browser-Check, CAPTCHA oder eine zusätzliche Bestätigung verlangt wird, '
                'auf der offiziellen Website anmelden und unten die Browser-Sitzung übernehmen. '
                'Eine vorhandene Kontoverbindung bleibt erhalten.')

    def store_verified(self, site, jar):
        name = self.who(site, jar)
        if not name or not any(True for _ in jar):
            return '', self.hint(site)
        self.b['_cam_session_store'](site, name, jar)
        return name, ''

    @staticmethod
    def xlove_password(password, key):
        """Match the site's WebAuthnys.encodeListKeyStr password wire format."""
        if not isinstance(key, str) or not re.fullmatch(r'\d{1,3}(?:,\d{1,3}){1,255}', key):
            raise ValueError('XloveCam hat keinen lesbaren Anmeldeschlüssel geliefert.')
        values = [int(part) for part in key.split(',')]
        if any(value > 255 for value in values):
            raise ValueError('XloveCam hat keinen lesbaren Anmeldeschlüssel geliefert.')
        raw = password.encode('utf-8')
        if len(raw) > 255:
            raise ValueError('Das XloveCam-Passwort ist für diesen Anmeldeweg zu lang.')
        padded = raw + secrets.token_bytes(max(0, 42 - len(raw)))
        encoded = bytes([len(raw) ^ values[0]]) + bytes(c ^ values[(i + 1) % len(values)] for i, c in enumerate(padded))
        return 'b64:' + base64.b64encode(encoded).decode('ascii')

    def login(self, site, username, password):
        jar = http.cookiejar.CookieJar()
        if site == 'cam4':
            status, _ = self.request(site, '/rest/v2.0/login/user', jar)
            if status != 200:
                return '', self.hint(site)
            status, value = self.request(site, '/rest/v2.0/login', jar,
                                         {'username': username, 'password': password})
            # Do not follow account redirects or attempt browser/2FA challenges.
            if (status != 200 or not isinstance(value, dict) or value.get('redirectUri')
                    or 'TWO_FA' in str(value.get('status', '')).upper() or value.get('error')):
                return '', self.hint(site)
        else:
            _, token = self.xlove_page(jar)
            if not token:
                return '', self.hint(site)
            status, value = self.request(site, '/en/login/popup/', jar,
                                         {'csrfProtectionToken': token, 'layer': 1}, form=True)
            content = value.get('content') if isinstance(value, dict) else None
            login = content.get('loginForm') if isinstance(content, dict) else None
            if status != 200 or not isinstance(login, dict):
                return '', self.hint(site)
            captcha = login.get('captcha')
            if isinstance(captcha, dict) and (captcha.get('google') or captcha.get('equation')):
                return '', self.hint(site)
            security_token = login.get('securityToken')
            if not isinstance(security_token, str) or not 1 <= len(security_token) <= 1000:
                return '', self.hint(site)
            form = {'nickname': username, 'password': password, 'token': security_token,
                    'csrfProtectionToken': token, 'stayConnected': 1, 'saveNickname': 0,
                    'webauthSupport': -1, 'webauthPlatform': -1}
            key = content.get('passwordKey')
            if key:
                try:
                    form.update(password='', passwordEncoded=self.xlove_password(password, key))
                except ValueError as error:
                    return '', str(error)
            status, value = self.request(site, '/en/login/submit/', jar, form, form=True)
            result = value.get('content') if isinstance(value, dict) else None
            if status != 200 or not isinstance(result, dict) or result.get('success') not in (1, True):
                return '', self.hint(site)
        return self.store_verified(site, jar)

    def session_take(self, site, raw):
        if not isinstance(raw, str) or not raw.strip() or len(raw) > 8000 or '\x00' in raw:
            return '', 'Bitte die angegebenen Sitzungscookies von der offiziellen Website einfügen.'
        names = self.COOKIES[site]
        parts = [part.strip() for part in re.split(r'[;\r\n]+', raw) if part.strip()]
        jar = http.cookiejar.CookieJar()
        for part in parts:
            name, sep, value = part.partition('=')
            if sep and name.strip() in names:
                name, value = name.strip(), value.strip()
            elif len(parts) == 1 and re.fullmatch(r'[A-Za-z0-9._~+/%\-]{8,2000}={0,3}', part):
                name, value = names[0], part
            else:
                continue
            if not re.fullmatch(r'[A-Za-z0-9._~+/%=\-]{8,2000}', value):
                continue
            # Domain comes from the provider, never from pasted text.
            self.b['_cam_put_cookie'](jar, name, value, '.cam4.com' if site == 'cam4' else 'www.xlovecam.com')
        if not any(c.name in names[:2] for c in jar):
            return '', 'Keine lesbare Sitzung gefunden. Bitte ' + ' und '.join(names[:2]) + ' prüfen.'
        return self.store_verified(site, jar)
