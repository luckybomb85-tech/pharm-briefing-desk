"""Bounded domestic A/B/C/D route collector. Never promotes search hits to verified coverage.

Only source_routes in config/briefing-settings.json defines primary routes.
WEB integration is deferred to the separate consolidation phase.
"""
import argparse
import html
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, time
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

from verify_originals import verify

KST = ZoneInfo("Asia/Seoul")
FIXED_GROUPS = ("A", "B", "C", "D")
ARTICLE_PATH = re.compile(
    r"(articleview|article_view|newsid=|idxno=|/news/read|/news/view|/news/\d|"
    r"/user/news/\d|/\d{4}/\d{2}/\d{2}/|/article/|/news/\w+-\d+)", re.I
)
DATE_TEXT = re.compile(r"\b(20\d{2})[./-](\d{1,2})[./-](\d{1,2})"
                       r"(?:\s*(?:T|\s)\s*(\d{1,2}):(\d{2})(?::(\d{2}))?)?")
USER_AGENT = "Mozilla/5.0 (compatible; PharmaBriefing/1.0; source-audit)"

def window(day):
    d = datetime.strptime(day, "%Y-%m-%d").date()
    return (datetime.combine(d - timedelta(days=1), time(12), KST),
            datetime.combine(d + timedelta(days=1), time.min, KST))

def publication_time(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        try:
            dt = parsedate_to_datetime(value)
        except (ValueError, TypeError, IndexError):
            match = DATE_TEXT.search(value)
            if not match:
                return None
            yy, mm, dd, hh, minute, sec = match.groups()
            try:
                dt = datetime(int(yy), int(mm), int(dd), int(hh or 0),
                              int(minute or 0), int(sec or 0), tzinfo=KST)
            except ValueError:
                return None
    if dt.tzinfo is None:
        return None  # Unzoned date is not verified KST.
    return dt.astimezone(KST)

def fetch_bytes(url):
    if not url.startswith("https://"):
        raise ValueError("Only HTTPS routes are allowed")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=12) as response:
        return response.read(650000)

class ListingLinks(HTMLParser):
    def __init__(self, base_url):
        super().__init__()
        self.base_url = base_url
        self.links = []
        self.times = []
        self._anchor = None
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            self._anchor = {"href": attrs.get("href", ""), "title": attrs.get("title", ""), "text": []}
        if tag == "time" and attrs.get("datetime"):
            dt = publication_time(attrs["datetime"])
            if dt:
                self.times.append(dt)
    def handle_data(self, data):
        if self._anchor is not None:
            self._anchor["text"].append(data)
    def handle_endtag(self, tag):
        if tag == "a" and self._anchor is not None:
            entry = self._anchor
            self._anchor = None
            url = urllib.parse.urljoin(self.base_url, entry["href"])
            parsed = urllib.parse.urlparse(url)
            title = html.unescape(" ".join(" ".join(entry["text"]).split()) or entry["title"])
            if (parsed.scheme == "https" and ARTICLE_PATH.search(parsed.path + "?" + parsed.query)
                    and len(title) >= 7):
                self.links.append({"url": url, "title": title})

def parse_listing(body, url):
    text = body.decode("utf-8", "replace")
    p = ListingLinks(url)
    p.feed(text)
    # Only <time datetime> attached to native HTML is used as listing boundary
    # evidence; random JSON/script dates must not create a spurious PASS.
    seen = set()
    links = []
    for item in p.links:
        if item["url"] not in seen:
            links.append(item)
            seen.add(item["url"])
    return links[:50], p.times[:100]

def parse_rss(body):
    root = ET.fromstring(body)
    out = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        when = (item.findtext("pubDate") or "").strip()
        if title and url:
            out.append({"title": title, "url": url, "index_published_at": when})
    return out[:40]

def google_url(query):
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"})

def search_query(domain, start, end, broad=False):
    # Google only supports day granularity. The KST noon boundary is checked
    # using publisher-original timestamps AFTER the index query.
    base = f"site:{domain} after:{start.date()} before:{end.date()}"
    if broad:
        return base
    return f"{base} (제약 OR 바이오 OR 신약 OR 임상 OR 특허)"

