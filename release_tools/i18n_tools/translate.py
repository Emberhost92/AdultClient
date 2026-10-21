"""One-time build of the offline catalogue from UI copy only; resumable."""
import concurrent.futures
import json
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request

HERE=Path(__file__).resolve().parent
inventory=json.loads((HERE/'inventory.json').read_text(encoding='utf-8'))
output=HERE/'translations.json'
saved=json.loads(output.read_text(encoding='utf-8')) if output.exists() else {}
pending=[s for s in inventory['strings'] if s not in saved]
batches=[];batch=[];size=0
for s in pending:
    n=len(s)+20
    if batch and size+n>2200:batches.append(batch);batch=[];size=0
    batch.append(s);size+=n
if batch:batches.append(batch)


def translate(rows):
    text='\n'.join('[[%d]] %s'%(i,s.replace('\n',' ')) for i,s in enumerate(rows))
    params={'client':'gtx','sl':'de','tl':'en','dt':'t','q':text}
    for attempt in range(4):
        try:
            request=urllib.request.Request('https://translate.googleapis.com/translate_a/single?'+urllib.parse.urlencode(params),headers={'User-Agent':'AdultClient-UI-localization-build'})
            with urllib.request.urlopen(request,timeout=40) as response:data=json.load(response)
            translated=''.join(row[0] or '' for row in data[0] if row)
            matches=list(re.finditer(r'\[\[\s*(\d+)\s*\]\]',translated))
            if len(matches)!=len(rows):raise ValueError('Unvollständige Markierungen')
            result={}
            for i,m in enumerate(matches):
                index=int(m[1]);end=matches[i+1].start() if i+1<len(matches) else len(translated)
                value=translated[m.end():end].strip()
                value=re.sub(r'\{\s*(\d+)\s*\}',r'{\1}',value)
                if not value:raise ValueError('Leere Übersetzung')
                if sorted(re.findall(r'\{\d+\}',value))!=sorted(re.findall(r'\{\d+\}',rows[index])):
                    raise ValueError('Platzhalter verändert')
                result[rows[index]]=value
            time.sleep(.5)
            return result
        except Exception:
            if attempt==3:
                # Small retries preserve exact boundaries when a long phrase confuses markers.
                if len(rows)>1:
                    mid=len(rows)//2;return {**translate(rows[:mid]),**translate(rows[mid:])}
                raise
            time.sleep(1+attempt*2)


print('PENDING',len(pending),'BATCHES',len(batches),flush=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    futures=[pool.submit(translate,rows) for rows in batches]
    for i,future in enumerate(concurrent.futures.as_completed(futures),1):
        try:saved.update(future.result())
        except Exception as e:print('BATCH_FAILED',type(e).__name__,str(e)[:100],flush=True)
        output.write_text(json.dumps(saved,ensure_ascii=False,indent=2),encoding='utf-8')
        if i%10==0 or i==len(futures):print('TRANSLATED',len(saved),'BATCH',i,flush=True)
