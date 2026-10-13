#!/usr/bin/env python3
"""Fail-soft global briefing checkpoint; never claims unverified source coverage."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path

KST = dt.timezone(dt.timedelta(hours=9))
GROUPS = ("specialist_media", "official_feeds", "gap_search")

def write_atomic(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=dt.datetime.now(KST).date().isoformat())
    p.add_argument("--input", help="JSON collector output; omit only to record NOT_STARTED")
    p.add_argument("--root", default=".")
    args = p.parse_args()
    now = dt.datetime.now(KST).isoformat()
    data = {}
    error = None
    if args.input:
        try:
            data = json.loads(Path(args.input).read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("collector output must be an object")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            error = f"{type(exc).__name__}: {exc}"
    groups = {}
    raw = data.get("groups", {}) if isinstance(data.get("groups", {}), dict) else {}
    for name in GROUPS:
        entry = raw.get(name, {})
        entry = entry if isinstance(entry, dict) else {}
        status = entry.get("status", "NOT_STARTED")
        if status not in ("PASS", "PARTIAL", "FAIL", "NOT_STARTED"):
            status = "FAIL"
        groups[name] = {"status": status, "count": len(entry.get("items", [])) if isinstance(entry.get("items"), list) else 0, "error": entry.get("error")}
    items = data.get("items", [])
    if not isinstance(items, list):
        items, error = [], "collector items is not a list"
    status = "FAIL" if error else ("PASS" if all(g["status"] == "PASS" for g in groups.values()) else "PARTIAL")
    if not args.input:
        status = "NOT_STARTED"
    output = {"date": args.date, "section": "global", "status": status, "checked_at_kst": now, "groups": groups, "items": items, "error": error, "checkpoint_version": "global-diagnostic-v1"}
    root = Path(args.root)
    dest = root / "staging" / f"{args.date}-global.json"
    write_atomic(dest, output)
    write_atomic(root / "status" / f"{args.date}-global-health.json", {"date": args.date, "status": status, "checked_at_kst": now, "group_status": {k:v["status"] for k,v in groups.items()}, "item_count": len(items), "error": error})
    print(f"global_checkpoint={dest} status={status} items={len(items)}")
    if error:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
