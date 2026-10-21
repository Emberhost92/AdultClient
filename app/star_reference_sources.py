"""Attributed FreeOnes and Grokipedia profile enrichment, without name-only merges."""
from __future__ import annotations

import datetime
import importlib.util
import json
import re
import time
import urllib.parse

from star_runtime import SourceError
from star_sources import clean, identity, mature, normal, year

SITES = {
    "freeones": {"name": "FreeOnes", "url": "https://www.freeones.com/", "host": "freeones.com"},
    "grokipedia": {"name": "Grokipedia", "url": "https://grokipedia.com/", "host": "grokipedia.com"},
}
FIELDS = {
    "dateOfBirth": "Geburtsdatum", "placeOfBirth": "Geburtsort", "nationality": "Staatsangehörigkeit",
    "ethnicity": "Herkunft", "profession": "Beruf", "careerStatus": "Karrierestatus",
    "careerStart": "Karrierebeginn", "careerEnd": "Karriereende", "hair_color": "Haarfarbe",
    "eye_color": "Augenfarbe", "height": "Größe", "weight": "Gewicht", "bust": "Brustumfang",
    "cup": "Cup", "bra": "BH-Größe", "waist": "Taille", "hip": "Hüfte",
    "boobs": "Brusttyp", "tattoos": "Tätowierungen", "piercings": "Piercings",
}
MONTHS = {name: n for n, name in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"), 1)}


def birth_date(text):
    """Only an explicit, valid complete date; no years inferred from prose."""
    match = re.search(r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2}),\s*((?:19|20)\d{2})\b", text or "")
    try:
        if match:
            return datetime.date(int(match[3]), MONTHS[match[1]], int(match[2])).isoformat()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text or ""):
            return datetime.date.fromisoformat(text).isoformat()
    except ValueError:
        pass
    return None


