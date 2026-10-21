"""Source-attributed public metadata; conservative identity matching, no guessed facts."""
from __future__ import annotations

import datetime
import functools
import html
import os
import re
import time
import unicodedata
import urllib.parse

from star_runtime import SourceError

SOURCES = [
    {"id":"wikidata","name":"Wikidata · Wikipedia · Commons","url":"https://www.wikidata.org/","kind":"public","note":"Belegte Fakten, deutsche Artikel und Bilder mit Quellenangaben."},
    {"id":"tpdb","name":"ThePornDB","url":"https://api.theporndb.net/docs","kind":"key","note":"Zusätzliche Profile, Bilder und Angaben aus der Performer-API."},
]
PROPERTIES = {"P569":"Geburtsdatum","P570":"Verstorben","P19":"Geburtsort","P27":"Staatsangehörigkeit", "P106":"Beruf", "P166":"Auszeichnung", "P1411":"Nominierung", "P2031":"Karrierebeginn", "P2032":"Karriereende", "P2048":"Größe", "P856":"Offizielle Website"}


def clean(value):
    return _clean_text(str(value or ''))


@functools.lru_cache(maxsize=32768)
def _clean_text(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", " ", value))).strip()


def normal(value):
    return _normal_text(str(value or ''))


@functools.lru_cache(maxsize=65536)
def _normal_text(value):
    value = unicodedata.normalize("NFKD", value).casefold()
    return " ".join(re.findall(r"[^\W_]+", "".join(c for c in value if not unicodedata.combining(c)), re.UNICODE))


def year(profile):
    explicit = profile.get("birth_year") or profile.get("birth_date")
    candidates = [str(explicit or "")]
    for row in list(profile.get("facts") or []) + list((profile.get("extra") or {}).get("facts") or []):
        if re.search(r"gebor|geburts|birth", str(row.get("label") or ""), re.I):
            candidates.append(str(row.get("value") or ""))
    for value in candidates:
        match = re.search(r"(?:19|20)\d{2}", value)
        if match:
            return int(match.group())
    return None


def mature(date):
    if not date:
        return True
    match = re.search(r"\d{4}-\d{2}-\d{2}", str(date))
    if not match:
        return True
    try:
        born = datetime.date.fromisoformat(match.group())
    except ValueError:
        return int(match.group()[:4]) <= datetime.date.today().year-19
    today = datetime.date.today()
    return today.year-born.year-((today.month,today.day)<(born.month,born.day)) >= 18


def values(entity, prop):
    return [row.get("mainsnak",{}).get("datavalue",{}).get("value") for row in entity.get("claims",{}).get(prop,[]) if row.get("rank")!="deprecated" and row.get("mainsnak",{}).get("snaktype")=="value"]


def identity(profile, names, born=None, external_id=""):
    expected = {normal(profile.get("name")), *(normal(n) for n in profile.get("aliases") or [])}
    actual = {normal(n) for n in names if n}
    if not expected.intersection(actual):
        return False
    if born and not mature(born):
        return False
    known = year(profile)
    match = re.search(r"\d{4}", str(born or ""))
    if known and match:
        if known != int(match.group()):
            return False
        expected_date = re.search(r"\d{4}-\d{2}-\d{2}",str(profile.get("birth_date") or ""))
        actual_date = re.search(r"\d{4}-\d{2}-\d{2}",str(born or ""))
        if expected_date and actual_date and actual_date.group()[5:7]!="00" and actual_date.group()[8:]!="00":
            return expected_date.group()==actual_date.group()
        return True
    # Equal short names alone are not proof that two profiles describe a person.
    return bool(external_id and external_id in set((profile.get("source_ids") or {}).values()))


class PublicSources:
    def __init__(self, runtime):
        self.runtime = runtime
        self.box_catalog = None
        from star_models_sources import ModelSources
        self.models=ModelSources(runtime)
        from star_reference_sources import ReferenceSources
        self.references=ReferenceSources(runtime)

    def catalog(self):
        rows=[{**source,"configured":source["kind"]=="public" or source["id"]=="tpdb" and bool(os.environ.get("AH_TPDB_KEY"))} for source in SOURCES]
        return rows+(self.box_catalog() if self.box_catalog else [])+self.models.catalog()+self.references.catalog()

    def optional(self, url, result, part):
        try:return self.runtime.json(url)
        except SourceError as error:
            result.setdefault("partial_errors",[]).append({"part":part,"status":error.reason,"retry_at":error.retry_at})
            return {}

    @staticmethod
    def commons_rows(data):
        rows=[]
        for page in data.get("query",{}).get("pages",[]):
            for image in page.get("imageinfo",[]):
                if not str(image.get("mime") or "image/").startswith("image/"):continue
                meta=image.get("extmetadata",{})
                rows.append({"url":image.get("url"),"thumb":image.get("thumburl"),"width":image.get("width"),"height":image.get("height"),"source":"Wikimedia Commons","page":image.get("descriptionurl"),"credit":clean((meta.get("Artist") or {}).get("value")),"license":clean((meta.get("LicenseShortName") or {}).get("value")),"license_url":(meta.get("LicenseUrl") or {}).get("value","")})
        return rows

    def commons_images(self, entity, continuation=None):
        if not re.fullmatch(r"Q\d+",str(entity or "")):return {"images":[]}
        params={"action":"query","generator":"search","gsrsearch":"haswbstatement:P180="+entity,"gsrnamespace":6,"gsrlimit":24,"prop":"imageinfo","iiprop":"url|size|mime|extmetadata","iiurlwidth":480,"iiextmetadatafilter":"Artist|LicenseShortName|LicenseUrl|Credit","format":"json","formatversion":2,"maxlag":5}
        for key in ("gsroffset","continue"):
            if key in (continuation or {}):params[key]=continuation[key]
        data=self.runtime.json("https://commons.wikimedia.org/w/api.php?"+urllib.parse.urlencode(params))
        return {"images":self.commons_rows(data),"image_continue":data.get("continue"),"at":data.get("_observed_at")}

    def wikidata(self, profile, *, entity_id=None, text_only=False):
        entity_id=entity_id or (profile.get('source_ids') or {}).get('wikidata')
        params = {"action":"wbsearchentities","search":profile["name"],"language":"en","uselang":"de","type":"item","limit":5,"format":"json","maxlag":5}
        if entity_id is not None and not re.fullmatch(r"Q[1-9]\d{0,11}", str(entity_id)):
            raise ValueError("Ungültige Wikidata-Kennung.")
        search = {} if entity_id else self.runtime.json("https://www.wikidata.org/w/api.php?"+urllib.parse.urlencode(params))
        ids = [entity_id] if entity_id else [row["id"] for row in search.get("search",[]) if re.fullmatch(r"Q\d+",str(row.get("id") or ""))]
        if not ids:
            return {"id":"wikidata","name":"Wikidata","ok":False,"status":"missing","at":time.time()}
        params = {"action":"wbgetentities","ids":"|".join(ids),"props":"labels|aliases|claims|sitelinks","languages":"de|en","format":"json","maxlag":5}
        response = self.runtime.json("https://www.wikidata.org/w/api.php?"+urllib.parse.urlencode(params))
        observed = response.get("_observed_at") or time.time()
        entities = response.get("entities",{})
        matched = []
        for entity in entities.values():
            if not any(isinstance(v,dict) and v.get("id")=="Q5" for v in values(entity,"P31")):
                continue
            names = [v.get("value","") for v in entity.get("labels",{}).values()]
            names += [v.get("value","") for rows in entity.get("aliases",{}).values() for v in rows]
            dates = values(entity,"P569")
            born = dates[0].get("time") if dates and isinstance(dates[0],dict) else ""
            confirmed = entity_id and entity.get("id") == entity_id and (profile.get("source_ids") or {}).get("wikidata") == entity_id
            if confirmed and mature(born) or identity(profile,names,born,entity.get("id")):
                matched.append(entity)
        if len(matched)!=1:
            return {"id":"wikidata","name":"Wikidata","ok":False,"status":"ambiguous","at":time.time(),"note":"Keine eindeutige Übereinstimmung von Name und Geburtsangabe."}
        entity = matched[0]
        ident = entity["id"]
        label_ids = set()
        for prop in PROPERTIES:
            for value in values(entity,prop):
                if isinstance(value,dict) and value.get("id"): label_ids.add(value["id"])
                if isinstance(value,dict) and str(value.get("unit","")).startswith("http://www.wikidata.org/entity/"):label_ids.add(value["unit"].rsplit("/",1)[-1])
        labels = {}
        if label_ids:
            params = {"action":"wbgetentities","ids":"|".join(sorted(label_ids)[:50]),"props":"labels","languages":"de|en","languagefallback":1,"format":"json","maxlag":5}
            rows = self.runtime.json("https://www.wikidata.org/w/api.php?"+urllib.parse.urlencode(params)).get("entities",{})
            labels = {key:(row.get("labels",{}).get("de") or row.get("labels",{}).get("en") or {}).get("value",key) for key,row in rows.items()}
        url = "https://www.wikidata.org/wiki/"+ident
        facts = []
        for prop,label in PROPERTIES.items():
            for value in values(entity,prop):
                text = ""
                if isinstance(value,str): text = value
                elif isinstance(value,dict) and value.get("id"): text = labels.get(value["id"],value["id"])
                elif isinstance(value,dict) and value.get("time"):
                    precision = int(value.get("precision",0))
                    raw = value["time"].lstrip("+")
                    text = raw[:10] if precision>=11 else raw[:7] if precision==10 else raw[:4]
                elif isinstance(value,dict) and value.get("amount"):
                    unit = str(value.get("unit","")).rsplit("/",1)[-1]
                    text = value["amount"].lstrip("+")+" "+labels.get(unit,"")
                if text:
                    facts.append({"label":label,"value":clean(text),"source":"Wikidata","url":url,"at":observed})
        result = {"id":"wikidata","name":"Wikidata / Wikipedia","ok":True,"status":"matched","url":url,"entity":ident,"at":observed,"facts":facts,"images":[],"links":[],"aliases":[v.get("value","") for rows in entity.get("aliases",{}).values() for v in rows]}
        for language in ("de","en"):
            link = entity.get("sitelinks",{}).get(language+"wiki")
            if not link:
                continue
            params = {"action":"query","titles":link["title"],"prop":"extracts","explaintext":1,"exintro":1,"format":"json","formatversion":2,"maxlag":5}
            data = self.optional("https://"+language+".wikipedia.org/w/api.php?"+urllib.parse.urlencode(params),result,"Wikipedia")
            pages = data.get("query",{}).get("pages",[])
            text = clean(pages[0].get("extract")) if pages else ""
            if text:
                result["description"] = text
                result["language"] = language
                result["text_at"] = data.get("_observed_at") or observed
                result["text_url"] = "https://"+language+".wikipedia.org/wiki/"+urllib.parse.quote(link["title"].replace(" ","_"))
                break
        if text_only:
            return result
        files = ["File:"+str(value) for value in values(entity,"P18") if isinstance(value,str)][:12]
        if files:
            params = {"action":"query","titles":"|".join(files),"prop":"imageinfo","iiprop":"url|size|mime|extmetadata","iiurlwidth":480,"iiextmetadatafilter":"Artist|LicenseShortName|LicenseUrl|Credit","format":"json","formatversion":2,"maxlag":5}
            data = self.optional("https://commons.wikimedia.org/w/api.php?"+urllib.parse.urlencode(params),result,"Commons-Porträt")
            result["images"].extend(self.commons_rows(data))
        try:
            extra=self.commons_images(ident)
            result["images"].extend(extra["images"])
            result["image_continue"]=extra.get("image_continue")
        except SourceError as error:
            result.setdefault("partial_errors",[]).append({"part":"Commons-Galerie","status":error.reason,"retry_at":error.retry_at})
        unique={row["url"]:row for row in result["images"] if row.get("url")}
        result["images"]=list(unique.values())
        return result

    def tpdb(self, profile):
        token = os.environ.get("AH_TPDB_KEY", "").strip()
        if not token:
            return {"id":"tpdb","name":"ThePornDB","ok":False,"status":"unconfigured"}
        entity=(profile.get('source_ids') or {}).get('tpdb')
        query = urllib.parse.urlencode({"q":profile["name"],"per_page":10,"orderBy":"MOST_RELEVANT"})
        data = self.runtime.json("https://api.theporndb.net/performers/"+urllib.parse.quote(str(entity),safe='') if entity else "https://api.theporndb.net/performers?"+query,{"Authorization":"Bearer "+token})
        candidates=[data.get('data')] if entity and isinstance(data.get('data'),dict) else data.get('data',[])
        rows = [row for row in candidates if identity(profile,[row.get("name"),*(row.get("aliases") or [])],(row.get("extras") or {}).get("birthday"),row.get("id"))]
        if len(rows)!=1:
            return {"id":"tpdb","name":"ThePornDB","ok":False,"status":"ambiguous" if rows else "missing","at":time.time()}
        row = rows[0]
        extras = row.get("extras") or {}
        labels = {"gender":"Geschlecht","birthday":"Geburtsdatum","birthplace":"Geburtsort","nationality":"Staatsangehörigkeit","hair_colour":"Haarfarbe","eye_colour":"Augenfarbe","height":"Größe","weight":"Gewicht","measurements":"Maße","tattoos":"Tätowierungen","piercings":"Piercings","career_start_year":"Karrierebeginn","career_end_year":"Karriereende"}
        url = "https://theporndb.net/performers/"+urllib.parse.quote(row.get("slug") or row["id"])
        observed = data.get("_observed_at") or time.time()
        facts = [{"label":label,"value":clean(extras[key]),"source":"ThePornDB","url":url,"at":observed} for key,label in labels.items() if extras.get(key) is not None and str(extras[key]).strip()]
        if row.get("rating") is not None:
            facts.append({"label":"Bewertung (ThePornDB)","value":str(row["rating"]),"source":"ThePornDB","url":url,"at":observed})
        images = [{"url":image,"source":"ThePornDB","page":url} for image in [row.get("image"),*[(p or {}).get("url") for p in row.get("posters") or []]] if isinstance(image,str) and image.startswith("https://")]
        return {"id":"tpdb","name":"ThePornDB","ok":True,"status":"matched","url":url,"entity":row["id"],"at":observed,"facts":facts,"images":images,"aliases":row.get("aliases") or [],"description":clean(row.get("bio")),"language":"en","links":[{"label":label,"url":value} for label,value in (extras.get("links") or {}).items() if isinstance(value,str) and value.startswith("https://")]}

    def collect(self, profile, only=None):
        if only in ('data18','iafd'):found=self.models.collect(profile,only=only)
        elif only in ('freeones','grokipedia'):found=self.references.collect(profile,only=only)
        elif only:found=[]
        else:found=self.models.collect(profile)+self.references.collect(profile)
        for source, fetch in (("wikidata",self.wikidata),("tpdb",self.tpdb)):
            if only and source!=only:continue
            if source=="tpdb" and not os.environ.get("AH_TPDB_KEY"):
                continue
            if not year(profile) and not profile.get("source_ids"):
                found.append({"id":source,"name":"Wikidata" if source=="wikidata" else "ThePornDB","ok":False,"status":"ambiguous","at":time.time(),"note":"Eine Geburtsangabe oder bereits bestätigte Quellen-ID fehlt für die sichere Zuordnung."})
                continue
            try:
                found.append(fetch(profile))
            except SourceError as error:
                found.append({"id":source,"name":"Wikidata" if source=="wikidata" else "ThePornDB","ok":False,"status":error.reason,"retry_at":error.retry_at,"at":time.time()})
            except (ValueError,KeyError,TypeError):
                found.append({"id":source,"name":source,"ok":False,"status":"invalid","at":time.time()})
        return found
