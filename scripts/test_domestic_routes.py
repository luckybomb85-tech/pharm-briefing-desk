"""Deterministic, no-network step-2 tests for domestic source routes."""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from domestic_route_collector import scan_fixed

KST=ZoneInfo("Asia/Seoul")
DAY="2026-10-12"
LIST_URL="https://news.example.com/news/articleList.html"
HTML_OK=b"""<html><time datetime="2026-10-12T08:00:00+09:00"></time>
<a href="/news/articleView.html?idxno=101">Test pharmaceutical clinical news number one</a>
<time datetime="2026-10-11T10:00:00+09:00"></time></html>"""
RSS_OK=b"""<?xml version="1.0"?><rss><channel><item>
<title>Test pharmaceutical news from RSS</title>
<link>https://news.google.com/rss/articles/testtoken</link>
<pubDate>Mon, 12 Oct 2026 00:01:00 GMT</pubDate>
</item></channel></rss>"""

def settings():
    return {
        "domestic":{"collectors":{"A":["news.example.com"],"B":[],"C":[],"D":[]},
                    "source_routes":{"news.example.com":{"group":"A","primary_method":"DIRECT_LIST",
                                      "primary_url":LIST_URL}}},
        "runtime_safety":{"retry_budget":{"domestic_source_max_retry":1}}
    }

def fake_verify(x):
    return {
        "verified_original":True,"original_title":x["title"],
        "resolved_url":x["url"] if "google.com" not in x["url"] else "https://news.example.com/news/articleView.html?idxno=333",
        "published_at_verified":"2026-10-12T08:01:00+09:00"
    }

class DomesticRouteTests(unittest.TestCase):
    def test_primary_pass_skips_fallback(self):
        calls=[]
        def load(url):
            calls.append(url)
            return HTML_OK
        result=scan_fixed(DAY,settings(),loader=load,verifier=fake_verify,
                          now_kst=datetime(2026,10,12,10,tzinfo=KST))
        source=result["source_health"]["A"]["news.example.com"]
        self.assertEqual(source["status"],"PASS")
        self.assertEqual(source["route_count"],1)
        self.assertEqual(len(calls),1)
        self.assertEqual(len(result["candidates"]),1)
        self.assertFalse(result["publish_allowed"])

    def test_primary_fails_fallback_once_and_preserves_partial(self):
        calls=[]
        def load(url):
            calls.append(url)
            if url==LIST_URL:raise OSError("403 blocked")
            return RSS_OK
        result=scan_fixed(DAY,settings(),loader=load,verifier=fake_verify,
                          now_kst=datetime(2026,10,12,10,tzinfo=KST))
        source=result["source_health"]["A"]["news.example.com"]
        self.assertEqual(source["route_count"],2)
        self.assertEqual(len(calls),2)
        self.assertEqual(source["status"],"PARTIAL")
        self.assertEqual(source["verified_candidate_count"],1)

    def test_no_third_attempt_even_when_both_fail(self):
        calls=[]
        def load(url):
            calls.append(url)
            raise OSError("blocked")
        result=scan_fixed(DAY,settings(),loader=load,verifier=fake_verify,
                          now_kst=datetime(2026,10,12,10,tzinfo=KST))
        source=result["source_health"]["A"]["news.example.com"]
        self.assertEqual(len(calls),2)
        self.assertEqual(source["route_count"],2)
        self.assertEqual(source["status"],"FAIL")

    def test_empty_rss_not_pass_zero(self):
        cfg=settings()
        cfg["domestic"]["source_routes"]["news.example.com"]={
            "group":"A","primary_method":"SITE_SEARCH",
            "primary_query_template":"site:news.example.com after:{start_date} before:{end_date_exclusive}"}
        calls=[]
        def load(url):
            calls.append(url)
            return b"<rss><channel></channel></rss>"
        result=scan_fixed(DAY,cfg,loader=load,verifier=fake_verify,
                          now_kst=datetime(2026,10,12,10,tzinfo=KST))
        self.assertEqual(len(calls),2)
        self.assertEqual(result["source_health"]["A"]["news.example.com"]["status"],"PARTIAL")

    def test_before_six_kst_must_not_search(self):
        calls=[]
        with self.assertRaisesRegex(ValueError,"BEFORE_06"):
            scan_fixed(DAY,settings(),loader=lambda u:calls.append(u),
                       verifier=fake_verify,now_kst=datetime(2026,10,12,5,59,tzinfo=KST))
        self.assertEqual(calls,[])

    def test_off_window_article_does_not_count_as_verified(self):
        def stale(x):
            r=fake_verify(x)
            r["published_at_verified"]="2026-10-11T09:00:00+09:00"
            return r
        result=scan_fixed(DAY,settings(),loader=lambda u:HTML_OK,verifier=stale,
                          now_kst=datetime(2026,10,12,10,tzinfo=KST))
        self.assertEqual(result["source_health"]["A"]["news.example.com"]["status"],"PARTIAL")
        self.assertEqual(result["candidates"],[])

    def test_source_failure_does_not_stop_next_source(self):
        cfg=settings()
        cfg["domestic"]["collectors"]["A"]=["broken.example.com","news.example.com"]
        cfg["domestic"]["source_routes"]["broken.example.com"]={
            "group":"A","primary_method":"DIRECT_LIST",
            "primary_url":"https://broken.example.com/news/articleList.html"}
        result=scan_fixed(DAY,cfg,loader=lambda u:HTML_OK if "news.example.com" in u else (_ for _ in ()).throw(OSError("fail")),
                          verifier=fake_verify,now_kst=datetime(2026,10,12,10,tzinfo=KST))
        self.assertEqual(result["source_health"]["A"]["broken.example.com"]["status"],"FAIL")
        self.assertEqual(result["source_health"]["A"]["news.example.com"]["status"],"PASS")
        self.assertEqual(result["domestic_groups"]["A"]["status"],"PARTIAL")

if __name__=="__main__":
    unittest.main()
