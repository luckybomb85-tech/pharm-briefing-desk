"""Auditable source scanner. Search execution != verified coverage."""
import argparse,json,urllib.parse,urllib.request,xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from domestic_route_collector import scan_fixed

TZ=ZoneInfo("Asia/Seoul")
def now(): return datetime.now(TZ).isoformat(timespec="seconds")
def fetch(q):
    url="https://news.google.com/rss/search?"+urllib.parse.urlencode({"q":q,"hl":"ko","gl":"KR","ceid":"KR:ko"})
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (briefing-audit/2.0)"})
    with urllib.request.urlopen(req,timeout=18) as r: body=r.read()
    root=ET.fromstring(body)
    return [{"title":(e.findtext("title") or "").strip(),"url":(e.findtext("link") or "").strip(),"published_at":(e.findtext("pubDate") or "").strip()} for e in root.findall(".//item")]

def scan_extra(queries,group,candidates):
    routes=[]
    for q in queries:
        route={"query":q,"checked_at":now(),"method":"GOOGLE_NEWS_RSS","status":"FAIL","hits":0}
        try:
            hits=fetch(q)
            route["hits"]=len(hits)
            route["status"]="PARTIAL"
            candidates.extend([{**x,"group":group,"verified_original":False} for x in hits[:30]])
        except Exception as exc:
            route["error"]=str(exc)[:240]
        routes.append(route)
    return {"checked_at":now(),"status":"PARTIAL" if any(r["status"]=="PARTIAL" for r in routes) else "FAIL","routes":routes}

def scan(day,settings,domestic_only=False):
    start=(datetime.fromisoformat(day+"T00:00:00+09:00")-timedelta(hours=12))
    end=datetime.fromisoformat(day+"T23:59:59+09:00")
    # A/B/C/D now use per-source primary routes from config; only failed
    # sources may use ONE fallback. WEB consolidation is a separate phase.
    fixed = scan_fixed(day, settings)
    groups = fixed["domestic_groups"]
    candidates = list(fixed["candidates"])
    errors = [name for g in fixed["source_health"].values()
              for name, state in g.items() if state["status"] == "FAIL"]
    if domestic_only:
        return {"date": day, "generated_at": now(),
                "mode": "domestic_only_step2", "domestic_groups": groups,
                "source_health": fixed["source_health"], "candidates": candidates,
                "publish_allowed": False}
    # Existing WEB collector retained temporarily; step 3 will consolidate it.
    for group, domains in settings["domestic"]["collectors"].items():
        if group != "WEB":
            continue
        routes = []
        for domain in domains:
            query=f'site:{domain} (제약 OR 바이오 OR 신약 OR 임상 OR 특허) after:{start.date()} before:{(end+timedelta(days=1)).date()}'
            route={"source":domain,"query":query,"checked_at":now(),"method":"GOOGLE_NEWS_RSS","status":"FAIL","hits":0}
            try:
                hits=fetch(query)
                route["hits"]=len(hits)
                route["status"]="PARTIAL"  # Search index is not native completeness proof.
                for x in hits:
                    candidates.append({**x,"group":group,"source_domain":domain,"verified_original":False})
            except Exception as exc:
                route["error"]=str(exc)[:240]; errors.append(domain)
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
    global_audit=scan_extra(["FDA biotech drug approval phase 3 when:2d","EMA pharmaceutical CHMP trial results when:2d","site:clinicaltrials.gov phase 3 biotech when:2d","pharma licensing clinical results Reuters when:2d"],"GLOBAL",candidates)
    patent_audit=scan_extra(["제약 특허심판원 심결 특허법원 판결 when:3d","제약 우선판매품목허가 통지의약품 when:3d","의약품 특허만료 제네릭 출시 when:3d","pharma patent litigation biosimilar when:3d"],"PATENT",candidates)
    p0=[]
    for x in candidates:
        if any(k in x["title"].lower() for k in ("에페글레나타이드","에페오토","epheglena")):
            p0.append({"event_id":"HANMI-EPHE-APPROVAL","title":x["title"],"url":x["url"],"verified_original":False})
    return {"date":day,"generated_at":now(),"source_health":fixed["source_health"],"domestic_groups":groups,"web_gap_scan":{"checked_at":now(),"status":"PARTIAL" if any(x["status"]!="FAIL" for x in gap) else "FAIL","routes":gap},"p0_followups":[{"event_id":"HANMI-EPHE-APPROVAL","checked_at":now(),"status":"PARTIAL","candidates":p0}],"global":global_audit,"patent":patent_audit,"candidates":candidates,"errors":errors,"note":"검색결과는 원문 검증 전 후보이며 PASS가 아님. 글로벌·특허 후보 수집 연결됨. 1차 공식자료·특허 9개 축 전체 검증 전 PASS 불가."}
if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--date",required=True)
    ap.add_argument("--domestic-only",action="store_true",help="A/B/C/D source routes only; no WEB, global or patent queries")
    a=ap.parse_args()
    settings=json.loads(Path("config/briefing-settings.json").read_text(encoding="utf-8"))
    out=scan(a.date,settings,domestic_only=a.domestic_only)
    # Audit is a checkpoint, NOT a publication or a claim of readiness.
    source_checks={group:{domain:{"status":state["status"],
                                   "route_count":state["route_count"],
                                   "verified_candidate_count":state["verified_candidate_count"],
                                   "routes":state["routes"]}
                          for domain,state in sources.items()}
                   for group,sources in out.get("source_health",{}).items()}
    health={"schema_version":"briefing-domestic-source-health-v1.0",
            "date":a.date,"source_checks":source_checks,
            "collector_status":{g:out["domestic_groups"][g]["status"]
                                for g in ("A","B","C","D")},
            "publish_allowed":False}
    health_path=Path("staging")/f"{a.date}-source-health.json"
    health_path.parent.mkdir(exist_ok=True)
    health_path.write_text(json.dumps(health,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    p=(Path("staging")/f"{a.date}-domestic-route-audit.json" if a.domestic_only
       else Path("status")/f"{a.date}-collection-evidence.json")
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"AUDIT {p}: candidates={len(out['candidates'])} groups="+str({k:v['status'] for k,v in out['domestic_groups'].items()}))
