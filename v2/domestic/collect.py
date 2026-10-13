#!/usr/bin/env python3
"""V2 domestic discovery. No publication or automatic deployment."""
import argparse
import datetime as dt
import email.utils
import hashlib
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
KST = ZoneInfo("Asia/Seoul")
USER_AGENT = "PharmBriefingDesk/2.0 (newsroom research)"
KEYWORDS = ("제약", "바이오", "신약", "의약품", "임상", "약가", "급여", "특허", "제네릭", "허가", "식약처", "기술수출", "바이오시밀러", "제약사", "항암제")

def fetch(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read(1_500_000)

def canonical_url(url):
    p = urllib.parse.urlsplit(url.strip())
    if p.scheme not in ("https", "http") or not p.hostname:
        return None
    if p.hostname.lower() in ("news.google.com", "google.com"):
        return None
    query = urllib.parse.parse_qsl(p.query, keep_blank_values=True)
    query = [(k, v) for k, v in query if not (k.lower().startswith("utm_") or k.lower() in ("fbclid", "gclid"))]
    return urllib.parse.urlunsplit((p.scheme, p.netloc.lower(), p.path, urllib.parse.urlencode(query), ""))

def host_matches(url, domain):
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return host == domain or host.endswith("." + domain)

def query_url(domain, term):
    q = "site:" + domain + " " + term + " when:2d"
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": q, "hl": "ko", "gl": "KR", "ceid": "KR:ko"})

def parse_feed(data):
    root = ET.fromstring(data)
    out = []
    for item in root.findall(".//item"):
        source = item.find("source")
        out.append({
            "title": (item.findtext("title") or "").strip(),
            "url": (item.findtext("link") or "").strip(),
            "published": (item.findtext("pubDate") or "").strip(),
            "publisher": (source.text or "").strip() if source is not None else "",
            "publisher_url": source.attrib.get("url", "") if source is not None else "",
        })
    return out

def parse_time(raw):
    try:
        value = email.utils.parsedate_to_datetime(raw)
        return value.astimezone(KST) if value.tzinfo else None
    except (TypeError, ValueError, IndexError):
        return None

def collect(now, config, transport=fetch):
    start = (now - dt.timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
    if now.hour < 12:
        start -= dt.timedelta(days=1)
    # The requested window is always previous calendar day 12:00 KST.
    start = (now.date() - dt.timedelta(days=1))
    start = dt.datetime.combine(start, dt.time(12), tzinfo=KST)
    accepted, seen, diagnostics = [], set(), []
    for name, domain in config["priority_sites"]:
        counts = {"site": name, "domain": domain, "status": "PASS_ZERO", "found": 0, "accepted": 0, "rejected": 0, "errors": []}
        for term in config["search_terms"]:
            try:
                feed = parse_feed(transport(query_url(domain, term), config["discovery"]["timeout_seconds"]))
            except Exception as exc:
                counts["errors"].append(type(exc).__name__ + ": " + str(exc)[:140])
                continue
            counts["found"] += len(feed)
            for item in feed[:config["discovery"]["max_per_site"]]:
                published = parse_time(item["published"])
                link = canonical_url(item["url"])
                publisher_link = item["publisher_url"]
                # Google News links are not source URLs. Never mislabel them as verified originals.
                if not published or not start <= published <= now or not link or not host_matches(link, domain):
                    counts["rejected"] += 1
                    continue
                if publisher_link and not host_matches(publisher_link, domain):
                    counts["rejected"] += 1
                    continue
                if not any(k in item["title"] for k in KEYWORDS):
                    counts["rejected"] += 1
                    continue
                key = hashlib.sha256(link.encode()).hexdigest()
                if key in seen:
                    continue
                seen.add(key)
                accepted.append({"title": item["title"], "url": link, "source_name": name,
                                 "published_at": published.isoformat(), "summary": "",
                                 "verification_status": "discovery_only", "priority": "unreviewed",
                                 "source_id": key[:20]})
                counts["accepted"] += 1
        counts["status"] = ("PARTIAL" if counts["errors"] else "PASS") if counts["accepted"] else ("FAIL" if len(counts["errors"]) == len(config["search_terms"]) else ("PARTIAL" if counts["errors"] else "PASS_ZERO"))
        diagnostics.append(counts)
    accepted.sort(key=lambda x: x["published_at"], reverse=True)
    return {"schema_version": "domestic-discovery-v2", "date": now.date().isoformat(),
            "timezone": "Asia/Seoul", "window_start": start.isoformat(),
            "window_end": now.isoformat(), "items": accepted, "source_status": diagnostics,
            "status": "FAIL" if all(s["status"] == "FAIL" for s in diagnostics) else
                      "PARTIAL" if any(s["status"] in ("PARTIAL", "FAIL") for s in diagnostics) else "PASS"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD; date to collect in KST")
    ap.add_argument("--output", help="Explicit JSON output path; no automatic publication")
    args = ap.parse_args()
    now = dt.datetime.now(KST)
    if args.date:
        target = dt.date.fromisoformat(args.date)
        if target != now.date():
            raise SystemExit("Historical date collection is disabled: use current KST date only")
    config = json.loads((ROOT / "domestic" / "sources.json").read_text(encoding="utf-8"))
    result = collect(now, config)
    body = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    else:
        print(body)
    print(f"domestic candidates={len(result['items'])} status={result['status']}", file=sys.stderr)
    if result["status"] == "FAIL":
        raise SystemExit(2)

if __name__ == "__main__":
    main()
