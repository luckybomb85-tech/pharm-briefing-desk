import argparse, json, sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

EXPECTED_EXACT = {"domestic": 10, "global": 10}
REQUIRED = ("tag","title","summary","source","source_name","published_at","article_preview")


def choose_path(mode):
    root=Path("data")
    if mode=="today":
        day=datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
        return root/f"{day}.json"
    files=sorted(root.glob("20??-??-??.json"))
    if not files:
        raise ValueError("no briefing files")
    return files[-1]


def validate_items(section, items, expected=None):
    if not isinstance(items, list):
        raise ValueError(f"{section}: invalid section")
    if expected is not None and len(items) != expected:
        raise ValueError(f"{section}: expected {expected}, got {len(items)}")
    titles=set()
    for i,x in enumerate(items,1):
        missing=[k for k in REQUIRED if k not in x]
        if missing:
            raise ValueError(f"{section}[{i}] missing fields: {','.join(missing)}")
        if not x["title"].strip() or not x["summary"].strip() or not x["source"].strip() or not x["source_name"].strip():
            raise ValueError(f"{section}[{i}] has blank required text")
        norm=" ".join(x["title"].split()).lower()
        if norm in titles:
            raise ValueError(f"{section}[{i}] duplicate title")
        titles.add(norm)
        p=x["article_preview"]
        for mode,textkey in (("quick","lead"),("diff","direction")):
            q=p.get(mode,{}) if isinstance(p,dict) else {}
            if not q.get("title") or not q.get(textkey):
                raise ValueError(f"{section}[{i}] invalid {mode} preview")
            opts=q.get("title_options")
            if not isinstance(opts,list) or len(opts)!=2 or any(not str(v).strip() for v in opts):
                raise ValueError(f"{section}[{i}] {mode}.title_options must contain 2 titles")


def validate(path, allowed_statuses=("published",)):
    if not path.exists():
        raise ValueError(f"missing briefing: {path}")
    try:
        d=json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"invalid json: {e}")
    day=path.name.split("-final.json")[0] if path.name.endswith("-final.json") else path.stem
    if d.get("date")!=day:
        raise ValueError(f"date mismatch: file={day}, json={d.get('date')}")
    if d.get("status") not in allowed_statuses:
        raise ValueError(f"status must be one of {','.join(allowed_statuses)}")
    if d.get("timezone")!="Asia/Seoul":
        raise ValueError("timezone must be Asia/Seoul")

    for section,n in EXPECTED_EXACT.items():
        validate_items(section, d.get(section), n)

    validate_items("patent", d.get("patent"), None)
    if len(d.get("patent", [])) > 5:
        raise ValueError(f"patent: maximum 5, got {len(d['patent'])}")
    return d


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--mode",choices=["latest","today"],default="latest")
    ap.add_argument("--path",help="validate an explicit briefing file, including staging/YYYY-MM-DD-final.json")
    ap.add_argument("--staging",action="store_true",help="allow staging status ready as well as published")
    args=ap.parse_args()
    try:
        p=Path(args.path) if args.path else choose_path(args.mode)
        statuses=("ready","published") if args.staging else ("published",)
        d=validate(p,statuses)
        print(f"VALID {p}: domestic={len(d['domestic'])} global={len(d['global'])} patent={len(d['patent'])}")
    except Exception as e:
        print(f"INVALID: {e}",file=sys.stderr); sys.exit(1)
