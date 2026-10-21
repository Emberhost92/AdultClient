"""Count the shipped catalogue with the real application, using public seed data only."""
import gzip
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

BASE=Path(__file__).resolve().parent.parent
ROOT=BASE/'distribution'/'AdultClient-0.3.1-beta.1'

with tempfile.TemporaryDirectory(prefix='ac-public-count-',dir=BASE/'distribution') as folder:
    profile=Path(folder)
    os.environ.update(AH_ADDON=str(ROOT/'addon'),AH_PROFILE=str(profile))
    for key in ('AH_STASHDB_KEY','AH_FANSDB_KEY','AH_TPDB_KEY'):os.environ.pop(key,None)
    with gzip.open(ROOT/'data'/'star-data.sqlite3.gz','rb') as source,(profile/'star_data.sqlite3').open('wb') as target:
        shutil.copyfileobj(source,target)
    sys.path.insert(0,str(ROOT/'app'))
    import server
    sites=server._catalog_sites()
    capabilities=server.media_library.provider_capabilities(str(ROOT/'addon'))
    nonlive=[s for s in sites if s['id'] not in server.media_library.LIVE_SITES]
    video=[s for s in nonlive if 'video' in capabilities.get(s['id'],{'mediaTypes':['video']}).get('mediaTypes',[])]
    result=server.star_catalog({'per':'12','compact':'1'})
    import importlib
    gs=importlib.import_module('resources.lib.global_search')
    search_class=next(c for c in vars(gs).values() if isinstance(c,type) and c.__module__==gs.__name__ and hasattr(c,'_available_sources'))
    available=search_class(1)._available_sources()
    report={'program_version':'0.3.1-beta.1','data_created':json.loads((ROOT/'data'/'star-data.sqlite3.json').read_text())['created'],
            'sites_nonlive':len(nonlive),'sites_with_video':len(video),'global_search_sources':len(available),
            'star_finder_total':result['total'],'base_library':result['library'],'discovered_people':result['people']}
    (BASE/'distribution'/'PUBLIC-CATALOG-COUNTS.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report),flush=True)
    if getattr(server,'_star_store',None):server._star_store.close()
