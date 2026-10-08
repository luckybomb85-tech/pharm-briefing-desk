import json, os, time
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

base=os.environ.get("PAGE_URL","").rstrip("/")
if not base: raise SystemExit("PAGE_URL missing")
files=sorted(Path("data").glob("20??-??-??.json"))
if not files: raise SystemExit("No dated briefing")
p=files[-1]
expected=json.loads(p.read_text(encoding="utf-8"))
url=f"{base}/data/{p.name}"
for attempt in range(12):
    try:
        req=Request(url+f"?check={attempt}",headers={"Cache-Control":"no-cache"})
        with urlopen(req,timeout=20) as resp: actual=json.load(resp)
        if actual.get("date")==expected.get("date") and all(len(actual.get(k,[]))==len(expected.get(k,[])) for k in ("domestic","global","patent")) and actual.get("status")==expected.get("status"):
            print("LIVE VERIFIED",url,"counts",*[len(actual.get(k,[])) for k in ("domestic","global","patent")]);break
        print("Live content not current yet",attempt)
    except Exception as e: print("Live check error",repr(e))
    time.sleep(10)
else: raise SystemExit("FAIL: live briefing does not match deployed dataset")
