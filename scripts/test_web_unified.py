"""Offline tests for WEB consolidation: six index calls, zero original calls."""
import unittest
import urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo
from web_unified_collector import scan_web, AXES, build_queries, classify

KST = ZoneInfo("Asia/Seoul")
DAY = "2026-10-12"
NOW = datetime(2026, 10, 12, 10, 0, tzinfo=KST)

def config():
    selected = {
        "rnd": ["임상 3상"],
        "bd": ["기술수출"],
        "governance": ["최대주주"],
        "court": ["제약 판결"],
        "market_risk": ["거래정지"],
        "policy": ["약가"]
    }
    pubs = {
        "조선비즈": ["chosunbiz.com", "biz.chosun.com"],
        "서울경제": ["sedaily.com"],
        "머니투데이": ["mt.co.kr"],
        "매일경제": ["mk.co.kr"],
        "아시아경제": ["asiae.co.kr"],
        "파이낸셜뉴스": ["fnnews.com"],
        "헤럴드경제": ["heraldcorp.com"],
        "이투데이": ["etoday.co.kr"]
    }
    return {"domestic": {
        "web_keyword_axes": selected,
        "excluded_general_news": ["메디게이트뉴스"],
        "collectors": {
            "A": ["dailypharm.com"],
            "B": [], "C": [], "D": [],
            "WEB": list(pubs) + ["기타 전체 웹"]
        },
        "web_unified_search": {
            "base_query": "(제약 OR 바이오 OR 의약품)",
            "selected_terms_by_axis": selected,
            "publisher_domains": pubs,
            "query_budget": 6,
            "max_index_hits_per_axis": 35,
            "max_discovery_candidates": 36,
            "max_candidates_per_publisher": 4,
            "original_fetch_budget": 0
        }
    }}

def rss(rows):
    return ('<rss><channel>' + ''.join(
        '<item><title>' + title + '</title>'
        '<link>https://news.google.com/rss/articles/' + token + '</link>'
        '<pubDate>' + pub + '</pubDate>'
        '<source url="' + domain + '">' + name + '</source>'
        '</item>'
        for token, title, pub, domain, name in rows
    ) + '</channel></rss>').encode("utf-8")

PUB = "Mon, 12 Oct 2026 00:00:00 GMT"
OLD = "Sun, 11 Oct 2026 02:00:00 GMT"
ROWS = [
    ("t1", "루닛 바이오 임상 성과", PUB, "https://www.mt.co.kr", "머니투데이"),
    ("t2", "제약사 한미 경영권 변화", PUB, "https://www.etoday.co.kr", "이투데이"),
    ("t3", "제약사 임상 결과", PUB, "https://www.dailypharm.com", "데일리팜"),
    ("t4", "보건 의료 정책", PUB, "https://www.medigatenews.com", "메디게이트뉴스")
]

