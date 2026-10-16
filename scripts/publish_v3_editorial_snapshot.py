#!/usr/bin/env python3
"""Preserve *curated* daily briefings from the secure read-only Supabase feed.

Runs every day (including weekends), never sends Telegram, never publishes
raw/unverified candidate pools as final editorial selections.
"""
import json
from html import unescape
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

BASE = "https://mqkhtnryxyntrrfrfing.supabase.co/functions/v1/briefing-feed-v2?date="
TODAY = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")

def get_feed(day):
    request = Request(BASE + day, headers={"User-Agent": "PharmBriefingArchive/3.0"})
    with urlopen(request, timeout=22) as resp:
        obj = json.load(resp)
    if obj.get("date") != day or obj.get("schema_version") != "briefing-v2":
        raise RuntimeError("Feed date/schema mismatch")
    return obj

def normalize(item, section):
    title = unescape((item.get("title") or "").strip())
    summary = unescape((item.get("summary") or "").strip())
    source = (item.get("url") or "").replace("&amp;", "&")
    if not title or not summary or not source.startswith("https://"):
        return None
    if section == "global" and not re.search(r"[가-힣]", title):
        return None
    return {
        "title": title,
        "summary": summary,
        "source": source,
        "source_name": item.get("source_name") or "",
        "published_at": item.get("published_at") or "",
        # Source priority (P0/P1/major) and editorial status are not article topics.
        "tag": (item.get("category") or item.get("tag"))
               if (item.get("category") or item.get("tag")) in {
                   "약가·급여", "특허·소송", "허가·규제", "신약·임상",
                   "기술수출·계약", "기업·경영", "산업·정책", "의약품·시장"
               } else "의약품·시장",
        "verification_status": item.get("verification_status") or "candidate",
        "selection_status": "selected",
        "original_title": item.get("original_title") or None
    }

def run(day):
    if not re.fullmatch(r"20\d\d-\d\d-\d\d", day):
        raise ValueError("YYYY-MM-DD required")
    feed = get_feed(day)
    domestic = [
        x for item in feed.get("domestic", [])
        if item.get("selection_status") == "selected"
        if (x := normalize(item, "domestic")) is not None
    ]
    global_items = [
        x for item in feed.get("global", [])
        if item.get("selection_status") == "selected"
        if (x := normalize(item, "global")) is not None
    ]
    # Raw discovery-only records must not be written into editorial snapshots.
    uncurated = feed.get("status") == "candidate" and not (domestic or global_items)
    if uncurated:
        print("EDITORIAL_NOT_READY: candidate-only feed; do not replace/archive a completed briefing.")
        return 0
    target = Path("data") / (day + ".json")
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
        if existing.get("generated_by") != "daily-editorial-snapshot-v3":
            print("PRESERVED_MANUAL_EDITORIAL_ARCHIVE", target)
            return 0
    obj = {
        "schema_version": "briefing-editorial-v1",
        "date": day,
        "timezone": "Asia/Seoul",
        "status": "editorial-selected" if domestic or global_items else "editorial-empty",
        "generated_by": "daily-editorial-snapshot-v3",
        "editorial_scope": "중요 기사만 선별한 자동 브리핑. 주말도 최소 건수 없음",
        "test_run": False,
        "domestic": domestic,
        "global": global_items,
        "patent": [],
        "telegram": False,
        "publish_allowed": False,
        "selected_count": {"domestic": len(domestic), "global": len(global_items)},
        "note": "원문 확인이 완료되지 않은 기사는 별도 표시. 이 파일은 공개 데스크 보존용이며 텔레그램 자동발송을 의미하지 않는다."
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
    if target.exists() and target.read_text(encoding="utf-8") == rendered:
        print("NO_ARCHIVE_CHANGES", day)
        return 0
    target.write_text(rendered, encoding="utf-8")
    print("SAVED_EDITORIAL_ARCHIVE", day, "domestic", len(domestic), "global", len(global_items))
    return 0

if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else TODAY))
