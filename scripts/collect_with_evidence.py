"""Auditable source scanner. Search execution != verified coverage."""
import argparse,json,urllib.parse,urllib.request,xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

TZ=ZoneInfo("Asia/Seoul")
def now(): return datetime.now(TZ).isoformat(timespec="seconds")
def fetch(q):
    url="https://news.google.com/rss/search?"+urllib.parse.urlencode({"q":q,"hl":"ko","gl":"KR","ceid":"KR:ko"})
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (briefing-audit/2.0)"})
    with urllib.request.urlopen(req,timeout=18) as r: body=r.read()
    root=ET.fromstring(body)
    return [{"title":(e.findtext("title") or "").strip(),"url":(e.findtext("link") or "").strip(),"published_at":(e.findtext("pubDate") or "").strip()} for e in root.findall(".//item")]
def scan(day,settings):
    start=(datetime.fromisoformat(day+"T00:00:00+09:00")-timedelta(hours=12))
    end=datetime.fromisoformat(day+"T23:59:59+09:00")
    groups={}; candidates=[]; errors=[]
    for group,domains in settings["domestic"]["collectors"].items():
        routes=[]
        for domain in domains:
            query=f'site:{domain} (제약 OR 바이오 OR 신약 OR 임상 OR 특허) after:{start.date()} before:{(end+timedelta(days=1)).date()}'
            route={"source":domain,"query":query,"checked_at":now(),"method":"GOOGLE_NEWS_RSS","status":"FAIL","hits":0}
            try:
                hits=fetch(query)
                route["hits"]=len(hits)
                route["status"]="PARTIAL" # Search index cannot prove full outlet coverage
                for x in hits:
                    candidates.append({**x,"group":group,"source_domain":domain,"verified_original":False})
            except Exception as exc:
                route["error"]=str(exc)[:240];errors.append(domain)
            routes.append(route)
        groups[group]={"checked_at":now(),"status":"FAIL" if all(x["status"]=="FAIL" for x in routes) else "PARTIAL","routes":routes}
    gap_queries=["제약 바이오 단독 임상 허가 기술수출","한미 에페글레나타이드 허가 후속 약가 급여 경쟁 출시","제약 특허심판 판결 우선판매품목허가"]
    gap=[]
    for q in gap_queries:
        route={"query":q,"checked_at":now(),"status":"FAIL","hits":0}
        try:
            hits=fetch(q);route["hits"]=len(hits);route["status"]="PARTIAL"
            candidates.extend([{**x,"group":"WEB_GAP","source_domain":"web","verified_original":False} for x in hits])
        except Exception as exc:route["error"]=str(exc)[:240]
        gap.append(route)
    p0=[]
    for x in candidates:
        if any(k in x["title"].lower() for k in ("에페글레나타이드","에페오토","epheglena")):
            p0.append({"event_id":"HANMI-EPHE-APPROVAL","title":x["title"],"url":x["url"],"verified_original":False})
    return {"date":day,"generated_at":now(),"domestic_groups":groups,"web_gap_scan":{"checked_at":now(),"status":"PARTIAL" if any(x["status"]!="FAIL" for x in gap) else "FAIL","routes":gap},"p0_followups":[{"event_id":"HANMI-EPHE-APPROVAL","checked_at":now(),"status":"PARTIAL","candidates":p0}],"global":{"status":"FAIL","checked_at":None,"routes":[]},"patent":{"status":"FAIL","checked_at":None,"routes":[]},"candidates":candidates,"errors":errors,"note":"검색결과는 원문 검증 전 후보이며 PASS가 아님. 글로벌·특허 수집은 이 스캐너에 미구현."}
if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--date",required=True);a=ap.parse_args()
    settings=json.loads(Path("config/briefing-settings.json").read_text())
    out=scan(a.date,settings)
    p=Path("status")/f"{a.date}-collection-evidence.json";p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
    print(f"AUDIT {p}: candidates={len(out['candidates'])} groups="+str({k:v['status'] for k,v in out['domestic_groups'].items()}))
