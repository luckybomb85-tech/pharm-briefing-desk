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
from domestic_window_paging import parse_publisher_page

KST = ZoneInfo("Asia/Seoul")
FIXED_GROUPS = ("A", "B", "C", "D")
ARTICLE_PATH = re.compile(
    r"(articleview|article_view|newsid=|idxno=|/news/read|/news/view|/news/\d|"
    r"/user/news/\d|/\d{4}/\d{2}/\d{2}/|/article/|/news/\w+-\d+)", re.I
)
DATE_TEXT = re.compile(r"\b(20\d{2})[./-](\d{1,2})[./-](\d{1,2})"
                       r"(?:\s*(?:T|\s)\s*(\d{1,2}):(\d{2})(?::(\d{2}))?)?")
USER_AGENT = "Mozilla/5.0 (compatible; PharmaBriefing/1.0; source-audit)"

# Broad business pages mix pharmaceuticals with unrelated politics or finance.
# Specialized pharma lists can be consumed directly; general pages need topic signals.
BUSINESS_GENERAL_SOURCES = {"dealsite.co.kr", "businesspost.co.kr", "newdaily.co.kr"}
PHARMA_TOPIC = re.compile(
    r"(제약|바이오|의약|신약|임상|치료|약가|급여|제네릭|의료|건강보험|"
    r"한미약품|한미사이언스|셀트리온|삼성바이오|유한양행|대웅|종근당|"
    r"녹십자|보령|동아ST|동아에스티|일동제약|HK이노엔|루닛|레고켐|"
    r"특허|백신|항암|FDA|CDMO|CRO|GLP-1|"
    r"pharma|clinical|biotech|therap|drug)", re.I)
NEWS_PRIORITY = re.compile(
    r"(단독|임상\s*[123]상|3상|계약해지|기술수출|허가|fda|급여|약가|"
    r"특허|소송|판결|실적|최대주주|합병|증여|상장|지분|거래정지|"
    r"의약품|신약|임상|마운자로|위고비|로수젯|케이캡)", re.I)


