"""Step 3: six shared WEB discovery searches instead of per-publisher searches.

Index hits are NOT original-article verification or proof of source completeness.
The only network activity in this module is the six configured RSS queries.
P0/P1 original confirmation and event deduplication belong to stage 4.
"""
import argparse
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, time
from pathlib import Path

from domestic_route_collector import KST, fetch_bytes, google_url, publication_time, window

GROUP = "WEB"
AXES = ("rnd", "bd", "governance", "court", "market_risk", "policy")
SIGNALS = ("단독", "exclusive", "3상", "임상 중단", "fda", "허가", "승인",
           "기술수출", "계약해지", "최대주주", "합병", "판결", "가처분",
           "상장폐지", "거래정지", "약가", "급여")


def hostname(url):
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        while host.startswith(("www.", "m.")):
            host = host.split(".", 1)[1]
        return host
    except (TypeError, ValueError):
        return ""


def domain_match(host, domain):
    domain = domain.lower().strip()
    return bool(domain) and (host == domain or host.endswith("." + domain))


def feed_items(data, limit):
    root = ET.fromstring(data)
    result = []
    for item in root.findall(".//item")[:limit]:
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        date = (item.findtext("pubDate") or "").strip()
        source = item.find("source")
        source_name = (source.text or "").strip() if source is not None else ""
        source_url = source.attrib.get("url", "") if source is not None else ""
        if title and url and urllib.parse.urlparse(url).scheme in ("https", "http"):
            result.append({"title": title, "url": url, "index_pub_date": date,
                           "index_source_name": source_name,
                           "index_source_url": source_url})
    return result


def build_queries(settings, start, end):
    config = settings["domestic"]
    unified = config["web_unified_search"]
    by_axis = unified["selected_terms_by_axis"]
    approved = config["web_keyword_axes"]
    budget = int(unified["query_budget"])
    if set(by_axis) != set(AXES) or budget != len(AXES):
        raise ValueError("WEB_QUERY_BUDGET_OR_AXES_MISMATCH")
    base = unified["base_query"]
    result = {}
    for axis in AXES:
        terms = by_axis[axis]
        if not terms or any(term not in approved[axis] for term in terms):
            raise ValueError("WEB_TERMS_NOT_IN_AUTHORITATIVE_KEYWORDS")
        terms = " OR ".join('"' + t.replace('"', '') + '"' for t in terms)
        result[axis] = (f"{base} ({terms}) "
                        f"after:{start.date()} before:{end.date()}")
    return result


def classify(entry, settings):
    config = settings["domestic"]
    web = config["web_unified_search"]
    publisher = entry["index_source_name"].strip()
    host = hostname(entry["index_source_url"])
    if not host:
        host = hostname(entry["url"])
    # Respect configured excluded outlets before aggregating.
    excluded = config.get("excluded_general_news", [])
    if any(publisher and publisher.casefold() == x.casefold() for x in excluded):
        return "EXCLUDED", host
    # Avoid fetching and rediscovering A/B/C/D headlines as WEB articles.
    for group in ("A", "B", "C", "D"):
        for configured in config["collectors"].get(group, []):
            domain = configured.split("/", 1)[0]
            if domain_match(host, domain):
                return "FIXED_GROUP", host
    for name, domains in web["publisher_domains"].items():
        if any(domain_match(host, domain) for domain in domains):
            return name, host
    # If the publisher link is missing, exact known publisher name may classify
    # discovery provenance. It is never treated as verified source evidence.
    names = config["collectors"]["WEB"]
    if publisher in names and publisher != "기타 전체 웹":
        return publisher, host
    return "기타 전체 웹", host


def dedupe_key(entry):
    # Restrict to exact-title within publisher OR identical index link.
    norm = " ".join(re.sub(r"\s+", " ", entry["title"].lower()).split())
    host = hostname(entry["index_source_url"]) or entry["index_source_name"].casefold()
    return (host, norm)


def importance(title):
    lower = title.casefold()
    return sum(2 if value in ("단독", "3상", "상장폐지") else 1
               for value in SIGNALS if value in lower)


def distribute(pool, publishers, per_publisher, max_total):
    buckets = defaultdict(list)
    for value in sorted(pool, key=lambda x: -importance(x["title"])):
        buckets[value["source_bucket"]].append(value)
    # Round-robin protects lesser-covered outlets from a single dominant source.
    counts = Counter()
    selected = []
    while len(selected) < max_total:
        advanced = False
        for name in publishers:
            if counts[name] >= per_publisher or not buckets[name]:
                continue
            selected.append(buckets[name].pop(0))
            counts[name] += 1
            advanced = True
            if len(selected) >= max_total:
                break
        if not advanced:
            break
    return selected


