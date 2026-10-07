import argparse, json, re, sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

LEGACY_REQUIRED=("tag","title","summary","source","source_name","published_at","article_preview")
V1_REQUIRED=("tag","title","summary","source","source_name","published_at","article_preview","priority")
ISO_KST=re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?\+09:00$")

def choose_path(mode):
    root=Path("data")
    if mode=="today":
        day=datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
        return root/f"{day}.json"
    files=sorted(root.glob("20??-??-??.json"))
    if not files: raise ValueError("no briefing files")
    return files[-1]

def good_url(v):
    try:
        u=urlparse(str(v or "").strip())
        return u.scheme in ("http","https") and bool(u.netloc) and str(v).strip() not in ("#","https://www.dailypharm.com/")
    except Exception: return False

def validate_preview(section,i,p):
    if not isinstance(p,dict): raise ValueError(f"{section}[{i}] article_preview invalid")
    for k in ("quick","diff"):
        if not isinstance(p.get(k),dict): raise ValueError(f"{section}[{i}] article_preview.{k} missing")
    if not str(p["quick"].get("title","")).strip() or not str(p["quick"].get("lead","")).strip():
        raise ValueError(f"{section}[{i}] quick preview incomplete")
    if not str(p["diff"].get("title","")).strip() or not str(p["diff"].get("direction","")).strip():
        raise ValueError(f"{section}[{i}] diff preview incomplete")

def validate_v1_items(section,items,strict_ready):
    if not isinstance(items,list): raise ValueError(f"{section} must be an array")
    titles=set()
    for i,x in enumerate(items,1):
        if not isinstance(x,dict): raise ValueError(f"{section}[{i}] invalid item")
        missing=[k for k in V1_REQUIRED if k not in x]
        if missing: raise ValueError(f"{section}[{i}] missing fields: {','.join(missing)}")
        title=str(x.get("title","")).strip()
        if not title: raise ValueError(f"{section}[{i}] missing title")
        norm=" ".join(title.split()).lower()
        if norm in titles: raise ValueError(f"{section}[{i}] duplicate title")
        titles.add(norm)
        if not str(x.get("tag","")).strip(): raise ValueError(f"{section}[{i}] missing tag")
        if x.get("priority") not in ("P0","P1","P2","P3"): raise ValueError(f"{section}[{i}] invalid priority")
        if not str(x.get("summary","")).strip(): raise ValueError(f"{section}[{i}] missing summary")
        if not str(x.get("source_name","")).strip(): raise ValueError(f"{section}[{i}] missing source_name")
        validate_preview(section,i,x.get("article_preview"))
        src=x.get("source","")
        ts=str(x.get("published_at","") or "")
        unverified=bool(x.get("timestamp_unverified",False))
        if strict_ready and not good_url(src): raise ValueError(f"{section}[{i}] invalid/blank source URL")
        if src and not good_url(src): raise ValueError(f"{section}[{i}] invalid source URL")
        if ts and not ISO_KST.match(ts): raise ValueError(f"{section}[{i}] published_at must be KST ISO8601")
        if not ts and not unverified: raise ValueError(f"{section}[{i}] blank published_at requires timestamp_unverified=true")
        if strict_ready and x.get("priority") in ("P0","P1") and (not ts or unverified):
            raise ValueError(f"{section}[{i}] P0/P1 requires verified published_at")

def validate_v1(d,path):
    if d.get("schema_version")!="briefing-final-v1.0": raise ValueError("invalid v1 schema_version")
    day=path.stem
    if d.get("date")!=day: raise ValueError(f"date mismatch: file={day}, json={d.get('date')}")
    if d.get("timezone")!="Asia/Seoul": raise ValueError("timezone must be Asia/Seoul")
    status=d.get("status")
    if status not in ("ready","partial","failed","published","test-published"): raise ValueError("invalid v1 status")
    if not isinstance(d.get("search_window"),dict): raise ValueError("search_window missing")
    cs=d.get("collector_status")
    if not isinstance(cs,dict) or any(k not in cs for k in ("A","B","C","D","WEB")): raise ValueError("collector_status incomplete")
    if any(cs[k] not in ("PASS","PARTIAL","FAIL") for k in ("A","B","C","D","WEB")): raise ValueError("collector_status invalid")
    comp=d.get("completeness_status")
    if comp not in ("ready","partial","failed"): raise ValueError("completeness_status invalid")
    strict=status in ("ready","published") and not d.get("test_run",False)
    for section in ("domestic","global","patent"):
        validate_v1_items(section,d.get(section),strict)
    if strict:
        if comp!="ready": raise ValueError("READY/published requires completeness_status=ready")
        if any(cs[k]!="PASS" for k in ("A","B","C","D","WEB")): raise ValueError("READY/published requires all domestic collectors PASS")
        health=d.get("section_health")
        if not isinstance(health,dict): raise ValueError("READY/published requires section_health")
        for section in ("domestic","global","patent","schedule"):
            if health.get(section)!="PASS": raise ValueError(f"READY/published requires section_health.{section}=PASS")
    if status=="test-published" and not d.get("test_run",False): raise ValueError("test-published requires test_run=true")
    return d

def validate_legacy_items(section,items,expected=None):
    if not isinstance(items,list): raise ValueError(f"{section}: invalid section")
    if expected is not None and len(items)!=expected: raise ValueError(f"{section}: expected {expected}, got {len(items)}")
    titles=set()
    for i,x in enumerate(items,1):
        missing=[k for k in LEGACY_REQUIRED if k not in x]
        if missing: raise ValueError(f"{section}[{i}] missing fields: {','.join(missing)}")
        norm=" ".join(x["title"].split()).lower()
        if norm in titles: raise ValueError(f"{section}[{i}] duplicate title")
        titles.add(norm)

def validate(path,allowed_statuses=("published",)):
    if not path.exists(): raise ValueError(f"missing briefing: {path}")
    try: d=json.loads(path.read_text(encoding="utf-8"))
    except Exception as e: raise ValueError(f"invalid json: {e}")
    if d.get("schema_version")=="briefing-final-v1.0": return validate_v1(d,path)
    day=path.name.split("-final.json")[0] if path.name.endswith("-final.json") else path.stem
    if d.get("date")!=day: raise ValueError(f"date mismatch: file={day}, json={d.get('date')}")
    if d.get("status") not in allowed_statuses: raise ValueError("legacy status invalid")
    if d.get("timezone")!="Asia/Seoul": raise ValueError("timezone must be Asia/Seoul")
    validate_legacy_items("domestic",d.get("domestic"),10)
    validate_legacy_items("global",d.get("global"),10)
    validate_legacy_items("patent",d.get("patent"),None)
    if len(d.get("patent",[]))>5: raise ValueError("legacy patent maximum 5")
    return d

if __name__=="__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("--mode",choices=["latest","today"],default="latest"); ap.add_argument("--path"); ap.add_argument("--staging",action="store_true"); args=ap.parse_args()
    try:
        p=Path(args.path) if args.path else choose_path(args.mode)
        d=validate(p,("ready","published") if args.staging else ("published",))
        print(f"VALID {p}: schema={d.get('schema_version','legacy')} domestic={len(d.get('domestic',[]))} global={len(d.get('global',[]))} patent={len(d.get('patent',[]))}")
    except Exception as e:
        print(f"INVALID: {e}",file=sys.stderr); sys.exit(1)
