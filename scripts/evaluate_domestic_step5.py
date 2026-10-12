"""Assess domestic step-5 collection without promoting or publishing any data.

Known-case recovery compares against a previously reviewed candidate list and
is NOT an estimate of all-news recall, which requires independent ground truth.
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path

from domestic_candidate_pipeline import canon_url, clean_title
from domestic_coverage_gate import score_operational_coverage


def assess(day, collection, stage4, config, reviewed):
    sources = collection.get("source_health", {})
    names = config["domestic"]["collectors"]
    audited = []
    for group in ("A", "B", "C", "D", "WEB"):
        for name in names[group]:
            node = sources.get(group, {}).get(name, {})
            audited.append({"group": group, "name": name, "status": node.get("status", "MISSING")})
    counts = Counter(x["status"] for x in audited)
    completed = counts["PASS"] + counts["PASS_ZERO"]
    total = len(audited)
    target = config["readiness_gate"]["domestic"].get("min_source_coverage_ratio", 0.9)
    fixed = [x for x in audited if x["group"] != "WEB"]
    web_sources = [x for x in audited if x["group"] == "WEB"]
    mixed_coverage=score_operational_coverage(config,collection)
    routes = [z for group in ("A", "B", "C", "D")
              for node in collection.get("domestic_groups", {}).get(group, {}).get("routes", [])
              for z in node.get("routes", [])]
    discovery_attempts = sum(z.get("method") not in ("CONFIG", None) for z in routes)
    original_checks = sum(z.get("original_checks", 0) for z in routes)
    extra_native_pages=sum(max(0,z.get("listing_pages_fetched",0)-1) for z in routes)
    fallback_attempts = sum(x.get("route_count", 0) > 1
                            for g in ("A", "B", "C", "D")
                            for x in sources.get(g, {}).values())
    web_stats = collection.get("web_unified_statistics", {})
    # Access and candidate discovery are operational metrics, NOT source
    # completeness and must never change publisher PASS status.
    fixed_access = sum(bool(node.get("routes")) and any(
        r.get("status") != "FAIL" and r.get("hits", 0) > 0
        for r in node.get("routes", []))
        for group in ("A", "B", "C", "D")
        for node in collection.get("domestic_groups", {}).get(group, {}).get("routes", []))
    web_axis_access = sum(r.get("status") == "PARTIAL" for r in
                          collection.get("domestic_groups", {}).get("WEB", {}).get("routes", []))
    step4_stats = stage4.get("statistics", {})
    source_items = reviewed.get("domestic", [])
    observed = collection.get("candidates", [])
    output_items = stage4.get("domestic", [])
    known_urls = {canon_url(x.get("source")) for x in source_items}
    seen_urls = {canon_url(x.get("url")) for x in observed}
    seen_urls.update(canon_url(x.get("source")) for x in output_items)
    known_titles = {clean_title(x.get("title")) for x in source_items}
    seen_titles = {clean_title(x.get("title")) for x in observed + output_items}
    hit_reviews = [x for x in source_items
                   if canon_url(x.get("source")) in seen_urls or
                   clean_title(x.get("title")) in seen_titles]
    request_stats = {
        "fixed_discovery_route_calls": discovery_attempts,
        "native_listing_page_requests": sum(r.get("listing_pages_fetched",0) for r in routes),
        "extra_native_page_calls": extra_native_pages,
        "fixed_original_verifier_calls": original_checks,
        "fallback_used_sources": fallback_attempts,
        "web_rss_calls": web_stats.get("rss_requests", 0),
        "stage4_new_original_verifier_calls": step4_stats.get("new_original_verifier_calls", 0),
        "stage4_reused_preverified_originals": step4_stats.get("reused_preverified_originals", 0),
        "logical_calls_total": (
            discovery_attempts + extra_native_pages + original_checks
            + web_stats.get("rss_requests", 0)
            + step4_stats.get("new_original_verifier_calls", 0)),
        "note": "Logical route/original-verifier calls, not exact HTTP request count. A Google News token resolver may use multiple HTTP requests."
    }
    measured = {
        "schema_version": "briefing-domestic-step5-evaluation-v1.0",
        "date": day, "scope": "domestic_only",
        "status": "PARTIAL",
        "search_task_operational_coverage": mixed_coverage,
        "publisher_completion": {
            "verified_sources": completed, "all_sources": total,
            "ratio": round(completed / total, 4) if total else 0,
            "target_ratio": target, "target_reached": total > 0 and completed / total >= target,
            "source_status_counts": dict(counts),
            "fixed_sources": {"completed": sum(x["status"] in ("PASS", "PASS_ZERO") for x in fixed),
                              "all": len(fixed)},
            "web_sources": {"completed": sum(x["status"] in ("PASS", "PASS_ZERO") for x in web_sources),
                            "all": len(web_sources)},
            "unverified_sources": [x for x in audited if x["status"] not in ("PASS", "PASS_ZERO")],
        },
        "route_discovery_access": {
            "fixed_sources_with_usable_index": fixed_access,
            "fixed_source_count": len(fixed),
            "web_axes_with_successful_index_query": web_axis_access,
            "web_axis_count": 6,
            "combined_ratio": round((fixed_access + web_axis_access) / (len(fixed) + 6), 4),
            "NOT_PUBLISHER_COMPLETENESS": True
        },
        "source_query_health": {
            "fixed_route_status_counts": dict(Counter(x.get("status", "MISSING") for x in routes)),
            "web_axis_status_counts": dict(Counter(
                z.get("status", "MISSING") for z in
                collection.get("domestic_groups", {}).get("WEB", {}).get("routes", []))),
        },
        "collection": {
            "pre_stage4_discovered_candidates": len(observed),
            "stage4_output_candidates": len(output_items),
            "stage4_verified_originals": sum(x.get("verified_original") is True for x in output_items),
            "stage4_unverified_originals": sum(x.get("verified_original") is not True for x in output_items),
            "stage4_core_fact_pending": sum(x.get("core_fact_check_required") is True for x in output_items),
            "step4": step4_stats,
        },
        "known_case_recovery": {
            "reviewed_known_examples": len(source_items),
            "matched_by_exact_url_or_normalized_title": len(hit_reviews),
            "matched_ratio": round(len(hit_reviews) / len(source_items), 4) if source_items else None,
            "not_recovered": [{"title": x.get("title"), "source": x.get("source")}
                              for x in source_items if x not in hit_reviews],
            "interpretation": "Previously reviewed 26 candidates are a time-dependent diagnostic sample, not a complete independent ground truth for all news."
        },
        "requests": request_stats,
        "known_structural_limit": (
            "20 search tasks can be assessed operationally, while independent article "
            "recall is unmeasured without separate reference samples. The legacy "
            "23-publisher metric is diagnostic only, never the 90% denominator."
        ),
        "publish_allowed": False,
        "global_patent_schedule_untouched": True
    }
    # Never relabel route availability as verified article recall. A 90% route
    # gate may be met while news coverage is still PARTIAL/UNMEASURED.
    measured["status"]="PARTIAL"
    measured["operational_target_met"]=mixed_coverage["target_met"]
    measured["article_recall_measured"]=False
    return measured


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True)
    p.add_argument("--collection", required=True)
    p.add_argument("--stage4", required=True)
    p.add_argument("--config", default="config/briefing-settings.json")
    p.add_argument("--reviewed", required=True)
    p.add_argument("--output")
    args = p.parse_args()
    settings = json.loads(Path(args.config).read_text(encoding="utf-8"))
    result = assess(
        args.date,
        json.loads(Path(args.collection).read_text(encoding="utf-8")),
        json.loads(Path(args.stage4).read_text(encoding="utf-8")),
        settings,
        json.loads(Path(args.reviewed).read_text(encoding="utf-8"))
    )
    path = Path(args.output or f"staging/{args.date}-domestic-step5-evaluation.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("STEP5_RESULT", json.dumps({
        "status": result["status"],
        "publisher_completion": result["publisher_completion"]["verified_sources"],
        "operational_search_tasks": result["search_task_operational_coverage"]["verified_usable_search_tasks"],
        "operational_all_tasks": result["search_task_operational_coverage"]["configured_search_tasks"],
        "operational_target_met":result["operational_target_met"],
        "publisher_total": result["publisher_completion"]["all_sources"],
        "web_axis_status": result["source_query_health"]["web_axis_status_counts"],
        "known_case_recovery": result["known_case_recovery"]["matched_by_exact_url_or_normalized_title"],
        "known_cases": result["known_case_recovery"]["reviewed_known_examples"],
        "observed_candidates": result["collection"]["pre_stage4_discovered_candidates"],
        "route_discovery_access": result["route_discovery_access"],
        "verified_originals": result["collection"]["stage4_verified_originals"],
        "requests": result["requests"]
    }, ensure_ascii=False))
    print("STEP5_ARTIFACT", path)
    if result["status"] != "PASS":
        print("STEP5_STAGING_ONLY_PARTIAL_DO_NOT_PUBLISH")


if __name__ == "__main__":
    main()