def scan_web(day, settings, *, loader=fetch_bytes, now_kst=None):
    current = now_kst or datetime.now(KST)
    if current.tzinfo is None:
        raise ValueError("now_kst must be timezone-aware")
    target = datetime.strptime(day, "%Y-%m-%d").date()
    local_now = current.astimezone(KST)
    if target > local_now.date():
        raise ValueError("FUTURE_BRIEFING_DATE")
    if target == local_now.date() and local_now.time() < time(6):
        raise ValueError("WEB_BEFORE_06_00_KST")
    start, end = window(day)
    upper = min(local_now, end)
    unified = settings["domestic"]["web_unified_search"]
    if unified["original_fetch_budget"] != 0:
        raise ValueError("STEP3_ORIGINAL_FETCH_BUDGET_MUST_BE_ZERO")
    queries = build_queries(settings, start, end)
    routes, entries = [], {}
    excluded_hits = 0
    overlap = 0
    count_by_bucket = Counter()
    attempted = 0
    for axis, query in queries.items():
        attempted += 1
        record = {"axis": axis, "method": "SHARED_GOOGLE_NEWS_RSS",
                  "query": query, "status": "FAIL", "hits": 0,
                  "eligible_index_hits": 0,
                  "checked_at": local_now.isoformat(timespec="seconds")}
        try:
            rss = feed_items(loader(google_url(query)),
                             int(unified["max_index_hits_per_axis"]))
            record["hits"] = len(rss)
            for entry in rss:
                discovered = publication_time(entry["index_pub_date"])
                if discovered and not (start <= discovered <= upper):
                    continue
                bucket, host = classify(entry, settings)
                if bucket == "EXCLUDED":
                    excluded_hits += 1
                    continue
                if bucket == "FIXED_GROUP":
                    overlap += 1
                    continue
                record["eligible_index_hits"] += 1
                count_by_bucket[bucket] += 1
                key = dedupe_key(entry)
                if key in entries:
                    if axis not in entries[key]["discovery_axes"]:
                        entries[key]["discovery_axes"].append(axis)
                    continue
                entries[key] = {
                    "title": entry["title"], "url": entry["url"],
                    "published_at": "", "timestamp_unverified": True,
                    "source_name": bucket, "source_bucket": bucket,
                    "source_domain": host, "index_pub_date": entry["index_pub_date"],
                    "index_source_name": entry["index_source_name"],
                    "index_source_url": entry["index_source_url"],
                    "group": GROUP, "discovery_axes": [axis],
                    "verified_original": False,
                    "original_verification": {"status": "NOT_CHECKED",
                                              "reason": "DEFERRED_TO_STEP4"},
                    "route_method": "SHARED_GOOGLE_NEWS_RSS"
                }
            # A successful index request, including zero hits, is not PASS_ZERO.
            record["status"] = "PARTIAL"
        except Exception as exc:
            record["reason"] = type(exc).__name__
            record["error"] = str(exc)[:160]
        routes.append(record)

    configured = settings["domestic"]["collectors"]["WEB"]
    selected = distribute(list(entries.values()), configured,
                          int(unified["max_candidates_per_publisher"]),
                          int(unified["max_discovery_candidates"]))
    selected_counts = Counter(x["source_bucket"] for x in selected)
    successes = sum(x["status"] == "PARTIAL" for x in routes)
    status = "PARTIAL" if successes else "FAIL"
    health = {}
    for name in configured:
        health[name] = {
            "status": status, "method": "SHARED_WEB_INDEX",
            "index_hits": count_by_bucket[name],
            "selected_candidates": selected_counts[name],
            "coverage_proven": False, "reason": "INDEX_ONLY_NO_COMPLETENESS_PROOF"
            if successes else "ALL_INDEX_QUERIES_FAILED",
            "shared_query_count": attempted, "independent_site_queries": 0,
            "route_count": 0, "verified_candidate_count": 0,
            "routes": []  # Actual shared routes are recorded once at WEB group level.
        }
    return {
        "schema_version": "web-unified-discovery-v1.0", "date": day,
        "timezone": "Asia/Seoul", "checked_at": local_now.isoformat(timespec="seconds"),
        "status": status, "search_window": {"from": start.isoformat(),
                                          "to_exclusive": upper.isoformat()},
        "routes": routes, "source_health": health, "candidates": selected,
        "statistics": {"rss_requests": attempted, "original_requests": 0,
                       "eligible_index_hits": sum(count_by_bucket.values()),
                       "unique_index_candidates": len(entries),
                       "selected_candidates": len(selected),
                       "excluded_hits": excluded_hits,
                       "fixed_group_overlap_hits": overlap},
        "publish_allowed": False,
        "note": "Six RSS index queries. Publisher/clock attribution is unverified until step 4; do not upgrade sources to PASS."
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--settings", default="config/briefing-settings.json")
    ap.add_argument("--output")
    args = ap.parse_args()
    settings = json.loads(Path(args.settings).read_text(encoding="utf-8"))
    result = scan_web(args.date, settings)
    path = Path(args.output or f"staging/{args.date}-web-discovery.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(path), "status": result["status"],
                      "requests": result["statistics"]["rss_requests"],
                      "candidates": len(result["candidates"]),
                      "publish_allowed": False}, ensure_ascii=False))

if __name__ == "__main__":
    main()
