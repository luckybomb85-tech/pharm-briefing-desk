"""Domestic stage 4: conservative event dedup BEFORE bounded verification.

This consumes candidates already gathered by A/B/C/D and six shared WEB queries.
It performs ZERO additional discovery searches. Output is staging only, never READY.
"""
import argparse
import json
import re
import unicodedata
import urllib.parse
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from domestic_route_collector import KST, publication_time, window
from verify_originals import verify

GROUPS = ("A", "B", "C", "D", "WEB")
LEVELS = ("P0", "P1", "P2", "P3")
TRACKERS = ("utm_", "fbclid", "gclid", "mc_", "ref_", "igshid")
STAGES = (
    ("litigation", ("판결", "심결", "소송", "기각", "인용", "가처분")),
    ("reimbursement", ("급여", "약가", "보험등재", "신속등재")),
    ("approval", ("허가", "승인", "crl", "fda")),
    ("clinical", ("임상", "3상", "2상", "1상", "중단", "pivotal")),
    ("deal", ("기술수출", "기술이전", "계약해지", "권리반환", "license")),
    ("launch", ("출시", "판매개시", "상업화")),
    ("governance", ("최대주주", "지배구조", "합병", "증자", "경영권")),
    ("financial", ("영업이익", "매출", "손실", "실적", "유동성")),
)
PRIORITY_CUES = {
    "P0": ("임상 3상 실패", "3상 실패", "3상 성공", "임상 중단", "거래정지",
           "상장폐지", "최대주주 변경", "fda 승인", "fda crl"),
    "P1": ("단독", "exclusive", "급여", "약가", "고등법원", "2상",
           "지분변동", "합병", "분할", "판결"),
    "P2": ("제약", "바이오", "임상", "허가", "투자", "특허", "기술수출",
           "계약", "신약", "바이오시밀러"),
}
ACTUAL_VERIFIED = ("VERIFIED", "ORIGINAL_VERIFIED", "MEDIA_ORIGINAL",
                   "ORIGINAL_CHECKED", "PRIMARY_CONFIRMED")
FACT_CONFIRMED = ("PRIMARY_CONFIRMED", "PRIMARY_SOURCE_CONFIRMED")


def clean_title(title):
    s = unicodedata.normalize("NFKC", str(title or ""))
    s = re.sub(r"^\s*\[(?:단독|exclusive)\]\s*", "", s, flags=re.I)
    s = re.sub(r"\s+[-|]\s+(?:[가-힣A-Za-z0-9 .]{2,30})$", "", s)
    s = re.sub(r"[^\w가-힣]+", " ", s.lower(), flags=re.UNICODE)
    return " ".join(s.split())


def canon_url(url):
    try:
        p = urllib.parse.urlsplit(str(url or "").strip())
        if p.scheme not in ("https", "http") or not p.hostname:
            return ""
        q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith(TRACKERS)]
        normalized = urllib.parse.urlencode(sorted(q))
        domain = p.hostname.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return urllib.parse.urlunsplit(("https", domain,
                                        p.path.rstrip("/") or "/", normalized, ""))
    except (ValueError, TypeError):
        return ""


def milestone(title):
    text = unicodedata.normalize("NFKC", str(title or "")).casefold()
    for key, terms in STAGES:
        if any(term in text for term in terms):
            return key
    return "general"


def priority(candidate):
    value = candidate.get("priority")
    if value in LEVELS:
        return value
    title = str(candidate.get("title", "")).casefold()
    for level in LEVELS[:3]:
        if any(term in title for term in PRIORITY_CUES[level]):
            return level
    return "P3"


def candidate_url(candidate):
    return str(candidate.get("source") or candidate.get("url") or "").strip()


def authentic(candidate, start, end):
    """A prior verified original with KST original timestamp is trusted once."""
    url = candidate.get("resolved_url") or candidate_url(candidate)
    if not canon_url(url) or urllib.parse.urlsplit(url).hostname in (
            "news.google.com", "news.google.co.kr"):
        return False
    dt = publication_time(candidate.get("published_at"))
    return (candidate.get("verified_original") is True
            and candidate.get("timestamp_unverified") is not True
            and dt is not None and start <= dt < end)