def choose_relevant(items, domain, max_candidates):
    """Keep useful headlines from the list, not only its three newest posts."""
    pairs = [(i, x) for i, x in enumerate(items)
             if domain not in BUSINESS_GENERAL_SOURCES or
             PHARMA_TOPIC.search(x["title"])]
    ranked = sorted(pairs,
                    key=lambda pair: (-int(bool(NEWS_PRIORITY.search(pair[1]["title"]))),
                                      pair[0]))
    # Spread a small portion over the later page to catch early-morning stories.
    selected = ranked[:max_candidates]
    if len(pairs) > max_candidates and max_candidates >= 4:
        tail = pairs[len(pairs)*2//3:]
        candidate = tail[-1]
        if candidate[0] not in {i for i, _ in selected}:
            selected[-1] = candidate
    return [x for _, x in sorted(selected, key=lambda item: item[0])]


def choose_time_balanced(items, domain, max_candidates, start):
    """Reserve candidate slots for 06–09, 09–12, previous-day afternoon.
    No extra HTTP requests; this only redistributes already fetched links.
    """
    if not any(x.get("listing_published_at") for x in items):
        return choose_relevant(items,domain,max_candidates)
    eligible=[x for x in items if (
        domain not in BUSINESS_GENERAL_SOURCES or PHARMA_TOPIC.search(x["title"]))]
    now_date=(start+timedelta(hours=12)).date()
    groups={"early":[],"morning":[],"previous":[],"later":[],"unknown":[]}
    for x in eligible:
        dt=publication_time(x.get("listing_published_at"))
        if not dt:
            category="unknown"
        elif dt.date()==now_date and 6<=dt.hour<9:
            category="early"
        elif dt.date()==now_date and 9<=dt.hour<12:
            category="morning"
        elif dt.date()<now_date:
            category="previous"
        else:
            category="later"
        groups[category].append(x)
    def rank(seq):
        return sorted(seq,key=lambda x:-int(bool(NEWS_PRIORITY.search(x["title"]))))
    # These reserves are maxima, not invented quotas: unused slots return to
    # the rest of the dated listing. IMPORTANT: the original page is not refetched.
    reserves={"early":max(1,max_candidates//3),
              "morning":max(1,max_candidates//4),
              "previous":max(1,max_candidates//5)}
    selected=[]
    seen=set()
    def add(x):
        if x["url"] not in seen and len(selected)<max_candidates:
            selected.append(x);seen.add(x["url"])
    for category in ("early","morning","previous"):
        for x in rank(groups[category])[:reserves[category]]:
            add(x)
    for category in ("early","morning","previous","later","unknown"):
        for x in rank(groups[category]):
            add(x)
    return selected

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
            *, max_original_checks=3, max_candidates=12, broad=False,
            max_extra_pages=0):
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
            day=(end-timedelta(days=1)).date().isoformat()
            first=parse_publisher_page(data,request_url,day)
            items=list(first["links"])
            result["listing_pages_fetched"]=1
            result["pagination_page2_found"]=bool(first["page2_url"])
            result["pagination_page2_attempted"]=False
            result["pagination_page2_failed"]=False
            initial_dates=first["dates"]
            early_reached=bool(initial_dates and min(initial_dates)<start)
            should_page=(max_extra_pages>0 and bool(first["page2_url"])
                         and len(items)>=10 and not early_reached)
            if should_page:
                result["pagination_page2_attempted"]=True
                try:
                    second=parse_publisher_page(loader(first["page2_url"]),
                                                first["page2_url"],day)
                    result["listing_pages_fetched"]+=1
                    items.extend(second["links"])
                except Exception as exc:
                    result["pagination_page2_failed"]=True
                    result["pagination_page2_error"]=type(exc).__name__
            dedup={}
            for item in items:
                if item["url"] not in dedup or (
                        not dedup[item["url"]].get("listing_published_at")
                        and item.get("listing_published_at")):
                    dedup[item["url"]]=item
            items=list(dedup.values())
            dates=[publication_time(x.get("listing_published_at")) for x in items]
            dates=[x for x in dates if x is not None]
            is_descending=all(a>=b for a,b in zip(dates,dates[1:]))
            # Only explicit per-article local listing dates count. Never infer
            # coverage from page heading dates or from RSS index timestamps.
            result["listing_time_count"]=len(dates)
            result["listing_dated_fraction"]=round(len(dates)/len(items),3) if items else 0
            result["listing_order_descending"]=is_descending
            result["listing_boundary_seen"]=(
                len(dates)>=2 and is_descending and len(dates)==len(items)
                and dates[0]>=start and dates[-1]<start)
            result["listing_all_older_than_window"]=(
                len(dates)>=2 and is_descending and len(dates)==len(items)
                and dates[0]<start)
            result["listing_earliest_at"]=min(dates).isoformat() if dates else None
            result["listing_latest_at"]=max(dates).isoformat() if dates else None
        else:
            items=parse_rss(data)
            result["listing_boundary_seen"]=False
            result["listing_pages_fetched"]=0
        result["hits"] = len(items)
        # Index dates only filter clearly stale hits; they are never copied
        # into original published_at or treated as verified timestamps.
        eligible = [x for x in items
                    if not (x.get("index_published_at") or x.get("listing_published_at"))
                    or not publication_time(x.get("index_published_at") or x.get("listing_published_at"))
                    or start <= publication_time(
                        x.get("index_published_at") or x.get("listing_published_at")) < end]
        selected = (choose_time_balanced(eligible,domain,max_candidates,start)
                    if method=="DIRECT_LIST" else
                    choose_relevant(eligible,domain,max_candidates))
        result["relevant_hits"] = len(selected)
        if not selected:
            result["status"] = "PARTIAL"
            result["reason"] = "NO_RELEVANT_CANDIDATES"
            return result
        for index, candidate in enumerate(selected):
            # One small sampled original check per publisher in production;
            # remaining list links are retained for one-stage verification.
            if index < max_original_checks:
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
                if check.get("verified_original") and when and start <= when < end:
                    result["verified_in_window"] += 1
                    result["candidates"].append({
                        "title": check.get("original_title") or candidate["title"],
                        "url": check.get("resolved_url") or candidate["url"],
                        "published_at": when.isoformat(timespec="seconds"),
                        "source_domain": domain, "verified_original": True,
                        "timestamp_unverified": False,
                        "route_method": method
                    })
                    continue
                # An article explicitly verified outside the search window
                # must not silently reappear as an unverified candidate.
                if check.get("verified_original") and when:
                    continue
            result["candidates"].append({
                "title": candidate["title"], "url": candidate["url"],
                "published_at": "", "timestamp_unverified": True,
                "source_domain": domain, "verified_original": False,
                "index_published_at": candidate.get("index_published_at", ""),
                "listing_published_at": candidate.get("listing_published_at", ""),
                "listing_date_evidence": candidate.get("listing_date_evidence", False),
                "source_page": candidate.get("source_page", request_url),
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
               now_kst=None, max_original_checks=1, max_candidates=36):
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
    max_extra_pages=min(1,int(config.get("native_pagination",{}).get("max_extra_pages_per_source",0)))
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
                # Broaden discovery from an already-fetched publisher listing;
                # keep general business portals narrow to avoid irrelevant news.
                source_cap = min(max_candidates, 10) if domain in BUSINESS_GENERAL_SOURCES else max_candidates
                page_budget=(max_extra_pages if domain in config.get(
                    "native_pagination",{}).get("enabled_sources",[]) else 0)
                first = attempt(primary, domain, info, start, end, loader,
                                verifier, max_original_checks=max_original_checks,
                                max_candidates=source_cap,max_extra_pages=page_budget)
                route_results = [first]
                # Do not repeat a search when the first page yielded relevant
                # candidates, even if full publisher-window coverage is PARTIAL.
                # Retry only failed/empty discovery, capped at one fallback.
                if (first["status"] not in ("PASS", "PASS_ZERO")
                        and not first.get("candidates") and max_fallback):
                    fallback = "SITE_SEARCH" if primary == "DIRECT_LIST" else "WEB_SEARCH_RECOVERY"
                    second = attempt(fallback, domain, info, start, end, loader,
                                     verifier, max_original_checks=max_original_checks,
                                     max_candidates=source_cap,max_extra_pages=0, broad=(fallback == "WEB_SEARCH_RECOVERY"))
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
                "verified_candidate_count": sum(bool(x.get("verified_original")) for x in verified),
                "discovered_candidate_count": len(verified),
                "primary_method": primary,
                "native_page_requests": sum(r.get("listing_pages_fetched",0) for r in route_results),
                "routes": route_results
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