class UnifiedWebTests(unittest.TestCase):
    def test_exact_six_shared_requests_and_no_original_fetch(self):
        calls = []
        def load(url):
            calls.append(url)
            return rss(ROWS)
        result = scan_web(DAY, config(), loader=load, now_kst=NOW)
        self.assertEqual(len(calls), 6)
        self.assertTrue(all("news.google.com/rss/search" in x for x in calls))
        self.assertTrue(all("site%3A" not in x for x in calls))
        self.assertEqual(result["statistics"]["original_requests"], 0)
        self.assertFalse(result["publish_allowed"])
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(len(result["candidates"]), 2)
        self.assertEqual({x["source_bucket"] for x in result["candidates"]},
                         {"머니투데이", "이투데이"})
        self.assertEqual(result["statistics"]["fixed_group_overlap_hits"], 6)
        self.assertEqual(result["statistics"]["excluded_hits"], 6)

    def test_index_success_with_zero_hits_is_not_pass_zero(self):
        result = scan_web(DAY, config(), loader=lambda _: rss([]), now_kst=NOW)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(len(result["candidates"]), 0)
        self.assertTrue(all(x["status"] == "PARTIAL"
                            for x in result["source_health"].values()))
        self.assertTrue(all(not x["coverage_proven"]
                            for x in result["source_health"].values()))

    def test_partial_failure_does_not_retry_the_six_axes(self):
        calls = []
        def load(url):
            calls.append(url)
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["q"][0]
            if "거래정지" in query or "기술수출" in query:
                raise OSError("temporary blocked")
            return rss(ROWS[:1])
        result = scan_web(DAY, config(), loader=load, now_kst=NOW)
        self.assertEqual(len(calls), 6)
        self.assertEqual(sum(x["status"] == "FAIL" for x in result["routes"]), 2)
        self.assertEqual(result["status"], "PARTIAL")

    def test_all_axes_fail_source_health_fails_honestly(self):
        def fail(url):
            raise OSError("blocked")
        result = scan_web(DAY, config(), loader=fail, now_kst=NOW)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(len(result["routes"]), 6)
        self.assertTrue(all(x["status"] == "FAIL"
                            for x in result["source_health"].values()))

    def test_index_date_outside_noon_window_excluded(self):
        result = scan_web(DAY, config(), loader=lambda _: rss(
            [("old", "새로운 신약 연구", OLD, "https://www.mt.co.kr", "머니투데이")]
        ), now_kst=NOW)
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["status"], "PARTIAL")

    def test_index_date_is_never_verified_publication_time(self):
        result = scan_web(DAY, config(), loader=lambda _: rss(ROWS[:1]), now_kst=NOW)
        c = result["candidates"][0]
        self.assertEqual(c["published_at"], "")
        self.assertTrue(c["timestamp_unverified"])
        self.assertFalse(c["verified_original"])
        self.assertEqual(c["original_verification"]["status"], "NOT_CHECKED")
        self.assertEqual(len(c["discovery_axes"]), 6)

    def test_limits_source_concentration_and_unknown_source(self):
        cfg = config()
        cfg["domestic"]["web_unified_search"]["max_candidates_per_publisher"] = 2
        rows = [("x"+str(i), "이슈 "+str(i)+" 바이오", PUB,
                 "https://news.otherexample.kr", "기타 언론사") for i in range(5)]
        rows += [("k"+str(i), "신약 소식 "+str(i), PUB,
                  "https://www.mt.co.kr", "머니투데이") for i in range(5)]
        result = scan_web(DAY, cfg, loader=lambda _: rss(rows), now_kst=NOW)
        count = {}
        for cand in result["candidates"]:
            count[cand["source_bucket"]] = count.get(cand["source_bucket"], 0) + 1
        self.assertEqual(count, {"머니투데이": 2, "기타 전체 웹": 2})

    def test_missing_date_keeps_unverified_candidate(self):
        rows = [("x1", "제약 현장 판결 확인", "",
                 "https://www.sedaily.com", "서울경제")]
        result = scan_web(DAY, config(), loader=lambda _: rss(rows), now_kst=NOW)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["candidates"][0]["source_name"], "서울경제")
        self.assertEqual(result["candidates"][0]["published_at"], "")

    def test_requires_six_authorized_axes(self):
        cfg = config()
        cfg["domestic"]["web_keyword_axes"] = {
            **cfg["domestic"]["web_keyword_axes"], "policy": ["허가"]
        }  # Break shared fixture reference; authoritative terms now differ.
        with self.assertRaises(ValueError):
            scan_web(DAY, cfg, loader=lambda _: b"", now_kst=NOW)

    def test_rejects_before_six_without_search(self):
        calls = []
        with self.assertRaisesRegex(ValueError, "BEFORE_06"):
            scan_web(DAY, config(), loader=lambda url: calls.append(url),
                     now_kst=datetime(2026, 10, 12, 5, 59, tzinfo=KST))
        self.assertEqual(calls, [])

    def test_origin_subdomain_exact_matching(self):
        cfg = config()
        name, host = classify({"index_source_name": "조선비즈",
                               "index_source_url": "https://biz.chosun.com",
                               "url": "https://news.google.com/rss/articles/xyz"}, cfg)
        self.assertEqual(name, "조선비즈")
        name, host = classify({"index_source_name": "머니투데이",
                               "index_source_url": "https://attacker-mt.co.kr",
                               "url": "https://news.google.com/rss/articles/xyz"}, cfg)
        self.assertEqual(name, "머니투데이")  # Publisher text only; unverified.

if __name__ == "__main__":
    unittest.main()
