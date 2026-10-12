"""Date text parsing and bounded native pagination regression tests (no network)."""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from domestic_window_paging import parse_publisher_page
from domestic_route_collector import scan_fixed

KST=ZoneInfo("Asia/Seoul")
DAY="2026-10-12"
PAGE="https://www.hitnews.co.kr/news/articleList.html"
PAGE2=PAGE+"?page=2"
def item(i,date):
    return ('<li><a href="/news/articleView.html?idxno=%s">'
            '제약바이오 신약 개발 임상 결과 %s</a>'
            '<span class="date">%s</span></li>'%(i,i,date))
def fixture(dates,pagination=True):
    links="".join(item(i,date) for i,date in enumerate(dates,1))
    nav='<a href="?page=2">2</a>' if pagination else ""
    return ('<html><script>2026-10-01 11:01</script>'
            '<header>2026-10-12 11:28</header><ul>'+links+
            '</ul><nav>'+nav+'</nav></html>').encode("utf-8")
def settings(enable=True):
    return {"domestic":{"collectors":{"A":["hitnews.co.kr"],"B":[],"C":[],"D":[]},
                        "source_routes":{"hitnews.co.kr":{
                            "group":"A","primary_method":"DIRECT_LIST","primary_url":PAGE}},
                        "native_pagination":{"max_extra_pages_per_source":1,
                                             "enabled_sources":["hitnews.co.kr"] if enable else []}},
            "runtime_safety":{"retry_budget":{"domestic_source_max_retry":1}}}
def verifier(x):
    return {"verified_original":True,
            "resolved_url":x["url"],"original_title":x["title"],
            "published_at_verified":"2026-10-12T10:00:00+09:00"}

class NativeTimelineTests(unittest.TestCase):
    def test_article_specific_date_parses_full_and_short_korean_patterns(self):
        raw=fixture(["2026-10-12 10:25","10.12 09:15","10-12 06:05"],False)
        d=parse_publisher_page(raw,PAGE,DAY)
        self.assertEqual([x["listing_published_at"] for x in d["links"]],
                         ["2026-10-12T10:25:00+09:00",
                          "2026-10-12T09:15:00+09:00",
                          "2026-10-12T06:05:00+09:00"])
        self.assertEqual(d["dated_article_count"],3)
        self.assertIsNone(d["page2_url"])

    def test_page_header_date_is_not_substituted_for_missing_article_date(self):
        raw=fixture(["NO DATE","10.12 08:30"],False)
        d=parse_publisher_page(raw,PAGE,DAY)
        self.assertEqual(d["links"][0]["listing_published_at"],"")
        self.assertEqual(d["links"][1]["listing_published_at"],
                         "2026-10-12T08:30:00+09:00")

    def test_page_two_url_requires_same_origin_and_literal_page_two(self):
        raw=fixture(["10.12 10:00"]*10)
        d=parse_publisher_page(raw,PAGE,DAY)
        self.assertEqual(d["page2_url"],PAGE2)
        attack=raw.replace(b'<a href="?page=2">2</a>',
                           b'<a href="https://evil.example/?page=2">2</a>')
        self.assertIsNone(parse_publisher_page(attack,PAGE,DAY)["page2_url"])

    def test_reaches_early_morning_and_no_third_request(self):
        day1=["10.12 11:%02d"%i for i in range(20,10,-1)]
        day2=["10.12 08:45","10.12 07:30","10.12 06:10",
              "10.11 19:20","10.11 11:50"]
        calls=[]
        def load(url):
            calls.append(url)
            return fixture(day1) if url==PAGE else fixture(day2,False)
        result=scan_fixed(DAY,settings(),loader=load,verifier=verifier,
                          now_kst=datetime(2026,10,12,12,tzinfo=KST))
        source=result["source_health"]["A"]["hitnews.co.kr"]
        self.assertEqual(calls,[PAGE,PAGE2])
        self.assertEqual(source["native_page_requests"],2)
        first=source["routes"][0]
        self.assertTrue(first["listing_boundary_seen"])
        self.assertTrue(any(x["listing_published_at"].endswith("06:10:00+09:00")
                            for x in result["candidates"]))
        self.assertEqual(source["status"],"PASS")

    def test_page_one_reaches_boundary_then_skips_second(self):
        dates=["10.12 10:00"]*10+["10.11 11:00"]
        calls=[]
        def load(url):
            calls.append(url)
            return fixture(dates)
        result=scan_fixed(DAY,settings(),loader=load,verifier=verifier,
                          now_kst=datetime(2026,10,12,12,tzinfo=KST))
        self.assertEqual(calls,[PAGE])
        self.assertEqual(result["source_health"]["A"]["hitnews.co.kr"]["native_page_requests"],1)

    def test_unapproved_source_never_paginates(self):
        calls=[]
        def load(url):
            calls.append(url)
            return fixture(["10.12 10:00"]*12)
        scan_fixed(DAY,settings(False),loader=load,verifier=verifier,
                   now_kst=datetime(2026,10,12,12,tzinfo=KST))
        self.assertEqual(calls,[PAGE])

    def test_second_page_failure_retains_first_page_without_third_fetch(self):
        calls=[]
        def load(url):
            calls.append(url)
            if url==PAGE2:
                raise OSError("403 blocked")
            return fixture(["10.12 10:00"]*12)
        result=scan_fixed(DAY,settings(),loader=load,verifier=verifier,
                          now_kst=datetime(2026,10,12,12,tzinfo=KST))
        route=result["source_health"]["A"]["hitnews.co.kr"]["routes"][0]
        self.assertEqual(calls,[PAGE,PAGE2])
        self.assertTrue(route["pagination_page2_failed"])
        self.assertEqual(route["status"],"PARTIAL")
        self.assertTrue(result["candidates"])

    def test_previous_day_before_noon_does_not_enter_candidate_list(self):
        data=fixture(["10.12 09:00","10.11 11:30"],False)
        result=scan_fixed(DAY,settings(),loader=lambda u:data,verifier=verifier,
                          now_kst=datetime(2026,10,12,12,tzinfo=KST))
        self.assertEqual(len(result["candidates"]),1)
        self.assertTrue(result["candidates"][0]["title"].endswith("1"))

if __name__=="__main__":
    unittest.main()