class ReferenceSources:
    def __init__(self, runtime):
        self.runtime = runtime

    def catalog(self):
        available = importlib.util.find_spec("bs4") is not None
        return [{"id": key, "name": site["name"], "url": site["url"], "kind": "public",
                 "configured": available, "scope": "profile-only",
                 "note": "Ergänzt eindeutig zugeordnete Profile; kein vollständiger Personenkatalog. " +
                 ("KI-verfasste Artikel bleiben als Grokipedia-Angaben gekennzeichnet." if key == "grokipedia"
                  else "Veröffentlichte Merkmale, Aliase, Quellnotizen und Profilporträts.")}
                for key, site in SITES.items()]

    @staticmethod
    def canonical(source, url):
        try:
            parsed = urllib.parse.urlsplit(str(url))
            if (parsed.scheme != "https" or parsed.hostname.removeprefix("www.") != SITES[source]["host"]
                    or parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.query):
                return None
            path = parsed.path.rstrip("/")
            if source == "freeones":
                match = re.fullmatch(r"/([a-z0-9][a-z0-9-]+)(?:/(?:bio|photos))?", path)
                if match and match[1] not in {"performers", "search", "login", "register", "photos", "videos"}:
                    return "https://www.freeones.com/" + match[1] + "/bio"
            elif re.fullmatch(r"/page/[^/]+", path):
                return "https://grokipedia.com" + path
        except (ValueError, AttributeError):
            pass
        return None

    def locate(self, source, profile):
        candidates = set()
        entity = (profile.get("source_ids") or {}).get(source)
        if entity:
            value = str(entity)
            if not value.startswith("https://"):
                value = SITES[source]["url"] + ("page/" if source == "grokipedia" else "") + urllib.parse.quote(value, safe="_-")
            target = self.canonical(source, value)
            if not target:
                raise SourceError("ambiguous")
            candidates.add(target)
        links = list(profile.get("links") or []) + list((profile.get("extra") or {}).get("links") or [])
        for row in profile.get("sources") or []:
            if row.get("ok"):
                links.extend(row.get("links") or [])
                if row.get("id") == source and row.get("url"):
                    links.append({"url": row["url"]})
        for link in links:
            target = self.canonical(source, link.get("url")) if isinstance(link, dict) else None
            if target:
                candidates.add(target)
        if len(candidates) > 1:
            raise SourceError("ambiguous")
        if candidates:
            return candidates.pop(), True
        if not year(profile):
            raise SourceError("ambiguous")
        # A name-derived address is only a search candidate, never identity proof.
        name = str(profile.get("name") or "").strip()
        slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") if source == "freeones" else name.replace(" ", "_")
        if not slug or "/" in slug or "\\" in slug:
            raise SourceError("ambiguous")
        value = SITES[source]["url"] + ("page/" if source == "grokipedia" else "") + urllib.parse.quote(slug, safe="_-")
        return self.canonical(source, value), False

    @staticmethod
    def parse(source, body, url):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(body, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        if re.search(r"just a moment|access denied|verify (?:you|that)|captcha", title, re.IGNORECASE):
            raise SourceError("blocked")
        canonical = soup.select_one('link[rel="canonical"]')
        if canonical and ReferenceSources.canonical(source, canonical.get("href")) != url:
            raise SourceError("redirect")
        if source == "freeones":
            return ReferenceSources.parse_freeones(soup, url)
        return ReferenceSources.parse_grokipedia(soup, url)

    @staticmethod
    def parse_freeones(soup, url):
        people = []
        for node in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(node.get_text())
                rows = data if isinstance(data, list) else [data]
                people.extend(row for row in rows if isinstance(row, dict) and row.get("@type") == "Person")
            except (ValueError, TypeError):
                continue
        names = {clean(row.get("name")) for row in people if clean(row.get("name"))}
        names.update(clean(n.get_text(" ", strip=True)) for n in soup.select('[data-test="link_name"]'))
        if len(names) != 1:
            raise SourceError("invalid")
        name = names.pop()
        fields = {}
        for key in ["aliases", *FIELDS]:
            values = list(dict.fromkeys(clean(n.get_text(" ", strip=True)) for n in soup.select(f'a[data-test="link_{key}"]')))
            if values:
                fields[key] = values
        if not fields:
            raise SourceError("invalid")
        dates = fields.get("dateOfBirth", [])
        born = birth_date(next(iter(dates), ""))
        if len(dates) > 1 or dates and born is None:
            raise SourceError("invalid")
        facts, warnings = [], []
        for key, label in FIELDS.items():
            for value in fields.get(key, []):
                number = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(cm|kg)", value)
                if key in {"height", "weight"} and (not number or not
                        ((120 <= float(number[1]) <= 240 and number[2] == "cm") if key == "height" else
                         (25 <= float(number[1]) <= 350 and number[2] == "kg"))):
                    warnings.append(f"Unplausibler Quellwert für {label}: {value}; nicht als Merkmal übernommen.")
                    continue
                facts.append({"label": label, "value": born if key == "dateOfBirth" and born else value})
        block = soup.select_one('[data-test="biography"]')
        description = block.get_text(" ", strip=True) if block else ""
        images = {}
        for node in soup.select('img[alt][src]'):
            target = urllib.parse.urljoin(url, node["src"])
            parsed = urllib.parse.urlsplit(target)
            if (normal(node["alt"]) == normal(name) and parsed.scheme == "https"
                    and parsed.hostname == "thumbs.freeones.com" and not parsed.username and not parsed.password):
                images[target] = {"url": target, "source": "FreeOnes", "page": url, "kind": "portrait"}
        return {"person_name": name, "birth_date": born, "aliases": fields.get("aliases"), "facts": facts,
                "description": description, "images": list(images.values()), "warnings": warnings,
                "metadata": {"reported_fields": fields}, "references": []}

    @staticmethod
    def parse_grokipedia(soup, url):
        heading, root = soup.select_one("h1"), soup.select_one("article .article-body")
        if heading is None or root is None:
            raise SourceError("invalid")
        parts = []
        for node in root.children:
            if getattr(node, "name", None) in {"h2", "h3"}:
                break
            if getattr(node, "name", None):
                parts.append(node.get_text(" ", strip=True))
        description = "\n\n".join(parts)
        if len(description) < 80:
            raise SourceError("invalid")
        born_clause = re.search(r"\(born\b([^)]{0,180})\)", description, re.IGNORECASE)
        born = birth_date(born_clause[1]) if born_clause else None
        refs = {}
        # References stay separate from identity links: a citation can discuss
        # another person and must never establish that person's source identity.
        for node in soup.select('article a[href^="https://"]'):
            target = node["href"]
            if urllib.parse.urlsplit(target).hostname not in {"grokipedia.com", "www.grokipedia.com"}:
                refs[target] = {"url": target, "label": node.get_text(" ", strip=True) or "Literaturverweis"}
        return {"person_name": heading.get_text(" ", strip=True), "birth_date": born, "aliases": None,
                "facts": [{"label": "Geburtsdatum", "value": born}] if born else [], "description": description,
                "images": [], "warnings": [], "metadata": {}, "references": list(refs.values())}

    def fetch(self, source, profile):
        url, confirmed = self.locate(source, profile)
        response = self.runtime.request(url, {"Accept-Language": "en"}, ttl=12*3600, limit=2_000_000)
        if self.canonical(source, response["url"]) != url:
            raise SourceError("redirect")
        parsed = self.parse(source, response["body"], url)
        names = [parsed["person_name"], *(parsed.get("aliases") or [])]
        expected = {normal(profile.get("name")), *(normal(n) for n in profile.get("aliases") or [])}
        born = parsed.get("birth_date")
        valid = identity(profile, names, born)
        if confirmed and expected.intersection(normal(n) for n in names) and mature(born):
            known = profile.get("birth_date")
            valid = not born or (known == born if known else not year(profile) or year(profile) == int(born[:4]))
        if not valid:
            raise SourceError("ambiguous")
        observed = response.get("at") or time.time()
        return {"id": source, "name": SITES[source]["name"], "ok": True, "status": "matched", "url": url,
                "entity": url, "at": observed, "checked_at": time.time(), "identity_basis": "published_link" if confirmed else "name_and_birth",
                "description": parsed["description"], "language": "en", "text_url": url, "text_at": observed,
                "aliases": parsed["aliases"], "facts": [{**f, "source": SITES[source]["name"], "url": url, "at": observed} for f in parsed["facts"]],
                "images": parsed["images"], "metadata": parsed["metadata"], "references": parsed["references"],
                "note": " ".join((["KI-verfasste Biografie; Angaben stammen von Grokipedia."] if source == "grokipedia" else []) + parsed["warnings"]),
                "links": [{"label": SITES[source]["name"], "url": url}]}

    def collect(self, profile, only=None):
        results = []
        for source, site in SITES.items():
            if only and source!=only:continue
            try:
                if importlib.util.find_spec("bs4") is None:
                    raise SourceError("adapter-missing")
                results.append(self.fetch(source, profile))
            except SourceError as error:
                results.append({"id": source, "name": site["name"], "ok": False, "status": error.reason,
                                "retry_at": error.retry_at, "at": time.time()})
            except (ImportError, ValueError, KeyError, TypeError):
                results.append({"id": source, "name": site["name"], "ok": False, "status": "invalid", "at": time.time()})
        return results
