# -*- coding: utf-8 -*-
"""Traegt neue Creator-Sites in website_catalog.json ein."""

import io
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "resources", "website_catalog.json")
ADD = ["coomer", "kemono"]


def _cid(value):
    try:
        return int(value)
    except Exception:
        return 0


with io.open(PATH, encoding="utf-8") as handle:
    data = json.load(handle)

sites = data.setdefault("sites", {})
taxonomy = data.setdefault("taxonomy", {})
content = taxonomy.setdefault("content", {})
types = taxonomy.setdefault("types", {})
content.setdefault("creator", [])
types.setdefault("archive", [])

next_id = max([_cid(v.get("catalog_id")) for v in sites.values()] or [0]) + 1

for name in ADD:
    if name not in sites:
        sites[name] = {"catalog_id": next_id}
        next_id += 1
    if name not in content["creator"]:
        content["creator"].append(name)
    if name not in types["archive"]:
        types["archive"].append(name)

with io.open(PATH, "w", encoding="utf-8") as handle:
    json.dump(data, handle, indent=2, ensure_ascii=False)

print("OK - eingetragen:", ", ".join(ADD))
print("sites jetzt:", len(sites), "| creator:", len(content["creator"]), "| archive:", len(types["archive"]))