def group_candidates(candidates):
    """Merge only exact original links, exact normalized headlines, or explicit
    event IDs within the SAME milestone. Company-name similarity is not enough.
    """
    rows = [dict(c) for c in candidates if c.get("group") in GROUPS
            and c.get("title") and candidate_url(c)]
    parent = list(range(len(rows)))
    identities = {}

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def join(a, b):
        ra, rb = root(a), root(b)
        if ra != rb:
            parent[rb] = ra

    for i, row in enumerate(rows):
        keys = []
        url = canon_url(candidate_url(row))
        if url:
            keys.append("url:" + url)
        title = clean_title(row["title"])
        if title:
            keys.append("title:" + title)
        event_id = row.get("event_id")
        if event_id:
            keys.append("event:" + str(event_id) + ":" + milestone(row["title"]))
        for key in keys:
            if key in identities:
                join(i, identities[key])
            else:
                identities[key] = i
    groups = defaultdict(list)
    for i in range(len(rows)):
        groups[root(i)].append(rows[i])
    return list(groups.values()), len(rows)


def candidate_rank(item, start, end):
    # Existing verified, timestamped publisher articles win over RSS index hits.
    verified = authentic(item, start, end)
    priority_order = LEVELS.index(priority(item))
    return (0 if verified else 1,
            0 if item.get("group") != "WEB" else 1,
            priority_order, -len(str(item.get("title", ""))))


