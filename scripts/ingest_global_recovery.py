#!/usr/bin/env python3
"""Safely ingest an externally supplied global staging payload; never publish."""
import argparse, base64, hashlib, json, os, re, sys
from pathlib import Path

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--date",required=True)
    p.add_argument("--payload-env",default="GLOBAL_PAYLOAD_B64")
    args=p.parse_args()
    if not re.fullmatch(r"20\d\d-\d\d-\d\d",args.date):
        raise ValueError("invalid date")
    encoded=os.environ.get(args.payload_env,"")
    if not encoded or len(encoded)>90000:
        raise ValueError("missing/oversized payload")
    raw=base64.b64decode(encoded,validate=True)
    if len(raw)>65536: raise ValueError("payload too large")
    data=json.loads(raw)
    if not isinstance(data,dict) or data.get("date")!=args.date:
        raise ValueError("date mismatch")
    if data.get("publish_allowed") is not False or data.get("no_telegram") is not True:
        raise ValueError("unsafe publish flags")
    items=data.get("global")
    if not isinstance(items,list) or not items:
        raise ValueError("global items missing")
    if data.get("discovered_count",len(items))<len(items):
        raise ValueError("discovered count less than saved items")
    for i,item in enumerate(items):
        if not isinstance(item,dict) or not str(item.get("title","")).strip():
            raise ValueError(f"invalid item {i}")
        if not str(item.get("source","")).startswith(("https://","http://")):
            raise ValueError(f"invalid source {i}")
    target=Path("staging")/f"{args.date}-global.json"
    target.parent.mkdir(exist_ok=True)
    if target.exists():
        old=json.loads(target.read_text(encoding="utf-8"))
        if isinstance(old.get("global"),list) and len(old["global"])>=len(items):
            raise ValueError("existing staging has same or more candidates; refusing overwrite")
    output=json.dumps(data,ensure_ascii=False,indent=2)+"\n"
    target.write_text(output,encoding="utf-8")
    verify=json.loads(target.read_text(encoding="utf-8"))
    if verify!=data: raise ValueError("readback mismatch")
    print(json.dumps({"status":"PASS","count":len(items),"file":str(target),"sha256":hashlib.sha256(output.encode()).hexdigest()}))

if __name__=="__main__":
    main()
