import argparse,json,re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
from domestic_coverage_gate import score_operational_coverage

def url_ok(v):
    try:
        u=urlparse(str(v or "")); return u.scheme in ("http","https") and bool(u.netloc) and str(v).strip() not in ("#","https://www.dailypharm.com/")
    except: return False

def main(path):
    p=Path(path); d=json.loads(p.read_text(encoding="utf-8")); day=d.get("date",p.stem[:10]); now=datetime.now(ZoneInfo("Asia/Seoul"))
    report={"schema_version":"briefing-quality-v1.0","date":day,"checked_at":now.isoformat(timespec="seconds"),"sections":{},"overall":"PASS","blocking":[]}
    for sec in ("domestic","global","patent"):
        items=d.get(sec,[]) if isinstance(d.get(sec),list) else []
        bad_url=[x.get("title","") for x in items if not url_ok(x.get("source"))]
        bad_p01=[x.get("title","") for x in items if x.get("priority") in ("P0","P1") and (not x.get("published_at") or x.get("timestamp_unverified") or (x.get("core_fact_check_required") is True or x.get("verification_status") in ("PAYWALL_CORE_FACT_UNVERIFIED","CORE_FACT_UNVERIFIED","EDITORIAL_CORE_FACT_PENDING")))]
        dup=len(items)-len({" ".join(str(x.get("title","")).lower().split()) for x in items})
        st="PASS" if not bad_url and not bad_p01 and dup==0 else "PARTIAL"
        report["sections"][sec]={"status":st,"count":len(items),"valid_source_urls":len(items)-len(bad_url),"invalid_source_titles":bad_url,"unverified_p0_p1_titles":bad_p01,"duplicate_titles":dup}
        if st!="PASS": report["overall"]="PARTIAL"; report["blocking"].append(sec)
    cs=d.get("collector_status",{})
    report["domestic_collectors"]={k:cs.get(k,"MISSING") for k in ("A","B","C","D","WEB")}
    # 90% OPERATIONAL coverage of 14 fixed routes plus six shared WEB
    # queries; never treat six WEB queries as nine publisher PASSes.
    settings_path=Path("config/briefing-settings.json")
    settings=json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
    audit=d.get("collection_evidence",{}) if isinstance(d.get("collection_evidence"),dict) else {}
    if not audit:
        for audit_path in (Path("staging")/f"{day}-domestic-route-audit.json",
                           Path("status")/f"{day}-collection-evidence.json"):
            if audit_path.exists():
                try:
                    audit=json.loads(audit_path.read_text(encoding="utf-8"))
                    break
                except (ValueError,OSError):
                    continue
    if settings and audit:
        coverage=score_operational_coverage(settings,audit)
    else:
        coverage={"verified_usable_search_tasks":0,"configured_search_tasks":
                  sum(len(settings.get("domestic",{}).get("collectors",{}).get(k,[]))
                      for k in ("A","B","C","D"))
                  +len(settings.get("domestic",{}).get("web_unified_search",{})
                       .get("selected_terms_by_axis",{})),
                  "ratio":0,"goal_ratio":0.9,"target_met":False,
                  "article_recall_status":"UNMEASURED",
                  "unusable_tasks":["MISSING_COLLECTION_AUDIT"],
                  "publisher_completeness_not_inferred":True}
    source_gate=bool(settings and audit and coverage["target_met"])
    report["domestic_operational_coverage"]={**coverage,"pass":source_gate}
    report["domestic_source_coverage"]={
        "metric":"SHARED_SEARCH_TASK_EXECUTION_NOT_PUBLISHER_PASS",
        "verified_sources":coverage["verified_usable_search_tasks"],
        "total_sources":coverage["configured_search_tasks"],
        "ratio":coverage["ratio"],"target_ratio":coverage["goal_ratio"],
        "pass":source_gate,"article_recall_status":"UNMEASURED"}
    report["sections"]["domestic"]["operational_coverage_pass"]=source_gate
    report["sections"]["domestic"]["article_recall_90pct_confirmed"]=False
    report["sections"]["domestic"]["article_recall_note"]=(
        "Article recall requires independent date-matched reference articles; "
        "search task success is not 90% article recall.")
    if not source_gate:
        report["sections"]["domestic"]["status"]="PARTIAL"
        report["overall"]="PARTIAL"; report["blocking"].append("domestic_search_task_coverage")
    sh=Path("status/schedule-health.json")
    sched=json.loads(sh.read_text(encoding="utf-8")) if sh.exists() else {}
    same_day=str(sched.get("checked_at","")).startswith(day) and sched.get("status")=="PASS"
    report["sections"]["schedule"]={"status":"PASS" if same_day else "FAIL","health":sched}
    if not same_day: report["overall"]="PARTIAL"; report["blocking"].append("schedule")
    patent_status=d.get("patent_axis_status",{})
    required=["특허심판 청구","특허심판원 심결","특허법원·각급법원 판결·결정","우선판매품목허가","통지의약품","의약품 특허기간 만료·임박","우판기간 만료·임박","특허법·허가특허연계 입법","국내사 특허도전·소송 및 출시·독점기간 변화"]
    report["patent_axes"]={x:patent_status.get(x,"MISSING") for x in required}
    if any(v not in ("PASS","PASS_ZERO") for v in report["patent_axes"].values()):
        report["overall"]="PARTIAL"; report["blocking"].append("patent_axes")
    gs=d.get("global_search_status",{})
    reqg=["PRIMARY_REGULATORY_AND_COMPANY","TRADE_AND_WIRE","WHOLE_WEB_RECOVERY"]
    report["global_source_groups"]={x:gs.get(x,"MISSING") for x in reqg}
    if any(v!="PASS" for v in report["global_source_groups"].values()):
        report["overall"]="PARTIAL"; report["blocking"].append("global_source_groups")
    report["blocking"]=list(dict.fromkeys(report["blocking"]))
    out=Path("status")/f"{day}-quality.json"; out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"overall":report["overall"],"blocking":report["blocking"],"output":str(out)},ensure_ascii=False))
    if report["overall"]!="PASS": raise SystemExit(2)

if __name__=="__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("path"); a=ap.parse_args(); main(a.path)
