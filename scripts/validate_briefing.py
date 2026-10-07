import argparse, json, sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

LEGACY_REQUIRED=("tag","title","summary","source","source_name","published_at","article_preview")

def choose_path(mode):
    root=Path("data")
    if mode=="today":
        day=datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
        return root/f"{day}.json"
    files=sorted(root.glob("20??-??-??.json"))
    if not files: raise ValueError("no briefing files")
    return files[-1]

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

def validate_v1(d,path):
    if d.get("schema_version")!="briefing-final-v1.0": raise ValueError("invalid v1 schema_version")
    if d.get("timezone")!="Asia/Seoul": raise ValueError("timezone must be Asia/Seoul")
    if d.get("status") not in ("ready","partial","published","test-published"): raise ValueError("invalid v1 status")
    items=d.get("domestic")
    if not isinstance(items,list): raise ValueError("domestic must be an array")
    titles=set()
    for i,x in enumerate(items,1):
        if not isinstance(x,dict) or not str(x.get("title","")).strip(): raise ValueError(f"domestic[{i}] missing title")
        norm=" ".join(x["title"].split()).lower()
        if norm in titles: raise ValueError(f"domestic[{i}] duplicate title")
        titles.add(norm)
    cs=d.get("collector_status")
    if not isinstance(cs,dict) or any(k not in cs for k in ("A","B","C","D","WEB")): raise ValueError("collector_status incomplete")
    return d

def validate(path,allowed_statuses=("published",)):
    if not path.exists(): raise ValueError(f"missing briefing: {path}")
    try: d=json.loads(path.read_text(encoding="utf-8"))
    except Exception as e: raise ValueError(f"invalid json: {e}")
    if d.get("schema_version")=="briefing-final-v1.0":
        return validate_v1(d,path)
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
    ap=argparse.ArgumentParser()
    ap.add_argument("--mode",choices=["latest","today"],default="latest")
    ap.add_argument("--path")
    ap.add_argument("--staging",action="store_true")
    args=ap.parse_args()
    try:
        p=Path(args.path) if args.path else choose_path(args.mode)
        d=validate(p,("ready","published") if args.staging else ("published",))
        print(f"VALID {p}: schema={d.get('schema_version','legacy')} domestic={len(d.get('domestic',[]))}")
    except Exception as e:
        print(f"INVALID: {e}",file=sys.stderr); sys.exit(1)
