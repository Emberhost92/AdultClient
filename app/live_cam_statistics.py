"""Read-only projections for the Live statistics centre; never account credentials."""
import copy
import time

from live_cam_models import SORTS, number

EXTRA_SORTS = {'watch-share': ('watchMs', True), 'previews-most': ('previews', True),
               'infos-most': ('infos', True), 'own-tags-most': ('_ownTags', True),
               'quality-best': ('_quality', False), 'images-first': ('_image', True)}
LIMITS = {'WatchMinutes': ('watchMs', 60000), 'Sessions': ('sessions', 1),
          'ActiveDays': ('activeDays', 1), 'Previews': ('previews', 1),
          'Infos': ('infos', 1), 'Rating': ('rating', 1), 'Priority': ('priority', 1),
          'Appearances': ('appearances', 1), 'Samples': ('observations', 1)}


def rules(raw):
    if not isinstance(raw, dict):
        raise ValueError('Ungültige Statistikfilter.')
    result = {}
    for key,allowed in {'hd':('any','yes','no','unknown'),'gaming':('any','yes','no','unknown'),
                        'hdGaming':('any','both','neither','hd-only','gaming-only','unknown'),
                        'presence':('any','live','away','offline','private','unknown','error')}.items():
        value=raw.get(key,'any')
        if value not in allowed:raise ValueError('Ungültiger Statistikfilter: '+key)
        if value!='any':result[key]=value
    for field in LIMITS:
        for prefix in ('min', 'max'):
            value = raw.get(prefix + field)
            if value is not None:
                if isinstance(value, bool) or number(value) is None or value < 0:
                    raise ValueError('Statistikgrenzen müssen nichtnegative Zahlen sein.')
                result[prefix + field] = value
        if result.get('min'+field, 0) > result.get('max'+field, float('inf')):
            raise ValueError('Die Untergrenze liegt über der Obergrenze.')
    return result


