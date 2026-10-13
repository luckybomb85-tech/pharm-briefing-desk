"""Auditable source scanner. Search execution != verified coverage."""
import argparse,json,urllib.parse,urllib.request,xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from domestic_route_collector import scan_fixed
from web_unified_collector import scan_web
from domestic_candidate_pipeline import build_domestic_stage4
from global_source_collector import scan_global_sources
from global_candidate_ranker import select as rank_global_candidates

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
    # Step 3: ONE shared WEB search per six configured news axes; no nine
    # per-publisher site searches and no extra overlapping WEB_GAP queries.
    web = scan_web(day, settings)
    groups["WEB"] = {"status": web["status"],
                     "checked_at": web["checked_at"],
                     "routes": web["routes"]}
    source_health = {**fixed["source_health"], "WEB": web["source_health"]}
    candidates.extend(web["candidates"])
    errors.extend("WEB/"+r["axis"] for r in web["routes"] if r["status"] == "FAIL")
    web_gap = {"checked_at": web["checked_at"], "status": web["status"],
               "routes": web["routes"], "reuses_unified_web_scan": True}
    domestic_candidates=list(candidates)
    if domestic_only:
        return {"date": day, "generated_at": now(),
                "mode": "domestic_only_step3", "domestic_groups": groups,
                "source_health": source_health, "web_gap_scan": web_gap,
                "web_unified_statistics": web["statistics"],
                "candidates": candidates, "errors": errors,
                "publish_allowed": False}
    global_audit=scan_global_sources(day,settings,now)
    candidates.extend(global_audit["candidates"])
    global_shortlist=rank_global_candidates(global_audit["candidates"],limit=30)
    patent_audit=scan_extra(["제약 특허심판원 심결 특허법원 판결 when:3d","제약 우선판매품목허가 통지의약품 when:3d","의약품 특허만료 제네릭 출시 when:3d","pharma patent litigation biosimilar when:3d"],"PATENT",candidates)
    p0=[]
    for x in candidates:
        if any(k in x["title"].lower() for k in ("에페글레나타이드","에페오토","epheglena")):
            p0.append({"event_id":"HANMI-EPHE-APPROVAL","title":x["title"],"url":x["url"],"verified_original":bool(x.get("verified_original",False))})
    return {"date":day,"generated_at":now(),"source_health":source_health,"domestic_groups":groups,"web_gap_scan":web_gap,"web_unified_statistics":web["statistics"],"p0_followups":[{"event_id":"HANMI-EPHE-APPROVAL","checked_at":now(),"status":"PARTIAL","candidates":p0}],"domestic_candidates":domestic_candidates,"global":global_audit,"global_shortlist":global_shortlist,"patent":patent_audit,"candidates":candidates,"errors":errors,"note":"WEB는 6개 공유 RSS 검색만 수행하고 원문 검증은 후속 단계로 이관. 인덱스 검색만으로 PASS/PASS_ZERO 불가. 글로벌·특허는 기존 분리 상태이며 추가 검증 전 PASS 불가."}
def source_health_checkpoint(day, out):
    """Preserve WEB shared-query evidence without pretending independent visits."""
    checks = {}
    for group, sources in out.get("source_health", {}).items():
        checks[group] = {}
        for domain, state in sources.items():
            checks[group][domain] = {
                "status": state.get("status", "FAIL"),
                "route_count": state.get("route_count", 0),
                "verified_candidate_count": state.get("verified_candidate_count", 0),
                "selected_candidates": state.get("selected_candidates", 0),
                "shared_query_count": state.get("shared_query_count", 0),
                "coverage_proven": state.get("coverage_proven", False),
                "routes": state.get("routes", [])
            }
    return {"schema_version": "briefing-domestic-source-health-v1.0",
            "date": day, "source_checks": checks,
            "collector_status": {g: out["domestic_groups"][g]["status"]
                                 for g in ("A","B","C","D","WEB")},
            "web_unified_statistics": out.get("web_unified_statistics", {}),
            "publish_allowed": False}

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--date",required=True)
    ap.add_argument("--domestic-only",action="store_true",help="Domestic A/B/C/D + shared WEB only; no global or patent queries")
    a=ap.parse_args()
    settings=json.loads(Path("config/briefing-settings.json").read_text(encoding="utf-8"))
    out=scan(a.date,settings,domestic_only=a.domestic_only)
    # Merge A/B/C/D/WEB first, then verify only previously unverified
    # distinct candidates. Never re-open an already-confirmed original.
    stage4=build_domestic_stage4(a.date,out.get("domestic_candidates",out.get("candidates",[])),settings)
    stage4_path=Path("staging")/f"{a.date}-domestic-stage4.json"
    stage4_path.parent.mkdir(exist_ok=True)
    stage4_path.write_text(json.dumps(stage4,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    out["domestic_stage4_path"]=str(stage4_path)
    out["domestic_stage4_statistics"]=stage4["statistics"]
    out["publish_allowed"]=False
    if not a.domestic_only:
        shortlist_path=Path("staging")/f"{a.date}-global-shortlist.json"
        shortlist_path.write_text(json.dumps(out.get("global_shortlist",{}),ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    # Audit is a checkpoint, NOT a publication or a claim of readiness.
    health=source_health_checkpoint(a.date,out)
    health_path=Path("staging")/f"{a.date}-source-health.json"
    health_path.parent.mkdir(exist_ok=True)
    health_path.write_text(json.dumps(health,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    p=(Path("staging")/f"{a.date}-domestic-route-audit.json" if a.domestic_only
       else Path("status")/f"{a.date}-collection-evidence.json")
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"AUDIT {p}: candidates={len(out['candidates'])} groups="+str({k:v['status'] for k,v in out['domestic_groups'].items()}))
    print("STAGE4",stage4_path,"verifier_calls",stage4["statistics"]["new_original_verifier_calls"],"duplicates",stage4["statistics"]["duplicates_suppressed"])
