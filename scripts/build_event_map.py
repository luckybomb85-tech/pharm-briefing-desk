"""Conservative article deduplication and follow-up event mapping."""
import argparse,json,re,urllib.parse
from pathlib import Path

def key(item):
    v=item.get('original_verification',{})
    url=v.get('resolved_url') or item.get('url','')
    p=urllib.parse.urlparse(url)
    return (p.hostname or '').removeprefix('www.')+p.path.rstrip('/')

def classify(title):
    t=title.lower()
    if not any(x in t for x in ('에페글레나타이드','에페오토','efpeglenatide')):return None
    stages={'approval':('허가','승인'),'reimbursement':('급여','약가'),'launch':('출시','판매','처방'),'competition':('경쟁','위고비','마운자로'),'clinical':('임상','체중감소','안전성')}
    return ('HANMI-EPHE-APPROVAL',[k for k,terms in stages.items() if any(term in t for term in terms)] or ['general'])

def build(data):
    unique=[];duplicates=[];seen={};events={}
    for i,item in enumerate(data.get('candidates',[])):
        k=key(item)
        if k and k in seen:
            duplicates.append({'index':i,'kept_index':seen[k],'reason':'SAME_ORIGINAL_URL'})
            continue
        if k:seen[k]=len(unique)
        unique.append(item)
        match=classify(item.get('title',''))
        if match:
            event,stages=match
            e=events.setdefault(event,{'articles':[],'milestones':{}})
            article={'title':item.get('title',''),'url':item.get('original_verification',{}).get('resolved_url') or item.get('url',''),'verified_original':bool(item.get('verified_original')),'published_at':item.get('original_verification',{}).get('published_at_verified')}
            e['articles'].append(article)
            for stage in stages:e['milestones'].setdefault(stage,[]).append(article)
    data['unique_candidates']=unique
    data['deduplication']={'input':len(data.get('candidates',[])),'unique':len(unique),'duplicates':len(duplicates),'removed':duplicates}
    data['event_map']=events
    data['event_watch_status']={'HANMI-EPHE-APPROVAL':'FOUND' if events else 'NOT_FOUND_IN_SCAN'}
    return data

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    d=build(json.loads(Path(a.input).read_text(encoding='utf-8')))
    Path(a.output).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('DEDUPLICATION',d['deduplication']['input'],d['deduplication']['unique'],d['deduplication']['duplicates'])
    print('EVENT_WATCH',d['event_watch_status'])