def attempt(method, domain, route, start, end, loader, verifier,
            *, max_original_checks=3, broad=False):
    result = {"method": method, "status": "PARTIAL", "hits": 0,
              "original_checks": 0, "verified_original_count": 0, "verified_in_window": 0, "verified_before_window": 0,
              "coverage_proven": False, "candidates": []}
    if method == "DIRECT_LIST":
        url = route.get("primary_url")
        if not url:
            result.update(status="FAIL", reason="NO_DIRECT_LIST_URL")
            return result
        request_url = url
    else:
        template = route.get("primary_query_template") if not broad else None
        query = (template.format(start_date=start.date(),
                                 end_date_exclusive=end.date())
                 if template and method == "SITE_SEARCH"
                 else search_query(domain, start, end, broad=broad))
        request_url = google_url(query)
        result["query"] = query
    result["request_url"] = request_url
    try:
        data = loader(request_url)
        if method == "DIRECT_LIST":
            links, times = parse_listing(data, request_url)
            # Covering the lower boundary requires an observed in-window date
            # AND an older list item, in descending order. Timestamp tags alone
            # do not prove originals were checked.
            dates = times
            is_descending = all(a >= b for a, b in zip(dates, dates[1:]))
            result["listing_time_count"] = len(dates)
            result["listing_boundary_seen"] = (
                len(dates) >= 2 and is_descending and dates[0] >= start
                and dates[-1] < start)
            result["listing_all_older_than_window"] = (
                len(dates) >= 2 and is_descending and dates[0] < start)
            items = links
        else:
            items = parse_rss(data)
            result["listing_boundary_seen"] = False
        result["hits"] = len(items)
        if not items:
            result["status"] = "PARTIAL"
            result["reason"] = "NO_CONFIRMED_WINDOW_COVERAGE"
            return result
        for candidate in items[:max_original_checks]:
            result["original_checks"] += 1
            try:
                check = verifier(candidate)
            except Exception as exc:
                check = {"verified_original": False, "reason": type(exc).__name__}
            when = publication_time(check.get("published_at_verified"))
            if check.get("verified_original") and when:
                result["verified_original_count"] += 1
                if when < start:
                    result["verified_before_window"] += 1
            if not (check.get("verified_original") and when and start <= when < end):
                continue
            result["verified_in_window"] += 1
            result["candidates"].append({
                "title": check.get("original_title") or candidate["title"],
                "url": check.get("resolved_url") or candidate["url"],
                "published_at": when.isoformat(timespec="seconds"),
                "source_domain": domain, "verified_original": True,
                "route_method": method
            })
        # Google RSS is discovery only: search index coverage cannot be PASS.
        # A dated native listing can PASS only when all in-window links were
        # checked and original URLs/times were verified.
        # Reading the whole dated listing proves the clock-window boundary;
        # verify a bounded sample of originals without fetching every article.
        # Any failed sample keeps this source PARTIAL.
        if (method == "DIRECT_LIST" and result["listing_boundary_seen"]
                and result["verified_in_window"] > 0
                and result["verified_original_count"] == result["original_checks"]):
            result["status"] = "PASS"
            result["coverage_proven"] = True
        elif (method == "DIRECT_LIST" and result["listing_all_older_than_window"]
              and result["original_checks"] > 0
              and result["verified_before_window"] == result["original_checks"]):
            # A chronological publisher list with its newest dated items already
            # before the cutoff and matching older originals proves zero new items.
            result["status"] = "PASS_ZERO"
            result["coverage_proven"] = True
        else:
            result["status"] = "PARTIAL"
            result["reason"] = ("NATIVE_LIST_INCOMPLETE_OR_UNVERIFIED" if method == "DIRECT_LIST"
                                else "SEARCH_INDEX_NOT_EXHAUSTIVE")
    except Exception as exc:
        result["status"] = "FAIL"
        result["reason"] = type(exc).__name__
        result["error"] = str(exc)[:180]
    return result