class StatisticsHub:
    def __init__(self, hub):
        self.h = hub

    def handle(self, body):
        if body['op'] == 'statistics-query':
            if not isinstance(body.get('filters',{}),dict):
                raise ValueError('Ungültige Statistikfilter.')
            extra = rules(body.get('extra', {}))
            sort = body.get('sort', 'watch-most')
            if not isinstance(sort,str) or sort not in SORTS and sort not in EXTRA_SORTS:
                raise ValueError('Unbekannte Statistiksortierung.')
            values = self.h.metrics.get(body.get('metrics'), (0, {}))[1]
            quality=body.get('qualityRates',{})
            if not isinstance(quality,dict) or len(quality)>60000 or any(not self.h.key(k) or isinstance(v,bool) or number(v) is None or not 0<=v<=1 for k,v in quality.items()):
                raise ValueError('Ungültige Frameverlust-Messwerte.')
            # Imported or locally watched models remain available without a catalog entry.
            source, _ = self.h.source()
            def project(row):
                if row.get('show') in ('away','idle','abwesend') and row.get('status')!='unknown':row['status']='away'
                if body.get('periodScoped'):
                    local=values.get(row['id'],{})
                    for field in ('watchMs','sessions','activeDays','previews','infos'):
                        row[field]=local.get(field,0)
                    for field in ('firstVisit','lastVisit','longestSession'):
                        row[field]=local.get(field)
                    row['averageSession']=row['watchMs']/row['sessions'] if row['sessions'] else None
                return row
            scope = {r['id']: True for r in source}
            known={r['id'] for r in source}
            for key,local in values.items():
                if key not in known:
                    item={k:local[k] for k in ('watchMs','sessions','activeDays','previews','infos','firstVisit','lastVisit','longestSession') if k in local}
                    item['personal']={k:copy.deepcopy(local[k]) for k in ('notes','tags','rating','priority','saved','bookmarked','archived') if k in local}
                    item['_search']=' '.join([key,*local.get('tags',[]),local.get('notes','')]).casefold()
                    item['averageSession']=item.get('watchMs',0)/item['sessions'] if item.get('sessions') else None
                    scope[key]=item
            following=body.get('filters',{}).get('view')=='following'
            if following:
                public=self.h.b['_cam_user_hub']().public() if '_cam_user_hub' in self.h.b else {}
                current=set()
                for site,connection in public.get('connections',{}).items():
                    if not connection.get('on'):continue
                    snapshot=public.get('accounts',{}).get(site+':'+str(connection.get('user','')), {})
                    for item in snapshot.get('items',[]):
                        key=self.h.b['_cam_pair'](site,item.get('name'))
                        if key:current.add(key)
                scope={key:scope.get(key,{'accountFav':True}) for key in current}
            def predicate(row):
                local = values.get(row['id'], {})
                if not row.get('seen') and local:
                    for k in ('watchMs','sessions','activeDays','previews','infos','firstVisit','lastVisit','longestSession'):
                        if k in local: row[k] = local[k]
                    row['averageSession'] = row.get('watchMs',0)/row['sessions'] if row.get('sessions') else None
                if extra.get('presence') and row.get('status')!=extra['presence']:return False
                for field in ('hd','gaming'):
                    expected=extra.get(field)
                    actual=row.get(field)
                    if expected=='unknown' and type(actual) is bool:return False
                    if expected in ('yes','no') and (type(actual) is not bool or actual!=(expected=='yes')):return False
                combination=extra.get('hdGaming')
                if combination:
                    known=type(row.get('hd')) is bool and type(row.get('gaming')) is bool
                    if combination=='unknown' and known:return False
                    if combination!='unknown' and (not known or (row['hd'],row['gaming'])!={'both':(True,True),'neither':(False,False),'hd-only':(True,False),'gaming-only':(False,True)}[combination]):return False
                for field, (key, factor) in LIMITS.items():
                    value = row.get(key)
                    for prefix in ('min','max'):
                        limit = extra.get(prefix+field)
                        if limit is not None and (value is None or (value < limit*factor if prefix=='min' else value > limit*factor)):
                            return False
                return True
            field, reverse = EXTRA_SORTS.get(sort, SORTS.get(sort))
            def order(rows):
                for row in rows:
                    row['_ownTags'] = len(row['personal'].get('tags', []))
                    row['_image'] = bool(row.get('cover') or row.get('thumb'))
                    # Quality sorting is unknown until native frame samples exist.
                    row['_quality'] = quality.get(row['id'])
                known = [r for r in rows if r.get(field) is not None and r.get(field) != '']
                unknown = [r for r in rows if r.get(field) is None or r.get(field) == '']
                known.sort(key=lambda r:r['id'])
                known.sort(key=lambda r:r[field].casefold() if isinstance(r[field],str) else r[field], reverse=reverse)
                return known+sorted(unknown,key=lambda r:r['id'])
            filters = {**body.get('filters', {}), 'sort':'name-az'}
            if following:filters['view']='all'
            return self.h.query({**body,'filters':filters},scope=scope,predicate=predicate,order=order,include_config=False,project=project)
        if body['op'] == 'statistics-context':
            sites=body.get('sites',list(self.h.b['_CAM_SITES']))
            if not isinstance(sites,list) or any(s not in self.h.b['_CAM_SITES'] for s in sites):
                raise ValueError('Unbekannte Statistikanbieter.')
            visited=body.get('visited')
            if visited is not None and (not isinstance(visited,list) or len(visited)>60000 or any(not self.h.key(key) for key in visited)):
                raise ValueError('Ung\u00fcltige Auswahl besuchter Models.')
            visited=set(visited) if visited is not None else None
            rows, groups=self.h.records(body.get('metrics',''),int(time.time()*1000))
            selected=[r for r in rows if r['site'] in sites]
            values=self.h.metrics.get(body.get('metrics'),(0,{}))[1]
            fields=('id','site','name','tags','subject','country','place','age','gender','hd','fav','profileLoaded','seen','status','lastOnline','cover','thumb')
            items=[]
            for row in selected:
                if row['id'] not in values and not row.get('fav'):continue
                item={k:copy.deepcopy(row[k]) for k in fields if k in row}
                item['personal']={k:copy.deepcopy(row['personal'][k]) for k in ('tags','saved','rating','priority') if k in row['personal']}
                items.append(item)
            return {'ok':True,'items':items,'groups':len(groups),'total':len(selected),
                    'saved':sum(bool(r['personal'].get('saved')) for r in selected),
                    'favorites':sum(bool(r.get('fav')) for r in selected),
                    'savedNeverVisited':sum(bool(r['personal'].get('saved')) and r['id'] not in visited and not (number(r['personal'].get('watchMs')) or number(r['personal'].get('sessions'))) for r in selected) if visited is not None else None,
                    'coverage':{key:sum(bool(r.get(key)) for r in selected) for key in ('seen','profileLoaded','country','age','tags','cover')},
                    'latest':max((r.get('seen',0) or 0 for r in selected),default=0)}
        raise ValueError('Unbekannte Statistikaktion.')
