#!/usr/bin/env python3
"""Public performer metadata from IAFD + Data18, with explicit nulls and provenance.

Run: python models.py "Name"
Requires: requests, beautifulsoup4; selenium is loaded only for browser fallback.
Selectors/endpoints were checked against the upstream source files listed in
MODELS.md. This is an independent metadata-only implementation: no images, media
URLs, descriptions or explicit media are downloaded. Challenges are detected;
ordinary headless rendering is not a guaranteed Cloudflare bypass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
BASES = {"iafd": "https://www.iafd.com", "data18": "https://www.data18.com"}
SCHEMA_VERSION = 4
EMPTY = {"", "unknown", "no data", "n/a", "none", "not available", "not known"}
BODY_FIELDS = ("height", "weight", "measurements", "tattoos", "piercings")


class MetadataError(Exception):
    pass


class Blocked(MetadataError):
    pass


class NotFound(MetadataError):
    pass


def clean(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()
    return None if value.casefold() in EMPTY else value


def name_key(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip().casefold()


def unique(values) -> list:
    seen, result = set(), []
    for value in values:
        if isinstance(value, str) and (value := clean(value)) and name_key(value) not in seen:
            seen.add(name_key(value))
            result.append(value)
    return result


def safe_link(value: str, base: str) -> str | None:
    try:
        url = urljoin(base, value)
        parsed, origin = urlsplit(url), urlsplit(base)
        if parsed.scheme not in {"http", "https"} or parsed.username is not None:
            return None
        if (parsed.scheme, parsed.netloc.lower()) != (origin.scheme, origin.netloc.lower()):
            return None
        return url.split("#", 1)[0]
    except ValueError:
        return None


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".models-", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


class Cache:
    def __init__(self, folder: Path, ttl: float = 86400, refresh: bool = False):
        self.folder, self.ttl, self.refresh = folder, ttl, refresh

    def path(self, key: dict) -> Path:
        digest = hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()
        return self.folder / f"{key['source']}-{digest}.json"

    def get(self, key: dict) -> dict | None:
        if self.refresh or self.ttl == 0:
            return None
        try:
            record = json.loads(self.path(key).read_text(encoding="utf-8"))
            age = time.time() - record["saved_at"]
            if record["version"] == SCHEMA_VERSION and 0 <= age <= self.ttl:
                result = record["result"]
                if (
                    isinstance(result, dict)
                    and result.get("status") in {"ok", "partial"}
                    and result.get("source") == key["source"]
                    and all(field in result for field in empty_source(key["source"]))
                    and isinstance(result.get("attributes"), dict)
                    and isinstance(result.get("attributes", {}).get("body"), dict)
                    and all(field in result["attributes"]["body"] for field in BODY_FIELDS)
                    and not source_issues(result)
                ):
                    cached = {**result, "cache_hit": True,
                              "original_requests": result.get("requests", 0), "requests": 0,
                              "original_browser_used": result.get("browser_used", False),
                              "browser_used": False}
                    finalize_source(cached)
                    return cached
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def put(self, key: dict, result: dict) -> None:
        if self.ttl and result["status"] in {"ok", "partial"} and not source_issues(result):
            atomic_json(
                self.path(key), {"version": SCHEMA_VERSION, "saved_at": time.time(), "result": result}
            )


@dataclass
class Page:
    url: str
    html: str
    status: int | None = 200
    backend: str = "requests"

    @property
    def soup(self):
        return BeautifulSoup(self.html, "html.parser")


def blocker(html: str, headers: dict | None = None) -> str | None:
    headers = {key.lower(): value for key, value in (headers or {}).items()}
    lowered = html[:200_000].lower()
    if (
        headers.get("cf-mitigated", "").lower() == "challenge"
        or re.search(r"<title[^>]*>\s*(just a moment|attention required!\s*\|\s*cloudflare)", lowered)
        or ("/cdn-cgi/challenge-platform/" in lowered and 'id="challenge-form"' in lowered)
        or ("_cf_chl_opt" in lowered and "/cdn-cgi/challenge-platform/" in lowered)
    ):
        return "Cloudflare-Challenge"
    title = BeautifulSoup(html[:100_000], "html.parser").title
    if title and re.fullmatch(r"ADULTS\s+ONLY[!\s.]*", title.get_text(" ", strip=True), re.I):
        return "Altersabfrage"
    if re.search(r"<title[^>]*>[^<]*(captcha|access denied)", lowered):
        return "Zugriffsprüfung"
    return None


class Browser:
    """Selenium/CDP browser; no stealth patches or automated CAPTCHA interaction."""

    def __init__(self, browser_name="chrome", timeout=25, headless=True, driver_path=None, binary=None):
        self.browser_name, self.timeout, self.headless = browser_name, timeout, headless
        self.driver_path, self.binary, self.driver = driver_path, binary, None

    def start(self):
        if self.driver:
            return self.driver
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.service import Service as ChromeService
            from selenium.webdriver.edge.service import Service as EdgeService

            options = webdriver.EdgeOptions() if self.browser_name == "edge" else webdriver.ChromeOptions()
            if self.headless:
                options.add_argument("--headless=new")
            options.add_argument("--window-size=1280,900")
            options.page_load_strategy = "eager"
            options.set_capability(
                "ms:loggingPrefs" if self.browser_name == "edge" else "goog:loggingPrefs",
                {"performance": "ALL"},
            )
            if self.binary:
                options.binary_location = self.binary
            service_type = EdgeService if self.browser_name == "edge" else ChromeService
            service = service_type(executable_path=self.driver_path, log_output=os.devnull)
            # Selenium Manager supplies the matching driver when no explicit path is set.
            self.driver = (webdriver.Edge if self.browser_name == "edge" else webdriver.Chrome)(
                options=options,
                service=service,
            )
            self.driver.set_page_load_timeout(self.timeout)
            self.driver.execute_cdp_cmd("Network.enable", {})
            return self.driver
        except Exception as error:
            self.close()
            message = str(error).split("Stacktrace:", 1)[0][:1800]
            raise MetadataError(f"Selenium-{self.browser_name}-Start fehlgeschlagen: {message}") from None

    def install_state(self, cookies: list[dict], base: str, user_agent: str | None = None) -> None:
        driver = self.start()
        if user_agent:
            driver.execute_cdp_cmd("Network.setUserAgentOverride", {"userAgent": user_agent})
        accepted = []
        for cookie in cookies:
            domain = str(cookie.get("domain", "")).lstrip(".")
            host = urlsplit(base).hostname or ""
            if not domain or not (host == domain or host.endswith("." + domain)):
                continue
            expiry = cookie.get("expires", cookie.get("expiry", -1))
            if expiry and expiry > 0 and expiry <= time.time():
                continue
            item = {
                key: cookie[key]
                for key in ("name", "value", "domain", "path", "secure", "httpOnly")
                if key in cookie
            }
            if expiry and expiry > 0:
                item["expires"] = expiry
            if cookie.get("sameSite") in {"Strict", "Lax", "None"}:
                item["sameSite"] = cookie["sameSite"]
            if item.get("name") and isinstance(item.get("value"), str):
                accepted.append(item)
        if accepted:
            driver.execute_cdp_cmd("Network.setCookies", {"cookies": accepted})

    def export_state(self, base: str) -> dict:
        driver = self.start()
        host = urlsplit(base).hostname or ""
        cookies = driver.execute_cdp_cmd("Storage.getCookies", {}).get("cookies", [])
        cookies = [
            cookie
            for cookie in cookies
            if (host == cookie["domain"].lstrip(".") or host.endswith("." + cookie["domain"].lstrip(".")))
        ]
        return {"user_agent": driver.execute_script("return navigator.userAgent"), "cookies": cookies}

    def fetch(self, url: str, headers: dict | None = None, selector: str | None = None) -> Page:
        from selenium.common.exceptions import TimeoutException

        driver = self.start()
        driver.execute_cdp_cmd("Network.setExtraHTTPHeaders", {"headers": headers or {}})
        with suppress(Exception):
            driver.get_log("performance")
        try:
            driver.get(url)
        except TimeoutException:
            pass  # Inspect the loaded document within the bounded readiness window below.
        deadline = time.monotonic() + self.timeout
        status, response_headers = None, {}
        while True:
            html = driver.page_source
            with suppress(Exception):
                for entry in driver.get_log("performance"):
                    message = json.loads(entry["message"])["message"]
                    params = message.get("params", {})
                    response = params.get("response", {})
                    if (
                        message.get("method") == "Network.responseReceived"
                        and params.get("type") == "Document"
                        and response.get("url", "").split("#")[0] == driver.current_url.split("#")[0]
                    ):
                        status = int(response["status"])
                        response_headers = {
                            key.lower(): str(value) for key, value in response.get("headers", {}).items()
                        }
            if status == 429 or response_headers.get("retry-after"):
                raise Blocked("Browser: Rate-Limit/Warteaufforderung; später erneut versuchen")
            blocked = blocker(html, response_headers)
            ready = not selector or BeautifulSoup(html, "html.parser").select_one(selector)
            if not blocked and ready:
                break
            if blocked == "Altersabfrage":
                raise Blocked("Altersabfrage: --setup-session verwenden und die Freigabe selbst abschließen")
            if time.monotonic() >= deadline:
                raise Blocked(blocked or "Erwartete Seitenstruktur wurde im Browser nicht geladen")
            time.sleep(0.25)
        return Page(driver.current_url, html, status, "selenium-cdp")

    def close(self):
        if self.driver:
            with suppress(Exception):
                self.driver.quit()
            self.driver = None


class Fetcher:
    def __init__(self, source: str, base: str, args):
        self.source, self.base, self.args = source, base, args
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ModelMetadata/1.0", "Accept-Language": "en-US,en;q=0.8"})
        self.session.trust_env = False
        self.browser = Browser(
            args.browser_name, args.timeout, driver_path=args.driver_path, binary=args.browser_binary
        )
        self.state_file = args.session_dir / f"{source}.json"
        if source == "data18" and args.data18_session:
            self.state_file = args.data18_session
        self.state = {"cookies": []}
        self.browser_loaded, self.browser_sticky = False, args.browser == "always"
        self.last_request, self.requests = 0.0, 0
        if self.state_file.exists():
            try:
                self.state = json.loads(self.state_file.read_text(encoding="utf-8"))
                if not isinstance(self.state, dict) or not isinstance(self.state.get("cookies"), list):
                    raise ValueError("state schema")
                self._apply_state(self.state)
            except (OSError, ValueError, KeyError, TypeError):
                raise MetadataError(f"Sitzungsdatei nicht lesbar: {self.state_file}") from None

    def _apply_state(self, state):
        if state.get("user_agent"):
            self.session.headers["User-Agent"] = state["user_agent"]
        host = urlsplit(self.base).hostname or ""
        for cookie in state.get("cookies", []):
            domain = str(cookie.get("domain", host)).lstrip(".")
            if not domain or not (host == domain or host.endswith("." + domain)):
                continue
            expiry = cookie.get("expires", cookie.get("expiry", -1))
            if expiry and expiry > 0 and expiry <= time.time():
                continue
            self.session.cookies.set(
                cookie["name"],
                cookie["value"],
                domain=cookie.get("domain") or host,
                path=cookie.get("path", "/"),
                secure=bool(cookie.get("secure", False)),
            )

    def get(self, url: str, *, selector: str | None = None, referer: str | None = None, ajax=False) -> Page:
        if not safe_link(url, self.base):
            raise MetadataError("Quellenfremde URL verworfen")
        if self.requests >= self.args.max_requests:
            raise MetadataError("Abruflimit erreicht; Ergebnis ist unvollständig")
        self.requests += 1
        time.sleep(max(0, self.args.delay - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        headers = {"Referer": referer or self.base + "/"}
        if ajax:
            headers["X-Requested-With"] = "XMLHttpRequest"
        if not self.browser_sticky:
            try:
                with self.session.get(
                    url, headers=headers, timeout=self.args.timeout, stream=True
                ) as response:
                    body = bytearray()
                    for chunk in response.iter_content(65536):
                        body.extend(chunk)
                        if len(body) > self.args.max_bytes:
                            raise MetadataError("Antwort überschreitet das Größenlimit")
                    encoding = (
                        response.encoding if "charset=" in response.headers.get("Content-Type", "") else None
                    )
                    if not encoding:
                        encoding = BeautifulSoup(bytes(body), "html.parser").original_encoding or "utf-8"
                    page = Page(response.url, body.decode(encoding, errors="replace"), response.status_code)
                    reason = blocker(page.html, response.headers)
                    if page.status == 429 or response.headers.get("Retry-After"):
                        raise Blocked("Rate-Limit/Warteaufforderung; später erneut versuchen")
                    if reason == "Altersabfrage":
                        raise Blocked("Altersabfrage: Sitzung mit --setup-session data18 einrichten")
                    if page.status == 404 and not reason:
                        raise NotFound("Quellseite nicht gefunden (HTTP 404)")
                    if not reason and page.status < 400 and (not selector or page.soup.select_one(selector)):
                        return self._validate_origin(page)
                    if self.args.browser == "never":
                        raise Blocked(reason or f"HTTP {page.status} oder erwartete Struktur fehlt")
            except requests.RequestException as error:
                if self.args.browser == "never":
                    raise MetadataError(f"HTTP-Abruf fehlgeschlagen ({type(error).__name__})") from None
        try:
            if not self.browser_loaded:
                self.browser.install_state(
                    self.state.get("cookies", []), self.base, self.state.get("user_agent")
                )
                self.browser_loaded = True
            page = self.browser.fetch(url, headers, selector)
            state = self.browser.export_state(self.base)
        except MetadataError:
            raise
        except Exception as error:
            detail = str(error).split("Stacktrace:", 1)[0][:1200]
            raise MetadataError(f"Browser-Abruf fehlgeschlagen ({type(error).__name__}): {detail}") from None
        self._validate_origin(page)
        if len(page.html.encode("utf-8")) > self.args.max_bytes:
            raise MetadataError("Browser-Dokument überschreitet das Größenlimit")
        if page.status == 404:
            raise NotFound("Quellseite nicht gefunden (Browser HTTP 404)")
        if page.status is not None and page.status >= 400:
            raise Blocked(f"Browser meldet HTTP {page.status}")
        self._apply_state(state)
        self.browser_sticky = True  # Keep the working browser/TLS context for this source.
        return page

    def _validate_origin(self, page):
        if not safe_link(page.url, self.base):
            raise MetadataError("Weiterleitung auf einen anderen Host; Quelle nicht automatisch übernommen")
        return page

    def close(self):
        self.session.close()
        self.browser.close()


def empty_source(source: str) -> dict:
    return {
        "source": source,
        "status": "unavailable",
        "url": None,
        "name": None,
        "aliases": None,
        "attributes": {"hair": None, "body": dict.fromkeys(BODY_FIELDS)},
        "filmography_titles": None,
        "filmography_entries": None,
        "studios": None,
        "studio_entries": None,
        "studios_complete": False,
        "tags": None,
        "tag_entries": None,
        "tags_complete": False,
        "tags_expected": None,
        "tags_found": 0,
        "tags_origin": None,
        "tags_url": None,
        "tag_pages_read": 0,
        "filmography_complete": False,
        "details_complete": False,
        "collections": {},
        "field_status": {},
        "fetched_at": None,
        "cache_hit": False,
        "requests": 0,
        "browser_used": False,
        "warnings": [],
        "errors": [],
        "candidates": [],
    }


def source_issues(result: dict) -> list[str]:
    """Validate stored/source results before reuse; count proofs are never trusted blindly."""
    issues = []
    if not isinstance(result, dict) or any(key not in result for key in empty_source("iafd")):
        return ["Unvollständiges Quellenschema"]
    for field in ("name", "url", "fetched_at"):
        if result[field] is not None and not isinstance(result[field], str):
            issues.append(f"Ungültiger Typ: {field}")
    for field in ("aliases", "filmography_titles", "studios", "tags", "warnings", "errors"):
        values = result[field]
        if (values is None and field in {"warnings", "errors"}) or (values is not None and (
            not isinstance(values, list) or any(not isinstance(value, str) for value in values)
        )):
            issues.append(f"Ungültige Liste: {field}")
    for field in ("filmography_complete", "studios_complete", "tags_complete", "cache_hit", "browser_used"):
        if type(result[field]) is not bool:
            issues.append(f"Ungültiger Wahrheitswert: {field}")
    for field, label in (("filmography_entries", "title"), ("studio_entries", "name"),
                         ("tag_entries", "name")):
        entries = result[field]
        if entries is None:
            continue
        if not isinstance(entries, list) or any(
            not isinstance(row, dict) or (row.get(label) is not None and not isinstance(row[label], str))
            or (field == "filmography_entries" and not isinstance(row.get("url"), str))
            for row in entries
        ):
            issues.append(f"Ungültige Datensätze: {field}")
    attributes = result.get("attributes")
    if not isinstance(attributes, dict) or not isinstance(attributes.get("body"), dict):
        issues.append("Ungültige Attribute")
    else:
        for value in [attributes.get("hair"), *attributes["body"].values()]:
            if value is not None and not isinstance(value, str):
                issues.append("Nicht belegbarer Attributtyp")
    collections = result["collections"]
    if not isinstance(collections, dict):
        return issues + ["Ungültige Mengenprüfungen"]
    for section, report in collections.items():
        if not isinstance(report, dict):
            issues.append(f"Ungültige Mengenprüfung: {section}")
            continue
        total, count = report.get("expected"), report.get("found")
        if type(report.get("complete")) is not bool:
            issues.append(f"Ungültiger Wahrheitswert: {section}")
        if ((total is not None and (type(total) is not int or total < 0))
                or type(count) is not int or count < 0):
            issues.append(f"Ungültige Mengenwerte: {section}")
        if report.get("complete") and (
            total is None or count != total or report.get("parse_errors") != 0
            or report.get("missing_labels") != 0 or report.get("count_consistent") is not True
            or report.get("stop_reason") not in {"expected_count_reached", "end"}
        ):
            issues.append(f"Unbelegte Vollständigkeit: {section}")
    for field, complete in (("tags", "tags_complete"), ("studios", "studios_complete")):
        if result[complete]:
            report = collections.get(field, {})
            if (not isinstance(report, dict) or not report.get("complete")
                    or not isinstance(result[field], list)):
                issues.append(f"Unbelegte Vollständigkeit: {field}")
            elif len(result[field]) != report.get("unique_labels"):
                issues.append(f"Abweichende Anzahl: {field}")
    if result["filmography_complete"] and result["source"] == "data18":
        if not all(isinstance(collections.get(key), dict) and collections[key].get("complete") is True
                   for key in ("scenes", "movies")):
            issues.append("Unbelegte vollständige Filmografie")
    if result["source"] == "data18":
        entries = result["filmography_entries"]
        if isinstance(entries, list) and all(isinstance(row, dict) for row in entries):
            urls = [row.get("url") for row in entries]
            if len(urls) != len(set(url for url in urls if isinstance(url, str))):
                issues.append("Doppelte oder ungültige Filmografie-IDs")
            for section in ("scenes", "virtual_reality", "movies"):
                report = collections.get(section)
                if isinstance(report, dict):
                    count = sum(section in row.get("collections", []) for row in entries
                                if isinstance(row.get("collections"), list))
                    if report.get("found") != count:
                        issues.append(f"Datensätze und Mengenprüfung widersprechen sich: {section}")
        for section, entry_field in (("studios", "studio_entries"), ("tags", "tag_entries")):
            report = collections.get(section)
            entries = result[entry_field]
            if isinstance(report, dict) and isinstance(entries, list):
                if report.get("found") != len(entries):
                    issues.append(f"Datensätze und Mengenprüfung widersprechen sich: {section}")
                if all(isinstance(row, dict) for row in entries):
                    labels = unique(row.get("name") for row in entries)
                    if labels != result[section]:
                        issues.append(f"Namen und Datensätze widersprechen sich: {section}")
    return issues


def finalize_source(result: dict) -> None:
    blocked = result["status"] not in {"ok", "partial"}
    unavailable = "blocked" if result["status"] == "blocked" else "unavailable"
    checks = {}
    for field in ("name", "aliases"):
        checks[field] = unavailable if blocked else ("documented" if result[field] is not None else "unknown")
    checks["attributes.hair"] = unavailable if blocked else (
        "documented" if result["attributes"]["hair"] is not None else "unknown"
    )
    for field in BODY_FIELDS:
        checks[f"attributes.body.{field}"] = unavailable if blocked else (
            "documented" if result["attributes"]["body"][field] is not None else "unknown"
        )
    for field, flag in (("filmography_titles", "filmography_complete"),
                        ("studios", "studios_complete"), ("tags", "tags_complete")):
        checks[field] = unavailable if blocked else (
            "complete" if result[flag] else ("partial" if result[field] is not None else "unknown")
        )
    result["field_status"] = checks
    issues = source_issues(result)
    if issues:
        result["warnings"].extend("Validierungsfehler: " + issue for issue in issues)
        result.update(tags_complete=False, studios_complete=False, filmography_complete=False)
        if result["status"] == "ok":
            result["status"] = "partial"
        for key in ("filmography_titles", "studios", "tags"):
            if checks[key] == "complete":
                checks[key] = "partial"


def biography_fields(soup) -> dict:
    fields = {}
    for heading in soup.select("p.bioheading"):
        label = re.sub(r"\s+", " ", heading.get_text(" ", strip=True)).rstrip(":").casefold()
        node = heading.find_next_sibling()
        if node and "bioheading" not in node.get("class", []):
            fields[label] = node
    return fields


def parse_iafd_profile(page: Page) -> dict:
    result = empty_source("iafd")
    soup = page.soup
    fields = biography_fields(soup)
    title = soup.select_one("h1")
    if not title or not fields:
        raise MetadataError("IAFD-Profilstruktur nicht erkannt; keine Daten geraten")
    result.update(status="ok", url=page.url, name=clean(title.get_text(" ", strip=True)))
    hair = next((value for key, value in fields.items() if key.startswith("hair color")), None)
    if hair:
        result["attributes"]["hair"] = clean(hair.get_text(" ", strip=True))
    for label in BODY_FIELDS:
        if label in fields:
            result["attributes"]["body"][label] = clean(fields[label].get_text(" ", strip=True))
    aliases = next((value for key, value in fields.items() if "aka" in key), None)
    if aliases:
        text = aliases.get_text("\n", strip=True)
        if "no known aliases" in text.casefold():
            result["aliases"] = []
        else:
            values = [part for part in re.split(r"\n|,|;", text) if part.strip()]
            # Ambiguous 'A or B' is not promoted to either identity.
            result["aliases"] = unique(value for value in values if " or " not in value.casefold()) or None
    return result


def iafd_candidates(page: Page, base: str) -> list[dict]:
    found = {}
    for row in page.soup.select("#tblFem tr, #tblMal tr"):
        for anchor in row.select('a[href*="person.rme"]'):
            name = clean(anchor.get_text(" ", strip=True))
            url = safe_link(anchor.get("href", ""), base)
            if name and url:
                found[url] = {"name": name, "url": url}
    return list(found.values())


def iafd_film_links(page: Page) -> list[dict] | None:
    """Only tables labelled as filmography or with a Title/Film column are used.

    The upstream IAFD adapter does not itself scrape a profile's filmography.
    This semantic table discovery is intentionally conservative; unrecognised
    markup yields null rather than collecting unrelated sidebar recommendations.
    """
    found, recognized = {}, False
    for table in page.soup.select("table"):
        headings = [item.get_text(" ", strip=True).casefold() for item in table.select("th")]
        hint = (str(table.get("id", "")) + " " + str(table.get("aria-label", ""))).casefold()
        if not (
            "filmography" in hint
            or (table.get("id") == "personal"
                and any(re.fullmatch(r"title|film|movie|film title", label) for label in headings))
        ):
            continue
        recognized = True
        for anchor in table.select('a[href*="title.rme"]'):
            title, url = clean(anchor.get_text(" ", strip=True)), safe_link(anchor["href"], page.url)
            if title and url:
                found[url] = {"title": title, "url": url}
    return list(found.values()) if recognized else None


def iafd_metadata(name: str, fetcher: Fetcher, args) -> dict:
    base = fetcher.base
    if args.iafd_url:
        if not safe_link(args.iafd_url, base) or "/person.rme/" not in args.iafd_url:
            raise MetadataError("--iafd-url muss eine IAFD-Profil-URL sein")
        url = args.iafd_url
    else:
        search = base + "/results.asp?" + urlencode({"searchtype": "comprehensive", "searchstring": name})
        page = fetcher.get(search, selector="#tblFem, #tblMal, p.bioheading")
        if "/person.rme/" in urlsplit(page.url).path:
            candidate = parse_iafd_profile(page)
            if name_key(candidate["name"] or "") == name_key(name):
                url = page.url
            else:
                raise MetadataError("IAFD leitete auf einen nicht eindeutig passenden Namen weiter")
        else:
            candidates = iafd_candidates(page, base)
            exact = [item for item in candidates if name_key(item["name"]) == name_key(name)]
            if len(exact) != 1:
                result = empty_source("iafd")
                result.update(status="ambiguous" if candidates else "not_found", candidates=candidates)
                result["errors"].append("Kein eindeutiger Namensmatch; bei Bedarf --iafd-url angeben")
                return result
            url = exact[0]["url"]
    page = fetcher.get(url, selector="p.bioheading")
    result = parse_iafd_profile(page)
    if not args.iafd_url and name_key(result["name"] or "") != name_key(name):
        raise MetadataError("IAFD-Profilname weicht vom gewählten Suchtreffer ab; keine Zuordnung geraten")
    films = iafd_film_links(page)
    if films is None:
        result["status"] = "partial"
        result["warnings"].append("IAFD-Filmografietabelle nicht erkannt; Titel bleiben null")
        return result
    result["filmography_titles"] = unique(item["title"] for item in films)
    result["filmography_entries"] = [dict(item, kind="movie") for item in films]
    # The live profile/table layout has not been verified. No next-link is not a total-count proof.
    result["filmography_complete"] = False
    result["warnings"].append("IAFD: Keine unabhängig abgeglichene Gesamtzahl der Filmografie verfügbar")
    studios, checked = [], 0
    for film in films[: args.max_details]:
        try:
            detail = fetcher.get(film["url"], referer=page.url)
            fields = biography_fields(detail.soup)
            studio = next((node for label, node in fields.items() if label.startswith("studio")), None)
            if studio:
                studios.extend(node.get_text(" ", strip=True) for node in studio.select("a"))
                if not studio.select("a"):
                    studios.append(studio.get_text(" ", strip=True))
            checked += 1
        except MetadataError as error:
            result["warnings"].append(f"IAFD-Filmdetails unvollständig: {error}")
            break
    result["studios"] = unique(studios) or None
    result["studios_complete"] = False
    result["details_complete"] = checked == len(films)
    if not result["filmography_complete"] or not result["details_complete"]:
        result["status"] = "partial"
        result["warnings"].append("Filmografie oder Detailabrufe begrenzt; Vollständigkeitsflags beachten")
    return result


def data18_items(page: Page, kind: str = "scene") -> list[dict]:
    rows = []
    prefix, path = ("mitem", "/movies/") if kind == "movie" else ("item", "/scenes/")
    for box in page.soup.select(f'div[id^="{prefix}"]'):
        if not re.fullmatch(prefix + r"\d+", box.get("id", "")):
            continue
        anchors = [
            node for node in box.select(f'a[href*="{path}"]')
            if "#" not in node["href"] and safe_link(node["href"], page.url)
        ]
        # Visible link text is the title. Image tooltips may name the containing movie instead.
        anchor = next((node for node in anchors if clean(node.get_text(" ", strip=True))), None)
        if anchor is None:
            anchor = next(iter(anchors), None)
        if anchor is None or not (url := safe_link(anchor["href"], page.url)):
            continue
        if not re.fullmatch(path + r"\d+(?:-[^/]+)?", urlsplit(url).path):
            continue
        title = clean(anchor.get_text(" ", strip=True))
        title_origin = "visible_text" if title else None
        if title and title.endswith(("..", "…")):
            prefix_text = title.rstrip(".…").strip()
            expanded = unique(
                image.get("alt") for node in anchors for image in node.select("img[alt]")
                if safe_link(node["href"], page.url) == url
                and (clean(image.get("alt")) or "").startswith(prefix_text)
            )
            title = expanded[0] if len(expanded) == 1 else None
            title_origin = "image_alt_confirmed_by_caption" if title else None
        studio_nodes = [node for node in box.select('a[href*="/studios/"], a[href*="/sites/"]')
                        if re.match(r"^/(studios|sites)/", urlsplit(urljoin(page.url, node["href"])).path)
                        and safe_link(node["href"], page.url)]
        if url:
            rows.append(
                {
                    "title": title,
                    "url": url.split("?", 1)[0],
                    "kind": kind,
                    "title_origin": title_origin,
                    "title_scope": "source_listing_label",
                    "studios": unique(node.get_text(" ", strip=True) for node in studio_nodes),
                    "studio": clean(studio_nodes[0].get_text(" ", strip=True)) if studio_nodes else None,
                    "performers": [
                        (item.get("href", ""), item.get_text(" ", strip=True))
                        for item in box.select('a[href*="/name/"]')
                    ],
                }
            )
    return rows


def data18_tags(page: Page) -> list[str] | None:
    tags = []
    recognized = False
    for label in page.soup.find_all(["b", "span"]):
        if label.get_text(strip=True) not in {"Categories:", "Ethnicity:"}:
            continue
        recognized = True
        for anchor in label.parent.select('a[href*="/tags/"]'):
            tags.append(anchor.get_text(" ", strip=True))
    return unique(tags) if recognized else None


def data18_tag_rows(page: Page) -> dict[str, str]:
    """Parse category rows, excluding ranks and scene/movie counts from names."""
    found = {}
    for node in page.soup.select('p.listtag[id^="tag_"]'):
        match = re.fullmatch(
            r"#\d+\s*-\s*(\d+)\s*-\s*(.+?)\s*-{2,}\s*[\d,]+\s+scenes?\s*-\s*[\d,]+\s+movies?",
            node.get_text(" ", strip=True),
            re.I,
        )
        if match and node["id"] == "tag_" + match[1] and (label := clean(match[2])):
            found[match[1]] = label
    return found


DATA18_SECTIONS = {
    "scenes": ("scenes", 2, "", "scene"),
    "virtual_reality": ("virtual-reality", 10, "", "vr_scene"),
    "movies": ("movies", 3, "", "movie"),
    "studios": ("studios", 6, "studios", None),
    "tags": ("tags", 7, "", None),
}


def data18_menu(profile: Page) -> dict:
    menu = {}
    for section, (suffix, *_rest) in DATA18_SECTIONS.items():
        url = profile.url.rstrip("/") + "/" + suffix
        for node in profile.soup.select("a[href]"):
            if safe_link(node["href"], profile.url) != url:
                continue
            count = re.fullmatch(r".+?\s*-\s*([\d,]+)", node.get_text(" ", strip=True))
            if count:
                menu[section] = {"url": url, "expected": int(count[1].replace(",", ""))}
                break
    return menu


def data18_collection_rows(page: Page, section: str) -> tuple[list[dict], int]:
    """Return parsed records and malformed candidates; never silently skip a changed card."""
    if section == "tags":
        nodes = page.soup.select('p.listtag[id^="tag_"]')
        rows = [{"id": key, "name": value} for key, value in data18_tag_rows(page).items()]
    elif section == "studios":
        rows = []
        nodes = page.soup.select('#listing_results .navstarzone[id^="opennavstarzone-"]')
        for node in nodes:
            identity = re.fullmatch(r"opennavstarzone-(\d+)-(\d+)-(\d+)", node["id"])
            box = node.find_parent("div")
            label = box.find("b", recursive=False) if box else None
            if not identity or not label or not (name := clean(label.get_text(" ", strip=True))):
                continue
            link = box.find_parent("a", href=True)
            url = safe_link(link["href"], page.url) if link else None
            if not url:
                button = box.select_one('button[onclick]')
                match = re.fullmatch(r"window\.location\s*=\s*['\"]([^'\"]+)['\"];?", button["onclick"]) \
                    if button else None
                url = safe_link(match[1], page.url) if match else None
            rows.append({"id": identity[1] + ":" + identity[2], "name": name, "url": url})
    else:
        kind = DATA18_SECTIONS[section][3]
        prefix = "mitem" if kind == "movie" else "item"
        nodes = page.soup.select(f'div[id^="{prefix}"]')
        rows = [{**row, "id": row["url"]} for row in data18_items(page, kind)]
    return rows, max(0, len(nodes) - len(rows))


def data18_next_page(page: Page, number: int) -> bool | None:
    container = page.soup.select_one("#pagination_bar")
    if page.soup.select_one('a[rel~="next"]'):
        return True
    if container is None:
        return None
    for node in container.select(".spage[id], .mpage[id]"):
        match = re.fullmatch(r"[sm]page[a-c]?(\d+)", node["id"])
        if match and int(match[1]) > number:
            return True
    return False


def data18_collection(profile: Page, fetcher: Fetcher, args, section: str, spec: dict) -> tuple[list, dict]:
    suffix, mode, html2, _kind = DATA18_SECTIONS[section]
    report = {
        "url": spec["url"], "expected": spec["expected"], "found": 0,
        "unique_labels": 0, "missing_labels": 0, "complete": False, "pages_read": 0, "parse_errors": 0,
        "count_consistent": True, "stop_reason": "page_limit", "page_urls": [],
    }
    legacy = spec.get("legacy", False)
    if legacy:
        mode = 1
    found = {}
    slug = urlsplit(profile.url).path.rstrip("/").rsplit("/", 1)[-1]
    for number in range(1, args.max_pages + 1):
        try:
            if number == 1 and not legacy:
                page = fetcher.get(spec["url"], referer=profile.url)
            else:
                page_key = "mpage" if section == "movies" else "spage"
                params = {"t": 2, "b": mode, "o": 0, "html": slug, "html2": html2,
                          "total": 0, "doquery": 1, page_key: number, "dopage": 1}
                page = fetcher.get(
                    fetcher.base + "/sys/page.php?" + urlencode(params),
                    referer=spec["url"], ajax=True,
                )
            report["pages_read"] += 1
            report["page_urls"].append(page.url)
            # A change in an advertised total must not turn into a false completeness claim.
            if number == 1 and not legacy:
                current = data18_menu(Page(profile.url, page.html)).get(section)
                if current and current["expected"] != spec["expected"]:
                    report["count_consistent"] = False
            rows, malformed = data18_collection_rows(page, section)
            for row in rows:
                row["source_page"] = page.url
            report["parse_errors"] += malformed
            fresh = {}
            for row in rows:
                previous = found.get(row["id"], fresh.get(row["id"]))
                if (previous and previous.get("name", previous.get("title"))
                        != row.get("name", row.get("title"))):
                    report["count_consistent"] = False
                if row["id"] not in found:
                    fresh[row["id"]] = row
            if not rows:
                empty = not page.soup.get_text(" ", strip=True)
                known_empty = spec["expected"] == 0 and page.soup.select_one("#listing_results")
                report["stop_reason"] = "end" if empty or known_empty else "unrecognized_layout"
                break
            if not fresh:
                report["stop_reason"] = "repeated_page"
                break
            found.update(fresh)
            if spec["expected"] is not None and len(found) >= spec["expected"]:
                report["stop_reason"] = "expected_count_reached"
                break
            if data18_next_page(page, number) is False:
                report["stop_reason"] = "end"
                break
        except MetadataError as error:
            report["stop_reason"] = "blocked" if isinstance(error, Blocked) else "fetch_error"
            report["error"] = str(error)
            break
    report["found"] = len(found)
    report["unique_labels"] = len(unique(row.get("name", row.get("title")) for row in found.values()))
    report["missing_labels"] = sum(not clean(row.get("name", row.get("title"))) for row in found.values())
    # Absence of a next-link or an empty response alone cannot prove a declared collection complete.
    report["complete"] = (
        spec["expected"] is not None and report["found"] == spec["expected"]
        and report["parse_errors"] == 0 and report["missing_labels"] == 0 and report["count_consistent"]
        and report["stop_reason"] in {"expected_count_reached", "end"}
    )
    if section in {"tags", "studios"}:
        report["complete"] &= report["unique_labels"] == report["found"]
    return list(found.values()), report


def data18_metadata(name: str, fetcher: Fetcher, args) -> dict:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug and not args.data18_url:
        raise MetadataError("Data18-Slug kann aus diesem Namen nicht bestimmt werden")
    profile_url = args.data18_url or fetcher.base + "/name/" + slug
    if not safe_link(profile_url, fetcher.base) or not re.fullmatch(
        r"/name/[^/]+", urlsplit(profile_url).path
    ) or urlsplit(profile_url).query or urlsplit(profile_url).fragment:
        raise MetadataError("--data18-url muss eine Data18-Profil-URL ohne Filter sein")
    profile = fetcher.get(profile_url)
    if profile.url.rstrip("/") != profile_url:
        raise MetadataError("Data18 leitete auf ein anderes Profil weiter; Zuordnung abgebrochen")
    heading = profile.soup.select_one("h1")
    candidates = [heading.get_text(" ", strip=True)] if heading else []
    candidates.extend(
        node.get_text(" ", strip=True) for node in profile.soup.select("a[href]")
        if safe_link(node["href"], profile.url) == profile_url
    )
    if heading and name_key(heading.get_text(" ", strip=True)) != name_key(name) and not args.data18_url:
        raise MetadataError("Data18-Profilname stimmt nicht mit der Anfrage überein")
    identity = clean(heading.get_text(" ", strip=True)) if args.data18_url and heading else next(
        (clean(value) for value in candidates if name_key(value) == name_key(name)), None
    )
    if not identity:
        raise MetadataError("Data18-Profilname nicht belegt; keine Zuordnung geraten")
    result = empty_source("data18")
    result.update(status="ok", url=profile.url, name=identity,
                  identity_basis="explicit_profile_url" if args.data18_url else "exact_name")
    menu = data18_menu(profile)
    if not any(key in menu for key in ("scenes", "movies", "virtual_reality")):
        menu["scenes"] = {"url": profile_url, "expected": None, "legacy": True}
    film_rows, fallback_tags, blocked = {}, [], False
    for section in DATA18_SECTIONS:
        if section not in menu or blocked:
            continue
        rows, report = data18_collection(profile, fetcher, args, section, menu[section])
        result["collections"][section] = report
        blocked = report["stop_reason"] == "blocked"
        if not report["complete"]:
            result["warnings"].append(
                f"Data18 {section}: {report['found']} / "
                f"{report['expected'] if report['expected'] is not None else 'unbekannt'}; "
                f"{report['stop_reason']} (Parsefehler: {report['parse_errors']})"
            )
        if section == "tags":
            result.update(
                tag_entries=rows if rows or report["complete"] else None,
                tags=unique(row["name"] for row in rows) if rows or report["complete"] else None,
                tags_origin="profile_overview" if rows or report["complete"] else None,
                tags_url=menu[section]["url"], tags_expected=report["expected"],
                tags_found=report["unique_labels"], tags_complete=report["complete"],
                tag_pages_read=report["pages_read"],
            )
        elif section == "studios":
            result["studio_entries"] = rows if rows or report["complete"] else None
            result["studios"] = unique(row["name"] for row in rows) if rows or report["complete"] else None
            result["studios_complete"] = report["complete"]
        else:
            for row in rows:
                record = {key: value for key, value in row.items() if key not in {"performers", "id"}}
                record["collections"] = [section]
                if row["url"] not in film_rows:
                    film_rows[row["url"]] = record
                else:
                    existing = film_rows[row["url"]]
                    if name_key(existing["title"] or "") != name_key(row["title"] or ""):
                        report["complete"] = False
                        result["warnings"].append("Data18: Widersprüchliche Titel für dieselbe Datensatz-URL")
                    existing["collections"].append(section)
                    existing["studios"] = unique(existing["studios"] + row["studios"])
    film_sections = set(menu).intersection({"scenes", "movies", "virtual_reality"})
    known_empty = bool(film_sections) and all(
        result["collections"].get(key, {}).get("complete")
        and result["collections"][key]["found"] == 0 for key in film_sections
    )
    result["filmography_entries"] = list(film_rows.values()) if film_rows or known_empty else None
    result["filmography_titles"] = unique(row["title"] for row in film_rows.values()) or (
        [] if known_empty else None
    )
    result["filmography_complete"] = (
        {"scenes", "movies"}.issubset(film_sections)
        and all(result["collections"].get(key, {}).get("complete", False) for key in film_sections)
    )
    if result["studios"] is None:
        result["studios"] = unique(studio for row in film_rows.values() for studio in row["studios"]) or None
    if result["tags_origin"] is None and not blocked:
        checked = 0
        for row in list(film_rows.values())[:args.max_details]:
            try:
                detail = fetcher.get(row["url"], referer=profile.url)
                values = data18_tags(detail)
                if values is not None:
                    fallback_tags.extend(values)
                checked += 1
            except MetadataError as error:
                result["warnings"].append(f"Data18-Details unvollständig: {error}")
                break
        result["details_complete"] = bool(film_rows) and checked == len(film_rows)
        result["tags"] = unique(fallback_tags) or None
        result["tags_found"] = len(result["tags"] or [])
        result["tags_origin"] = "scene_details" if result["tags"] else None
    else:
        result["details_complete"] = None  # Not required when the profile overview supplies tags.
    if not all(result[key] for key in ("filmography_complete", "studios_complete", "tags_complete")):
        result["status"] = "partial"
    return result


def merge(name: str, results: list[dict]) -> dict:
    available = [item for item in results if item["status"] in {"ok", "partial"} and item["name"]]
    primary = available[0] if available else None
    identities = (
        {name_key(primary["name"]), *(name_key(alias) for alias in primary["aliases"] or [])}
        if primary
        else set()
    )
    compatible = [
        item
        for item in available
        if identities.intersection(
            {name_key(item["name"]), *(name_key(alias) for alias in item["aliases"] or [])}
        )
    ]
    mismatched = [item["source"] for item in available if item not in compatible]
    result = {
        "query": name,
        "name": primary["name"] if primary else None,
        "aliases": None,
        "attributes": {"hair": None, "body": dict.fromkeys(BODY_FIELDS)},
        "filmography_titles": None,
        "filmography_entries": None,
        "filmography_complete": False,
        "studios": None,
        "studios_complete": False,
        "tags": None,
        "tags_complete": False,
        "tags_scope": "filmography_metadata_not_personal_traits",
        "conflicts": [],
        "identity_basis": "Name/alias overlap; cross-site identity not independently verified",
        "sources": {item["source"]: item for item in results},
        "warnings": ["Mengenabgleiche gelten nur für die gelesenen Quellensammlungen"],
    }
    if mismatched:
        result["warnings"].append("Abweichende Identitäten nicht zusammengeführt: " + ", ".join(mismatched))
    for field in ("aliases", "filmography_titles", "studios", "tags"):
        known = [item[field] for item in compatible if item[field] is not None]
        if known:
            result[field] = unique(value for group in known for value in group)
    tag_sources = [item for item in compatible if item["tags"] is not None]
    result["tags_complete"] = bool(tag_sources) and all(item["tags_complete"] for item in tag_sources)
    for field, flag in (("filmography_titles", "filmography_complete"), ("studios", "studios_complete")):
        providers = [item for item in compatible if item[field] is not None]
        result[flag] = bool(providers) and all(item[flag] for item in providers)
    entries = {}
    for item in compatible:
        for entry in item["filmography_entries"] or []:
            entries.setdefault(entry["url"], {**entry, "source": item["source"]})
    result["filmography_entries"] = list(entries.values()) or None
    for section, field in [("hair", None), *(("body", key) for key in BODY_FIELDS)]:
        values = {
            item["source"]: (item["attributes"][section][field] if field else item["attributes"][section])
            for item in compatible
        }
        values = {source: value for source, value in values.items() if value is not None}
        if len(unique(values.values())) > 1:
            result["conflicts"].append(
                {"field": f"attributes.{section}" + (f".{field}" if field else ""), "values": values}
            )
        elif values:
            value = next(iter(values.values()))
            if field:
                result["attributes"][section][field] = value
            else:
                result["attributes"][section] = value
    result["field_status"], result["provenance"] = {}, {}
    scalar_fields = {"name": result["name"], "aliases": result["aliases"],
                     "attributes.hair": result["attributes"]["hair"]}
    scalar_fields.update({f"attributes.body.{key}": result["attributes"]["body"][key] for key in BODY_FIELDS})
    conflicts = {item["field"] for item in result["conflicts"]}
    for field, value in scalar_fields.items():
        result["field_status"][field] = "conflict" if field in conflicts else (
            "documented" if value is not None else "unknown"
        )
    for field, flag in (("filmography_titles", "filmography_complete"),
                        ("studios", "studios_complete"), ("tags", "tags_complete")):
        result["field_status"][field] = "complete" if result[flag] else (
            "partial" if result[field] is not None else "unknown"
        )
    for field in result["field_status"]:
        providers = []
        for item in compatible:
            value = item
            for key in field.split("."):
                value = value.get(key) if isinstance(value, dict) else None
            if value is not None:
                url = item["collections"].get(field, {}).get("url", item["url"])
                providers.append({"source": item["source"], "url": url,
                                  "fetched_at": item["fetched_at"]})
        result["provenance"][field] = providers
    result["status"] = "unavailable" if result["name"] is None else (
        "ok" if all(value in {"documented", "complete"} for value in result["field_status"].values())
        and all(item["status"] == "ok" for item in results) else "partial"
    )
    return result


def collect(name: str, args, bases=None) -> dict:
    results = []
    cache = Cache(args.cache_dir, args.cache_ttl, args.refresh)
    for source in args.sources:
        base = (bases or BASES)[source]
        key = {
            "source": source,
            "query": name_key(name),
            "base": base,
            "profile": args.iafd_url,
            "data18_profile": args.data18_url,
            "max_pages": args.max_pages,
            "max_details": args.max_details,
            "max_requests": args.max_requests,
            "version": SCHEMA_VERSION,
        }
        result = cache.get(key)
        if result:
            results.append(result)
            continue
        result, fetcher = empty_source(source), None
        try:
            fetcher = Fetcher(source, base, args)
            result = (iafd_metadata if source == "iafd" else data18_metadata)(name, fetcher, args)
            result["requests"] = fetcher.requests
            result["browser_used"] = fetcher.browser_loaded
            result["fetched_at"] = datetime.now(timezone.utc).isoformat()
            finalize_source(result)
            try:
                cache.put(key, result)
            except OSError as error:
                result["warnings"].append(
                    f"Metadaten gelesen, Cache konnte nicht geschrieben werden: {error}"
                )
        except (MetadataError, OSError, ValueError) as error:
            result["status"] = (
                "blocked"
                if isinstance(error, Blocked)
                else ("not_found" if isinstance(error, NotFound) else "unavailable")
            )
            result["errors"].append(str(error))
        finally:
            if fetcher:
                result["requests"] = fetcher.requests
                result["browser_used"] = fetcher.browser_loaded
                fetcher.close()
        if result["fetched_at"] is None:
            result["fetched_at"] = datetime.now(timezone.utc).isoformat()
        finalize_source(result)
        results.append(result)
    return merge(name, results)


def setup_session(source: str, args) -> dict:
    browser = Browser(
        args.browser_name,
        args.timeout,
        headless=False,
        driver_path=args.driver_path,
        binary=args.browser_binary,
    )
    try:
        driver = browser.start()
        driver.get(BASES[source] + "/")
        print("Im Browser Freigabe/Anmeldung selbst abschließen. Danach hier Enter drücken.", file=sys.stderr)
        input()
        if blocker(driver.page_source):
            raise Blocked("Freigabe noch nicht abgeschlossen; keine Sitzung gespeichert")
        if not safe_link(driver.current_url, BASES[source]):
            raise Blocked("Browser befindet sich nicht auf der gewählten Quelle; keine Sitzung gespeichert")
        destination = args.session_dir / f"{source}.json"
        atomic_json(destination, browser.export_state(BASES[source]))
        return {"source": source, "session_saved": str(destination)}
    finally:
        browser.close()


def arguments(argv=None):
    parser = argparse.ArgumentParser(description="IAFD + Data18: belegte Modell-Metadaten als JSON")
    parser.add_argument("name", nargs="?")
    parser.add_argument("--sources", nargs="+", choices=list(BASES), default=list(BASES))
    parser.add_argument("--browser", choices=["auto", "never", "always"], default="auto")
    parser.add_argument("--browser-name", choices=["chrome", "edge"], default="chrome")
    parser.add_argument("--browser-binary", help="Optionaler Browserpfad")
    parser.add_argument("--driver-path", help="Optionaler Chrome-/EdgeDriver-Pfad")
    parser.add_argument("--setup-session", choices=list(BASES))
    parser.add_argument("--session-dir", type=Path, default=ROOT / ".auth" / "models")
    parser.add_argument("--data18-session", type=Path, help="Auch setup_session.py-Format wird unterstützt")
    parser.add_argument("--iafd-url", help="Explizite IAFD-Profil-URL bei Namensmehrdeutigkeit")
    parser.add_argument("--data18-url", help="Bestätigte Data18-Profil-URL, z. B. aus dem Quellkatalog")
    parser.add_argument("--max-pages", type=int, default=50)
    parser.add_argument("--max-details", type=int, default=50)
    parser.add_argument("--max-requests", type=int, default=160)
    parser.add_argument("--max-bytes", type=int, default=5 * 1024 * 1024)
    parser.add_argument("--timeout", type=float, default=25)
    parser.add_argument("--delay", type=float, default=0.75)
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "data" / "cache")
    parser.add_argument("--cache-ttl", type=float, default=86400)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args(argv)
    if not args.setup_session and not clean(args.name):
        parser.error('Modellnamen angeben, z. B. python models.py "Name"')
    if (
        args.max_pages < 1
        or args.max_details < 0
        or args.max_requests < 1
        or args.max_bytes < 1
        or args.timeout <= 0
        or args.delay < 0
        or args.cache_ttl < 0
    ):
        parser.error("Ungültige Abruf-, Zeit- oder Cache-Grenzen")
    args.sources = list(dict.fromkeys(args.sources))
    return args


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = arguments(argv)
    try:
        result = (
            setup_session(args.setup_session, args)
            if args.setup_session
            else collect(args.name.strip(), args)
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.setup_session:
            return 0
        return 0 if result["status"] == "ok" else (2 if result["name"] else 1)
    except (MetadataError, OSError, ValueError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 1
    except KeyboardInterrupt:
        print(json.dumps({"error": "Abgebrochen"}))
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
