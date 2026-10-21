"""Compile locally shipped messages and fail on missing/invalid placeholders."""
import json
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent
APP=HERE.parents[1]/'AdultHideoutWeb'
inventory=json.loads((HERE/'inventory.json').read_text(encoding='utf-8'))
translations=json.loads((HERE/'translations.json').read_text(encoding='utf-8'))
overrides=json.loads((HERE/'overrides.json').read_text(encoding='utf-8'))
messages={s:translations[s] for s in inventory['strings'] if s in translations}
messages.update(overrides)
missing=[s for s in inventory['strings'] if s not in messages]
bad=[s for s,t in messages.items() if sorted(re.findall(r'\{\d+\}',s))!=sorted(re.findall(r'\{\d+\}',t))]
if missing or bad:raise SystemExit('Missing: '+str(len(missing))+'; broken placeholders: '+str(len(bad)))
payload={'messages':messages,'patterns':inventory['patterns']}
(APP/'static'/'ui_messages.js').write_text('/* Shipped offline UI catalogue. German source keys; model content excluded. */\n'+
    '(function(r){r.AppUIMessages='+json.dumps(payload,ensure_ascii=False,separators=(',',':'))+';})(globalThis);\n',encoding='utf-8')
stats={'languages':['de','en'],'source_messages':len(inventory['strings']),'translated_messages':len(messages),'missing':missing,'broken_placeholders':bad,'runtime_network_translation':False}
(HERE/'coverage.json').write_text(json.dumps(stats,indent=2),encoding='utf-8')
print('CATALOG_OK',len(messages),'MISSING',len(missing),'BROKEN_PLACEHOLDERS',len(bad))
