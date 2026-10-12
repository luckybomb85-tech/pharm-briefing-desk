"""Integration tests: domestic-only includes WEB and never searches global/patent."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import collect_with_evidence as collector


def fixed():
    return {
        "domestic_groups": {
            g: {"status": "PARTIAL", "checked_at": "2026-10-12T10:00:00+09:00", "routes": []}
            for g in ("A", "B", "C", "D")
        },
        "source_health": {g: {} for g in ("A", "B", "C", "D")},
        "candidates": [{
            "title": "Original A headline", "url": "https://example.com/a",
            "verified_original": True, "group": "A"
        }]
    }


def web():
    return {
        "status": "PARTIAL", "checked_at": "2026-10-12T10:00:00+09:00",
        "routes": [{"axis": a, "status": "PARTIAL", "hits": 1}
                   for a in ("rnd", "bd", "governance", "court", "market_risk", "policy")],
        "source_health": {"머니투데이": {
            "status": "PARTIAL", "route_count": 0,
            "verified_candidate_count": 0, "selected_candidates": 1,
            "shared_query_count": 6, "coverage_proven": False, "routes": []
        }},
        "candidates": [{
            "title": "Original WEB headline",
            "url": "https://news.google.com/rss/articles/one",
            "verified_original": False, "group": "WEB",
            "timestamp_unverified": True, "published_at": ""
        }],
        "statistics": {"rss_requests": 6, "original_requests": 0}
    }


class DomesticOnlyIntegrationTests(unittest.TestCase):
    def test_domestic_only_includes_web_but_never_calls_extra(self):
        with patch.object(collector, "scan_fixed", return_value=fixed()) as f:
            with patch.object(collector, "scan_web", return_value=web()) as w:
                with patch.object(collector, "scan_extra", side_effect=AssertionError(
                        "Global/patent collector unexpectedly invoked")):
                    result = collector.scan("2026-10-12", {}, domestic_only=True)
        f.assert_called_once()
        w.assert_called_once()
        self.assertEqual(list(result["domestic_groups"]), ["A", "B", "C", "D", "WEB"])
        self.assertEqual(result["mode"], "domestic_only_step3")
        self.assertEqual(len(result["candidates"]), 2)
        self.assertEqual(result["web_unified_statistics"]["rss_requests"], 6)
        self.assertTrue(result["web_gap_scan"]["reuses_unified_web_scan"])
        self.assertFalse(result["publish_allowed"])

    def test_health_schema_covers_web_but_does_not_fake_pass(self):
        with patch.object(collector, "scan_fixed", return_value=fixed()):
            with patch.object(collector, "scan_web", return_value=web()):
                result = collector.scan("2026-10-12", {}, domestic_only=True)
        health = collector.source_health_checkpoint("2026-10-12", result)
        self.assertEqual(health["source_checks"]["WEB"]["머니투데이"]["status"],
                         "PARTIAL")
        self.assertEqual(health["source_checks"]["WEB"]["머니투데이"]["route_count"], 0)
        self.assertEqual(health["source_checks"]["WEB"]["머니투데이"]["shared_query_count"], 6)
        self.assertEqual(health["collector_status"]["WEB"], "PARTIAL")
        self.assertFalse(health["publish_allowed"])

    def test_repo_settings_are_authoritative_and_have_six_axes(self):
        settings = json.loads(Path("config/briefing-settings.json").read_text(encoding="utf-8"))
        unified = settings["domestic"]["web_unified_search"]
        self.assertEqual(unified["query_budget"], 6)
        self.assertEqual(len(unified["selected_terms_by_axis"]), 6)
        self.assertEqual(unified["original_fetch_budget"], 0)
        self.assertEqual(set(unified["publisher_domains"]),
                         set(settings["domestic"]["collectors"]["WEB"]) - {"기타 전체 웹"})
        self.assertFalse(unified["publish_allowed"])


if __name__ == "__main__":
    unittest.main()