def build_domestic_stage4(day, candidates, settings, *, verifier=verify):
    start, end = window(day)
    conf = settings["domestic"]["event_validation"]
    if conf.get("scope") != "domestic_only" or conf.get("publish_allowed") is not False:
        raise ValueError("STAGE4_NON_DOMESTIC_OR_PUBLISHING_CONFIGURATION")
    budget = int(conf.get("max_new_original_verifications", 0))
    if not 0 <= budget <= 30:
        raise ValueError("INVALID_STAGE4_ORIGINAL_VERIFICATION_BUDGET")
    grouped, total = group_candidates(candidates)
    prepared = []
    for members in grouped:
        chosen = sorted(members, key=lambda x: candidate_rank(x, start, end))[0]
        rank = min(LEVELS.index(priority(x)) for x in members)
        event_state = next((x.get("event_status") for x in members
                            if x.get("event_status") == "UPDATE"), "NEW")
        prepared.append({
            "representative": chosen, "members": members,
            "priority": LEVELS[rank], "event_status": event_state
        })
    # Resolve most newsworthy unverified candidates first; no quota chasing.
    prepared.sort(key=lambda x: (LEVELS.index(x["priority"]),
                                 0 if authentic(x["representative"], start, end) else 1,
                                 clean_title(x["representative"]["title"])))
    verification_cache = {}
    results = []
    duplicates = []
    out_of_window = []
    original_calls = 0
    prior_reused = 0
    deferred = 0
    confirmed = 0
    invalid = 0
    final_urls = set()
    for cluster in prepared:
        rep = cluster["representative"]
        url = candidate_url(rep)
        method = "REUSED_PREVERIFIED" if authentic(rep, start, end) else "NOT_CHECKED"
        final_url = rep.get("resolved_url") or url
        published = rep.get("published_at", "") if method == "REUSED_PREVERIFIED" else ""
        if method == "REUSED_PREVERIFIED":
            prior_reused += 1
        elif original_calls < budget:
            key = canon_url(url)
            if key in verification_cache:
                response = verification_cache[key]
                method = "REUSED_URL_CACHE"
            else:
                original_calls += 1
                try:
                    response = verifier({"url": url, "title": rep["title"]})
                except Exception as exc:
                    response = {"verified_original": False, "reason": type(exc).__name__}
                verification_cache[key] = response
                method = "ORIGINAL_CHECKED"
            dt = publication_time(response.get("published_at_verified"))
            resolved = response.get("resolved_url")
            if response.get("verified_original") and canon_url(resolved) and dt:
                published = dt.isoformat(timespec="seconds")
                final_url = resolved
        else:
            deferred += 1
            method = "DEFERRED_NOT_VERIFIED"
        original_time = publication_time(published)
        good = (bool(original_time) and start <= original_time < end
                and canon_url(final_url)
                and urllib.parse.urlsplit(final_url).hostname not in (
                    "news.google.com", "news.google.co.kr"))
        if original_time and not (start <= original_time < end):
            out_of_window.append(rep["title"])
            continue
        if good:
            confirmed += 1
        else:
            invalid += 1
        actual_url = canon_url(final_url)
        if actual_url and actual_url in final_urls:
            duplicates.append({"title": rep["title"], "reason": "SAME_RESOLVED_ORIGINAL_URL",
                               "source": final_url})
            continue
        if actual_url:
            final_urls.add(actual_url)
        is_important = cluster["priority"] in ("P0", "P1")
        fact_verified = bool(
            rep.get("core_fact_verified") is True and
            rep.get("verification_status") in FACT_CONFIRMED and
            canon_url(rep.get("primary_source_url"))
        )
        source_names = list(dict.fromkeys(
            str(x.get("source_name") or x.get("source_domain") or x.get("group"))
            for x in cluster["members"]))
        original_sources = list(dict.fromkeys(candidate_url(x) for x in cluster["members"]))
        stage = milestone(rep["title"])
        results.append({
            "title": rep["title"], "source": final_url,
            "source_name": rep.get("source_name") or rep.get("source_domain") or "",
            "tag": rep.get("tag") or stage,
            "summary": rep.get("summary") or "",
            "article_preview": rep.get("article_preview") or {},
            "priority": cluster["priority"],
            "published_at": published if good else "",
            "timestamp_unverified": not good,
            "verified_original": good,
            "original_verification_method": method,
            "verification_status": ("EDITORIAL_CORE_FACT_PENDING" if is_important
                                    and not fact_verified else
                                    "ORIGINAL_VERIFIED" if good else
                                    "ORIGINAL_UNVERIFIED"),
            "core_fact_check_required": is_important and not fact_verified,
            "needs_editorial_enrichment": not bool(rep.get("summary"))
                                          or not bool(rep.get("article_preview")),
            "event_id": rep.get("event_id") or "",
            "event_status": cluster["event_status"],
            "milestone": stage,
            "discovery_groups": list(dict.fromkeys(x.get("group") for x in cluster["members"])),
            "discovery_sources": source_names,
            "source_urls": original_sources,
            "discovery_duplicates_removed": len(cluster["members"]) - 1,
            "publish_allowed": False
        })
        for other in cluster["members"]:
            if other is rep:
                continue
            duplicates.append({"title": other["title"],
                               "source": candidate_url(other),
                               "reason": "SAME_URL_TITLE_OR_EVENT_MILESTONE",
                               "kept_title": rep["title"]})
    # Do not conflate a title-confirmed publisher page with verification of
    # the underlying claimed clinical, financial or legal fact.
    stats = {
        "input_domestic_candidates": total, "preverification_clusters": len(prepared),
        "duplicates_suppressed": len(duplicates), "events_output": len(results),
        "reused_preverified_originals": prior_reused,
        "new_original_verifier_calls": original_calls,
        "new_original_verification_budget": budget,
        "deferred_for_budget": deferred, "original_time_in_window": confirmed,
        "original_unverified": invalid, "out_of_window_removed": len(out_of_window),
        "p0_p1_core_fact_checks_pending": sum(
            x["core_fact_check_required"] for x in results),
    }
    return {"schema_version": "briefing-domestic-stage4-v1.0",
            "date": day, "timezone": "Asia/Seoul", "status": "PARTIAL",
            "mode": "DOMESTIC_DEDUP_AND_BOUNDED_VERIFY",
            "domestic": results, "duplicate_candidates": duplicates,
            "excluded_outside_window": out_of_window, "statistics": stats,
            "publish_allowed": False,
            "note": "Discovery and headline dedup are provisional; high-priority core facts are not marked verified merely because the source article opened."}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--input", required=True)
    ap.add_argument("--settings", default="config/briefing-settings.json")
    ap.add_argument("--output")
    args = ap.parse_args()
    settings = json.loads(Path(args.settings).read_text(encoding="utf-8"))
    source = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = build_domestic_stage4(args.date, source.get("candidates", []), settings)
    path = Path(args.output or f"staging/{args.date}-domestic-stage4.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(json.dumps({"path": str(path), "status": result["status"],
                      "statistics": result["statistics"],
                      "publish_allowed": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
