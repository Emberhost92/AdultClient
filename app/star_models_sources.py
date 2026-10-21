"""Data18 catalogue and verified profile metadata, using the standalone models adapter.

No browser is opened by background synchronization. A blocked source remains
blocked; previously saved human-approved sessions can be reused. Only published
performer portraits are extracted here, not unrelated banners or scene stills.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import threading
import time
import urllib.parse
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from star_runtime import SourceError
from star_sources import clean, normal

SOURCES = {
    "data18": {"name": "Data18", "url": "https://www.data18.com", "catalogue": True},
    "iafd": {"name": "IAFD", "url": "https://www.iafd.com", "catalogue": False},
}
_load_lock = threading.RLock()
_host_locks = {source: threading.RLock() for source in SOURCES}


class ModelSources:
    def __init__(self, runtime=None, script=None, session_dir=None):
        self.runtime = runtime
        self.script = (
            Path(script) if script else Path(__file__).resolve().parent.parent / "MediaScraper" / "models.py"
        )
        self.session_dir = Path(session_dir) if session_dir else Path(__import__("os").environ["AH_PROFILE"]) / "source_sessions"
        self.module = None
        self.cooldowns = {}

    def load(self):
        if self.module:
            return self.module
        with _load_lock:
            if not self.script.is_file():
                raise SourceError("adapter-missing")
            key = "_star_models_adapter"
            existing = sys.modules.get(key)
            if existing is not None and Path(existing.__file__).resolve() == self.script.resolve():
                self.module = existing
                return existing
            spec = importlib.util.spec_from_file_location(key, self.script)
            module = importlib.util.module_from_spec(spec)
            sys.modules[key] = module
            try:
                spec.loader.exec_module(module)
            except (ImportError, OSError):
                sys.modules.pop(key, None)
                raise SourceError("adapter-missing") from None
            self.module = module
            return module

    def catalog(self):
        available = self.script.is_file() and all(
            importlib.util.find_spec(name) for name in ("requests", "bs4")
        )
        return [
            {
                "id": source,
                "name": config["name"],
                "url": config["url"],
                "kind": "public",
                "configured": bool(
                    available and (source == "iafd" or (self.session_dir / "data18.json").is_file())
                ),
                "catalogue": config["catalogue"],
                "note": (
                    "Vollständiger veröffentlichter Personenkatalog, Metadaten und Profilporträts. "
                    "Gespeicherte Freigabe erforderlich."
                    if source == "data18"
                    else "Metadaten und Profilporträts über bestätigte Personenlinks. "
                    "Eine Zugriffssperre wird als offen ausgewiesen; kein bestätigter Gesamtkatalog."
                ),
            }
            for source, config in SOURCES.items()
        ]

    def configured(self, source="data18"):
        """Boolean only; session contents must never be returned to a caller/UI."""
        return any(row["id"] == source and row["configured"] for row in self.catalog())

    @contextmanager
    def fetcher(self, source, name="Catalogue", profile_url=None):
        if source not in SOURCES:
            raise ValueError("Unbekannte Modellquelle")
        module = self.load()
        with _host_locks[source]:
            previous_reason, retry = self.cooldowns.get(source, ("blocked", 0))
            if retry > time.time():
                raise SourceError(previous_reason, retry)
            params = [
                name,
                "--sources",
                source,
                "--browser",
                "never",
                "--max-pages",
                "1000",
                "--max-details",
                "0",
                "--max-requests",
                "6000",
                "--timeout",
                "15",
                "--cache-ttl",
                "0",
                "--session-dir",
                str(self.session_dir),
            ]
            if profile_url:
                params += ["--data18-url" if source == "data18" else "--iafd-url", profile_url]
            args = module.arguments(params)
            fetcher = None
            try:
                fetcher = module.Fetcher(source, module.BASES[source], args)
                if self.runtime:
                    original_get=fetcher.get
                    def paced_get(*args,**kwargs):
                        self.runtime.wait()
                        return original_get(*args,**kwargs)
                    fetcher.get=paced_get
                yield module, fetcher, args
            except module.NotFound:
                raise SourceError("missing") from None
            except module.Blocked as error:
                text = str(error)
                reason = (
                    "rate-limit"
                    if "Rate-Limit" in text
                    else "session-required"
                    if "Altersabfrage" in text
                    else "blocked"
                )
                retry = time.time() + (300 if reason == "rate-limit" else 1800)
                self.cooldowns[source] = (reason, retry)
                raise SourceError(reason, retry) from None
            except module.MetadataError:
                raise SourceError("source-error") from None
            finally:
                if fetcher:
                    fetcher.close()

    def fetch_page(self, source="data18", state=None):
        """Return (performers, advertised total, terminal page), with no guessed names."""
        if isinstance(source, dict) and state is None:
            source, state = "data18", source
        state = state or {}
        if source != "data18":
            raise SourceError("catalog-unavailable")
        number = int(state.get("page", 1))
        if number < 1:
            raise SourceError("pagination")
        with self.fetcher("data18") as (module, fetcher, _args):
            params = {
                "t": 1,
                "b": 5,
                "o": 0,
                "html": "index",
                "html2": "",
                "total": 0,
                "doquery": 1,
                "spage": number,
                "dopage": 1,
            }
            if number == 1:
                fetcher.get(
                    fetcher.base + "/sys/page.php?" + urllib.parse.urlencode({**params, "reset": 1}),
                    referer=fetcher.base + "/names/pornstars",
                    ajax=True,
                )
            # The site's selector stores this preference in the browser session;
            # `o=1` does not select alphabetical ordering. Repeat in the dedicated
            # saved-session context so pages cannot silently revert to recent activity.
            fetcher.get(
                fetcher.base + "/sys/user.php?functions=1&order=1",
                referer=fetcher.base + "/names/pornstars",
                ajax=True,
            )
            url = fetcher.base + "/sys/page.php?" + urllib.parse.urlencode(params)
            page = fetcher.get(url, referer=fetcher.base + "/names/pornstars", ajax=True)
            return self.parse_catalogue(page, module, number)

    @staticmethod
    def parse_catalogue(page, module, number):
        soup = page.soup
        root = soup.select_one("#listing_results")
        if root is None:
            raise SourceError("pagination")
        count = re.search(r"\b([\d,]+)\s+Pornstars\b", root.get_text(" ", strip=True), re.IGNORECASE)
        if not count:
            raise SourceError("pagination")
        total = int(count[1].replace(",", ""))
        order = soup.select_one("#orderpage option[selected]")
        if order is not None and order.get("value") != "1":
            raise SourceError("pagination")
        found = {}
        for link in root.select("a[href]"):
            url = module.safe_link(link["href"], SOURCES["data18"]["url"])
            match = re.fullmatch(r"/name/([^/]+)", urllib.parse.urlsplit(url).path) if url else None
            if not match:
                continue
            image = link.select_one("img")
            visible = clean(link.get_text(" ", strip=True))
            alt = clean(image.get("alt")) if image else ""
            caption = clean(link.get("title"))
            name = visible or alt or caption
            if not name or (alt and caption and normal(alt) != normal(caption)):
                raise SourceError("pagination")
            pictures = []
            if image:
                raw = image.get("data-src") or image.get("src") or ""
                image_url = urllib.parse.urljoin(url, raw)
                parsed = urllib.parse.urlsplit(image_url)
                if (
                    raw
                    and parsed.scheme == "https"
                    and parsed.hostname
                    and not parsed.username
                    and not parsed.password
                    and not re.search(r"no_prev|placeholder|noimage", image_url, re.IGNORECASE)
                ):
                    pictures.append({"url": image_url, "source": "Data18", "page": url, "kind": "portrait"})
            row = {
                "id": match[1],
                "name": name,
                "url": url,
                "urls": [{"url": url}],
                "birth_date": None,
                "aliases": None,
                "images": pictures,
                "catalog_page": page.url,
                "catalogue_only": True,
            }
            previous = found.get(match[1])
            if previous and normal(previous["name"]) != normal(name):
                raise SourceError("pagination")
            if previous and not pictures:
                continue
            found[match[1]] = row
        controls = soup.select_one("#pagination_bar")
        if controls is None:
            raise SourceError("pagination")
        more = any(
            (match := re.fullmatch(r"spage[a-c]?(\d+)", node.get("id", ""))) and int(match[1]) > number
            for node in controls.select(".spage[id]")
        )
        if not found and total:
            raise SourceError("pagination")
        return list(found.values()), total, not more

    @staticmethod
    def entity_url(source, entity):
        text = str(entity or "")
        if source == "data18":
            if re.fullmatch(r"[A-Za-z0-9_-]+", text):
                return SOURCES[source]["url"] + "/name/" + text
            return None
        parsed = urllib.parse.urlsplit(text)
        if (
            parsed.scheme == "https"
            and parsed.hostname in ("www.iafd.com", "iafd.com")
            and parsed.path.startswith("/person.rme/")
            and not parsed.username
            and not parsed.password
        ):
            return urllib.parse.urlunsplit(("https", "www.iafd.com", parsed.path, parsed.query, ""))
        return None

    def verified_url(self, source, profile):
        entity = (profile.get("source_ids") or {}).get(source)
        known = self.entity_url(source, entity)
        if known:
            return known
        links = [*(profile.get("links") or []), *((profile.get("extra") or {}).get("links") or [])]
        for row in profile.get("sources") or []:
            links.extend(row.get("links") or [])
            if row.get("id") == source and row.get("ok") and row.get("url"):
                links.append({"url": row["url"]})
        found = set()
        for link in links:
            url = link.get("url") if isinstance(link, dict) else ""
            parsed = urllib.parse.urlsplit(url or "")
            if source == "data18" and parsed.hostname in ("data18.com", "www.data18.com"):
                match = re.fullmatch(r"/name/([^/]+)", parsed.path)
                if match and (candidate := self.entity_url(source, match[1])):
                    found.add(candidate)
            elif source == "iafd" and (candidate := self.entity_url(source, url)):
                found.add(candidate)
        return next(iter(found)) if len(found) == 1 else None

    def extract_portraits(self, page, source, name):
        module = self.load()
        if source == "data18":
            marker = page.soup.select_one("#primaryimg")
            root = marker.find_parent(class_="backgroundmenu") if marker else None
            if root is None:
                return [], "unknown"
            images = []
            for link in root.select("a[href]"):
                if module.safe_link(link["href"], page.url) == page.url:
                    images.extend(link.select("img"))
        else:
            root = page.soup.select_one("#headshot")
            images = root.select("img") if root else []
        if not images:
            return [], "unknown"
        portraits, recognized = {}, True
        for image in images:
            if source == "data18" and normal(image.get("alt")) != normal(name):
                recognized = False
                continue
            raw = image.get("data-src") or image.get("src") or ""
            image_url = urllib.parse.urljoin(page.url, raw)
            parsed = urllib.parse.urlsplit(image_url)
            if (not raw or parsed.scheme != "https" or not parsed.hostname
                    or parsed.username or parsed.password):
                recognized = False
                continue
            if re.search("no_prev|placeholder|noimage", image_url, re.IGNORECASE):
                continue  # An explicit source placeholder documents the absence of a portrait.
            portraits[image_url] = {"url": image_url, "source": SOURCES[source]["name"],
                                    "page": page.url, "kind": "portrait"}
        return list(portraits.values()), "complete" if recognized else "partial"

    def collect(self, profile, only=None):
        results = []
        for source in [only] if only else SOURCES:
            config = SOURCES[source]
            url = self.verified_url(source, profile)
            base = {"id": source, "name": config["name"], "ok": False, "at": time.time()}
            if not url:
                results.append(
                    {
                        **base,
                        "status": "ambiguous",
                        "note": "Kein eindeutiger bestätigter Personenlink; keine Zuordnung nur nach Namen.",
                    }
                )
                continue
            try:
                with self.fetcher(source, profile["name"], url) as (module, fetcher, args):
                    parser = module.data18_metadata if source == "data18" else module.iafd_metadata
                    metadata = parser(profile["name"], fetcher, args)
                    metadata.update(
                        requests=fetcher.requests,
                        browser_used=False,
                        fetched_at=datetime.now(UTC).isoformat(),
                    )
                    module.finalize_source(metadata)
                    portraits, portrait_status = [], "unknown"
                    try:
                        page = fetcher.get(metadata.get("url") or url)
                        portraits, portrait_status = self.extract_portraits(page, source, metadata["name"])
                    except module.MetadataError:
                        portrait_status = "partial"
                    metadata["requests"] = fetcher.requests
                    facts = []
                    attributes = metadata.get("attributes") or {}
                    fields = {
                        "hair": "Haarfarbe",
                        "height": "Größe",
                        "weight": "Gewicht",
                        "measurements": "Maße",
                        "tattoos": "Tätowierungen",
                        "piercings": "Piercings",
                    }
                    values = {"hair": attributes.get("hair"), **(attributes.get("body") or {})}
                    for key, label in fields.items():
                        if values.get(key) is not None:
                            facts.append(
                                {
                                    "label": label,
                                    "value": values[key],
                                    "source": config["name"],
                                    "url": url,
                                    "at": base["at"],
                                }
                            )
                    for key, report in metadata.get("collections", {}).items():
                        facts.append(
                            {
                                "label": config["name"] + " · " + key,
                                "value": str(report["found"])
                                + (" / " + str(report["expected"]) if report["expected"] is not None else ""),
                                "source": config["name"],
                                "url": report["url"],
                                "at": base["at"],
                                "complete": report["complete"],
                            }
                        )
                    portrait_errors = (
                        []
                        if portrait_status == "complete"
                        else [
                            {
                                "part": "Profilporträts",
                                "status": "source-error"
                                if portrait_status == "partial"
                                else "unrecognized-layout",
                            }
                        ]
                    )
                    results.append(
                        {
                            **base,
                            "ok": metadata["status"] in ("ok", "partial") and bool(metadata["name"]),
                            "status": "matched",
                            "url": url,
                            "entity": urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]
                            if source == "data18"
                            else url,
                            "aliases": metadata.get("aliases"),
                            "facts": facts,
                            "images": portraits,
                            "images_status": portrait_status,
                            "metadata": metadata,
                            "partial": metadata["status"] == "partial" or bool(portrait_errors),
                            "partial_errors": portrait_errors,
                            "links": [{"label": config["name"], "url": url}],
                        }
                    )
            except SourceError as error:
                results.append({**base, "status": error.reason, "retry_at": error.retry_at, "url": url})
        return results