def scan_fixed(day, settings, *, loader=fetch_bytes, verifier=verify,
               now_kst=None, max_original_checks=3):
    current = now_kst or datetime.now(KST)
    if current.tzinfo is None:
        raise ValueError("now_kst must be timezone-aware")
    today = current.astimezone(KST).date()
    target = datetime.strptime(day, "%Y-%m-%d").date()
    if target > today:
        raise ValueError("Future briefing date")
    if target == today and current.astimezone(KST).time() < time(6):
        raise ValueError("DOMESTIC_BEFORE_06_00_KST")
    start, end = window(day)
    config = settings["domestic"]
    routes = config.get("source_routes", {})
    out, candidates, source_health = {}, [], {}
    max_fallback = min(1, int(settings.get("runtime_safety", {})
                          .get("retry_budget", {}).get("domestic_source_max_retry", 1)))
    for group in FIXED_GROUPS:
        group_routes = []
        source_health[group] = {}
        for domain in config["collectors"].get(group, []):
            info = routes.get(domain, {})
            primary = info.get("primary_method")
            if info.get("group") != group or primary not in ("DIRECT_LIST", "SITE_SEARCH"):
                route_results = [{"method": "CONFIG", "status": "FAIL",
                                  "reason": "MISSING_OR_INVALID_PRIMARY_ROUTE"}]
            else:
                first = attempt(primary, domain, info, start, end, loader,
                                verifier, max_original_checks=max_original_checks)
                route_results = [first]
                # Stop on PASS or certified zero; retry once only on non-PASS.
                if first["status"] not in ("PASS", "PASS_ZERO") and max_fallback:
                    fallback = "SITE_SEARCH" if primary == "DIRECT_LIST" else "WEB_SEARCH_RECOVERY"
                    second = attempt(fallback, domain, info, start, end, loader,
                                     verifier, max_original_checks=max_original_checks,
                                     broad=(fallback == "WEB_SEARCH_RECOVERY"))
                    route_results.append(second)
            # Preserve verified candidates from either path without duplicating.
            seen_urls = set()
            verified = []
            for result in route_results:
                for x in result.get("candidates", []):
                    if x["url"] not in seen_urls:
                        verified.append({**x, "group": group})
                        seen_urls.add(x["url"])
            candidates.extend(verified)
            statuses = [r["status"] for r in route_results]
            status = ("PASS" if "PASS" in statuses else
                      "PASS_ZERO" if "PASS_ZERO" in statuses else
                      "PARTIAL" if "PARTIAL" in statuses else "FAIL")
            source_health[group][domain] = {
                "status": status, "route_count": len(route_results),
                "verified_candidate_count": len(verified),
                "primary_method": primary, "routes": route_results
            }
            group_routes.append({"source": domain, **source_health[group][domain]})
        group_statuses = [x["status"] for x in group_routes]
        group_status = ("PASS" if group_statuses and all(
                         x in ("PASS", "PASS_ZERO") for x in group_statuses)
                        else "FAIL" if group_statuses and all(
                         x == "FAIL" for x in group_statuses) else "PARTIAL")
        out[group] = {"status": group_status, "checked_at": current.astimezone(KST).isoformat(timespec="seconds"), "routes": group_routes}
    return {
        "schema_version": "domestic-route-audit-v1.0", "date": day,
        "timezone": "Asia/Seoul", "mode": "DOMESTIC_A_TO_D_ONLY",
        "search_window": {"from": start.isoformat(), "to_exclusive": end.isoformat()},
        "domestic_groups": out, "source_health": source_health,
        "candidates": candidates, "publish_allowed": False,
        "note": "Source statuses require actual evidence. Search index is discovery only; no fabricated PASS_ZERO."
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--settings", default="config/briefing-settings.json")
    parser.add_argument("--output")
    args = parser.parse_args()
    settings = json.loads(Path(args.settings).read_text(encoding="utf-8"))
    result = scan_fixed(args.date, settings)
    path = Path(args.output or f"staging/{args.date}-domestic-route-audit.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(json.dumps({"path": str(path),
                      "sources": {k: {d: z["status"] for d, z in g.items()}
                                  for k, g in result["source_health"].items()},
                      "verified_candidates": len(result["candidates"]),
                      "publish_allowed": False}, ensure_ascii=False))

if __name__ == "__main__":
    main()
