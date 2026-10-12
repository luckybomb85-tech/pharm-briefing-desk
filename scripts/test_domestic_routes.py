"""Deterministic, no-network step-2 tests for domestic source routes."""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from domestic_route_collector import scan_fixed

KST=ZoneInfo("Asia/Seoul")
DAY="2026-10-12"
LIST_URL="https://news.example.com/news/articleList.html"
HTML_OK=b"""<html><li><a href="/news/articleView.html?idxno=101">Test pharmaceutical clinical news number one</a>
<time datetime="2026-10-12T08:00:00+09:00"></time></li>
<li><a href="/news/articleView.html?idxno=102">Previous older pharmaceutical report</a>
<time datetime="2026-10-11T10:00:00+09:00"></time></li></html>"""
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

    def test_trusted_old_native_list_can_pass_zero(self):
        html_old=b"""<li><a href="/news/articleView.html?idxno=12">Older pharmaceutical report</a>
<time datetime="2026-10-11T09:00:00+09:00"></time></li>
<li><a href="/news/articleView.html?idxno=13">Even older pharmaceutical report</a>
<time datetime="2026-10-10T18:00:00+09:00"></time></li>"""
        calls=[]
        def loader(url):
            calls.append(url)
            return html_old
        def old_verify(item):
            r=fake_verify(item)
            r["published_at_verified"]="2026-10-11T09:00:00+09:00"
            return r
        result=scan_fixed(DAY,settings(),loader=loader,verifier=old_verify,
                          now_kst=datetime(2026,10,12,10,tzinfo=KST))
        source=result["source_health"]["A"]["news.example.com"]
        self.assertEqual(source["status"],"PASS_ZERO")
        self.assertEqual(source["route_count"],1)
        self.assertEqual(len(calls),1)
        self.assertEqual(result["candidates"],[])

    def test_listing_keeps_breadth_and_skips_unnecessary_fallback(self):
        links = "".join(
            '<a href="/news/articleView.html?idxno=%d">제약 임상 급여 소식 %d</a>'
            % (i, i) for i in range(100, 120)
        )
        called = []
        def load(url):
            called.append(url)
            return links.encode("utf-8")
        verify_calls = []
        def v(candidate):
            verify_calls.append(candidate["url"])
            return fake_verify(candidate)
        result = scan_fixed(DAY, settings(), loader=load, verifier=v,
                            now_kst=datetime(2026,10,12,12,tzinfo=KST))
        source = result["source_health"]["A"]["news.example.com"]
        self.assertEqual(source["route_count"], 1)
        self.assertEqual(source["discovered_candidate_count"], 20)
        self.assertEqual(source["verified_candidate_count"], 1)
        self.assertEqual(len(verify_calls), 1)
        self.assertEqual(len(called), 1)
        self.assertEqual(sum(not x["verified_original"] for x in result["candidates"]), 19)

    def test_general_business_page_filters_unrelated_headlines(self):
        cfg = settings()
        cfg["domestic"]["collectors"]["A"] = []
        cfg["domestic"]["collectors"]["C"] = ["newdaily.co.kr"]
        cfg["domestic"]["source_routes"]["newdaily.co.kr"] = {
            "group": "C", "primary_method": "DIRECT_LIST",
            "primary_url": "https://biz.newdaily.co.kr/"}
        body = """<a href="/site/data/html/2026/10/12/123.html">청년 일자리 예산 축소</a>
        <a href="/site/data/html/2026/10/12/124.html">셀트리온 3분기 잠정 실적 공개</a>""".encode("utf-8")
        result = scan_fixed(DAY, cfg, loader=lambda u:body, verifier=fake_verify,
                            now_kst=datetime(2026,10,12,12,tzinfo=KST))
        self.assertEqual(len(result["candidates"]), 1)
        self.assertIn("셀트리온", result["candidates"][0]["title"])

    def test_empty_relevant_primary_triggers_exactly_one_fallback(self):
        calls = []
        def load(url):
            calls.append(url)
            if url == LIST_URL:
                return b"<html><a href='/news/articleView.html?idxno=2'></a></html>"
            return RSS_OK
        result = scan_fixed(DAY, settings(), loader=load, verifier=fake_verify,
                            now_kst=datetime(2026,10,12,12,tzinfo=KST))
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["source_health"]["A"]["news.example.com"]["route_count"], 2)

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
