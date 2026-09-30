import argparse, json, sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

EXPECTED = {"domestic": 10, "global": 10, "patent": 5}
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

def validate(path):
    if not path.exists():
        raise ValueError(f"missing briefing: {path}")
    try:
        d=json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"invalid json: {e}")
    day=path.stem
    if d.get("date")!=day: raise ValueError(f"date mismatch: file={day}, json={d.get('date')}")
    if d.get("status")!="published": raise ValueError("status must be published")
    if d.get("timezone")!="Asia/Seoul": raise ValueError("timezone must be Asia/Seoul")
    for section,n in EXPECTED.items():
        items=d.get(section)
        if not isinstance(items,list) or len(items)!=n:
            raise ValueError(f"{section}: expected {n}, got {len(items) if isinstance(items,list) else 'invalid'}")
        titles=set()
        for i,x in enumerate(items,1):
            missing=[k for k in REQUIRED if k not in x]
            if missing: raise ValueError(f"{section}[{i}] missing fields: {','.join(missing)}")
            if not x["title"].strip() or not x["summary"].strip() or not x["source"].strip() or not x["source_name"].strip():
                raise ValueError(f"{section}[{i}] has blank required text")
            norm=" ".join(x["title"].split()).lower()
            if norm in titles: raise ValueError(f"{section}[{i}] duplicate title")
            titles.add(norm)
            p=x["article_preview"]
            for mode,textkey in (("quick","lead"),("diff","direction")):
                q=p.get(mode,{}) if isinstance(p,dict) else {}
                if not q.get("title") or not q.get(textkey): raise ValueError(f"{section}[{i}] invalid {mode} preview")
                opts=q.get("title_options")
                if not isinstance(opts,list) or len(opts)!=2 or any(not str(v).strip() for v in opts):
                    raise ValueError(f"{section}[{i}] {mode}.title_options must contain 2 titles")
    return d

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--mode",choices=["latest","today"],default="latest")
    args=ap.parse_args()
    try:
        p=choose_path(args.mode); d=validate(p)
        print(f"VALID {p}: domestic=10 global=10 patent=5")
    except Exception as e:
        print(f"INVALID: {e}",file=sys.stderr); sys.exit(1)
